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
from typing import Any, BinaryIO


class Journal:
    def __init__(self, path: str, run_id: str):
        self.path = path
        self.run_id = run_id
        self.fsync_count = 0
        self._write_failed = False
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # Under the single-writer contract, repair interrupted framing before
        # deriving sequence numbers or allowing O_APPEND to extend the file.
        self._repair_tail()
        self._seq = self._next_seq()

    def _scan(self, fh: BinaryIO) -> tuple[list[dict], int]:
        """Return the intact prefix and its byte boundary; never hide corruption."""
        records: list[dict] = []
        intact_end = 0
        for number, raw in enumerate(fh, 1):
            try:
                line = raw.decode("utf-8").strip()
                record = json.loads(line) if line else None
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                # Only the last nonblank record can be a write interrupted by
                # SIGKILL. Anything after the damage makes this interior
                # corruption: truncation would destroy later durable records.
                if any(later.strip() for later in fh):
                    raise ValueError(f"journal interior corruption at line {number}") from exc
                return records, intact_end
            # The newline is part of append's framing. Even valid JSON without
            # it is an incomplete write; extending it would concatenate records.
            if not raw.endswith(b"\n"):
                return records, intact_end
            if line:
                records.append(record)
            intact_end = fh.tell()
        return records, intact_end

    def _repair_tail(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "rb") as fh:
            _, intact_end = self._scan(fh)
            size = os.fstat(fh.fileno()).st_size
        if intact_end < size:
            with open(self.path, "r+b") as fh:
                fh.truncate(intact_end)
                fh.flush()
                os.fsync(fh.fileno())
                self.fsync_count += 1

    def _next_seq(self) -> int:
        if not os.path.exists(self.path):
            return 0
        last = -1
        for rec in self.read():
            last = max(last, rec.get("seq", -1))
        return last + 1

    def append(self, kind: str, **payload: Any) -> dict:
        """Write one record and fsync. Returns the record as written."""
        if self._write_failed:
            raise RuntimeError("journal write failed; reopen before appending")
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
        # O_APPEND positions each write at EOF; one writer per workflow is
        # still required, including while completing a short write.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            remaining = memoryview(line.encode("utf-8"))
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("journal write made no progress")
                remaining = remaining[written:]
            os.fsync(fd)
            self.fsync_count += 1
        except BaseException:
            # A failed write may leave a torn tail. This instance must not
            # append past it; reopening performs the repair above.
            self._write_failed = True
            raise
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
        """Read the intact prefix; tolerate a torn tail, reject interior damage."""
        if not os.path.exists(self.path):
            return []
        with open(self.path, "rb") as fh:
            records, _ = self._scan(fh)
        return records

    def of_kind(self, *kinds: str) -> list[dict]:
        want = set(kinds)
        return [r for r in self.read() if r["kind"] in want]

    def __iter__(self) -> Iterator[dict]:
        return iter(self.read())
