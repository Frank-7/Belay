"""Out-of-band evidence: pointers, deterministic fetch, and coverage.

CONTRACT.md S4 proves that on an `opaque` service a lost acknowledgement is
undecidable *from the journal and the service API*. The outside world keeps
other records, though, and this module is the typed interface to them.

Three ideas, in order of importance.

**A pointer is not evidence.** The agent emits pointers; `EvidenceStore.fetch`
resolves them. A pointer to a source that does not exist, or a selector the
source cannot answer, returns `None`. So a fabricated pointer yields no
observation, and `second/adjudicate.py` will not let an uncited verdict
stand. This is the structural reason a hallucinating agent is safe here.

**Silence is an observation, but its weight comes from coverage.** A query
that matches nothing still returns an `Observation` -- with an empty match
list. Whether that silence *proves absence* depends entirely on what the
source claims about its own completeness, which is why every source carries
a manifest and why the validator requires the manifest to be cited
alongside the silence.

**Coverage is the honest part.** Two kinds:

  `complete_until(cutoff_ts)`
      A settlement report. Authoritative and exhaustive for events at or
      before the cutoff; says nothing about what happened after. This is
      how batch financial reporting actually behaves, and it is the reason
      a crash inside the settlement window stays ambiguous.

  `lossy(drop_rate)`
      A webhook archive. A hit is proof of commitment; silence proves
      nothing at all, ever, at any drop rate above zero. A source like this
      can confirm but can never exonerate.

Note the asymmetry that falls out: any source can prove an effect
*happened*. Only a source that claims completeness over the relevant window
can prove one *did not*. Half the abstentions in the experiment come from
exactly that gap, and they are correct abstentions.

Artefacts are JSON files on disk, written by `experiments/build_evidence.py`
(grader side, allowed to read the ledger). Nothing here reads the ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Selector grammar. Kept tiny on purpose: a wide pointer vocabulary would
# mean a wide surface for the agent to be wrong on in ways the fetcher
# cannot check.
SEL_MANIFEST = "manifest"
SEL_ORDER = "order"          # order:<order_id>
SEL_ANCHOR = "anchor"        # anchor:<hex>  -- unsupported by opaque sources


@dataclass(frozen=True)
class Pointer:
    """Where to look. The agent's only structured output."""

    source: str
    selector: str

    @classmethod
    def parse(cls, raw: Any) -> Pointer | None:
        """Parse `source:selector`. Returns None on anything malformed.

        Returning None rather than raising is deliberate: a malformed
        pointer is an ordinary thing for a model to emit, and it should cost
        the adjudication one unfetchable pointer, not an exception.
        """
        if not isinstance(raw, str):
            return None
        head, _, tail = raw.partition(":")
        head, tail = head.strip(), tail.strip()
        if not head or not tail:
            return None
        return cls(source=head, selector=tail)

    @property
    def kind(self) -> str:
        return self.selector.split(":", 1)[0]

    @property
    def arg(self) -> str:
        return self.selector.split(":", 1)[1] if ":" in self.selector else ""

    def __str__(self) -> str:
        return f"{self.source}:{self.selector}"


@dataclass(frozen=True)
class Observation:
    """A fetched artefact. The only thing a dossier may cite.

    `digest` is the citation identity: the agent cites digests, and the
    validator checks each cited digest against the observations this
    adjudication actually fetched. A digest the agent invents matches
    nothing.
    """

    pointer: Pointer
    payload: dict
    provenance: str
    fetched_at: float = field(default_factory=time.time)

    @property
    def digest(self) -> str:
        canon = json.dumps(
            {"pointer": str(self.pointer), "payload": self.payload},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

    @property
    def matches(self) -> list[dict]:
        return list(self.payload.get("matches", []))

    def as_dict(self) -> dict:
        return {
            "pointer": str(self.pointer),
            "digest": self.digest,
            "provenance": self.provenance,
            "payload": self.payload,
        }


# --------------------------------------------------------------------------
# Coverage
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    kind: str                     # "complete_until" | "lossy"
    cutoff_ts: float | None = None
    drop_rate: float | None = None
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Coverage:
        return cls(
            kind=str(d.get("kind", "lossy")),
            cutoff_ts=d.get("cutoff_ts"),
            drop_rate=d.get("drop_rate"),
            note=str(d.get("note", "")),
        )

    def proves_absence_at(self, ts: float) -> bool:
        """Can silence from this source rule out an event at time `ts`?

        Only a source claiming exhaustive coverage of a window containing
        `ts` can. A lossy source never can, whatever its drop rate -- which
        is the point of modelling it separately.
        """
        if self.kind != "complete_until":
            return False
        return self.cutoff_ts is not None and ts <= self.cutoff_ts

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "cutoff_ts": self.cutoff_ts,
            "drop_rate": self.drop_rate,
            "note": self.note,
        }


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


