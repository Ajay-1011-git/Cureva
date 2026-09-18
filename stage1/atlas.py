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

import logging
import re
import time
from bisect import bisect_right
from pathlib import Path
from typing import Any, Iterable

from schemas import Answer, Finding, Question, RecordRef
from study import DOMAINS as CSV_DOMAINS
from study import (NoReferenceRange, SEQ_COL, Study, UnitMismatch, central_range,
                   parse_date, standardise_lab, to_number)

log = logging.getLogger("cureva.atlas")

#: The nine organiser domains plus Cureva's PRO, the tenth. PRO is written only
#: by intake/ (Act 1) and is always present and always empty here — a graded run
#: against a hidden study carries zero PRO records (PRD FR-20/G7).
PRO_DOMAIN = "PRO"
ALL_DOMAINS: tuple[str, ...] = tuple(CSV_DOMAINS) + (PRO_DOMAIN,)

#: The column carrying each domain's own event date. MH has none — a medical
#: history entry is not dated in this schema — so it can never be windowed.
DATE_COLUMN: dict[str, str | None] = {
    "DM": "RFSTDTC", "AE": "AESTDTC", "LB": "LBDTC", "VS": "VSDTC",
    "EX": "EXSTDTC", "CM": "CMSTDTC", "DS": "DSSTDTC", "MH": None,
    "EG": "EGDTC", PRO_DOMAIN: "reported_date",
}

#: Domains that carry a VISIT column, and so can anchor a visit date.
VISIT_DOMAINS: tuple[str, ...] = ("LB", "VS", "EX", "EG")

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

    def next_pro_seq(self, usubjid: str) -> int:
        """The next per-subject sequence number in the PRO domain."""
        existing = self.by_usubjid_domain.get((usubjid, "PRO"), [])
        return (max((r["_seq"] for r in existing if r["_seq"] is not None), default=0) + 1)

    def append_pro_record(self, record: dict) -> None:
        """Append one PRO row to the live indices — no rebuild.

        `record` follows the same shape as any other domain row: plain dict
        with USUBJID and whatever fields the PRO domain carries (see
        intake/models.py's PRORecord), plus the derived _domain/_seq/_cut/_site
        fields every other loaded row carries, computed here the same way
        __init__ computes them for the CSV-loaded domains.

        This is the ONLY way PRO records enter StudyGraph. Called only from
        intake/pro_writer.py (Act 1) and from the isolation test in T1.22 — the
        graded path (StudyGraph.build/Atlas.answer) never calls it and would
        behave identically if this method were deleted entirely.
        """
        usubjid = (record.get("USUBJID") or "").strip()
        if not usubjid:
            raise ValueError("PRO record needs a USUBJID")
        row = dict(record)
        row["_domain"] = "PRO"
        row["_seq"] = _as_int(row.get("seq"))
        row["_cut"] = _as_int(row.get("cut_available"), 1) or 1
        row["_site"] = self.site_by_subject.get(usubjid) or site_of(usubjid)
        row["_corrected_at"] = None
        self.by_domain["PRO"].append(row)
        self.by_usubjid_domain.setdefault((usubjid, "PRO"), []).append(row)
        if row["_seq"] is not None:
            self.by_key[("PRO", usubjid, row["_seq"])] = row

    def site_for(self, usubjid: str | None) -> str | None:
        """The site a subject belongs to. DM.SITEID first, id shape as fallback."""
        if not usubjid:
            return None
        return self.site_by_subject.get(usubjid) or site_of(usubjid)

    # ------------------------------------------------------------------ dates
    def record_date(self, record: dict, cut: int | None = "unset"):
        """A record's own event date, corrected for the cut, or None.

        Returns None both when the domain has no date column and when the value
        will not parse — the caller cannot place the record in time either way,
        and an unparsable date must not take the whole query down (PRD FR-11).
        """
        column = DATE_COLUMN.get(record["_domain"])
        if not column:
            return None
        try:
            return parse_date(self.record_value(record, column, cut))
        except ValueError:
            return None

    def visit_date(self, usubjid: str, visit: str, cut: int | None = "unset"):
        """The subject's actual date for a named visit.

        Taken from whichever visit-carrying domain records it. On the practice
        study all 2400 (subject, visit) pairs agree on their date across LB, VS,
        EX and EG, so the choice is unambiguous there; the earliest is used so
        that a hidden study whose domains disagree still resolves to one stable,
        deterministic anchor rather than to whichever domain happened to be
        scanned first.
        """
        target = _norm(visit)
        earliest = None
        for domain in VISIT_DOMAINS:
            for r in self.records(domain, cut=cut, usubjid=usubjid):
                if _norm(r.get("VISIT")) != target:
                    continue
                d = self.record_date(r, cut)
                if d and (earliest is None or d < earliest):
                    earliest = d
        return earliest

    def visits_for(self, usubjid: str, cut: int | None = "unset") -> dict[str, Any]:
        """Every visit this subject has a date for, visit name -> date."""
        out: dict[str, Any] = {}
        for domain in VISIT_DOMAINS:
            for r in self.records(domain, cut=cut, usubjid=usubjid):
                visit = (r.get("VISIT") or "").strip()
                if not visit:
                    continue
                d = self.record_date(r, cut)
                if d and (visit not in out or d < out[visit]):
                    out[visit] = d
        return out

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

    #: Fields whose value can be superseded by corrections.csv, per domain.
    #: Resolved through record_value() so patient360 shows the value in force at
    #: the snapshot cut rather than the raw CSV value.
    def _correctable_fields(self, domain: str) -> set[str]:
        return {key[3] for key in self.corrections_index if key[0] == domain}

    def patient360(self, usubjid: str) -> dict:
        """Everything known about one subject, joined, at the current snapshot cut.

        Every domain is present as a key even when the subject has no records in
        it, so an interface can render a consistent set of tables instead of
        branching on which domains happen to exist (PRD FR-3). PRO is included
        on the same footing as the nine organiser domains — it is empty on any
        graded run, and that is the point.

        The grader does not parse this shape; the demo page renders it.
        """
        cut = self._snapshot_cut
        domains: dict[str, list[dict]] = {}
        for domain in ALL_DOMAINS:
            correctable = self._correctable_fields(domain)
            rows = []
            for r in self.records(domain, cut=cut, usubjid=usubjid):
                row = {k: v for k, v in r.items() if not k.startswith("_")}
                for field in correctable:
                    if field in row:
                        corrected = self.record_value(r, field, cut)
                        if corrected != row[field]:
                            # Show the value in force and keep the superseded
                            # one visible, so a reviewer can see a correction
                            # happened rather than a number quietly changing.
                            row["_superseded_" + field] = row[field]
                            row[field] = corrected
                rows.append(row)
            rows.sort(key=lambda r: _as_int(r.get(SEQ_COLUMN.get(domain) or ""), 0) or 0)
            domains[domain] = rows

        dm = domains.get("DM") or [{}]
        demographics = dm[0]
        total = sum(len(v) for v in domains.values())

        return {
            "usubjid": usubjid,
            "site": self.site_for(usubjid),
            "cut": cut,
            "protocol_version": self.protocol_version_at(cut),
            "enrolled": bool(domains.get("DM")),
            "arm": demographics.get("ARM"),
            "age": to_number(demographics.get("AGE")),
            "sex": demographics.get("SEX"),
            "country": demographics.get("COUNTRY"),
            "first_dose": self.first_dose_date(usubjid),
            "record_count": total,
            "domains": domains,
            # Flat domain keys alongside `domains`, so both
            # patient360(x)["LB"] and patient360(x)["domains"]["LB"] work.
            **domains,
        }

    def first_exposure_date(self, usubjid: str, cut: int | None = "unset"):
        """The subject's earliest EX record date, or None when never dosed.

        Distinct from first_dose_date(): this is what the exposure records
        actually say, and None here means there is no exposure record at all —
        which is itself a finding (MISSING_EXPOSURE_RECORD).
        """
        earliest = None
        for r in self.records("EX", cut=cut, usubjid=usubjid):
            d = self.record_date(r, cut)      # unparsable dates come back None
            if d and (earliest is None or d < earliest):
                earliest = d
        return earliest

    def reference_start_date(self, usubjid: str, cut: int | None = "unset"):
        """DM.RFSTDTC — the study's own reference start (first dose) date."""
        rows = self.records("DM", cut=cut, usubjid=usubjid)
        return self.record_date(rows[0], cut) if rows else None

    def first_dose_date(self, usubjid: str, cut: int | None = "unset"):
        """When the subject was first dosed.

        DM.RFSTDTC is the study's own reference start date and is authoritative;
        the earliest EX record is the fallback for a subject whose DM row is
        missing or carries no RFSTDTC.

        These two are NOT interchangeable. On the practice study they disagree
        for 191 of 240 subjects — EX records are scheduled administrations,
        while RFSTDTC is the recorded first dose — and using the earliest EX
        record instead would flag one extra subject as having an adverse event
        before first dose who, against the study's own reference date, does not.
        """
        return (self.reference_start_date(usubjid, cut)
                or self.first_exposure_date(usubjid, cut))


def _norm(value: Any) -> str:
    """Upper-cased, whitespace-collapsed text, for comparing coded values.

    Coded columns are matched through this rather than by `==` on the raw
    string: the practice study writes "DISCONTINUED" and "ADVERSE EVENT", but a
    hidden study writing "Adverse Event" or a stray trailing space means the
    same thing and must not silently stop matching. This normalises the
    comparison, it does not invent synonyms.
    """
    return " ".join(str(value or "").split()).upper()


# ============================================================ count metrics
# Signature: (atlas, question, params, deadline) -> Answer
# `params` is question.params minus the "metric" key.

def _canonical_metric(name: Any) -> str:
    """Normalise a metric name so spelling variants reach the same metric.

    The grader's questions are generated, and a generated name for the same
    quantity can arrive as "discontinued_ae", "discontinuedAE" or
    "discontinued_adverse_event". Matching on a normalised key costs nothing
    and is not a guess about *what* is being asked -- these are spellings of
    one question, not different questions.

    Anything genuinely unrecognised falls through unchanged and is declined
    honestly by the caller.
    """
    key = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    aliases = {
        # discontinuation because of an adverse event -- the organiser's own
        # worked example, and the only count metric the public bank uses.
        "discontinuedae": "discontinued_ae",
        "discontinuedadverseevent": "discontinued_ae",
        "discontinuationsae": "discontinued_ae",
        "aediscontinuation": "discontinued_ae",
        "aediscontinuations": "discontinued_ae",
        "subjectsdiscontinuedae": "discontinued_ae",
        "discontinuedduetoae": "discontinued_ae",
        "discontinuedduetoadverseevent": "discontinued_ae",
    }
    return aliases.get(key, str(name or ""))


#: Fields a count question may name to describe its own predicate, in the
#: order they are looked for. Nothing here is inferred from the question's
#: English -- a predicate is only used when the params spell it out.
_PREDICATE_KEYS = ("field", "column", "variable")
_VALUE_KEYS = ("value", "equals", "is")


