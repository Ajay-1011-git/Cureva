"""Cureva Stage 1 — the graded contract: StudyGraph and Atlas.

This module is deliberately network-free. It imports only the standard library,
pydantic (via `schemas`) and `study` — never `intake/`, `graph/`, `requests` or
an LLM SDK. `run_local_harness.py` must be able to import and score it in an
environment with no internet access at all (cureva-stage1-trd.md §2).

Nothing observed in the practice study — no subject id, no site id, no record
count, no threshold — appears in a conditional anywhere in this file. Practice
values appear only in comments, as worked examples.
"""
from __future__ import annotations

import time
from bisect import bisect_right
from pathlib import Path
from typing import Any, Iterable

from schemas import Answer, Question
from study import DOMAINS as CSV_DOMAINS
from study import SEQ_COL, Study, parse_date, standardise_lab, to_number

#: The nine organiser domains plus Cureva's PRO, the tenth. PRO is written only
#: by intake/ (Act 1) and is always present and always empty here — a graded run
#: against a hidden study carries zero PRO records (PRD FR-20/G7).
PRO_DOMAIN = "PRO"
ALL_DOMAINS: tuple[str, ...] = tuple(CSV_DOMAINS) + (PRO_DOMAIN,)

#: Sequence column name per domain. DM has no sequence column — one row per
#: subject — and PRO uses a plain "seq", written by intake/pro_writer.
SEQ_COLUMN: dict[str, str | None] = dict(SEQ_COL) | {"DM": None, PRO_DOMAIN: "seq"}


