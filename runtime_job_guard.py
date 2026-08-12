#!/usr/bin/env python3
"""Small runtime guards for Render-heavy market jobs."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCK_FILE = BASE_DIR / ".market_heavy_job.lock"


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_lock_payload(path: Path = DEFAULT_LOCK_FILE) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


class InterProcessJobLock:
    def __init__(self, name: str, path: Path = DEFAULT_LOCK_FILE, stale_after_seconds: int = 7200) -> None:
        self.name = name
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def acquire(self) -> tuple[bool, dict]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                payload = {
                    "name": self.name,
                    "pid": os.getpid(),
                    "started_at": now,
                    "updated_at": now,
                }
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                self.acquired = True
                return True, payload
            except FileExistsError:
                payload = read_lock_payload(self.path)
                pid = int(payload.get("pid") or 0)
                started_at = float(payload.get("started_at") or self.path.stat().st_mtime)
                if not process_is_alive(pid) or now - started_at > self.stale_after_seconds:
                    try:
                        self.path.unlink(missing_ok=True)
                        continue
                    except OSError:
                        pass
                return False, payload

    def release(self) -> None:
        if not self.acquired:
            return
        payload = read_lock_payload(self.path)
        if int(payload.get("pid") or 0) == os.getpid():
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
        self.acquired = False

    def __enter__(self) -> "InterProcessJobLock":
        ok, payload = self.acquire()
        if not ok:
            holder = payload.get("name") or "unknown"
            pid = payload.get("pid") or "unknown"
            raise RuntimeError(f"heavy job already running: {holder} pid={pid}")
        return self

    def __exit__(self, exc_type, exc, tb) -> Optional[bool]:
        self.release()
        return None