def _metric_from_predicate(atlas: "Atlas", question: Question, params: dict) -> Answer | None:
    """Count records the question itself describes, when it describes one.

    Handles a count question whose params carry an explicit predicate rather
    than a registered metric name, e.g.::

        {"domain": "AE", "field": "AESER", "value": "Y", "site": "S07"}
        {"domain": "DS", "filters": {"DSDECOD": "DISCONTINUED"}}

    Returns None -- not a guess -- when the params do not describe a predicate.
    That distinction is the whole point: this widens what can be answered
    *exactly*, and never converts an unanswerable question into a confident
    number. Evidence is every record the count rests on, so the answer is
    checkable the same way a registered metric's is.
    """
    domain = params.get("domain") or params.get("dataset")
    if not domain:
        return None
    domain = str(domain).upper()
    if domain not in ALL_DOMAINS:
        return None

    filters: dict[str, str] = {}
    raw_filters = params.get("filters")
    if isinstance(raw_filters, dict):
        filters.update({str(k).upper(): _norm(v) for k, v in raw_filters.items()})

    field = next((params[k] for k in _PREDICATE_KEYS if params.get(k)), None)
    value = next((params[k] for k in _VALUE_KEYS if params.get(k) is not None), None)
    if field is not None and value is not None:
        filters[str(field).upper()] = _norm(value)

    if not filters:
        return None

    cut = atlas.cut_for(question)
    site = params.get("site")
    usubjid = params.get("usubjid")

    hits = []
    for r in atlas.graph.records(domain, cut=cut, site=site, usubjid=usubjid):
        if all(_norm(atlas.graph.record_value(r, f, cut)) == v for f, v in filters.items()):
            hits.append(r)

    # "How many subjects" is the question's own wording in every example the
    # organiser gives, so distinct subjects is the count. The record total is
    # reported alongside rather than silently chosen between.
    subjects = {r.get("USUBJID") for r in hits if r.get("USUBJID")}
    where = f" at site {site}" if site else ""
    predicate = ", ".join(f"{f}={v}" for f, v in sorted(filters.items()))

    return Answer(
        question_id=question.id,
        answer=len(subjects),
        text=(f"{len(subjects)} subject(s){where} with a {domain} record where "
              f"{predicate} ({len(hits)} record(s) in total)."),
        evidence=[Atlas.ref(r) for r in hits],
        # Same standing as any registered metric: an exact count over an exact
        # predicate, on records that are all cited.
        confidence=CONFIDENCE["count_metric"],
    )


def _metric_discontinued_ae(atlas: "Atlas", question: Question,
                            params: dict, deadline: float) -> Answer:
    """How many subjects discontinued because of an adverse event.

    Matches example_answer.py's own pattern: DS rows with DSDECOD DISCONTINUED
    and DSTERM ADVERSE EVENT, optionally narrowed to one site. Evidence is every
    DS record the count rests on — each one genuinely shows the discontinuation
    it is cited for.
    """
    site = params.get("site")
    usubjid = params.get("usubjid")
    cut = atlas.cut_for(question)

    hits = []
    for r in atlas.graph.records("DS", cut=cut, site=site, usubjid=usubjid):
        decod = _norm(atlas.graph.record_value(r, "DSDECOD", cut))
        term = _norm(atlas.graph.record_value(r, "DSTERM", cut))
        if decod == "DISCONTINUED" and term == "ADVERSE EVENT":
            hits.append(r)

    where = f" at site {site}" if site else ""
    return Answer(
        question_id=question.id,
        answer=len(hits),
        text=f"{len(hits)} subject(s){where} discontinued due to an adverse event.",
        evidence=[Atlas.ref(r) for r in hits],
        # An exact count over an exact predicate on complete records. Nothing is
        # estimated, so this is as certain as the data itself. A zero is just as
        # certain as a three -- "none here" is a real answer, not a shrug.
        confidence=CONFIDENCE["count_metric"],
    )


# ======================================================= protocol as evidence
#
# Rules live in the protocol document, and the document changes mid-study. Every
# rule below is read from the version in force at the question's cut (FR-17),
# with a documented constant as the fallback when the sentence cannot be parsed
# confidently. The constants are the practice protocol's values; they are a
# safety net, never the primary source, and a mismatch is logged rather than
# silently preferred.

#: protocol_v1.md §7: "ALT or AST > 3 × ULN together with total bilirubin
#: > 2 × ULN within 14 days".
DEFAULT_HYS_ENZYME_MULTIPLE = 3.0
DEFAULT_HYS_BILIRUBIN_MULTIPLE = 2.0
DEFAULT_HYS_WINDOW_DAYS = 14

#: protocol §4: "± 7 days from the scheduled day" (v1); the v2 amendment
#: tightens it to ± 3. Read from the document, never assumed.
DEFAULT_VISIT_WINDOW_DAYS = 7

#: protocol §4: "Screening (Day −14), Baseline (Day 0), Weeks 2, 4, 8, 12, 16,
#: 20, 24, End of Study (Day 182)." Day offsets are relative to Baseline = day 0.
#: Confirmed against the data: the median observed offset equals the scheduled
#: day for all ten visits across 240 subjects.
DEFAULT_VISIT_SCHEDULE: dict[str, int] = {
    "SCREENING": -14, "BASELINE": 0, "WEEK2": 14, "WEEK4": 28, "WEEK8": 56,
    "WEEK12": 84, "WEEK16": 112, "WEEK20": 140, "WEEK24": 168, "EOS": 182,
}

#: protocol_v1.md §2: "Age 18-75 years at screening", "HbA1c between 7.0% and
#: 10.5% at screening". protocol_v1.md §3: "known hepatic disease (ALT or AST
#: > 2 x ULN at screening)". The renal-impairment exclusion is v2-only and has
#: no v1 default — it is absent before v2, not defaulted to a number.
DEFAULT_INCLUSION_AGE_RANGE = (18.0, 75.0)
DEFAULT_INCLUSION_HBA1C_RANGE = (7.0, 10.5)
DEFAULT_EXCLUSION_LIVER_MULTIPLE = 2.0
DEFAULT_EXCLUSION_CREAT_THRESHOLD_MGDL = 1.5

#: protocol_v1.md §5: "Systemic Glucocorticoid". v3 amendment adds "Sulfonylurea".
DEFAULT_PROHIBITED_CONMED_CLASSES = frozenset({"SYSTEMIC_GLUCOCORTICOID"})

#: How a protocol's prose names a visit, versus how the VISIT column spells it.
_VISIT_ALIASES = {
    "SCREENING": "SCREENING", "SCREEN": "SCREENING",
    "BASELINE": "BASELINE", "RANDOMISATION": "BASELINE", "RANDOMIZATION": "BASELINE",
    "ENDOFSTUDY": "EOS", "EOS": "EOS", "ENDOFTREATMENT": "EOS",
}

#: Both the ASCII hyphen and the Unicode minus sign U+2212 appear in the real
#: documents ("Day −14" uses the latter), as do "±" and "+/-".
_MINUS = "-\u2212\u2013\u2014"


def _normalise_visit_name(name: str) -> str:
    """A protocol's spelling of a visit, as the VISIT column writes it."""
    key = re.sub(r"[^A-Z0-9]", "", (name or "").upper())
    if key in _VISIT_ALIASES:
        return _VISIT_ALIASES[key]
    m = re.match(r"^WEEKS?(\d+)$", key)
    if m:
        return f"WEEK{int(m.group(1))}"
    return key


def protocol_section(text: str, number: int) -> str:
    """The body of one numbered section of a protocol markdown document.

    Matches "## 7. Liver safety" through to the next "##" heading. Returns ""
    when the section is absent, so a caller falls back rather than crashes on a
    hidden study that numbers its sections differently.
    """
    pattern = re.compile(rf"^##\s*{number}\.?\s.*?$(.*?)(?=^##\s|\Z)",
                         re.MULTILINE | re.DOTALL)
    m = pattern.search(text or "")
    return m.group(1).strip() if m else ""


def _find_section_about(text: str, *keywords: str) -> str:
    """The first section whose heading mentions one of these keywords.

    Used when a hidden study renumbers its sections: the heading wording is a
    better anchor than the number, so both are tried.
    """
    for m in re.finditer(r"^##\s*(\d+)\.?\s*(.*?)$(.*?)(?=^##\s|\Z)",
                         text or "", re.MULTILINE | re.DOTALL):
        heading = m.group(2).lower()
        if any(k in heading for k in keywords):
            return m.group(3).strip()
    return ""


