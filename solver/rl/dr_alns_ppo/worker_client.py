from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from .schemas import BlockDecodedAction, DecodedAction, LearnedDestroyDecodedAction


RESTORATION_FINGERPRINT = Path("solver/reports/dr_alns_ppo_v2/restoration/phase1_env_fingerprints.json")
WORKER_PYTHON_ENV = "SETP_WORKER_PYTHON"
WORKER_CRASH_LOG_DIR_ENV = "SETP_WORKER_CRASH_LOG_DIR"
WORKER_CRASH_LOG_ENV = "SETP_WORKER_CRASH_LOG"


class WorkerClient:
    def __init__(self, bundle_dir: str | Path, *, seed: int, max_evals: int) -> None:
        self._request_id = 0
        self._closed = False
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self._repo_root = _repo_root()
        resolved_bundle_dir = _resolve_bundle_dir(bundle_dir, self._repo_root)
        worker_python = resolve_worker_python(self._repo_root)
        self.worker_python = str(worker_python)
        self._crash_log_path = _allocate_crash_log(self._repo_root)
        cmd = [
            str(worker_python),
            "-m",
            "dr_alns_ppo.worker",
            "--bundle-dir",
            str(resolved_bundle_dir),
            "--seed",
            str(seed),
            "--max-evals",
            str(max_evals),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(self._repo_root),
            env=_worker_env(self._repo_root, crash_log_path=self._crash_log_path),
        )

    def reset(self) -> dict[str, Any]:
        return self._request({"op": "reset"})

    def step(self, decoded_action: DecodedAction) -> dict[str, Any]:
        action = asdict(decoded_action)
        return self._request({"op": "step", "action": action})

    def block_step(self, decoded_action: BlockDecodedAction | LearnedDestroyDecodedAction) -> dict[str, Any]:
        action = asdict(decoded_action)
        return self._request({"op": "block_step", "action": action})

    def best_of_k_destroy(self, action: dict[str, Any]) -> dict[str, Any]:
        return self._request({"op": "best_of_k_destroy", "action": dict(action)})

    def close(self) -> dict[str, Any] | None:
        if self._closed:
            return None
        response: dict[str, Any] | None = None
        try:
            if self._proc.poll() is None:
                response = self._request({"op": "close"})
                self._proc.wait(timeout=5)
            else:
                self._reap_exited_worker()
        except Exception:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
            else:
                self._reap_exited_worker()
        finally:
            self._closed = True
            self._close_streams()
        return response

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError(f"worker client is closed; request={payload!r}")
        self._request_id += 1
        request = {"request_id": self._request_id, **payload}
        proc = self._proc
        if proc.poll() is not None:
            raise RuntimeError(self._error_message("worker exited before request", request))
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError(self._error_message("worker pipes are not available", request))
        try:
            proc.stdin.write(json.dumps(request, separators=(",", ":"), allow_nan=False) + "\n")
            proc.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError(self._error_message(f"worker pipe broke: {exc}", request)) from exc

        line = proc.stdout.readline()
        if line == "":
            raise RuntimeError(self._error_message("worker exited without a response", request))
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                self._error_message(f"worker returned malformed JSON: {line.rstrip()!r}; {exc}", request)
            ) from exc
        if not isinstance(response, dict):
            raise RuntimeError(self._error_message(f"worker response is not an object: {response!r}", request))
        return response

    def _error_message(self, reason: str, request: dict[str, Any]) -> str:
        return (
            f"{reason}; request={request!r}; stderr_tail={self._stderr_tail()!r}; "
            f"crash_log={str(self._crash_log_path)!r}; crash_log_tail={self._crash_log_tail()!r}"
        )

    def _stderr_tail(self, limit: int = 4000) -> str:
        try:
            self._stderr.flush()
            self._stderr.seek(0)
            data = self._stderr.read()
            return data[-limit:]
        except Exception:
            return ""

    def _close_streams(self) -> None:
        for stream in (self._proc.stdin, self._proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        try:
            self._stderr.close()
        except Exception:
            pass

    def _reap_exited_worker(self) -> None:
        try:
            self._proc.wait(timeout=0)
        except subprocess.TimeoutExpired:
            pass

    def _crash_log_tail(self, limit: int = 4000) -> str:
        try:
            if not self._crash_log_path.exists():
                return ""
            return self._crash_log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except Exception:
            return ""


__all__ = ["WorkerClient", "resolve_worker_python", "_worker_env"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_bundle_dir(bundle_dir: str | Path, repo_root: Path) -> Path:
    path = Path(bundle_dir)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def resolve_worker_python(repo_root: Path | None = None) -> Path:
    """Resolve the Python interpreter used by solver workers.

    The PPO process may run inside the RL venv, but solver workers should use
    the system Python environment that produced the audited winner baseline.
    """

    root = _repo_root() if repo_root is None else Path(repo_root)
    configured = os.environ.get(WORKER_PYTHON_ENV)
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        else:
            candidate = candidate.resolve()
        _require_executable(candidate, source=WORKER_PYTHON_ENV)
        return candidate
    auto = _auto_worker_python(root)
    if auto is not None:
        return auto
    print(
        "WARNING: SETP worker using current Python interpreter; if this is the RL venv, "
        "winner-kernel costs may drift from the system-Python anchor. "
        f"Set {WORKER_PYTHON_ENV} to the audited system Python.",
        file=sys.stderr,
    )
    return Path(sys.executable).resolve()


@lru_cache(maxsize=8)
def _auto_worker_python(repo_root_text: str | Path) -> Path | None:
    root = Path(repo_root_text)
    candidates: list[Path] = []
    fingerprint = root / RESTORATION_FINGERPRINT
    if fingerprint.exists():
        try:
            payload = json.loads(fingerprint.read_text(encoding="utf-8"))
            executable = payload.get("fingerprints", {}).get("system", {}).get("executable")
            if executable:
                candidates.append(Path(str(executable)))
        except Exception:
            pass
    candidates.extend(
        [
            Path("/opt/anaconda3/bin/python"),
            Path("/opt/homebrew/bin/python3"),
            Path("/usr/local/bin/python3"),
            Path("/usr/bin/python3"),
        ]
    )
    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if str(resolved) in seen:
            continue
        seen.add(str(resolved))
        if not _is_executable(resolved):
            continue
        if _candidate_can_import_worker(resolved, root):
            return resolved
    return None


def _require_executable(path: Path, *, source: str) -> None:
    if not _is_executable(path):
        raise RuntimeError(f"{source} points to a non-executable Python: {path}")


def _is_executable(path: Path) -> bool:
    return path.exists() and path.is_file() and os.access(path, os.X_OK)


@lru_cache(maxsize=16)
def _candidate_can_import_worker(python_exe: Path, repo_root: Path) -> bool:
    proc = subprocess.run(
        [
            str(python_exe),
            "-c",
            "import numpy; import setp_solver; import dr_alns_ppo.worker; print('ok')",
        ],
        cwd=repo_root,
        env=_worker_env(repo_root),
        text=True,
        capture_output=True,
        check=False,
        timeout=30.0,
    )
    return proc.returncode == 0


def _worker_env(
    repo_root: Path,
    *,
    crash_log_dir: str | Path | None = None,
    crash_log_path: str | Path | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    entries = [
        str(repo_root / "solver" / "rl"),
        str(repo_root / "solver" / "src"),
        str(repo_root / "models" / "src"),
    ]
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONFAULTHANDLER"] = "1"
    log_dir = Path(crash_log_dir) if crash_log_dir is not None else _default_crash_log_dir(repo_root)
    env[WORKER_CRASH_LOG_DIR_ENV] = str(log_dir)
    if crash_log_path is not None:
        env[WORKER_CRASH_LOG_ENV] = str(Path(crash_log_path))
    return env


def _default_crash_log_dir(repo_root: Path) -> Path:
    return Path(repo_root) / "solver" / "reports" / "dr_alns_ppo_v3" / "worker_crash_logs"


def _allocate_crash_log(repo_root: Path) -> Path:
    directory = _default_crash_log_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"worker_{os.getpid()}_{uuid.uuid4().hex}.log"
