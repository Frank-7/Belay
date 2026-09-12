"""Append-only journal with per-record fsync.

This is deliberately boring. Every runtime under test writes to the same
journal implementation so that differences in the experiment come from
recovery *semantics*, not from storage quality.

Durability model: a record is durable once `append` returns. We fsync the
file descriptor after every write. The process may be SIGKILLed at any
instruction; anything that has not returned from `append` is presumed lost.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any


class Journal:
    def __init__(self, path: str, run_id: str):
        self.path = path
        self.run_id = run_id
        self._seq = self._next_seq()
        self.fsync_count = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _next_seq(self) -> int:
        if not os.path.exists(self.path):
            return 0
        last = -1
        for rec in self.read():
            last = max(last, rec.get("seq", -1))
        return last + 1

    def append(self, kind: str, **payload: Any) -> dict:
        """Write one record and fsync. Returns the record as written."""
        rec = {
            "seq": self._seq,
            "ts": time.time(),
            "run_id": self.run_id,
            "pid": os.getpid(),
            "kind": kind,
            **payload,
        }
        self._seq += 1
        line = json.dumps(rec, sort_keys=False) + "\n"
        # O_APPEND keeps concurrent writers from interleaving partial lines.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
            self.fsync_count += 1
        finally:
            os.close(fd)
        return rec

    def observe(self, kind: str, **payload: Any) -> None:
        """Write to the observability sidecar, never to recovery state.

        Some experiments need to see a value that the runtime under test
        deliberately did NOT persist (an inline model decision, say). We
        record it here so the analysis and the trace viewer can show it.

        Nothing under `belay/runtimes/` reads trace.jsonl. It is not
        state. If a runtime ever read it, the experiment would be measuring
        the sidecar instead of the runtime.
        """
        import json as _json

        rec = {"ts": time.time(), "pid": os.getpid(), "run_id": self.run_id,
               "kind": kind, **payload}
        path = os.path.join(os.path.dirname(self.path) or ".", "trace.jsonl")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, (_json.dumps(rec) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def read(self) -> list[dict]:
        """Read all durable records. Tolerates a torn final line."""
        if not os.path.exists(self.path):
            return []
        out: list[dict] = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # A torn write at the tail. Treat as never having happened.
                    break
        return out

    def of_kind(self, *kinds: str) -> list[dict]:
        want = set(kinds)
        return [r for r in self.read() if r["kind"] in want]

    def __iter__(self) -> Iterator[dict]:
        return iter(self.read())