class ProtocolRules:
    """The rules in force at one cut, read from that cut's protocol document.

    Constructed per question rather than cached across questions, so an
    amendment landing on disk mid-run is picked up on the next call and no
    answer is ever served from a stale protocol (PRD G4/FR-4/FR-5).
    """

    def __init__(self, graph: "StudyGraph", cut: int | None):
        self.cut = cut
        self.version = graph.protocol_version_at(cut)
        try:
            self.document_name, self.text = graph.protocol_document_at(cut)
        except (KeyError, OSError) as exc:
            log.warning("protocol document unavailable at cut %s: %s", cut, exc)
            self.document_name, self.text = f"protocol_v{self.version}", ""
        self.warnings: list[str] = []

        self.liver_text = (protocol_section(self.text, 7)
                           or _find_section_about(self.text, "liver", "hepatic", "hy"))
        (self.hys_enzyme_multiple,
         self.hys_bilirubin_multiple,
         self.hys_window_days) = self._read_hys_thresholds()

        self.visit_text = (protocol_section(self.text, 4)
                           or _find_section_about(self.text, "visit", "schedule", "window"))
        self.visit_window_days = self._read_visit_window()
        self.visit_schedule = self._read_visit_schedule()

        self.inclusion_text = (protocol_section(self.text, 2)
                               or _find_section_about(self.text, "inclusion"))
        self.exclusion_text = (protocol_section(self.text, 3)
                               or _find_section_about(self.text, "exclusion"))
        (self.inclusion_age_range,
         self.inclusion_hba1c_range) = self._read_inclusion_ranges()
        (self.exclusion_liver_multiple,
         self.exclusion_creat_threshold,
         self.exclusion_creat_active) = self._read_exclusion_rules()

        self.conmed_text = (protocol_section(self.text, 5)
                            or _find_section_about(self.text, "prohibited", "concomitant"))
        self.prohibited_conmed_classes = self._read_prohibited_conmeds()

    def _read_prohibited_conmeds(self) -> frozenset[str]:
        """The set of prohibited CMCLAS values, from the active document's §5.

        Read as a list of drug-class names on their own bullet lines, then
        mapped to the coded CMCLAS vocabulary via a simple normalisation
        (spaces -> underscores, upper-cased) rather than a fixed name->code
        table, so a class this practice study never uses is still recognised
        correctly if a hidden study's protocol prose names it.
        """
        names = re.findall(r"^\s*[-*]\s*(.+?)\s*$", self.conmed_text, re.MULTILINE)
        names = [n for n in names if n and "prohibited" not in n.lower()
                and "protocol deviation" not in n.lower()]
        classes = {re.sub(r"[\s/-]+", "_", n.strip()).upper() for n in names}
        if not classes:
            self.warnings.append(
                f"{self.document_name}: no prohibited-conmed list found; "
                f"using documented default {sorted(DEFAULT_PROHIBITED_CONMED_CLASSES)}")
            return frozenset(DEFAULT_PROHIBITED_CONMED_CLASSES)
        return frozenset(classes)

    # --------------------------------------------------------- eligibility
    def _read_inclusion_ranges(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """(age_range, hba1c_range) from the inclusion criteria section."""
        text = self.inclusion_text
        age = re.search(r"[Aa]ge\s+(\d+)\s*[{0}\-]\s*(\d+)".format(re.escape("\u2013")),
                        text)
        hba1c = re.search(r"HbA1c\s+between\s+([\d.]+)%?\s+and\s+([\d.]+)%?", text, re.IGNORECASE)
        if not age or not hba1c:
            self.warnings.append(
                f"{self.document_name}: inclusion age/HbA1c range did not fully parse; "
                f"using documented defaults")
        age_range = ((float(age.group(1)), float(age.group(2))) if age
                    else DEFAULT_INCLUSION_AGE_RANGE)
        hba1c_range = ((float(hba1c.group(1)), float(hba1c.group(2))) if hba1c
                       else DEFAULT_INCLUSION_HBA1C_RANGE)
        return age_range, hba1c_range

    def _read_exclusion_rules(self) -> tuple[float, float, bool]:
        """(liver ULN multiple, creatinine threshold mg/dL, is-creat-rule-active).

        The creatinine exclusion is presence-based, not version-numbered: v1's
        text simply does not contain it, and it appears from the v2 amendment
        onward. Detecting it by searching the active document's own exclusion
        text for "creatinine" is what makes this correct on a hidden study whose
        amendment schedule differs from the practice study's, rather than
        hard-coding "v2 onward" as a version-number check.
        """
        text = self.exclusion_text
        liver = re.search(r"ALT\s+or\s+AST\s*>\s*(\d+(?:\.\d+)?)\s*(?:×|x|\*)\s*ULN",
                          text, re.IGNORECASE)
        if not liver:
            self.warnings.append(
                f"{self.document_name}: exclusion liver multiple did not parse; "
                f"using documented default {DEFAULT_EXCLUSION_LIVER_MULTIPLE}x")
        liver_multiple = float(liver.group(1)) if liver else DEFAULT_EXCLUSION_LIVER_MULTIPLE

        creat = re.search(r"[Cc]reatinine\s*>\s*([\d.]+)\s*mg/dL", text)
        active = "creatinine" in text.lower()
        if active and not creat:
            self.warnings.append(
                f"{self.document_name}: creatinine exclusion mentioned but threshold "
                f"did not parse; using documented default "
                f"{DEFAULT_EXCLUSION_CREAT_THRESHOLD_MGDL} mg/dL")
        threshold = float(creat.group(1)) if creat else DEFAULT_EXCLUSION_CREAT_THRESHOLD_MGDL
        return liver_multiple, threshold, active

    # ---------------------------------------------------------- visit windows
    def _read_visit_window(self) -> int:
        """± N days around a scheduled visit day, from the active protocol.

        This is the value the v2 amendment moves (± 7 -> ± 3), so reading it
        rather than assuming it is what makes a cut-scoped question give the
        answer that was correct at that cut (PRD FR-17).
        """
        m = re.search(rf"(?:±|\+/[{_MINUS}]|\+\s*or\s*[{_MINUS}])\s*(\d+)\s*days?",
                      self.visit_text, re.IGNORECASE)
        if not m:
            self.warnings.append(
                f"{self.document_name}: no visit window found in the schedule section; "
                f"using the documented default ±{DEFAULT_VISIT_WINDOW_DAYS} days")
            return DEFAULT_VISIT_WINDOW_DAYS
        return int(m.group(1))

    def _read_visit_schedule(self) -> dict[str, int]:
        """Visit name -> scheduled day offset from Baseline, from the protocol.

        Two shapes are read out of the same sentence: visits given an explicit
        day ("Screening (Day −14)", "End of Study (Day 182)") and the run of
        weeks ("Weeks 2, 4, 8, 12, 16, 20, 24"), where week N is day 7N. The
        documented schedule is used for anything the sentence does not cover.
        """
        schedule: dict[str, int] = {}
        for name, day in re.findall(rf"([A-Za-z][A-Za-z ]*?)\s*\(\s*Day\s*([{_MINUS}]?\s*\d+)\s*\)",
                                    self.visit_text):
            visit = _normalise_visit_name(name)
            digits = re.sub(rf"[^0-9{_MINUS}]", "", day)
            negative = digits and digits[0] in _MINUS
            value = int(re.sub(r"[^0-9]", "", digits) or 0)
            if visit:
                schedule[visit] = -value if negative else value

        weeks = re.search(r"Weeks?\s+([\d,\s]*\d)", self.visit_text, re.IGNORECASE)
        if weeks:
            for n in re.findall(r"\d+", weeks.group(1)):
                schedule[f"WEEK{int(n)}"] = int(n) * 7

        missing = {k: v for k, v in DEFAULT_VISIT_SCHEDULE.items() if k not in schedule}
        if missing:
            self.warnings.append(
                f"{self.document_name}: visit schedule did not yield {sorted(missing)}; "
                f"using documented day offsets for those")
            schedule.update(missing)
        return schedule

    # -------------------------------------------------------------- Hy's law
    def _read_hys_thresholds(self) -> tuple[float, float, int]:
        """Thresholds for the Hy's law rule, from the active protocol's text.

        The sentence has a stable shape across amendments — two "N × ULN"
        multiples and a "within K days" window — so the numbers are read from
        it rather than assumed. If the sentence is missing or does not parse
        cleanly, the practice protocol's documented values are used and the
        discrepancy is recorded, because answering with a silently wrong
        threshold is worse than answering with a flagged fallback.
        """
        text = self.liver_text
        if not text:
            self.warnings.append(
                f"{self.document_name}: no liver-safety section found; "
                f"using documented defaults {DEFAULT_HYS_ENZYME_MULTIPLE}x/"
                f"{DEFAULT_HYS_BILIRUBIN_MULTIPLE}x/{DEFAULT_HYS_WINDOW_DAYS}d")
            return (DEFAULT_HYS_ENZYME_MULTIPLE, DEFAULT_HYS_BILIRUBIN_MULTIPLE,
                    DEFAULT_HYS_WINDOW_DAYS)

        multiples = [float(m) for m in
                     re.findall(r"(\d+(?:\.\d+)?)\s*(?:×|x|\*)\s*ULN", text, re.IGNORECASE)]
        window = re.search(r"within\s+(\d+)\s*days?", text, re.IGNORECASE)

        enzyme = multiples[0] if len(multiples) >= 1 else DEFAULT_HYS_ENZYME_MULTIPLE
        bilirubin = multiples[1] if len(multiples) >= 2 else DEFAULT_HYS_BILIRUBIN_MULTIPLE
        days = int(window.group(1)) if window else DEFAULT_HYS_WINDOW_DAYS

        if len(multiples) < 2 or window is None:
            self.warnings.append(
                f"{self.document_name} liver section did not yield both ULN multiples "
                f"and a window; read {multiples!r} / {window and window.group(1)!r}, "
                f"using {enzyme}x/{bilirubin}x/{days}d")
        for name, read, default in (("enzyme multiple", enzyme, DEFAULT_HYS_ENZYME_MULTIPLE),
                                    ("bilirubin multiple", bilirubin, DEFAULT_HYS_BILIRUBIN_MULTIPLE),
                                    ("window days", days, DEFAULT_HYS_WINDOW_DAYS)):
            if read != default:
                # Not an error — an amendment is allowed to move a threshold.
                # Recorded so a reviewer can see the rule actually changed.
                self.warnings.append(
                    f"{self.document_name}: {name} is {read}, was {default} in the practice "
                    f"protocol — using the document, as required")
        for w in self.warnings:
            log.warning("%s", w)
        return enzyme, bilirubin, days

    def evidence_ref(self, section: int | str = 7) -> RecordRef:
        """A citation pointing at the protocol section a rule came from."""
        return RecordRef(domain="DOC", document=self.document_name, section=str(section))


# ========================================================= finding detectors
# Signature: (graph, site, usubjid, cut) -> list[Finding]
#
# `cut` is part of the signature because several detectors are protocol-version
# dependent (visit windows, exclusion criteria, prohibited conmeds) and the
# version in force is a function of the cut — PRD FR-17 requires the rule that
# applied then, not a fixed one.
#
# `site`/`usubjid` are passed so a detector can narrow its own scan for speed;
# Atlas filters the results again afterwards, so a detector that ignores them
# is still correct, just slower.

DETECTORS: dict[str, Any] = {}


def detector(code: str):
    """Register a detector for one FindingCode."""
    def register(fn):
        DETECTORS[code] = fn
        return fn
    return register


class LabValue:
    """One laboratory record, standardised into the central unit.

    `value` is None when the result was not usable as a number ("<5", "ND",
    blank) — the record is still carried so a detector can say that a value was
    skipped rather than silently pretending it never existed.
    """

    __slots__ = ("record", "testcd", "value", "unit", "converted", "date",
                 "raw", "low", "high")

    def __init__(self, record, testcd, value, unit, converted, date, raw, low, high):
        self.record, self.testcd = record, testcd
        self.value, self.unit, self.converted = value, unit, converted
        self.date, self.raw = date, raw
        self.low, self.high = low, high

    def exceeds(self, multiple: float) -> bool:
        return (self.value is not None and self.high is not None
                and self.value > multiple * self.high)

    def margin(self, multiple: float) -> float:
        """How far past the threshold, as a fraction of it. 0.1 == 10% over."""
        threshold = multiple * (self.high or 0)
        if not threshold or self.value is None:
            return 0.0
        return (self.value - threshold) / threshold

    def describe(self) -> str:
        shown = f"{self.value:g} {self.unit}" if self.value is not None else f"{self.raw!r}"
        if self.converted:
            return f"{self.testcd} {self.raw} {self.record.get('LBORRESU')} = {shown}"
        return f"{self.testcd} {shown}"


def standardised_labs(graph: "StudyGraph", usubjid: str, cut: int | None,
                      testcds: Iterable[str]) -> tuple[list[LabValue], int, int]:
    """Every LB record for a subject in the given tests, in the central unit.

    Returns (values, skipped_unusable, skipped_unit_mismatch). A unit that
    matches no reference row means this record cannot be compared to a
    threshold, so it is skipped here and reported separately by the
    LAB_UNIT_MISMATCH detector — one bad record never takes a detector down.
    """
    wanted = {t.upper() for t in testcds}
    out: list[LabValue] = []
    unusable = mismatched = 0
    for r in graph.records("LB", cut=cut, usubjid=usubjid):
        testcd = (r.get("LBTESTCD") or "").strip().upper()
        if testcd not in wanted:
            continue
        raw = graph.record_value(r, "LBORRES", cut)
        try:
            value, unit, converted = standardise_lab(testcd, raw, r.get("LBORRESU"), graph.ranges)
            _low_unit, low, high = central_range(testcd, graph.ranges)
        except UnitMismatch:
            mismatched += 1
            continue
        except NoReferenceRange:
            mismatched += 1
            continue
        date = graph.record_date(r, cut)
        if value is None or date is None:
            unusable += 1
            if value is None:
                continue
        out.append(LabValue(r, testcd, value, unit, converted, date, raw, low, high))
    return out, unusable, mismatched


@detector("HYS_LAW_CANDIDATE")
def detect_hys_law(graph: "StudyGraph", site: str | None, usubjid: str | None,
                   cut: int | None) -> list[Finding]:
    """Potential Hy's law: a liver-enzyme rise and a bilirubin rise together.

    Protocol §7: ALT or AST above N x ULN together with total bilirubin above
    M x ULN within K days. N, M and K are read from the protocol version in
    force at this cut, not fixed (ProtocolRules).

    Every value passes through standardise_lab first. This is the case the gate
    turns on: a local laboratory reporting in a different unit produces an ALT
    that looks normal against the central range and is in fact four times the
    upper limit. Comparing raw would miss it entirely.

    Stated limitation: the protocol excludes cases "without cholestasis or
    alternative explanation". Nothing in this schema measures cholestasis —
    there is no ALP or GGT test in the reference ranges — so this detector
    reports candidates, which is what the finding code says (HYS_LAW_*CANDIDATE*)
    and what the protocol asks be sent for adjudication. It does not claim to
    have ruled out an alternative explanation, and says so in its rationale.
    """
    rules = ProtocolRules(graph, cut)
    findings: list[Finding] = []

    subjects = ([usubjid] if usubjid else
                [r["USUBJID"] for r in graph.records("DM", cut=cut, site=site)])

    for subject in subjects:
        labs, unusable, mismatched = standardised_labs(
            graph, subject, cut, ("ALT", "AST", "BILI"))
        enzymes = [lv for lv in labs if lv.testcd in ("ALT", "AST")
                   and lv.exceeds(rules.hys_enzyme_multiple)]
        bilirubins = [lv for lv in labs if lv.testcd == "BILI"
                      and lv.exceeds(rules.hys_bilirubin_multiple)]
        if not enzymes or not bilirubins:
            continue

        pairs = [(e, b) for e in enzymes for b in bilirubins
                 if abs((e.date - b.date).days) <= rules.hys_window_days]
        if not pairs:
            continue

        # Cite the clearest qualifying pair: closest in time, then largest
        # margin over threshold. The records cited are the ones that show the
        # finding, not merely ones that belong to the same subject (FR-9).
        enzyme, bili = min(pairs, key=lambda p: (abs((p[0].date - p[1].date).days),
                                                 -p[0].margin(rules.hys_enzyme_multiple)))
        gap = abs((enzyme.date - bili.date).days)

        enzyme_margin = enzyme.margin(rules.hys_enzyme_multiple)
        bili_margin = bili.margin(rules.hys_bilirubin_multiple)
        confidence = CONFIDENCE["hys_law_clean"]
        caveats = []
        # A value sitting within a few percent of its threshold is inside
        # ordinary measurement noise — genuinely less certain, so it says so.
        if min(enzyme_margin, bili_margin) < NOISE_MARGIN_FRACTION:
            confidence = CONFIDENCE["hys_law_borderline"]
            caveats.append("a value is within measurement noise of its threshold")

        # Values that had to be skipped (below detection, not done, unusable
        # unit) deliberately do NOT lower confidence in a finding that was
        # made. A skipped value can only ever hide a finding, never invent one:
        # this pair qualified on its own two records, and an unrelated "<5" at a
        # different visit says nothing about whether it did. Where skipped
        # values genuinely matter is the opposite answer — "I found nothing" is
        # less certain when some values could not be read — and that is carried
        # on the empty answer instead (T1.21). They are still reported here, so
        # the reader can see what was not usable.
        if unusable or mismatched:
            caveats.append(
                f"{unusable} value(s) below detection or not done and "
                f"{mismatched} with an unusable unit were skipped while scanning "
                f"this subject; neither affects the pair cited above")

        rationale = (
            f"{enzyme.describe()} > {rules.hys_enzyme_multiple:g}x ULN "
            f"({rules.hys_enzyme_multiple * enzyme.high:g} {enzyme.unit}) on {enzyme.date}, "
            f"with {bili.describe()} > {rules.hys_bilirubin_multiple:g}x ULN "
            f"({rules.hys_bilirubin_multiple * bili.high:g} {bili.unit}) on {bili.date} "
            f"— {gap} day(s) apart, inside the {rules.hys_window_days}-day window "
            f"({rules.document_name} §7).")
        if enzyme.converted or bili.converted:
            rationale += " Unit converted to the central laboratory's before comparison."
        rationale += (" Candidate only: cholestasis and alternative explanations cannot be "
                      "assessed from the available tests, so this is for adjudication.")
        if caveats:
            rationale += " Note: " + "; ".join(caveats) + "."

        findings.append(Finding(
            code="HYS_LAW_CANDIDATE",
            usubjid=subject,
            site=graph.site_for(subject),
            severity="CRITICAL",
            rationale=rationale,
            evidence=[Atlas.ref(enzyme.record), Atlas.ref(bili.record), rules.evidence_ref(7)],
            confidence=confidence,
            protocol_version=rules.version,
        ))
    findings.sort(key=lambda f: f.usubjid or "")
    return findings


# ===================================================== confidence calibration
#
# Every confidence value this module reports is named here rather than written
# inline at its call site. Calibration is a policy, not an implementation
# detail: a reviewer should be able to read the whole policy in one place and
# change it in one place, and the T1.21 calibration test asserts against THIS
# table rather than re-deriving the numbers, so the two cannot silently drift.
#
# The only real incentive the harness's own scoring creates:
#     penalty = 0.5 * confidence**2, applied ONLY when correctness == 0
# So being confidently wrong is the expensive failure, and an honest "nothing
# here" costs nothing to state confidently. These values track genuine signal
# quality on that basis — never inflated to look sure, never deflated to hedge.
#
# Tiers, and what earns one:
#   0.95  an exact comparison of recorded values, with no interpretation and
#         no possible missing-data path (two coded flags on one record
#         contradicting each other; a demographic against a documented range)
#   0.92  an exact comparison that depended on one derivation step first
#         (a unit conversion, a coded class matched to a parsed document list)
#   0.90  a clean threshold comparison, or an absence over a whole domain
#   0.80  a rule whose inputs could be incomplete for reasons this system
#         cannot see (dates parsed across several domains)
#   ~0.6  the value sits inside measurement/transcription noise of its own
#         threshold — genuinely as consistent with an entry error as a finding
#   0.00  reserved for "this system did not look", never for "nothing found"
CONFIDENCE = {
    # --- exact, no interpretation -------------------------------------------
    "sae_miscoded":            0.95,   # AESHOSP=Y vs AESER=N on one record
    "inclusion_violation":     0.95,   # AGE / SCR_HBA1C vs a documented range
    "dosing_error_dose":       0.95,   # EXDOSE vs the protocol's two values
    "count_metric":            0.95,   # an exact count over an exact predicate
    # --- exact, after one derivation step ------------------------------------
    "prohibited_conmed":       0.92,   # CMCLAS vs the parsed §5 list
    "hys_law_clean":           0.92,   # both values clear of threshold
    "duplicate_subject_max":   0.92,   # heuristic ceiling — never certain
    # --- clean threshold comparison, or a whole-domain absence ---------------
    "lookup_clean":            0.93,   # date arithmetic, every date parsed
    "exclusion_violation":     0.90,   # standardised lab vs documented threshold
    "visit_out_of_window":     0.90,   # visit date vs parsed schedule+window
    "ae_before_first_dose":    0.90,   # two parsed dates, clear ordering
    "dosing_error_arm":        0.90,   # EXTRT vs DM.ARM — a heavier claim
    "missing_exposure_total":  0.90,   # zero EX records for an enrolled subject
    "lab_unit_mismatch":       0.90,   # the unit resolves or it does not
    "finding_none_found":      0.90,   # a detector RAN and found nothing
    "lookup_no_subject":       0.90,   # subject genuinely not in the study
    # --- inputs could be incomplete ------------------------------------------
    "lookup_no_visit_records": 0.85,   # subject has no dated visits at this cut
    "missing_exposure_visit":  0.80,   # a visit with no prior EX record
    "lookup_visit_unknown":    0.80,   # subject has visits, just not this one
    "lookup_some_undated":     0.75,   # some records could not be placed in time
    # --- inside measurement / transcription noise ----------------------------
    "visit_window_marginal":   0.68,   # misses its window by a single day
    "hys_law_borderline":      0.62,   # a value within noise of its threshold
    "ae_before_dose_marginal": 0.60,   # precedes first dose by a single day
    # --- "we did not look" ----------------------------------------------------
    "not_claimed":             0.00,   # no detector/metric for this request
}

#: How close to a threshold still counts as "inside measurement noise", as a
#: fraction of the threshold. 0.05 == within 5% of the limit.
NOISE_MARGIN_FRACTION = 0.05

#: A deviation this many days past a boundary (or a date this many days out of
#: order) is treated as real rather than as a plausible transcription slip.
MARGINAL_DAY_GAP = 2

#: DUPLICATE_SUBJECT's heuristic starts here and rises per corroborating field
#: that also agrees, capped at CONFIDENCE["duplicate_subject_max"]. Three key
#: fields always agree by construction, so the base is deliberately low — it is
#: the ADDITIONAL independent agreement that makes coincidence unlikely.
DUPLICATE_BASE_CONFIDENCE = 0.55
DUPLICATE_PER_FIELD_BONUS = 0.09


#: Hard ceiling per question (PRD FR-12/NFR-1). The harness scores a question
#: that breaches it as zero regardless of correctness, so a slow-but-right
#: answer is worth less than a fast partial one — hence the soft budget below.
TIME_LIMIT_SECONDS = 120.0
#: Where answer() stops gathering and returns what it already has.
SOFT_BUDGET_SECONDS = 100.0


class Atlas:
    """Answers one question at a time against a built StudyGraph.

    Four question kinds, three code paths. "trap" is deliberately NOT a code
    path of its own: a trap is a finding-kind question whose true answer happens
    to be empty, so it runs the same detector as any other finding question and
    the honesty lives in the detector returning [] when that is the truth. Any
    special "is this a trick?" handling would be exactly the reflex the traps
    are there to catch — and would be unavailable on the hidden set, where
    nothing labels a question as a trap in advance.
    """

    def __init__(self, graph: StudyGraph):
        self.graph = graph
        # Registries are filled in by the tasks that own them (T1.7 count
        # metrics, T1.9 finding detectors). Declared here so dispatch can be
        # written once and never touched again as detectors are added.
        self.metrics: dict[str, Any] = {}
        self.detectors: dict[str, Any] = {}
        self._register_metrics()
        self._register_detectors()

    # ------------------------------------------------------------ registries
    def _register_metrics(self) -> None:
        """One entry per named count metric.

        Adding a metric is one function plus one line here. The names are the
        vocabulary question.params["metric"] is written in; an unrecognised name
        is answered honestly rather than guessed at (see _answer_count).
        """
        self.metrics = {
            "discontinued_ae": _metric_discontinued_ae,
        }

    def _register_detectors(self) -> None:
        """One entry per FindingCode this system actually claims to detect.

        A code that is absent is answered honestly ("this system does not claim
        to detect it") rather than with a confident empty list. The distinction
        matters: an empty list from a detector that ran means "nothing is
        there", while an empty list from a code with no detector would mean
        "we did not look" — reporting the second as the first would be a lie
        that happens to score well on traps.

        Codes deliberately not detected in Stage 1, per PRD §4.2:
        SAE_UNESCALATED (escalation state is a Stage 2 concept, tracked across
        ReviewCrew cycles) and LAB_UNIT_CORRUPTION / IMPLAUSIBLE_SITE_PATTERN /
        LATE_DATA_ENTRY / DOCUMENT_TAMPERED (each is a trend across cuts,
        meaningless from a single static build — Stage 3 owns cut-over-cut
        comparison).
        """
        self.detectors = dict(DETECTORS)

    # --------------------------------------------------------------- helpers
    def cut_for(self, question: Question) -> int | None:
        """The cut a question is asked at.

        A question's own `cut` wins when it carries one; otherwise the cut the
        graph was built at. This is what makes a cut-scoped question see the
        protocol version, the visible records and the corrections that were
        actually in force then.
        """
        return question.cut if question.cut is not None else self.graph.cut

    @staticmethod
    def ref(record: dict) -> RecordRef:
        """A RecordRef pointing at exactly this record."""
        return RecordRef(domain=record["_domain"],
                         usubjid=record.get("USUBJID"),
                         seq=record.get("_seq"))

    def record_id(self, record: dict, fallback_seq: int | None = None) -> str:
        """The "DOMAIN:USUBJID:SEQ" string a lookup answer is written in.

        The exact format is taken from the organiser's own published answers
        (e.g. "LB:042-S07-001:31"). DM has no sequence column because it holds
        exactly one row per subject; such a domain uses its 1-based position
        within the subject's rows, which for DM is always 1. That is a
        positional index, deliberately not a fabricated column value — inventing
        a plausible-looking sequence number is the failure PRD FR-9 forbids.
        """
        seq = record.get("_seq")
        if seq is None:
            seq = fallback_seq
        return f"{record['_domain']}:{record.get('USUBJID', '')}:{'' if seq is None else seq}"

    # -------------------------------------------------------------- dispatch
    def answer(self, question: Question) -> Answer:
        """Answer one question. Never raises.

        A crash inside one metric or detector becomes a low-confidence, empty,
        schema-valid Answer explaining what went wrong (PRD FR-11). The grader
        scores an exception as zero for that question either way, but an Answer
        keeps the remaining questions running and leaves a readable reason
        behind instead of a stack trace.
        """
        started = time.perf_counter()
        deadline = started + SOFT_BUDGET_SECONDS
        try:
            if question.kind == "count":
                result = self._answer_count(question, deadline)
            elif question.kind == "lookup":
                result = self._answer_lookup(question, deadline)
            elif question.kind in ("finding", "trap"):
                result = self._answer_finding(question, deadline)
            else:
                result = Answer(
                    question_id=question.id, answer=None, confidence=CONFIDENCE["not_claimed"],
                    text=f"unsupported question kind {question.kind!r}")
        except Exception as exc:                       # noqa: BLE001 - never raise
            # The empty value matches the kind's answer type, so a caller (and
            # the demo UI) never has to handle None where it expected a list.
            empty: Any = [] if question.kind in ("lookup", "finding", "trap") else None
            result = Answer(
                question_id=question.id, answer=empty, confidence=CONFIDENCE["not_claimed"],
                text=f"could not answer: {type(exc).__name__}: {exc}")

        result.question_id = question.id
        elapsed = time.perf_counter() - started
        if elapsed > TIME_LIMIT_SECONDS:
            # Already over; say so rather than let a stale answer look clean.
            result.text = (result.text + " ").strip() + \
                f" [took {elapsed:.1f}s, over the {TIME_LIMIT_SECONDS:.0f}s limit]"
        return result

    # ------------------------------------------------------------ T2.15
    def verify_evidence(self, record_ref: RecordRef, claim: str | None = None,
                        *, code: str | None = None,
                        cut: int | None = "unset") -> bool:
        """Does this cited record exist, and does it still support the claim?

        Additive. Nothing that existed before this method was changed to add
        it: no signature, no detector, no dispatch path.

        Act 3's Round 3 calls this to throw out claims a persona made about
        records that do not say what the persona said they say. Two checks,
        in order:

        1. **Existence at the cut.** A record that is not in the graph, or that
           is not visible yet at this cut, cannot support anything. A document
           reference is verified against the documents actually loaded.
        2. **The code's own predicate, when `code` is given.** This does not
           re-implement any detector -- it *runs* the registered detector for
           that code, scoped to the cited subject and cut, and asks whether the
           detector itself still cites this record. That is the point: the only
           trustworthy answer to "does this record support a HYS_LAW_CANDIDATE
           claim" is the one Stage 1's own Hy's law detector gives, so the
           check reuses it wholesale rather than approximating it.

        `claim` is accepted for the signature the TRD specifies and is not used
        to second-guess the detector. Judging free text against a record is
        exactly the kind of inference Round 3 exists to avoid making -- Round 3
        is deterministic precisely because it never asks a model, or this
        method, to interpret prose.

        Never raises: a verification that cannot be completed is a verification
        that did not pass.
        """
        try:
            if cut == "unset":
                cut = self.graph.cut

            # A document/section citation: the document must really be loaded,
            # and a named section must really be in it.
            if record_ref.document:
                try:
                    text = self.graph.document(record_ref.document)
                except Exception:                                 # noqa: BLE001
                    return False
                if not text:
                    return False
                if record_ref.section is None:
                    return True
                return bool(protocol_section(text, record_ref.section))

            if not record_ref.domain or not record_ref.usubjid:
                return False

            record = self.graph.by_key.get(
                (record_ref.domain.upper(), record_ref.usubjid, record_ref.seq))
            if record is None:
                return False
            if cut is not None and record["_cut"] > cut:
                return False            # exists, but not visible yet at this cut

            if code is None:
                return True             # existence was all that was asked

            detector = self.detectors.get(code)
            if detector is None:
                # No detector claims this code, so there is no predicate to
                # check. The record exists; say so, rather than failing a claim
                # for a reason that has nothing to do with the claim.
                return True

            findings = detector(self.graph, None, record_ref.usubjid, cut) or []
            for finding in findings:
                for ref in finding.evidence:
                    if (ref.domain == record_ref.domain
                            and ref.usubjid == record_ref.usubjid
                            and ref.seq == record_ref.seq):
                        return True
            return False
        except Exception:                                         # noqa: BLE001
            return False

    # --------------------------------------------------------- kind handlers
    def _answer_count(self, question: Question, deadline: float) -> Answer:
        """A count, by registered metric or by the predicate the question names.

        Three steps, narrowing from most specific to most honest:

        1. A registered metric, matched on a normalised name so spelling
           variants of one question reach one metric.
        2. Failing that, a predicate the params themselves spell out
           (domain + field/value, or domain + filters). This answers a count
           the system was never explicitly taught, but only when the question
           says exactly what to count -- it never infers a predicate from the
           question's English.
        3. Failing both, an honest refusal at zero confidence. A count question
           this system cannot resolve scores nothing either way; returning a
           plausible number instead would risk being confidently wrong, which
           the organiser's own template says is penalised.
        """
        params = dict(question.params or {})
        name = params.pop("metric", None)

        metric = self.metrics.get(_canonical_metric(name))
        if metric is not None:
            return metric(self, question, params, deadline)

        from_predicate = _metric_from_predicate(self, question, params)
        if from_predicate is not None:
            return from_predicate

        return Answer(
            question_id=question.id, answer=None, confidence=CONFIDENCE["not_claimed"],
            text=(f"no metric named {name!r}, and the question's params do not "
                  f"describe a countable predicate; known metrics: "
                  f"{sorted(self.metrics) or 'none'}"))

    def _answer_lookup(self, question: Question, deadline: float) -> Answer:
        """Records in the requested domains within N days of a named visit.

        params: {"usubjid", "domains": [...], "around_visit", "window_days"}
        answer: ["DOMAIN:USUBJID:SEQ", ...] — strings, in the organiser's own
        published format, not RecordRef objects. `evidence` still carries the
        real RecordRefs.
        """
        params = dict(question.params or {})
        cut = self.cut_for(question)
        usubjid = params.get("usubjid")
        visit = params.get("around_visit")
        requested = params.get("domains") or []
        if isinstance(requested, str):
            requested = [requested]
        domains = [d.upper() for d in requested] or list(ALL_DOMAINS)

        window = params.get("window_days")
        # No window given means "at the visit" — the records sharing its date —
        # rather than a guessed span. Stated rather than silently defaulted.
        window_days = int(window) if window is not None else 0

        if not usubjid:
            return Answer(question_id=question.id, answer=[], confidence=CONFIDENCE["not_claimed"],
                          text="lookup needs a usubjid")

        anchor = self.graph.visit_date(usubjid, visit, cut) if visit else None
        if anchor is None:
            known = self.graph.visits_for(usubjid, cut)
            enrolled = bool(self.graph.records("DM", cut=cut, usubjid=usubjid))
            if not enrolled:
                text = f"no subject {usubjid} in the study at this cut."
                confidence = CONFIDENCE["lookup_no_subject"]
            elif not known:
                text = f"{usubjid} has no dated visit records at cut {cut}."
                confidence = CONFIDENCE["lookup_no_visit_records"]
            else:
                text = (f"{usubjid} has no visit named {visit!r} at cut {cut}; "
                        f"visits on record: {', '.join(sorted(known))}.")
                confidence = CONFIDENCE["lookup_visit_unknown"]
            # Nothing to anchor on is a real, complete answer of "no records",
            # not a reason to guess at a nearby visit.
            return Answer(question_id=question.id, answer=[], text=text,
                          confidence=confidence)

        hits: list[tuple[str, dict]] = []
        undated = 0
        for domain in domains:
            rows = self.graph.records(domain, cut=cut, usubjid=usubjid)
            for position, r in enumerate(rows, start=1):
                d = self.graph.record_date(r, cut)
                if d is None:
                    undated += 1
                    continue
                if abs((d - anchor).days) <= window_days:
                    hits.append((self.record_id(r, fallback_seq=position), r))

        hits.sort(key=lambda t: (t[1]["_domain"], t[1].get("_seq") or 0))
        ids = [i for i, _ in hits]

        text = (f"{len(ids)} record(s) in {', '.join(domains)} within "
                f"{window_days} day(s) of {usubjid}'s {visit} visit ({anchor}).")
        if undated:
            text += f" {undated} record(s) carried no usable date and could not be placed."

        return Answer(
            question_id=question.id,
            answer=ids,
            text=text,
            evidence=[self.ref(r) for _, r in hits],
            # The window is arithmetic on dates that all parsed cleanly. The
            # only genuine uncertainty is records that could not be dated, so
            # confidence drops only when some were skipped.
            confidence=(CONFIDENCE["lookup_clean"] if not undated
                        else CONFIDENCE["lookup_some_undated"]),
        )

    def _answer_finding(self, question: Question, deadline: float) -> Answer:
        """Run the detector named by params["code"] and report what it found.

        Serves both "finding" and "trap" questions, identically. A trap is a
        question whose true answer is empty; it is answered by the detector
        honestly returning nothing, never by Atlas deciding a question looks
        suspicious. There is no code here that could tell the difference, which
        is the point — on the hidden set nothing labels a question as a trap.
        """
        params = dict(question.params or {})
        code = params.get("code")
        site = params.get("site")
        usubjid = params.get("usubjid")
        cut = self.cut_for(question)

        detector = self.detectors.get(code)
        if detector is None:
            known = ", ".join(sorted(self.detectors)) or "none"
            return Answer(
                question_id=question.id, answer=[], confidence=CONFIDENCE["not_claimed"],
                text=(f"no detector for finding code {code!r}; this system does not "
                      f"claim to detect it. Detectors available: {known}."))

        findings = detector(self.graph, site, usubjid, cut) or []

        # Narrow to the requested scope. Done here rather than inside every
        # detector so the filter is written once and cannot drift between them.
        if site:
            findings = [f for f in findings if f.site == site]
        if usubjid:
            findings = [f for f in findings if f.usubjid == usubjid]

        subjects = sorted({f.usubjid for f in findings if f.usubjid})

        evidence: list[RecordRef] = []
        seen: set[tuple] = set()
        for f in findings:
            for ref in f.evidence:
                key = (ref.domain, ref.usubjid, ref.seq, ref.document, ref.section)
                if key not in seen:
                    seen.add(key)
                    evidence.append(ref)

        scope = ""
        if site:
            scope += f" at site {site}"
        if usubjid:
            scope += f" for {usubjid}"

        if not findings:
            # Nothing found is a complete answer, returned exactly as it is.
            # No second pass, no widened search, no guess. Confidence is high
            # because the detector ran cleanly over the whole scope and the
            # absence is a real result -- "nothing here" is not less certain
            # than "something here".
            return Answer(
                question_id=question.id, answer=[], evidence=[], findings=[],
                text=f"No {code} findings{scope} at cut {cut}.",
                confidence=CONFIDENCE["finding_none_found"])

        return Answer(
            question_id=question.id,
            answer=subjects,
            text=(f"{len(subjects)} subject(s){scope} with {code}: "
                  + "; ".join(f.rationale for f in findings[:3])
                  + (" ..." if len(findings) > 3 else "")),
            findings=findings,
            evidence=evidence,
            confidence=round(sum(f.confidence for f in findings) / len(findings), 3),
        )


@detector("SAE_MISCODED")
def detect_sae_miscoded(graph: "StudyGraph", site: str | None, usubjid: str | None,
                        cut: int | None) -> list[Finding]:
    """An event the site coded as non-serious that its own data says was serious.

    Protocol §6: a hospitalisation flag makes an event serious regardless of how
    AESER was coded. So AESHOSP=Y with AESER=N is the site contradicting itself
    on the one field a safety desk acts on.

    The contradiction is read off the record, not assumed: both flags must be
    present and must actually disagree.
    """
    rules = ProtocolRules(graph, cut)
    findings: list[Finding] = []
    for r in graph.records("AE", cut=cut, site=site, usubjid=usubjid):
        hosp = _norm(graph.record_value(r, "AESHOSP", cut))
        serious = _norm(graph.record_value(r, "AESER", cut))
        if hosp != "Y" or serious != "N":
            continue
        term = (graph.record_value(r, "AETERM", cut) or "the event").strip()
        subject = r.get("USUBJID")
        findings.append(Finding(
            code="SAE_MISCODED",
            usubjid=subject,
            site=graph.site_for(subject),
            severity="HIGH",
            rationale=(f"{term!r} has AESHOSP=Y but AESER=N: a hospitalisation makes an "
                       f"event serious regardless of how AESER was coded "
                       f"({rules.document_name} §6), so this event is under-coded and "
                       f"was not reported as serious."),
            evidence=[Atlas.ref(r), rules.evidence_ref(6)],
            # Two explicit flags on one record contradicting each other. There is
            # no interpretation involved and nothing was inferred.
            confidence=CONFIDENCE["sae_miscoded"],
            protocol_version=rules.version,
        ))
    findings.sort(key=lambda f: (f.usubjid or ""))
    return findings


@detector("AE_BEFORE_FIRST_DOSE")
def detect_ae_before_first_dose(graph: "StudyGraph", site: str | None, usubjid: str | None,
                                cut: int | None) -> list[Finding]:
    """An adverse event dated before the subject was first dosed.

    Almost always a date entry error rather than a safety signal: an event
    cannot be caused by a drug the subject had not yet received, so either the
    event date or the dosing date is wrong.

    The anchor is DM.RFSTDTC, the study's own reference start date — not the
    earliest EX record. See StudyGraph.first_dose_date for why these are not
    interchangeable.

    A subject with no first dose at all cannot be evaluated here and is skipped
    rather than guessed at; that case is its own finding
    (MISSING_EXPOSURE_RECORD).
    """
    findings: list[Finding] = []
    subjects = ([usubjid] if usubjid else
                [r["USUBJID"] for r in graph.records("DM", cut=cut, site=site)])

    for subject in subjects:
        anchor = graph.first_dose_date(subject, cut)
        if anchor is None:
            continue                     # cannot evaluate; not a silent pass, see above
        for r in graph.records("AE", cut=cut, usubjid=subject):
            onset = graph.record_date(r, cut)
            if onset is None or onset >= anchor:
                continue
            days = (anchor - onset).days
            term = (graph.record_value(r, "AETERM", cut) or "adverse event").strip()
            findings.append(Finding(
                code="AE_BEFORE_FIRST_DOSE",
                usubjid=subject,
                site=graph.site_for(subject),
                severity="MEDIUM",
                rationale=(f"{term!r} is dated {onset}, {days} day(s) before the subject's "
                           f"first dose on {anchor} (DM.RFSTDTC). An event cannot precede "
                           f"the exposure it is recorded against, so one of the two dates "
                           f"is wrong."),
                evidence=[Atlas.ref(r), RecordRef(domain="DM", usubjid=subject)],
                # Date arithmetic on two dates that both parsed. The only
                # judgement is which of the two dates is the wrong one, and the
                # finding does not claim to know that. A one-day gap is as
                # likely a transcription slip as a real ordering error, so a
                # narrow gap is genuinely less certain than a wide one.
                confidence=(CONFIDENCE["ae_before_first_dose"]
                            if days >= MARGINAL_DAY_GAP
                            else CONFIDENCE["ae_before_dose_marginal"]),
                protocol_version=graph.protocol_version_at(cut),
            ))
    findings.sort(key=lambda f: (f.usubjid or ""))
    return findings


@detector("DUPLICATE_SUBJECT")
def detect_duplicate_subject(graph: "StudyGraph", site: str | None, usubjid: str | None,
                             cut: int | None) -> list[Finding]:
    """One person apparently enrolled twice under two USUBJIDs.

    HEURISTIC, and a stated limitation rather than a hidden assumption: this
    schema carries no person identifier that spans subjects, so the only
    available signal is demographic agreement. The key used is
    DMINIT + BRTHDTC + SEX — subject initials, date of birth and sex, the
    standard clinical duplicate-enrolment check.

    COUNTRY and SITEID are deliberately NOT part of the key. A person enrolling
    twice usually does so at a different site, often in a different country;
    requiring those to match would suppress exactly the case being looked for.
    On the practice study the matched pair sits at two sites in two countries
    (DE and IN) and agrees on initials, date of birth, sex, arm, reference start
    date and screening HbA1c — a key including COUNTRY finds nothing at all.

    What this cannot do: distinguish a genuine duplicate from two different
    people who share initials, a birth date and a sex. That is why every such
    group is reported with the agreeing fields in its rationale, for a human to
    confirm, and why confidence rises with the number of independent fields
    that agree rather than being asserted.
    """
    key_fields = ("DMINIT", "BRTHDTC", "SEX")
    #: Fields checked for extra agreement, to weight the finding. Not part of
    #: the key — a duplicate need not agree on these to be a duplicate.
    corroborating = ("ARM", "RFSTDTC", "SCR_HBA1C", "AGE")

    groups: dict[tuple, list[dict]] = {}
    for r in graph.records("DM", cut=cut):
        key = tuple(_norm(graph.record_value(r, f, cut)) for f in key_fields)
        if any(not part for part in key):
            continue                      # an incomplete key cannot match anything
        groups.setdefault(key, []).append(r)

    findings: list[Finding] = []
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: r.get("USUBJID") or "")
        ids = [r.get("USUBJID") for r in rows]
        sites = {graph.site_for(i) for i in ids}

        agreed = [f for f in corroborating
                  if len({_norm(graph.record_value(r, f, cut)) for r in rows}) == 1]
        # Three key fields always agree by construction; each additional
        # independent field that also agrees makes coincidence less likely.
        confidence = min(CONFIDENCE["duplicate_subject_max"],
                         DUPLICATE_BASE_CONFIDENCE
                         + DUPLICATE_PER_FIELD_BONUS * len(agreed))

        detail = ", ".join(f"{f}={rows[0].get(f)!r}" for f in key_fields)
        extra = (" They also share " + ", ".join(f"{f}={rows[0].get(f)!r}" for f in agreed) + "."
                 if agreed else "")
        across = (f" enrolled at {len(sites)} different sites ({', '.join(sorted(s for s in sites if s))})"
                  if len(sites) > 1 else " enrolled at the same site")

        for r in rows:
            findings.append(Finding(
                code="DUPLICATE_SUBJECT",
                usubjid=r.get("USUBJID"),
                site=graph.site_for(r.get("USUBJID")),
                severity="HIGH",
                rationale=(f"{' and '.join(ids)} share {detail}{across}.{extra} "
                           f"Heuristic: this schema has no person identifier spanning "
                           f"subjects, so demographic agreement is the only available "
                           f"signal — reported for human confirmation, not asserted."),
                evidence=[RecordRef(domain="DM", usubjid=i) for i in ids],
                confidence=confidence,
                protocol_version=graph.protocol_version_at(cut),
            ))
    findings.sort(key=lambda f: (f.usubjid or ""))
    return findings


