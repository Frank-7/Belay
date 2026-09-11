"""The ledger is the oracle.

It records what the outside world actually did, independently of anything
the agent or runtime believes. Experiments grade a run by comparing the
runtime's reported outcome against this table. Nothing in `belay/` is
allowed to read it during a run.

SQLite with synchronous=FULL. Because our crashes are SIGKILL to a process
rather than a machine failure, a committed transaction is durable with
certainty, which is what we want: a lost acknowledgement must never mean a
lost effect.
"""

from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS committed (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    service      TEXT NOT NULL,
    kind         TEXT NOT NULL,
    order_id     TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    idem_key     TEXT,
    client_ref   TEXT,
    ts           REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idem ON committed(service, idem_key);
CREATE INDEX IF NOT EXISTS idx_ref  ON committed(service, client_ref);
CREATE INDEX IF NOT EXISTS idx_ord  ON committed(order_id);
"""


class Ledger:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(SCHEMA)
        self._conn.row_factory = sqlite3.Row

    def commit_effect(
        self,
        service: str,
        kind: str,
        order_id: str,
        amount_cents: int,
        idem_key: str | None = None,
        client_ref: str | None = None,
    ) -> int:
        import time

        cur = self._conn.execute(
            "INSERT INTO committed(service,kind,order_id,amount_cents,idem_key,client_ref,ts)"
            " VALUES (?,?,?,?,?,?,?)",
            (service, kind, order_id, amount_cents, idem_key, client_ref, time.time()),
        )
        return int(cur.lastrowid)

    def by_idem(self, service: str, idem_key: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM committed WHERE service=? AND idem_key=? ORDER BY id LIMIT 1",
            (service, idem_key),
        ).fetchone()

    def by_client_ref(self, service: str, client_ref: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM committed WHERE service=? AND client_ref=? ORDER BY id LIMIT 1",
            (service, client_ref),
        ).fetchone()

    def for_order(self, order_id: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM committed WHERE order_id=? ORDER BY id", (order_id,)
            ).fetchall()
        )

    def close(self) -> None:
        self._conn.close()
