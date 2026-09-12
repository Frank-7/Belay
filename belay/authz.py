"""Permission store held outside the agent process.

Permissions are read from disk at the moment of execution, not cached at
planning time. This is the whole point: an agent that planned an action
three seconds ago does not thereby hold a licence to perform it now.

The harness can revoke a scope while a worker is mid-workflow, which is how
we test contract invariant 2.
"""

from __future__ import annotations

import json
import os


class Denied(Exception):
    def __init__(self, scope: str):
        super().__init__(f"scope not held at execution time: {scope}")
        self.scope = scope


class PermissionStore:
    def __init__(self, path: str):
        self.path = path

    def grant_all(self, scopes: list[str]) -> None:
        self._write({s: True for s in scopes})

    def revoke(self, scope: str) -> None:
        state = self._read()
        state[scope] = False
        self._write(state)

    def held(self, scope: str) -> bool:
        return bool(self._read().get(scope, False))

    def require(self, scope: str) -> None:
        """Check at the instant of use. Raises Denied if not held."""
        if not self.held(scope):
            raise Denied(scope)

    def snapshot(self) -> dict:
        return self._read()

    def _read(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _write(self, state: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