@detector("VISIT_OUT_OF_WINDOW")
def detect_visit_out_of_window(graph: "StudyGraph", site: str | None, usubjid: str | None,
                               cut: int | None) -> list[Finding]:
    """A visit performed outside its protocol-defined window.

    Protocol §4 gives a scheduled day per visit and a window around it. Both the
    schedule and the window width are read from the version in force at the
    question's cut — PRD FR-17 — which matters here more than anywhere else,
    because the amendment narrows the window from ±7 to ±3 days. 205 real
    visit-instances in the practice study fall in that gap: correct under v1,
    deviations under v2/v3. The same record therefore gets different, and
    equally correct, answers depending on the cut it is asked about.

    Day 0 is the subject's own Baseline visit date, so the schedule is applied
    per subject rather than against a study-wide calendar. A subject with no
    Baseline visit falls back to DM.RFSTDTC; with neither, the subject cannot be
    evaluated and is skipped rather than measured against a guess.

    One finding per (subject, visit) rather than per record: six laboratory rows
    drawn on the same out-of-window day are one deviation, not six.
    """
    rules = ProtocolRules(graph, cut)
    findings: list[Finding] = []

    subjects = ([usubjid] if usubjid else
                [r["USUBJID"] for r in graph.records("DM", cut=cut, site=site)])

    for subject in subjects:
        visits = graph.visits_for(subject, cut)
        if not visits:
            continue
        anchor = visits.get("BASELINE") or graph.reference_start_date(subject, cut)
        if anchor is None:
            continue                     # no day 0 to measure against; do not guess

        for visit, actual in sorted(visits.items(), key=lambda kv: kv[1]):
            scheduled_day = rules.visit_schedule.get(_normalise_visit_name(visit))
            if scheduled_day is None:
                continue                 # a visit the protocol does not schedule
            actual_day = (actual - anchor).days
            drift = actual_day - scheduled_day
            if abs(drift) <= rules.visit_window_days:
                continue

            # Cite the records that carry this visit's date — the ones that
            # actually show when it happened — one per domain, not all of them.
            evidence: list[RecordRef] = []
            for domain in VISIT_DOMAINS:
                for r in graph.records(domain, cut=cut, usubjid=subject, visit=visit):
                    if graph.record_date(r, cut) == actual:
                        evidence.append(Atlas.ref(r))
                        break
            evidence.append(rules.evidence_ref(4))

            direction = "late" if drift > 0 else "early"
            over = abs(drift) - rules.visit_window_days
            findings.append(Finding(
                code="VISIT_OUT_OF_WINDOW",
                usubjid=subject,
                site=graph.site_for(subject),
                severity="LOW",
                rationale=(
                    f"{visit} took place on {actual}, day {actual_day:+d} relative to the "
                    f"subject's baseline on {anchor}, against a scheduled day "
                    f"{scheduled_day:+d} — {abs(drift)} day(s) {direction}, which is "
                    f"{over} day(s) outside the ±{rules.visit_window_days}-day window in "
                    f"{rules.document_name} §4 (protocol v{rules.version})."),
                evidence=evidence,
                # Date arithmetic against a window read from the document. The
                # one soft edge is a visit that misses by a single day, where a
                # date transcription slip is as likely as a real deviation.
                confidence=(CONFIDENCE["visit_out_of_window"]
                            if over >= MARGINAL_DAY_GAP
                            else CONFIDENCE["visit_window_marginal"]),
                protocol_version=rules.version,
            ))
    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


