#!/usr/bin/env python3
"""Behavioral watchdog for the active ReSETP Claude Code desktop session.

This script never sends a model request to inspect quota. It reads local
session/activity files and Claude Desktop's local plan-usage history. A wake is
allowed only after a task-completion event remains unacknowledged for the stale
threshold, and the persisted cooldown/reset gates have passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


REPO_ROOT = Path("/Volumes/移动硬盘（512G）/ReSETP")
DELIVERY_DIR = REPO_ROOT / "tools" / "claude_quota_watchdog"
CLAUDE_HOME = Path.home() / ".claude"
CLAUDE_APP_DATA = Path.home() / "Library" / "Application Support" / "Claude"
APP_SESSION_ROOT = CLAUDE_APP_DATA / "claude-code-sessions"
USAGE_HISTORY = CLAUDE_APP_DATA / "plan-usage-history.json"
CLAUDE_MAIN_LOG = Path.home() / "Library" / "Logs" / "Claude" / "main.log"
HELPER_APP = DELIVERY_DIR / "ReSETP Claude Quota Watchdog Helper.app"
HELPER_BIN = HELPER_APP / "Contents" / "MacOS" / "ReSETPClaudeWakeHelper"
STATE_PATH = DELIVERY_DIR / "state.json"
LOG_PATH = DELIVERY_DIR / "watchdog.log"
PID_PATH = DELIVERY_DIR / "watchdog.pid"

CHECK_INTERVAL_SECONDS = 60
STALE_SECONDS = 15 * 60
COOLDOWN_SECONDS = 20 * 60
USAGE_SAMPLE_MAX_AGE_SECONDS = 15 * 60
RESET_WINDOW_SECONDS = 5 * 60 * 60
RESET_SAFETY_SECONDS = 10 * 60
EXACT_RESET_SAFETY_SECONDS = 60
WAKE_MESSAGE = (
    "Codex 任务已完成，请读取最新的 done.json 和 report.md 并继续推进 ReSETP 项目。"
)
TEST_MESSAGE = "配额看门狗自测，请忽略。"


def now_ts() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    instant = dt.datetime.fromtimestamp(ts if ts is not None else now_ts()).astimezone()
    return instant.isoformat(timespec="seconds")


def log(message: str, **fields: Any) -> None:
    record = {"time": iso(), "message": message, **fields}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class Session:
    app_metadata_path: Path
    app_session_id: str
    cli_session_id: str
    bridge_session_id: str
    title: str
    org_id: str | None
    last_activity: float
    project_jsonl: Path
    tmp_root: Path


def iter_app_sessions() -> Iterable[tuple[Path, dict[str, Any]]]:
    if not APP_SESSION_ROOT.exists():
        return
    for path in APP_SESSION_ROOT.glob("*/*/local_*.json"):
        data = load_json(path, None)
        if isinstance(data, dict):
            yield path, data


def resolve_session() -> Session | None:
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    for path, data in iter_app_sessions():
        if data.get("cwd") != str(REPO_ROOT) or data.get("isArchived") is True:
            continue
        cli_session_id = data.get("cliSessionId")
        bridge_ids = data.get("bridgeSessionIds")
        if not isinstance(cli_session_id, str) or not isinstance(bridge_ids, list):
            continue
        bridge_id = next(
            (item for item in reversed(bridge_ids) if isinstance(item, str) and item),
            None,
        )
        if bridge_id is None:
            continue
        activity_ms = data.get("lastActivityAt")
        activity = float(activity_ms) / 1000 if isinstance(activity_ms, (int, float)) else 0.0
        candidates.append((activity, path, data))

    if not candidates:
        return None

    app_activity, path, data = max(candidates, key=lambda item: item[0])
    cli_id = str(data["cliSessionId"])
    bridge_id = next(
        (
            item
            for item in reversed(data["bridgeSessionIds"])
            if isinstance(item, str) and item
        ),
        "",
    )
    project_jsonl = (
        CLAUDE_HOME
        / "projects"
        / "-Volumes------512G--ReSETP"
        / f"{cli_id}.jsonl"
    )
    tmp_root = (
        Path("/private/tmp/claude-501")
        / "-Volumes------512G--ReSETP"
        / cli_id
    )
    file_activity = project_jsonl.stat().st_mtime if project_jsonl.exists() else 0.0
    org_id = path.parent.name if path.parent.name else None
    return Session(
        app_metadata_path=path,
        app_session_id=str(data.get("sessionId", "")),
        cli_session_id=cli_id,
        bridge_session_id=bridge_id,
        title=str(data.get("title") or ""),
        org_id=org_id,
        last_activity=max(app_activity, file_activity),
        project_jsonl=project_jsonl,
        tmp_root=tmp_root,
    )


@dataclass(frozen=True)
class QuotaState:
    percent: float | None
    sample_time: float | None
    reliable: bool
    reset_not_before: float | None
    exact_limit_detected: bool
    limit_message_time: float | None
    source: str


SESSION_LIMIT_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<clock>\d{2}:\d{2}:\d{2}).*?"
    r"(?P<session>local_[A-Za-z0-9_-]+).*?"
    r"You've hit your session limit\s*·\s*resets "
    r"(?P<reset>\d{1,2}(?::\d{2})?(?:am|pm)) "
    r"\(Asia/Singapore\)",
    re.IGNORECASE,
)


def recent_text(path: Path, max_bytes: int = 4 * 1024 * 1024) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def parse_session_limit(
    app_session_id: str,
    text: str,
) -> tuple[float | None, float | None]:
    timezone = ZoneInfo("Asia/Singapore")
    latest_message: float | None = None
    latest_reset: float | None = None

    for line in text.splitlines():
        match = SESSION_LIMIT_PATTERN.search(line)
        if match is None or match.group("session") != app_session_id:
            continue
        try:
            message_time = dt.datetime.strptime(
                f"{match.group('date')} {match.group('clock')}",
                "%Y-%m-%d %H:%M:%S",
            ).replace(tzinfo=timezone)
            reset_clock = dt.datetime.strptime(
                match.group("reset").lower(),
                "%I:%M%p" if ":" in match.group("reset") else "%I%p",
            ).time()
            reset_time = dt.datetime.combine(
                message_time.date(),
                reset_clock,
                tzinfo=timezone,
            )
            if reset_time <= message_time:
                reset_time += dt.timedelta(days=1)
        except ValueError:
            continue
        if latest_message is None or message_time.timestamp() > latest_message:
            latest_message = message_time.timestamp()
            latest_reset = reset_time.timestamp()

    return latest_message, latest_reset


def quota_state(session: Session) -> QuotaState:
    limit_message_time, exact_reset = parse_session_limit(
        session.app_session_id,
        recent_text(CLAUDE_MAIN_LOG),
    )
    exact_limit_detected = (
        limit_message_time is not None
        and exact_reset is not None
        and now_ts() < exact_reset + EXACT_RESET_SAFETY_SECONDS
    )

    history = load_json(USAGE_HISTORY, {})
    samples = history.get("samples") if isinstance(history, dict) else None
    if not isinstance(samples, list):
        return QuotaState(
            None,
            None,
            False,
            exact_reset + EXACT_RESET_SAFETY_SECONDS
            if exact_limit_detected and exact_reset is not None
            else None,
            exact_limit_detected,
            limit_message_time,
            str(CLAUDE_MAIN_LOG)
            if exact_limit_detected
            else "usage history unavailable",
        )

    selected: list[tuple[float, float]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        if session.org_id and sample.get("org") != session.org_id:
            continue
        raw_time = sample.get("t")
        usage = sample.get("u")
        raw_percent = usage.get("fh") if isinstance(usage, dict) else None
        if isinstance(raw_time, (int, float)) and isinstance(raw_percent, (int, float)):
            selected.append((float(raw_time) / 1000, float(raw_percent)))

    if not selected:
        return QuotaState(
            None,
            None,
            False,
            exact_reset + EXACT_RESET_SAFETY_SECONDS
            if exact_limit_detected and exact_reset is not None
            else None,
            exact_limit_detected,
            limit_message_time,
            str(CLAUDE_MAIN_LOG)
            if exact_limit_detected
            else "no matching five-hour samples",
        )

    selected.sort()
    sample_time, percent = selected[-1]
    reliable = now_ts() - sample_time <= USAGE_SAMPLE_MAX_AGE_SECONDS
    reset_not_before: float | None = (
        exact_reset + EXACT_RESET_SAFETY_SECONDS
        if exact_limit_detected and exact_reset is not None
        else None
    )

    if reset_not_before is None and reliable and percent >= 99:
        reset_transition: float | None = None
        for index in range(1, len(selected)):
            previous_percent = selected[index - 1][1]
            current_time, current_percent = selected[index]
            if current_percent <= 10 and previous_percent - current_percent >= 20:
                reset_transition = current_time
        if reset_transition is not None:
            reset_not_before = (
                reset_transition + RESET_WINDOW_SECONDS + RESET_SAFETY_SECONDS
            )

    return QuotaState(
        percent=percent,
        sample_time=sample_time,
        reliable=reliable,
        reset_not_before=reset_not_before,
        exact_limit_detected=exact_limit_detected,
        limit_message_time=limit_message_time,
        source=(
            f"{CLAUDE_MAIN_LOG} + {USAGE_HISTORY}"
            if exact_limit_detected
            else str(USAGE_HISTORY)
        ),
    )


@dataclass(frozen=True)
class CompletionEvent:
    key: str
    path: str
    timestamp: float
    kind: str


def is_pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def scan_completion_events(session: Session) -> list[CompletionEvent]:
    events: list[CompletionEvent] = []

    tasks_dir = session.tmp_root / "tasks"
    if tasks_dir.exists():
        for path in tasks_dir.glob("*.output"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > 0:
                events.append(
                    CompletionEvent(
                        key=f"task-output:{path}:{stat.st_mtime_ns}:{stat.st_size}",
                        path=str(path),
                        timestamp=stat.st_mtime,
                        kind="task_output_nonempty",
                    )
                )

    scratchpad = session.tmp_root / "scratchpad"
    if scratchpad.exists():
        for pid_path in scratchpad.glob("*.pid"):
            try:
                pid_text = pid_path.read_text(encoding="utf-8").strip()
                pid = int(pid_text)
            except (OSError, ValueError):
                continue
            if is_pid_alive(pid):
                continue
            stem = pid_path.stem
            related = [
                path
                for path in (scratchpad / f"{stem}.log", pid_path)
                if path.exists()
            ]
            event_time = max(path.stat().st_mtime for path in related)
            events.append(
                CompletionEvent(
                    key=f"exited-pid:{pid_path}:{pid}:{int(event_time * 1e9)}",
                    path=str(pid_path),
                    timestamp=event_time,
                    kind="scratchpad_pid_exited",
                )
            )

    roots = [REPO_ROOT / "docs" / "handoff", REPO_ROOT / "baselines" / "china_e3_e7"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("done.json"):
            if DELIVERY_DIR in path.parents:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            payload = load_json(path, {})
            status = payload.get("status") if isinstance(payload, dict) else None
            if not isinstance(status, str) or not status:
                continue
            events.append(
                CompletionEvent(
                    key=f"done:{path}:{stat.st_mtime_ns}:{stat.st_size}",
                    path=str(path),
                    timestamp=stat.st_mtime,
                    kind=f"done_json:{status}",
                )
            )

    events.sort(key=lambda event: event.timestamp)
    return events


def helper_probe() -> tuple[bool, dict[str, Any]]:
    if not HELPER_BIN.exists():
        return False, {"error": "HELPER_NOT_BUILT", "path": str(HELPER_BIN)}
    try:
        result = subprocess.run(
            [str(HELPER_BIN), "--probe"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": type(exc).__name__, "detail": str(exc)}
    payload = load_json_text(result.stdout)
    return result.returncode == 0 and payload.get("ok") is True, payload


def load_json_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text.strip())
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {"raw": text.strip()}


def send_message(session: Session, message: str) -> tuple[bool, dict[str, Any]]:
    deep_link = (
        "claude://code/"
        + urllib.parse.quote(session.bridge_session_id, safe="_-")
        + "?q="
        + urllib.parse.quote(message, safe="")
    )
    try:
        opened = subprocess.run(
            ["/usr/bin/open", deep_link],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": "DEEPLINK_EXCEPTION", "detail": str(exc)}
    if opened.returncode != 0:
        return False, {
            "error": "DEEPLINK_FAILED",
            "detail": opened.stderr.strip(),
            "returncode": opened.returncode,
        }

    time.sleep(2.0)
    try:
        result = subprocess.run(
            [
                str(HELPER_BIN),
                "--send",
                "--message",
                message,
                "--expect-title",
                session.title,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": "HELPER_EXCEPTION", "detail": str(exc)}
    payload = load_json_text(result.stdout)
    payload["returncode"] = result.returncode
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()
    return result.returncode == 0 and payload.get("ok") is True, payload


def load_state() -> dict[str, Any]:
    state = load_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", 1)
    state.setdefault("known_events", {})
    state.setdefault("pending_events", {})
    state.setdefault("last_wake_attempt", 0.0)
    state.setdefault("last_successful_wake", 0.0)
    return state


def evaluate_once(*, allow_wake: bool) -> dict[str, Any]:
    session = resolve_session()
    if session is None:
        result = {"decision": "NO_ACTIVE_RESET_PROJECT_SESSION"}
        log("check", **result)
        return result

    state = load_state()
    known: dict[str, Any] = state["known_events"]
    pending: dict[str, Any] = state["pending_events"]
    events = scan_completion_events(session)

    for event in events:
        known[event.key] = {
            "path": event.path,
            "timestamp": event.timestamp,
            "kind": event.kind,
        }
        if event.timestamp > session.last_activity + 2:
            pending[event.key] = known[event.key]

    for key in list(pending):
        timestamp = float(pending[key].get("timestamp", 0))
        if timestamp <= session.last_activity + 2:
            pending.pop(key, None)

    # Keep the state bounded without losing recent audit context.
    if len(known) > 2_000:
        newest = sorted(
            known.items(),
            key=lambda item: float(item[1].get("timestamp", 0)),
            reverse=True,
        )[:1_000]
        state["known_events"] = dict(newest)

    state["pending_events"] = pending
    state["session_id"] = session.cli_session_id
    state["last_check"] = now_ts()
    atomic_json(STATE_PATH, state)

    quota = quota_state(session)
    latest_pending = max(
        pending.values(),
        key=lambda value: float(value.get("timestamp", 0)),
        default=None,
    )
    inactivity = now_ts() - session.last_activity
    event_age = (
        now_ts() - float(latest_pending["timestamp"]) if latest_pending else None
    )
    helper_ok, helper_status = helper_probe()

    common = {
        "session_id": session.cli_session_id,
        "session_activity": iso(session.last_activity),
        "inactivity_seconds": round(inactivity),
        "pending_event_count": len(pending),
        "latest_pending_event": latest_pending,
        "five_hour_percent": quota.percent,
        "quota_sample_time": iso(quota.sample_time) if quota.sample_time else None,
        "quota_sample_reliable": quota.reliable,
        "exact_limit_detected": quota.exact_limit_detected,
        "limit_message_time": (
            iso(quota.limit_message_time) if quota.limit_message_time else None
        ),
        "quota_signal_source": quota.source,
        "reset_not_before": (
            iso(quota.reset_not_before) if quota.reset_not_before else None
        ),
        "helper_ready": helper_ok,
        "helper_status": helper_status,
    }

    if latest_pending is None:
        result = {"decision": "HEALTHY_NO_UNACKNOWLEDGED_COMPLETION", **common}
        log("check", **result)
        return result

    if inactivity < STALE_SECONDS or event_age is None or event_age < STALE_SECONDS:
        result = {"decision": "WAITING_STALE_THRESHOLD", **common}
        log("check", **result)
        return result

    if (
        (
            quota.exact_limit_detected
            or (
                quota.reliable
                and quota.percent is not None
                and quota.percent >= 99
            )
        )
        and quota.reset_not_before is not None
        and now_ts() < quota.reset_not_before
    ):
        result = {"decision": "WAITING_FOR_QUOTA_RESET", **common}
        log("check", **result)
        return result

    if (
        quota.reliable
        and quota.percent is not None
        and quota.percent >= 99
        and quota.reset_not_before is None
    ):
        result = {"decision": "WAITING_QUOTA_AT_CAP_RESET_UNKNOWN", **common}
        log("check", **result)
        return result

    since_attempt = now_ts() - float(state.get("last_wake_attempt", 0))
    if since_attempt < COOLDOWN_SECONDS:
        result = {
            "decision": "WAKE_COOLDOWN",
            "cooldown_remaining_seconds": round(COOLDOWN_SECONDS - since_attempt),
            **common,
        }
        log("check", **result)
        return result

    if not helper_ok:
        result = {"decision": "BLOCKED_WAKE_CHANNEL", **common}
        log("check", **result)
        return result

    if not allow_wake:
        result = {"decision": "WOULD_WAKE_DRY_RUN", **common}
        log("check", **result)
        return result

    state["last_wake_attempt"] = now_ts()
    atomic_json(STATE_PATH, state)
    success, detail = send_message(session, WAKE_MESSAGE)
    if success:
        state["last_successful_wake"] = now_ts()
        state["pending_events"] = {}
        decision = "WAKE_SENT"
    else:
        decision = "WAKE_FAILED"
    atomic_json(STATE_PATH, state)
    result = {"decision": decision, "wake_detail": detail, **common}
    log("check", **result)
    return result


def request_accessibility() -> int:
    if not HELPER_BIN.exists():
        print(json.dumps({"ok": False, "error": "HELPER_NOT_BUILT"}))
        return 2
    result = subprocess.run(
        [str(HELPER_BIN), "--request-accessibility"],
        text=True,
        check=False,
    )
    return result.returncode


def test_wake() -> int:
    session = resolve_session()
    if session is None:
        log("self_test", result="NO_ACTIVE_RESET_PROJECT_SESSION")
        return 2
    helper_ok, status = helper_probe()
    if not helper_ok:
        log("self_test", result="BLOCKED_WAKE_CHANNEL", detail=status)
        return 2
    success, detail = send_message(session, TEST_MESSAGE)
    log(
        "self_test",
        result="PASS" if success else "FAIL",
        session_id=session.cli_session_id,
        detail=detail,
    )
    return 0 if success else 1


def write_pid() -> None:
    if PID_PATH.exists():
        try:
            existing = int(PID_PATH.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing = 0
        if is_pid_alive(existing):
            raise RuntimeError(f"watchdog already running with PID {existing}")
    PID_PATH.write_text(f"{os.getpid()}\n", encoding="utf-8")


def remove_pid() -> None:
    try:
        if PID_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_PATH.unlink()
    except OSError:
        pass


def run_daemon() -> int:
    helper_ok, status = helper_probe()
    if not helper_ok:
        log(
            "startup_blocked",
            reason="wake helper lacks Accessibility permission",
            helper_status=status,
            user_action=(
                "Grant Accessibility permission to ReSETP Claude Quota Watchdog "
                "Helper in System Settings > Privacy & Security > Accessibility."
            ),
        )
        return 2

    write_pid()
    stopping = False

    def handle_signal(signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
        log("signal", signal=signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    log(
        "started",
        pid=os.getpid(),
        check_interval_seconds=CHECK_INTERVAL_SECONDS,
        stale_seconds=STALE_SECONDS,
        cooldown_seconds=COOLDOWN_SECONDS,
    )
    try:
        while not stopping:
            started = now_ts()
            try:
                evaluate_once(allow_wake=True)
            except Exception as exc:  # keep the long-running monitor auditable
                log("check_exception", error=type(exc).__name__, detail=str(exc))
            remaining = max(0.0, CHECK_INTERVAL_SECONDS - (now_ts() - started))
            deadline = now_ts() + remaining
            while not stopping and now_ts() < deadline:
                time.sleep(min(1.0, deadline - now_ts()))
    finally:
        remove_pid()
        log("stopped", pid=os.getpid())
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", action="store_true", help="print one dry-run decision")
    parser.add_argument(
        "--test-wake",
        action="store_true",
        help="send the fixed, explicitly marked self-test message",
    )
    parser.add_argument(
        "--request-accessibility",
        action="store_true",
        help="ask macOS to show the helper Accessibility permission prompt",
    )
    return parser.parse_args()


def main() -> int:
    DELIVERY_DIR.mkdir(parents=True, exist_ok=True)
    args = parse_args()
    if args.request_accessibility:
        return request_accessibility()
    if args.test_wake:
        return test_wake()
    if args.probe:
        result = evaluate_once(allow_wake=False)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return run_daemon()


if __name__ == "__main__":
    sys.exit(main())