def site_of(usubjid: str | None) -> str | None:
    """Site id out of a USUBJID formatted '<study>-<site>-<subject>'.

    Fallback only: StudyGraph prefers DM.SITEID, which is the study's own
    statement of where a subject is enrolled. This is used for subjects that
    have records in other domains but no DM row.

    study.Study.records(site=...) matches on the literal prefix "042-", which is
    this practice study's own id and would silently match nothing on a hidden
    study. Splitting on the separator works for any study id, so every site
    filter in this module goes through here or through DM.SITEID instead.
    """
    if not usubjid:
        return None
    parts = str(usubjid).split("-")
    return parts[1] if len(parts) >= 3 else None


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class StudyGraph:
    """The study, loaded once and indexed for O(1) lookup.

    Deliberately not a graph library. The organiser's own solution-design
    template flags networkx's per-build cost as unaffordable at this scale
    (~27k records, rebuilt per cut, across several hidden studies), and the
    only relationship this data actually has is subject -> record, which a dict
    of lists represents exactly. networkx earns its place in graph/ (Act 2),
    where the graph is genuinely a graph and genuinely small.

    Indices built once in __init__ and never rebuilt:
        by_domain[domain]                       -> list[record]
        by_usubjid_domain[(usubjid, domain)]    -> list[record]
        by_key[(domain, usubjid, seq)]          -> record
        reference_ranges[(testcd, lab)]         -> (unit, low, high)
        corrections_index[(domain, usubjid, seq, field)] -> [(cut, new_value)]

    Each record dict is augmented with derived fields, all underscore-prefixed
    so they can never collide with a column a hidden study adds:
        _domain, _seq (int|None), _cut (int), _site, _corrected_at (int|None)
    """

    def __init__(self, data_dir: str):
        self.data_dir = str(data_dir)
        self.study = Study(data_dir)

        #: Raw reference_ranges rows, passed straight to study.standardise_lab.
        self.ranges: list[dict] = self.study.ranges

        self.by_domain: dict[str, list[dict]] = {}
        self.by_usubjid_domain: dict[tuple[str, str], list[dict]] = {}
        self.by_key: dict[tuple[str, str, int | None], dict] = {}

        # Where each subject is enrolled, from DM.SITEID — the study's own
        # statement, rather than a substring of the id. On the practice study
        # the two agree for all 241 subjects; preferring the column means a
        # hidden study that formats USUBJID differently still resolves sites
        # correctly. site_of() covers subjects with no DM row.
        self.site_by_subject: dict[str, str] = {}
        for row in self.study.domains.get("DM", []):
            usubjid = (row.get("USUBJID") or "").strip()
            siteid = (row.get("SITEID") or "").strip()
            if usubjid and siteid:
                self.site_by_subject[usubjid] = siteid

        for domain in CSV_DOMAINS:
            rows = self.study.domains.get(domain, [])
            kept: list[dict] = []
            for row in rows:
                usubjid = (row.get("USUBJID") or "").strip()
                if not usubjid:
                    # A row with no subject cannot be cited as evidence or
                    # joined to anything. Skipped, never fatal (PRD NFR-2).
                    self._malformed += 1
                    continue
                seq_col = SEQ_COLUMN.get(domain)
                row["_domain"] = domain
                row["_seq"] = _as_int(row.get(seq_col)) if seq_col else None
                row["_cut"] = _as_int(row.get("cut_available"), 1) or 1
                row["_site"] = self.site_by_subject.get(usubjid) or site_of(usubjid)
                row["_corrected_at"] = _as_int(row.get("corrected_at_cut"))
                kept.append(row)
                self.by_usubjid_domain.setdefault((usubjid, domain), []).append(row)
                self.by_key[(domain, usubjid, row["_seq"])] = row
            self.by_domain[domain] = kept

        # The tenth domain. Reserved, indexed, and empty — StudyGraph must
        # construct and behave identically whether or not anything ever writes
        # to it. intake/pro_writer appends here in place, without a rebuild.
        self.by_domain[PRO_DOMAIN] = []

        # (LBTESTCD, LAB) -> (UNIT, LOW, HIGH). Pre-indexed so a lookup during a
        # threshold comparison is a dict hit, not a scan of the ranges list.
        self.reference_ranges: dict[tuple[str, str], tuple[str, float | None, float | None]] = {}
        for r in self.ranges:
            testcd = (r.get("LBTESTCD") or "").strip().upper()
            lab = (r.get("LAB") or "").strip().upper()
            if testcd:
                self.reference_ranges[(testcd, lab)] = (
                    (r.get("UNIT") or "").strip(), to_number(r.get("LOW")), to_number(r.get("HIGH")))

        # (domain, usubjid, seq, field) -> [(cut, new_value), ...] ascending by
        # cut, so "the value as of cut N" is a bisect rather than a scan.
        #
        # Direction matters and is easy to get backwards: the domain CSV carries
        # the value as it stood BEFORE the correction (verified on all 200
        # practice corrections — 187 differ from new_value, the other 13 are
        # no-ops where old_value == new_value). So a correction is applied when
        # viewing cut >= its cut, and the raw CSV value stands below that.
        self.corrections_index: dict[tuple[str, str, int | None, str], list[tuple[int, str]]] = {}
        for c in self.study.corrections:
            key = ((c.get("domain") or "").strip().upper(),
                   (c.get("usubjid") or "").strip(),
                   _as_int(c.get("seq")),
                   (c.get("field") or "").strip())
            cut = _as_int(c.get("cut"))
            if cut is None or not key[0] or not key[1]:
                self._malformed += 1
                continue
            self.corrections_index.setdefault(key, []).append((cut, c.get("new_value")))
        for hist in self.corrections_index.values():
            hist.sort(key=lambda t: t[0])

        # cut -> protocol_version, from cuts.csv.
        self.cut_protocol: dict[int, int] = {}
        for r in self.study.cuts:
            cut = _as_int(r.get("cut"))
            ver = _as_int(r.get("protocol_version"), 1)
            if cut is not None:
                self.cut_protocol[cut] = ver or 1

        self._doc_mtimes: dict[str, float] = {}
        self._doc_cache: dict[str, str] = {}
        self._snapshot_cut: int | None = None
        self._stats: dict = {}

    # ---------------------------------------------------------------- loading
    _malformed = 0

    @property
    def malformed_rows(self) -> int:
        """Rows skipped at load time for being unusable. Counted, never fatal."""
        return self._malformed

    # -------------------------------------------------------------- documents
    @property
    def documents_dir(self) -> Path:
        return Path(self.data_dir) / "documents"

    def document(self, name: str) -> str:
        """A document's text, re-read from disk whenever the file has changed.

        Cached per file mtime rather than per process: an amendment dropped into
        the folder mid-run is picked up on the next call, and only that file's
        entry is invalidated (PRD FR-4/FR-5, TRD §7). Never answer from a stale
        protocol.
        """
        path = self.documents_dir / f"{name}.md"
        if not path.exists():
            raise KeyError(f"{name} — have: {sorted(self.document_names())}")
        mtime = path.stat().st_mtime
        if self._doc_mtimes.get(name) != mtime or name not in self._doc_cache:
            self._doc_cache[name] = path.read_text()
            self._doc_mtimes[name] = mtime
        return self._doc_cache[name]

    def document_names(self) -> list[str]:
        """Every document currently on disk — re-listed, not cached, so a file
        added after construction is visible."""
        if not self.documents_dir.exists():
            return []
        return sorted(p.stem for p in self.documents_dir.glob("*.md"))

    def reload_documents(self) -> list[str]:
        """Drop every cached document. Mirrors study.Study.reload_documents."""
        before = set(self._doc_cache)
        self._doc_cache.clear()
        self._doc_mtimes.clear()
        return sorted(set(self.document_names()) - before)

    def protocol_version_at(self, cut: int | None) -> int:
        """Protocol version in force at a cut, from cuts.csv.

        cut=None means "the whole study as it stands", so it resolves to the
        latest version the study ever reached — the same version cut 12 sees.
        An unknown cut falls back to the newest version at or before it, and to
        the earliest version if it precedes every listed cut.
        """
        if not self.cut_protocol:
            return 1
        if cut is None:
            return max(self.cut_protocol.values())
        if cut in self.cut_protocol:
            return self.cut_protocol[cut]
        earlier = [c for c in self.cut_protocol if c <= cut]
        if earlier:
            return self.cut_protocol[max(earlier)]
        return self.cut_protocol[min(self.cut_protocol)]

    def protocol_document_at(self, cut: int | None) -> tuple[str, str]:
        """(document_name, text) of the protocol in force at a cut."""
        version = self.protocol_version_at(cut)
        name = f"protocol_v{version}"
        try:
            return name, self.document(name)
        except KeyError:
            # A hidden study may name or number its protocol differently. Fall
            # back to the newest protocol_v* actually on disk rather than fail.
            candidates = sorted(n for n in self.document_names() if n.startswith("protocol"))
            if not candidates:
                raise
            name = candidates[-1]
            return name, self.document(name)

    # ------------------------------------------------------------ corrections
    def value_at_cut(self, domain: str, usubjid: str, seq: int | None,
                     field: str, raw_value: Any, cut: int | None) -> Any:
        """A field's value as it stood at `cut`, applying any correction due by then.

        The domain CSV holds the pre-correction value, so this returns the raw
        value below the correction's cut and the corrected value at or above it.
        cut=None means the latest view, so every correction applies.
        """
        hist = self.corrections_index.get((domain.upper(), usubjid, seq, field))
        if not hist:
            return raw_value
        if cut is None:
            return hist[-1][1]
        i = bisect_right([c for c, _ in hist], cut)
        return hist[i - 1][1] if i else raw_value

    def record_value(self, record: dict, field: str, cut: int | None = "unset") -> Any:
        """A record's field, corrected for whichever cut the graph was built at.

        Every read of a correctable field should go through here rather than
        record[field] — that is what makes "the value as of this cut" true
        everywhere instead of only where someone remembered.
        """
        if cut == "unset":
            cut = self._snapshot_cut
        return self.value_at_cut(record["_domain"], record.get("USUBJID", ""),
                                 record.get("_seq"), field, record.get(field), cut)

    # ---------------------------------------------------------------- records
    def records(self, domain: str, cut: int | None = "unset", site: str | None = None,
                usubjid: str | None = None, visit: str | None = None) -> list[dict]:
        """Rows from one domain, filtered. Index lookups, never a CSV re-read."""
        domain = domain.upper()
        if cut == "unset":
            cut = self._snapshot_cut
        if usubjid:
            rows: Iterable[dict] = self.by_usubjid_domain.get((usubjid, domain), [])
        else:
            rows = self.by_domain.get(domain, [])
        out = []
        for r in rows:
            if cut is not None and r["_cut"] > cut:
                continue
            if site and r["_site"] != site:
                continue
            if visit and r.get("VISIT") != visit:
                continue
            out.append(r)
        return out

    def subjects(self, cut: int | None = "unset") -> list[dict]:
        return self.records("DM", cut=cut)

    def sites(self) -> list[str]:
        """Every site with at least one enrolled subject."""
        return sorted({s for s in (r["_site"] for r in self.by_domain["DM"]) if s})

    def site_for(self, usubjid: str | None) -> str | None:
        """The site a subject belongs to. DM.SITEID first, id shape as fallback."""
        if not usubjid:
            return None
        return self.site_by_subject.get(usubjid) or site_of(usubjid)

    # ------------------------------------------------------------------ build
    def build(self, cut: int | None = None) -> dict:
        """Snapshot the study at one cut and return the stats the grader reads.

        Returns exactly::

            {"nodes": int, "edges": int, "subjects": int, "cut": int|None, "ms": int}

        Definitions, stated here so they are not ambiguous later:

        * **nodes**  — every record visible at `cut`, across all ten domains
          (PRO included; zero on any graded run). One record is one node.
        * **edges**  — subject -> record links. Every record belongs to exactly
          one subject, so this equals `nodes` minus any record whose subject has
          no DM row: those records exist but link to no enrolled subject, and
          counting an edge for them would claim a link that is not there. On the
          practice study every record's subject is enrolled, so edges == nodes.
        * **subjects** — distinct USUBJIDs with at least one visible record.
        * **ms** — wall-clock time for this call.

        No CSV is re-read; this only re-filters indices built in __init__.
        Calling it twice with the same cut returns the same stats, and the graph
        is left in a state where every subsequent query defaults to this cut.
        """
        t0 = time.perf_counter()

        self._snapshot_cut = cut
        enrolled = {r["USUBJID"] for r in self.records("DM", cut=cut)}

        nodes = 0
        edges = 0
        subjects: set[str] = set()
        per_domain: dict[str, int] = {}

        for domain in ALL_DOMAINS:
            visible = self.records(domain, cut=cut)
            per_domain[domain] = len(visible)
            nodes += len(visible)
            for r in visible:
                usubjid = r.get("USUBJID") or ""
                if usubjid:
                    subjects.add(usubjid)
                    if usubjid in enrolled:
                        edges += 1

        # How many of the visible records have a correction already in force at
        # this cut. Not part of the graded dict — reported alongside it so the
        # demo UI and a reviewer can see that corrections are actually applied.
        corrected = 0
        for key, hist in self.corrections_index.items():
            domain, usubjid, seq, _field = key
            rec = self.by_key.get((domain, usubjid, seq))
            if rec is None or (cut is not None and rec["_cut"] > cut):
                continue
            if cut is None or hist[0][0] <= cut:
                corrected += 1

        stats = {
            "nodes": nodes,
            "edges": edges,
            "subjects": len(subjects),
            "cut": cut,
            "ms": int(round((time.perf_counter() - t0) * 1000)),
        }
        # Extra keys are additive; the grader reads the five above.
        self._stats = dict(stats, per_domain=per_domain,
                           corrections_applied=corrected,
                           protocol_version=self.protocol_version_at(cut),
                           malformed_rows=self._malformed,
                           documents=self.document_names())
        return stats

    @property
    def stats(self) -> dict:
        """The last build's stats, plus the non-graded extras."""
        return dict(self._stats)

    @property
    def cut(self) -> int | None:
        """The cut this graph was last built at."""
        return self._snapshot_cut

    def patient360(self, usubjid: str) -> dict:
        raise NotImplementedError("T1.5")


class Atlas:
    def __init__(self, graph: StudyGraph):
        raise NotImplementedError("T1.6")

    def answer(self, question: Question) -> Answer:
        raise NotImplementedError("T1.6")