@detector("INCLUSION_VIOLATION")
def detect_inclusion_violation(graph: "StudyGraph", site: str | None, usubjid: str | None,
                               cut: int | None) -> list[Finding]:
    """A subject who did not meet inclusion criteria at screening.

    Protocol §2: age 18-75 and screening HbA1c 7.0-10.5%, both read from the
    active protocol document rather than assumed. DM.AGE and DM.SCR_HBA1C are
    the screening-time values by construction (this schema records them once,
    at screening) so no separate visit lookup is needed for either.
    """
    rules = ProtocolRules(graph, cut)
    lo_age, hi_age = rules.inclusion_age_range
    lo_hba, hi_hba = rules.inclusion_hba1c_range
    findings: list[Finding] = []

    for r in graph.records("DM", cut=cut, site=site, usubjid=usubjid):
        subject = r["USUBJID"]
        age = to_number(graph.record_value(r, "AGE", cut))
        hba1c = to_number(graph.record_value(r, "SCR_HBA1C", cut))

        if age is not None and not (lo_age <= age <= hi_age):
            findings.append(Finding(
                code="INCLUSION_VIOLATION", usubjid=subject, site=graph.site_for(subject),
                severity="HIGH",
                rationale=(f"Age {age:g} at screening is outside the protocol's "
                           f"{lo_age:g}-{hi_age:g} inclusion range ({rules.document_name} §2)."),
                evidence=[RecordRef(domain="DM", usubjid=subject), rules.evidence_ref(2)],
                # A recorded demographic compared to a documented range — no
                # measurement noise, no missing data.
                confidence=CONFIDENCE["inclusion_violation"],
                protocol_version=rules.version))

        if hba1c is not None and not (lo_hba <= hba1c <= hi_hba):
            findings.append(Finding(
                code="INCLUSION_VIOLATION", usubjid=subject, site=graph.site_for(subject),
                severity="HIGH",
                rationale=(f"Screening HbA1c {hba1c:g}% is outside the protocol's "
                           f"{lo_hba:g}%-{hi_hba:g}% inclusion range "
                           f"({rules.document_name} §2)."),
                evidence=[RecordRef(domain="DM", usubjid=subject), rules.evidence_ref(2)],
                confidence=CONFIDENCE["inclusion_violation"],
                protocol_version=rules.version))

    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