class EvidenceStore:
    """Reads evidence artefacts from a directory. Deterministic, read-only.

    This is the fetcher that sits between the agent and anything durable.
    It has no model in it and no judgement in it; it either resolves a
    pointer or does not.
    """

    def __init__(self, evidence_dir: str):
        self.dir = evidence_dir
        self._root = Path(evidence_dir).resolve()
        self._cache: dict[str, dict] = {}
        self.fetch_log: list[dict] = []

    # -- catalogue ---------------------------------------------------------

    def catalog(self) -> list[str]:
        """Source names present on disk. The agent is told this much; it is
        not told what the sources contain."""
        try:
            names = os.listdir(self._root)
        except OSError:
            return []
        return sorted(
            f[:-5] for f in names
            if f.endswith(".json") and not f.startswith(".")
            and self._source_path(f[:-5]) is not None
        )

    def _source_path(self, source: str) -> Path | None:
        """Resolve a source basename inside the configured evidence root.

        Check both platforms' path syntax, then the actual symlink target.
        This runs before cache access too: replacing a cached source with an
        outside symlink must not keep that source available to the agent.
        """
        if (
            not isinstance(source, str) or not source or source in (".", "..")
            or any(char in source for char in ("/", "\\", ":", "\x00"))
        ):
            return None
        try:
            path = (self._root / f"{source}.json").resolve()
            if not path.is_relative_to(self._root) or not path.is_file():
                return None
        except (OSError, ValueError, RuntimeError):
            return None
        return path

    def _load(self, source: str) -> dict | None:
        path = self._source_path(source)
        if path is None:
            return None
        if source in self._cache:
            return self._cache[source]
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        self._cache[source] = doc
        return doc

    def coverage(self, source: str) -> Coverage | None:
        doc = self._load(source)
        if doc is None:
            return None
        return Coverage.from_dict(doc.get("coverage", {}))

    # -- fetch -------------------------------------------------------------

    def fetch(self, pointer: Pointer | None) -> Observation | None:
        """Resolve one pointer, or return None.

        None means "this pointer named nothing retrievable". Every path that
        can fail returns None rather than raising, and every attempt is
        logged so the experiment can report how many pointers an agent
        wasted.
        """
        ok = False
        try:
            if pointer is None:
                return None
            doc = self._load(pointer.source)
            if doc is None:
                return None
            records = doc.get("records") or []
            cov = Coverage.from_dict(doc.get("coverage", {}))
            path = os.path.join(self.dir, f"{pointer.source}.json")

            if pointer.kind == SEL_MANIFEST:
                ok = True
                return Observation(
                    pointer=pointer,
                    payload={
                        "source": pointer.source,
                        "coverage": cov.as_dict(),
                        "record_count": len(records),
                    },
                    provenance=f"{path}#coverage",
                )

            if pointer.kind == SEL_ORDER:
                ok = True
                hits = [r for r in records if r.get("order_id") == pointer.arg]
                return Observation(
                    pointer=pointer,
                    payload={
                        "source": pointer.source,
                        "selector": pointer.selector,
                        "matches": hits,
                    },
                    provenance=f"{path}#order={pointer.arg}",
                )

            if pointer.kind == SEL_ANCHOR:
                # An opaque service never received a caller key, so its
                # records carry no anchor and the question is unanswerable.
                # This is a realistic wrong turn for an agent to take, and
                # the fetcher declining it is the whole mechanism in
                # miniature: we do not synthesise an answer to a question
                # the source cannot answer.
                if not any(r.get("anchor") for r in records):
                    return None
                ok = True
                hits = [r for r in records if r.get("anchor") == pointer.arg]
                return Observation(
                    pointer=pointer,
                    payload={
                        "source": pointer.source,
                        "selector": pointer.selector,
                        "matches": hits,
                    },
                    provenance=f"{path}#anchor={pointer.arg}",
                )

            return None
        finally:
            self.fetch_log.append(
                {"pointer": str(pointer) if pointer else None, "resolved": ok}
            )
