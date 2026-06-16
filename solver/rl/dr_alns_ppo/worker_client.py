from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .schemas import DecodedAction


class WorkerClient:
    def __init__(self, bundle_dir: str | Path, *, seed: int, max_evals: int) -> None:
        self._request_id = 0
        self._closed = False
        self._stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        self._repo_root = _repo_root()
        resolved_bundle_dir = _resolve_bundle_dir(bundle_dir, self._repo_root)
        cmd = [
            sys.executable,
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
            env=_worker_env(self._repo_root),
        )

    def reset(self) -> dict[str, Any]:
        return self._request({"op": "reset"})

    def step(self, decoded_action: DecodedAction) -> dict[str, Any]:
        action = asdict(decoded_action)
        return self._request({"op": "step", "action": action})

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
        return f"{reason}; request={request!r}; stderr_tail={self._stderr_tail()!r}"

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


__all__ = ["WorkerClient"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_bundle_dir(bundle_dir: str | Path, repo_root: Path) -> Path:
    path = Path(bundle_dir)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _worker_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    entries = [
        str(repo_root / "solver" / "rl"),
        str(repo_root / "solver" / "src"),
        str(repo_root / "models" / "src"),
    ]
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env["PYTHONNOUSERSITE"] = "1"
    return env