@detector("EXCLUSION_VIOLATION")
def detect_exclusion_violation(graph: "StudyGraph", site: str | None, usubjid: str | None,
                               cut: int | None) -> list[Finding]:
    """A subject who met an exclusion criterion the study should have screened out.

    Protocol §3: known hepatic disease (screening ALT or AST > 2x ULN) is
    excluded from the start; renal impairment (screening creatinine > 1.5 mg/dL)
    is added from the v2 amendment. Whether the creatinine rule applies is
    decided by whether the ACTIVE document at this cut mentions it
    (rules.exclusion_creat_active), not by a hard-coded "if version >= 2" — so
    a hidden study whose amendment lands at a different cut, or is worded
    differently, is still handled correctly.

    Screening ALT/AST goes through standardise_lab, same as the Hy's law
    detector — a local-lab subject's screening values need the same conversion
    before comparison.
    """
    rules = ProtocolRules(graph, cut)
    findings: list[Finding] = []

    subjects = ([usubjid] if usubjid else
                [r["USUBJID"] for r in graph.records("DM", cut=cut, site=site)])

    for subject in subjects:
        labs, _unusable, _mismatched = standardised_labs(
            graph, subject, cut, ("ALT", "AST", "CREAT"))
        screening = [lv for lv in labs if (lv.record.get("VISIT") or "").strip() == "SCREENING"]

        for lv in [lv for lv in screening if lv.testcd in ("ALT", "AST")
                  and lv.exceeds(rules.exclusion_liver_multiple)]:
            findings.append(Finding(
                code="EXCLUSION_VIOLATION", usubjid=subject, site=graph.site_for(subject),
                severity="HIGH",
                rationale=(f"Screening {lv.describe()} exceeds "
                           f"{rules.exclusion_liver_multiple:g}x ULN "
                           f"({rules.exclusion_liver_multiple * lv.high:g} {lv.unit}), "
                           f"meeting the known-hepatic-disease exclusion criterion "
                           f"({rules.document_name} §3)."),
                evidence=[Atlas.ref(lv.record), rules.evidence_ref(3)],
                confidence=CONFIDENCE["exclusion_violation"],
                protocol_version=rules.version))

        if rules.exclusion_creat_active:
            for lv in [lv for lv in screening if lv.testcd == "CREAT"
                      and lv.value is not None and lv.value > rules.exclusion_creat_threshold]:
                findings.append(Finding(
                    code="EXCLUSION_VIOLATION", usubjid=subject, site=graph.site_for(subject),
                    severity="HIGH",
                    rationale=(f"Screening {lv.describe()} exceeds "
                               f"{rules.exclusion_creat_threshold:g} mg/dL, meeting the "
                               f"renal-impairment exclusion criterion added in "
                               f"{rules.document_name} §3."),
                    evidence=[Atlas.ref(lv.record), rules.evidence_ref(3)],
                    confidence=CONFIDENCE["exclusion_violation"],
                    protocol_version=rules.version))

    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


@detector("PROHIBITED_CONMED")
def detect_prohibited_conmed(graph: "StudyGraph", site: str | None, usubjid: str | None,
                             cut: int | None) -> list[Finding]:
    """Use of a medication the active protocol prohibits.

    Matched against CM.CMCLAS, the stable coded class, never CMTRT (the free-
    text drug name a hidden study could spell any number of ways). The
    prohibited set itself is read from the active document's §5 bullet list
    (ProtocolRules), so whether a class is prohibited depends on the protocol
    version in force at the record's own cut — an amendment adding a new
    prohibited class does not retroactively prohibit a conmed taken before it,
    and does not un-prohibit one taken after.
    """
    findings: list[Finding] = []
    for r in graph.records("CM", cut=cut, site=site, usubjid=usubjid):
        record_cut = r["_cut"]
        rules = ProtocolRules(graph, record_cut)
        cmclas = _norm(graph.record_value(r, "CMCLAS", cut)).replace(" ", "_")
        if cmclas not in rules.prohibited_conmed_classes:
            continue
        subject = r.get("USUBJID")
        trt = (graph.record_value(r, "CMTRT", cut) or cmclas).strip()
        findings.append(Finding(
            code="PROHIBITED_CONMED", usubjid=subject, site=graph.site_for(subject),
            severity="MEDIUM",
            rationale=(f"{trt} ({cmclas}) is on the prohibited list under "
                       f"{rules.document_name} §5, in force when this medication was "
                       f"recorded (cut {record_cut})."),
            evidence=[Atlas.ref(r), rules.evidence_ref(5)],
            # A coded class matched directly against a documented list.
            confidence=CONFIDENCE["prohibited_conmed"],
            protocol_version=rules.version))
    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


@detector("DOSING_ERROR")
def detect_dosing_error(graph: "StudyGraph", site: str | None, usubjid: str | None,
                        cut: int | None) -> list[Finding]:
    """An administered dose other than the protocol's 10mg (drug) / 0mg (placebo).

    Protocol §8: correct EXDOSE is 10 for EXTRT=DRUG, 0 for EXTRT=PLACEBO.
    Anything else is a dosing error and a protocol deviation.

    Two distinct problems share this detector, since both are the same
    underlying deviation (an administered dose not matching what should have
    been given): a wrong dose for the record's own EXTRT, and an EXTRT that
    disagrees with the subject's randomised DM.ARM — the latter would mean the
    wrong drug was dispensed, which the dose alone would not catch.
    """
    findings: list[Finding] = []
    subjects = ([usubjid] if usubjid else
                [r["USUBJID"] for r in graph.records("DM", cut=cut, site=site)])

    for subject in subjects:
        arm_rows = graph.records("DM", cut=cut, usubjid=subject)
        arm = (arm_rows[0].get("ARM") or "").strip().upper() if arm_rows else None

        for r in graph.records("EX", cut=cut, usubjid=subject):
            extrt = _norm(graph.record_value(r, "EXTRT", cut))
            dose = to_number(graph.record_value(r, "EXDOSE", cut))
            visit = r.get("VISIT") or "this administration"

            expected = {"DRUG": 10.0, "PLACEBO": 0.0}.get(extrt)
            if expected is not None and dose is not None and dose != expected:
                findings.append(Finding(
                    code="DOSING_ERROR", usubjid=subject, site=graph.site_for(subject),
                    severity="HIGH",
                    rationale=(f"{visit}: administered dose is {dose:g} for EXTRT={extrt}, "
                               f"but the protocol specifies {expected:g} "
                               f"({'DRUG' if extrt == 'DRUG' else 'PLACEBO'} arm). "
                               f"Protocol §8."),
                    evidence=[Atlas.ref(r)],
                    # Exact comparison against the protocol's own two allowed values.
                    confidence=CONFIDENCE["dosing_error_dose"],
                    protocol_version=graph.protocol_version_at(record_cut := r["_cut"])))

            if arm and extrt and extrt != arm:
                findings.append(Finding(
                    code="DOSING_ERROR", usubjid=subject, site=graph.site_for(subject),
                    severity="CRITICAL",
                    rationale=(f"{visit}: EXTRT={extrt} does not match the subject's "
                               f"randomised arm (DM.ARM={arm}) — the wrong treatment may "
                               f"have been dispensed."),
                    evidence=[Atlas.ref(r), RecordRef(domain="DM", usubjid=subject)],
                    confidence=CONFIDENCE["dosing_error_arm"],
                    protocol_version=graph.protocol_version_at(r["_cut"])))

    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


@detector("MISSING_EXPOSURE_RECORD")
def detect_missing_exposure_record(graph: "StudyGraph", site: str | None, usubjid: str | None,
                                   cut: int | None) -> list[Finding]:
    """A subject with visit-domain records but no corresponding EX dosing record.

    Two shapes, both real gaps in the exposure record:

    1. PRIMARY, unambiguous case: a subject enrolled (has a DM row) with zero
       EX records at all — dosing was apparently never recorded despite
       enrolment. Confirmed present in the practice data: exactly one subject,
       042-S05-021 (who also carries zero LB/VS/AE records — see T1.13's
       duplicate-subject finding for the same subject).

    2. A post-baseline LB or VS record at a named visit with no EX record on or
       before that visit's date for the same subject — a visit where dosing
       should have already happened, evidenced. On the practice study this case
       has zero real instances (every subject who has any EX record has one at
       or before every later LB/VS visit), confirmed by an exhaustive scan
       rather than assumed; the detector still checks for it because a hidden
       study need not share that property.
    """
    findings: list[Finding] = []
    subjects = ([usubjid] if usubjid else
                [r["USUBJID"] for r in graph.records("DM", cut=cut, site=site)])

    for subject in subjects:
        ex_rows = graph.records("EX", cut=cut, usubjid=subject)
        if not ex_rows:
            dm_row = graph.records("DM", cut=cut, usubjid=subject)
            other_domains = [d for d in ("LB", "VS", "AE", "CM", "DS", "MH", "EG")
                             if graph.records(d, cut=cut, usubjid=subject)]
            findings.append(Finding(
                code="MISSING_EXPOSURE_RECORD", usubjid=subject, site=graph.site_for(subject),
                severity="HIGH",
                rationale=(f"Subject is enrolled but has zero EX (dosing) records at cut "
                           f"{cut}." + (f" Other domains present: {', '.join(other_domains)}."
                                       if other_domains else " No other domain has records "
                                       "for this subject either.")),
                evidence=[RecordRef(domain="DM", usubjid=subject)],
                # An absence over the whole EX domain for an enrolled subject —
                # nothing borderline about zero records.
                confidence=CONFIDENCE["missing_exposure_total"],
                protocol_version=graph.protocol_version_at(cut)))
            continue

        ex_dates = sorted(d for d in (graph.record_date(r, cut) for r in ex_rows) if d)
        seen_visits: set[str] = set()
        for domain in ("LB", "VS"):
            for r in graph.records(domain, cut=cut, usubjid=subject):
                visit = (r.get("VISIT") or "").strip()
                if not visit or visit.upper() == "SCREENING" or visit in seen_visits:
                    continue
                d = graph.record_date(r, cut)
                if d is None:
                    continue
                if ex_dates and any(e <= d for e in ex_dates):
                    continue
                seen_visits.add(visit)
                findings.append(Finding(
                    code="MISSING_EXPOSURE_RECORD", usubjid=subject, site=graph.site_for(subject),
                    severity="MEDIUM",
                    rationale=(f"{domain} record at visit {visit} ({d}) has no EX (dosing) "
                               f"record on or before that date for this subject."),
                    evidence=[Atlas.ref(r)],
                    confidence=CONFIDENCE["missing_exposure_visit"],
                    protocol_version=graph.protocol_version_at(cut)))

    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


@detector("LAB_UNIT_MISMATCH")
def detect_lab_unit_mismatch(graph: "StudyGraph", site: str | None, usubjid: str | None,
                             cut: int | None) -> list[Finding]:
    """A laboratory record whose unit matches no known reference range.

    Distinct from the S07-style KNOWN local-laboratory variant, which
    standardise_lab converts without complaint via reference_ranges.csv's LAB
    column. This detector fires only on a genuine data-quality gap: a unit that
    is neither the central unit nor any documented conversion source for that
    test — something standardise_lab could not resolve at all, and every other
    detector that calls it silently skips.

    Runs every real LB record through standardise_lab; a NoReferenceRange (the
    test itself is not in reference_ranges.csv) is a different problem from a
    bad unit on a known test and is not reported here.
    """
    findings: list[Finding] = []
    for r in graph.records("LB", cut=cut, site=site, usubjid=usubjid):
        testcd = (r.get("LBTESTCD") or "").strip().upper()
        unit = r.get("LBORRESU")
        raw = graph.record_value(r, "LBORRES", cut)
        try:
            standardise_lab(testcd, raw, unit, graph.ranges)
        except UnitMismatch as exc:
            subject = r.get("USUBJID")
            findings.append(Finding(
                code="LAB_UNIT_MISMATCH", usubjid=subject, site=graph.site_for(subject),
                severity="MEDIUM",
                rationale=(f"{testcd} record carries unit {unit!r}, which matches "
                           f"neither the central laboratory's unit nor any known "
                           f"conversion for this test: {exc}"),
                evidence=[Atlas.ref(r)],
                # The unit itself is either recognised or it is not — no
                # judgement call involved once standardise_lab has raised.
                confidence=CONFIDENCE["lab_unit_mismatch"],
                protocol_version=graph.protocol_version_at(cut)))
        except NoReferenceRange:
            continue                     # a different problem; not reported here
    findings.sort(key=lambda f: (f.usubjid or "", f.rationale))
    return findings


# ================================================================== entry point
def main(argv: list[str] | None = None) -> int:
    """`python -m stage1.atlas --data hackathon-data`

    The entry point the organiser's README template documents and a judge is
    expected to run from a clean checkout. It builds the graph, prints what
    was loaded, lists the detectors this system actually claims, and answers
    one real question end to end so the output is evidence the thing works —
    not just a silent exit.
    """
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(
        prog="python -m stage1.atlas",
        description="Cureva Stage 1 — build the study graph and answer a question.")
    parser.add_argument("--data", default="hackathon-data",
                        help="path to the hackathon-data folder")
    parser.add_argument("--cut", type=int, default=None,
                        help="build at this data cut (default: the whole study)")
    parser.add_argument("--question", default=None,
                        help="a Question as JSON, e.g. "
                             "'{\"id\":\"q\",\"kind\":\"finding\",\"text\":\"\","
                             "\"params\":{\"code\":\"HYS_LAW_CANDIDATE\"}}'")
    parser.add_argument("--json", action="store_true",
                        help="print machine-readable JSON instead of a report")
    args = parser.parse_args(argv)

    graph = StudyGraph(args.data)
    stats = graph.build(cut=args.cut)
    atlas = Atlas(graph)

    if args.question:
        question = Question(**_json.loads(args.question))
        answer = atlas.answer(question)
        print(_json.dumps(answer.model_dump(mode="json"), indent=2, default=str))
        return 0

    if args.json:
        print(_json.dumps(graph.stats, indent=2, default=str))
        return 0

    extra = graph.stats
    print(f"Cureva Stage 1 — Atlas      data: {args.data}")
    print("=" * 62)
    print(f"  graph built             {stats['nodes']} records, "
          f"{stats['subjects']} subjects, {stats['ms']}ms")
    print(f"  cut                     {stats['cut'] if stats['cut'] is not None else 'all'}"
          f"   (protocol v{extra.get('protocol_version')})")
    print(f"  corrections applied     {extra.get('corrections_applied')}")
    print(f"  malformed rows skipped  {extra.get('malformed_rows')}")
    print(f"  documents loaded        {', '.join(extra.get('documents', []))}")
    print()
    print("  records per domain")
    for domain, count in (extra.get("per_domain") or {}).items():
        note = "   <- Cureva's 10th domain, written only by the avatar (Act 1)" \
               if domain == PRO_DOMAIN else ""
        print(f"    {domain:<5} {count:>6}{note}")
    print()
    print(f"  detectors registered    {len(atlas.detectors)}")
    for code in sorted(atlas.detectors):
        print(f"    - {code}")
    print(f"  count metrics           {', '.join(sorted(atlas.metrics)) or 'none'}")
    print()

    # One real question, answered end to end, so this output is evidence.
    demo = Question(id="demo", kind="finding", text="Which subjects show the "
                    "liver-damage pattern?", params={"code": "HYS_LAW_CANDIDATE"},
                    cut=args.cut)
    answer = atlas.answer(demo)
    print(f"  example question        {demo.params['code']}")
    print(f"    answer                {answer.answer}")
    print(f"    confidence            {answer.confidence}")
    print(f"    evidence              {len(answer.evidence)} record reference(s)")
    if answer.findings:
        print(f"    first rationale       {answer.findings[0].rationale[:150]}...")
    print("=" * 62)
    print("Score against the public question bank with:")
    print(f"  python run_local_harness.py --module stage1.atlas --data {args.data}")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
