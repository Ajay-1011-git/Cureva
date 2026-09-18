"""`ReviewCrew` — Cureva's Stage 2 review cycle. This is the graded contract.

    ReviewCrew(data_dir, atlas).run_cycle(cut, protocol_version) -> ReviewReport

Six nodes, always in this order, always all six:

    DETECT -> MEDICAL REVIEW -> DATA MANAGER -> COMPLIANCE -> HUMAN GATE -> EXECUTE

The single most important rule in this file: **no detector logic lives here.**
Every finding arrives through `Atlas.answer()`. Stage 1 spent its whole build
getting `AE_BEFORE_FIRST_DOSE`'s anchor, `DUPLICATE_SUBJECT`'s key and the
correction-resolution order right; re-deriving any of that here would quietly
reintroduce the bugs it fixed. The same goes for site membership, which always
goes through `StudyGraph.site_for()`, never a USUBJID prefix match.

The second rule: a cycle is repeatable. Running the same cut twice raises zero
new queries and zero new escalations. Every piece of state this file touches is
either derived deterministically from the finding itself or guarded by
`CrewMemory`, and the two places where the obvious implementation would have
broken that property are called out where they occur.

Contract shapes are documented in `docs/stage2-contract-audit.md`, read from
the organiser's real `schemas.py`/`study.py` rather than assumed.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from schemas import (EscalationOut, Finding, Question, QueryOut, RecordRef,
                     ReviewReport)
from stage1.atlas import Atlas, StudyGraph, _norm
from study import Study

from stage2.memory import CrewMemory, query_key
from stage2.models import EscalationRecord, TraceEntry
from stage2.trace import TraceWriter

log = logging.getLogger("cureva.stage2.crew")

# --------------------------------------------------------------------------
# Vocabulary. Every code here is one Stage 1 actually registers a detector for
# (verified against `Atlas.detectors` in docs/stage2-contract-audit.md 5),
# plus the one code Stage 2 owns.
# --------------------------------------------------------------------------

#: The 11 codes answerable from a single build snapshot. DETECT sweeps these.
SNAPSHOT_CODES: tuple[str, ...] = (
    "HYS_LAW_CANDIDATE", "SAE_MISCODED", "AE_BEFORE_FIRST_DOSE",
    "DUPLICATE_SUBJECT", "VISIT_OUT_OF_WINDOW", "INCLUSION_VIOLATION",
    "EXCLUSION_VIOLATION", "PROHIBITED_CONMED", "DOSING_ERROR",
    "MISSING_EXPOSURE_RECORD", "LAB_UNIT_MISMATCH",
)

#: The one code Stage 2 owns, per PRD 4.3's resolution of the ownership
#: conflict between the Stage 1 PRD and the Stage 2 overview.
SAE_UNESCALATED = "SAE_UNESCALATED"

# MEDICAL REVIEW's rule table. This was not specified upstream; it is a stated
# design decision, and the reasoning is the split between "a clinician has to
# look at this today" and "this is a data-quality defect the site should fix".
#
# Always escalation-worthy -- each is a safety or protocol-integrity event
# whose consequence is clinical, not clerical:
ALWAYS_ESCALATE: frozenset[str] = frozenset({
    "HYS_LAW_CANDIDATE",     # possible drug-induced liver injury
    "SAE_MISCODED",          # a serious event not reported as serious
    SAE_UNESCALATED,         # a serious event nobody ever acted on
    "PROHIBITED_CONMED",     # a banned concomitant medication, taken
    "DOSING_ERROR",          # the subject received the wrong dose
    "EXCLUSION_VIOLATION",   # the subject should never have been enrolled
})

# Monitor-only by default -- real defects, but ones a data manager resolves
# with a query rather than a clinician resolving with a decision. They become
# escalation-worthy when they compound on one subject (see COMPOUNDING_AT),
# because several independent defects on the same subject stop looking like
# clerical noise and start looking like a site that is not following the
# protocol.
MONITOR_BY_DEFAULT: frozenset[str] = frozenset({
    "AE_BEFORE_FIRST_DOSE", "VISIT_OUT_OF_WINDOW", "LAB_UNIT_MISMATCH",
    "MISSING_EXPOSURE_RECORD", "DUPLICATE_SUBJECT", "INCLUSION_VIOLATION",
})

#: How many flagged findings on one subject turn a monitor-only code into an
#: escalation. Stated design choice, not specified upstream.
COMPOUNDING_AT = 2

#: Codes DATA MANAGER raises site queries for -- the ones a site can actually
#: answer by checking source documents. A Hy's-law candidate is not on this
#: list: the lab values are not in doubt, the clinical interpretation is.
DATA_QUALITY_CODES: frozenset[str] = frozenset({
    "AE_BEFORE_FIRST_DOSE", "LAB_UNIT_MISMATCH",
    "MISSING_EXPOSURE_RECORD", "VISIT_OUT_OF_WINDOW",
})

#: Codes COMPLIANCE re-expresses as protocol deviations.
DEVIATION_CODES: frozenset[str] = frozenset({
    "INCLUSION_VIOLATION", "EXCLUSION_VIOLATION", "VISIT_OUT_OF_WINDOW",
    "PROHIBITED_CONMED", "DOSING_ERROR",
})

#: The three literals `study.escalate()` really returns (audit 2, confirmed
#: against the 1518 entries in the practice study's monitor_decisions.json).
APPROVED, REJECTED, CLARIFY = "APPROVED", "REJECTED", "CLARIFY"


def _stable_id(prefix: str, *parts: Any) -> str:
    """A short id derived from the finding itself, not from a counter.

    This is what makes idempotency work at all. Two cycles over the same cut
    produce the same findings, so they produce the same ids, so memory
    recognises the second cycle's escalations as ones it has already raised. A
    counter-based id would make every cycle's escalations look new.
    """
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()
    return f"{prefix}-{digest[:12]}"


def finding_id(finding: Finding) -> str:
    """A stable id for a finding. `Finding` has no id field of its own."""
    return _stable_id("F", finding.fingerprint())


def escalation_id_for(finding: Finding) -> str:
    return _stable_id("ESC", finding.fingerprint())


@dataclass
class Verdict:
    """MEDICAL REVIEW's judgment on one finding.

    Computed entirely from the rule table. Act 3's Tribunal may later add
    narrative and alternatives on top of this, but never changes `escalate`.
    """

    finding_id: str
    finding: Finding
    escalate: bool
    rule: str
    alternatives: list[str] = field(default_factory=list)
    narrative: str | None = None
    tribunal_ran: bool = False


@dataclass
class CycleContext:
    """The one mutable object threaded through all six nodes."""

    cut: int
    protocol_version: int
    cycle_number: int
    started: float
    findings: list[Finding] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    queries: list[QueryOut] = field(default_factory=list)
    deviations: list[Finding] = field(default_factory=list)
    escalations: list[EscalationOut] = field(default_factory=list)
    tokens_used: int = 0

    @property
    def elapsed_ms(self) -> int:
        return int(round((time.perf_counter() - self.started) * 1000))


class ReviewCrew:
    """The graded six-node review cycle."""

    def __init__(self, data_dir: str, atlas: Atlas,
                 state_dir: str | Path = "state"):
        self.data_dir = data_dir
        self.atlas = atlas
        self.graph: StudyGraph = atlas.graph

        # `Study` is constructed only for the organiser's two response
        # channels -- escalate() and query_site() -- which Atlas does not
        # expose. Every finding and every field value still comes through the
        # Atlas that was passed in, so FR-1 holds: the graph is not rebuilt.
        self.study = Study(data_dir)

        self.state_dir = Path(state_dir)
        self.memory = CrewMemory(self.state_dir / "memory_snapshot.json")
        self.memory.load()
        self.trace = TraceWriter(self.state_dir / "trace" / "cycle_trace.jsonl")

    # =====================================================================
    # The graded entry point
    # =====================================================================
    def run_cycle(self, cut: int, protocol_version: int) -> ReviewReport:
        """One review cycle. Six nodes, in order, every time."""
        started = time.perf_counter()

        # Snapshot the graph at this cut so every detector, every corrected
        # value and every protocol lookup in this cycle agrees on when "now"
        # is. This re-filters existing indices; no CSV is re-read.
        self.graph.build(cut)

        # The protocol version actually in force at this cut, resolved by
        # Stage 1's own T1.20 logic -- never the caller's word for it, never a
        # constant (T2.7). They agree in normal use; when they do not, the
        # resolved one is right and the disagreement is traced.
        resolved_version = self.graph.protocol_version_at(cut)

        self.memory.cycle_number += 1
        ctx = CycleContext(cut=cut, protocol_version=resolved_version,
                           cycle_number=self.memory.cycle_number, started=started)
        self.trace.begin_cycle()

        if protocol_version != resolved_version:
            self._trace(ctx, "DETECT", "finding_detected",
                        f"caller passed protocol_version={protocol_version} but cut {cut} "
                        f"is governed by v{resolved_version}; using v{resolved_version}")

        self._node_detect(ctx)
        self._node_medical_review(ctx)
        self._node_data_manager(ctx)
        self._node_compliance(ctx)
        self._node_human_gate(ctx)
        report = self._node_execute(ctx)

        # Snapshotted here, by the crew, not left to the caller to remember.
        self.memory.snapshot()
        return report

    # ------------------------------------------------------------- tracing
    def _trace(self, ctx: CycleContext, node: str, decision_type: str,
               summary: str, *, finding_id: str | None = None,
               escalation_id: str | None = None,
               evidence: list[RecordRef] | None = None,
               duration_ms: int = 0) -> TraceEntry:
        return self.trace.write(
            cycle=ctx.cycle_number, cut=ctx.cut,
            protocol_version=ctx.protocol_version, node=node,
            decision_type=decision_type, summary=summary,
            finding_id=finding_id, escalation_id=escalation_id,
            evidence=evidence, duration_ms=duration_ms)

    # =====================================================================
    # 1. DETECT
    # =====================================================================
    def _node_detect(self, ctx: CycleContext) -> None:
        """Sweep every snapshot code through `Atlas.answer()`.

        An empty result for a code is a correct, honest outcome -- the same
        honesty Stage 1's traps are built on -- not a gap to fill in with a
        second, looser pass.
        """
        for code in SNAPSHOT_CODES:
            t0 = time.perf_counter()
            question = Question(
                # `id` and `text` are required on the organiser's Question and
                # have no defaults (audit 6); the build document's example
                # omits both.
                id=f"cycle{ctx.cycle_number}-detect-{code.lower()}",
                kind="finding",
                text=f"Every {code} finding in the study at cut {ctx.cut}.",
                params={"code": code},
                cut=ctx.cut,
            )
            answer = self.atlas.answer(question)
            ctx.findings.extend(answer.findings)
            ctx.tokens_used += answer.tokens_used
            took = int(round((time.perf_counter() - t0) * 1000))
            self._trace(ctx, "DETECT", "finding_detected",
                        f"{code}: {len(answer.findings)} finding(s) at cut {ctx.cut}",
                        evidence=answer.evidence[:8], duration_ms=took)

        self._detect_sae_unescalated(ctx)

    def _detect_sae_unescalated(self, ctx: CycleContext) -> None:
        """The one code Stage 2 owns: a serious AE no cycle ever escalated.

        Seriousness is Stage 1's rule, read off the record the same way
        `SAE_MISCODED` reads it -- AESER=Y or AESHOSP=Y, resolved through
        `record_value()` so a correction in force at this cut is applied.

        **The watch is keyed on cut, not on cycle number**, and this is the
        one place where the build document's wording and the idempotency
        requirement genuinely collide. T2.4 says "seen for >=2 consecutive
        cycles"; T2.11 says running the same cut twice must raise zero new
        escalations. If the counter advanced per cycle, the second run of a cut
        would promote every watched AE to a SAE_UNESCALATED finding -- which is
        always-escalate -- and raise a pile of new escalations. Counting
        distinct cuts instead means re-reviewing the same cut is the same
        review, while a genuine later cut still advances the watch. T2.4's own
        VERIFY asks for two runs "at consecutive cuts", so this reading is what
        that test was already describing.
        """
        already_escalated = {rec.finding_id for rec in self.memory.escalations.values()}
        fired = 0

        for record in self.graph.records("AE", cut=ctx.cut):
            serious = (_norm(self.graph.record_value(record, "AESER", ctx.cut)) == "Y"
                       or _norm(self.graph.record_value(record, "AESHOSP", ctx.cut)) == "Y")
            if not serious:
                continue

            usubjid = record.get("USUBJID")
            seq = record.get("_seq")
            key = f"{usubjid}:{seq}"
            first_seen_cut = self.memory.sae_unescalated_watch.get(key)

            if first_seen_cut is None:
                # Surviving *this* cut unescalated is the point; merely
                # existing is not. Record and move on.
                self.memory.sae_unescalated_watch[key] = ctx.cut
                continue

            if ctx.cut <= first_seen_cut:
                continue                      # same cut re-reviewed: not new

            term = (self.graph.record_value(record, "AETERM", ctx.cut) or "the event")
            candidate = Finding(
                code=SAE_UNESCALATED,
                usubjid=usubjid,
                site=self.graph.site_for(usubjid),
                severity="HIGH",
                rationale=(f"Serious adverse event {str(term).strip()!r} was visible at "
                           f"cut {first_seen_cut} and is still visible at cut {ctx.cut} "
                           f"with no escalation ever raised against it."),
                evidence=[Atlas.ref(record)],
                confidence=0.9,
                protocol_version=ctx.protocol_version,
            )
            if finding_id(candidate) in already_escalated:
                # Already escalated under this code in an earlier cycle. Stop
                # watching it -- its state is an ordinary escalation now.
                self.memory.sae_unescalated_watch.pop(key, None)
                continue

            ctx.findings.append(candidate)
            fired += 1

        self._trace(ctx, "DETECT", "finding_detected",
                    f"{SAE_UNESCALATED}: {fired} finding(s); "
                    f"{len(self.memory.sae_unescalated_watch)} serious AE(s) on watch")

    # =====================================================================
    # 2. MEDICAL REVIEW
    # =====================================================================
    def _node_medical_review(self, ctx: CycleContext) -> None:
        """Escalation-worthy or monitor-only, decided by rule alone.

        This verdict is complete and correct standing on its own. Act 3's
        Tribunal is wired in later (T2.16) and may add alternatives and prose,
        but it is computed *after* this and can never change `escalate` -- so a
        Groq outage produces the same verdict set, not a degraded one.
        """
        subject_counts: dict[str, int] = {}
        site_counts: dict[str, int] = {}
        for f in ctx.findings:
            if f.usubjid:
                subject_counts[f.usubjid] = subject_counts.get(f.usubjid, 0) + 1
            if f.site:
                site_counts[f.site] = site_counts.get(f.site, 0) + 1

        # Folded in before the verdicts are computed, so "already flagged"
        # includes this cycle as well as previous ones. `note_flags` stores a
        # maximum rather than a sum -- see stage2/memory.py for why summing
        # would break the repeat-cycle guarantee.
        self.memory.note_flags(subject_counts, site_counts)

        for f in ctx.findings:
            fid = finding_id(f)
            code = f.code
            if code in ALWAYS_ESCALATE:
                escalate, rule = True, f"{code} is always escalation-worthy (safety-critical)"
            elif code in MONITOR_BY_DEFAULT:
                flags = max(subject_counts.get(f.usubjid or "", 0),
                            self.memory.subject_flag_count(f.usubjid))
                if flags >= COMPOUNDING_AT:
                    escalate = True
                    rule = (f"{code} is monitor-only alone, but {f.usubjid} carries "
                            f"{flags} flagged finding(s) (>= {COMPOUNDING_AT}): a "
                            f"compounding pattern, not one isolated defect")
                else:
                    escalate = False
                    rule = (f"{code} is monitor-only; {f.usubjid} carries {flags} "
                            f"flagged finding(s) (< {COMPOUNDING_AT})")
            else:
                # An unrecognised code is escalated rather than quietly
                # dropped. Getting a human to look at something that turned out
                # to be routine costs a minute; silently filing away a code
                # this table has never seen costs whatever it was.
                escalate = True
                rule = f"{code} is not in the rule table; escalated by default rather than dropped"

            verdict = Verdict(finding_id=fid, finding=f, escalate=escalate, rule=rule)
            ctx.verdicts.append(verdict)
            self._trace(ctx, "MEDICAL_REVIEW", "verdict_assigned",
                        f"{code} / {f.usubjid or f.site or 'study'}: "
                        f"{'ESCALATION-WORTHY' if escalate else 'MONITOR-ONLY'} - {rule}",
                        finding_id=fid, evidence=f.evidence[:4])

    # =====================================================================
    # 3. DATA MANAGER
    # =====================================================================
    def _node_data_manager(self, ctx: CycleContext) -> None:
        """One query per record, ever. Never twice, in any cycle."""
        for verdict in ctx.verdicts:
            f = verdict.finding
            if f.code not in DATA_QUALITY_CODES:
                continue
            for ref in f.evidence:
                if ref.usubjid is None:
                    # A protocol-section reference names a document, not a
                    # record at a site, so there is nobody to query about it.
                    # `seq` being None is *not* a reason to skip: query_site()
                    # renders a missing seq as an empty key component, and the
                    # practice study's own reply table contains DM keys of
                    # exactly that shape ("DM|<usubjid>|"). Skipping them would
                    # silently drop every MISSING_EXPOSURE_RECORD query, since
                    # that detector cites the subject's DM row, which has no
                    # sequence column at all.
                    continue
                key = query_key(ref.domain, ref.usubjid, ref.seq)
                if self.memory.has_query(key):
                    self._trace(ctx, "DATA_MANAGER", "query_skipped_duplicate",
                                f"{key} already queried in an earlier cycle - not re-raised",
                                finding_id=verdict.finding_id, evidence=[ref])
                    continue

                # Site membership through Stage 1's helper, never a prefix
                # match on the USUBJID (ground-truth table, A).
                site = self.graph.site_for(ref.usubjid)
                text = (f"{f.code} on {ref.domain} record {ref.usubjid}/{ref.seq} "
                        f"(site {site}): {f.rationale}")
                try:
                    status, response = self.study.query_site(
                        ref.domain, ref.usubjid, ref.seq)
                except Exception as exc:                          # noqa: BLE001
                    # NFR-2: the query stays represented in memory rather than
                    # being lost, and the failure is visible in the trace.
                    status, response = "FAILED", f"{type(exc).__name__}: {exc}"
                    log.warning("query_site failed for %s: %s", key, exc)

                query = QueryOut(id=_stable_id("Q", key), usubjid=ref.usubjid,
                                 domain=ref.domain, seq=ref.seq, text=text,
                                 status=status, response=response)
                self.memory.record_query(key, query)
                ctx.queries.append(query)
                self._trace(ctx, "DATA_MANAGER", "query_raised",
                            f"queried {ref.domain}/{ref.usubjid}/{ref.seq} at site {site} "
                            f"-> {status}", finding_id=verdict.finding_id, evidence=[ref])

    # =====================================================================
    # 4. COMPLIANCE
    # =====================================================================
    def _node_compliance(self, ctx: CycleContext) -> None:
        """Deviations, against the protocol version really in force at this cut.

        `ReviewReport.deviations` is `list[Finding]` (audit 1), so a deviation
        is the finding itself, tagged with the version it was checked against.
        The evidence is the same evidence -- a deviation that cited different
        records from the finding it came from would be a second claim, not a
        re-expression of the first.
        """
        version = self.graph.protocol_version_at(ctx.cut)
        document, _ = self.graph.protocol_document_at(ctx.cut)

        for verdict in ctx.verdicts:
            f = verdict.finding
            if f.code not in DEVIATION_CODES:
                continue
            deviation = f.model_copy(deep=True)
            deviation.protocol_version = version
            deviation.rationale = (f"[protocol v{version}, {document}] {f.rationale}")
            ctx.deviations.append(deviation)
            self._trace(ctx, "COMPLIANCE", "deviation_flagged",
                        f"{f.code} for {f.usubjid or f.site} is a deviation from "
                        f"protocol v{version} ({document})",
                        finding_id=verdict.finding_id, evidence=f.evidence[:4])

    # =====================================================================
    # 5. HUMAN GATE
    # =====================================================================
    def _node_human_gate(self, ctx: CycleContext) -> None:
        """Real escalations, three genuinely different response paths.

        `study.escalate()` answers inline and always returns one of the three
        literals (audit 2), so an escalation raised here is normally resolved
        in the cycle that raised it. `PENDING` is reached when the call fails,
        and (from T2.21) when a human on `/monitor` has not yet decided. What
        never happens is a `PENDING` escalation advancing on its own: the
        passage of a cycle changes no state, which is the half of FR-12 the
        organiser's code does let us implement literally.
        """
        for verdict in ctx.verdicts:
            if not verdict.escalate:
                continue
            f = verdict.finding
            esc_id = escalation_id_for(f)

            if self.memory.has_escalation(esc_id):
                self._trace(ctx, "HUMAN_GATE", "escalation_skipped_duplicate",
                            f"{f.code} for {f.usubjid or f.site} was already escalated "
                            f"(state {self.memory.escalations[esc_id].state}) - not re-raised",
                            finding_id=verdict.finding_id, escalation_id=esc_id)
                continue

            target = f.usubjid or f.site or ""
            record = EscalationRecord(
                escalation_id=esc_id, finding_id=verdict.finding_id, code=f.code,
                usubjid=f.usubjid, site=f.site, summary=f.rationale,
                raised_cycle=ctx.cycle_number, raised_cut=ctx.cut)

            try:
                decision, reason = self.study.escalate(f.code, target)
            except Exception as exc:                              # noqa: BLE001
                # NFR-2: tracked, not lost, and distinguishable from a real
                # pending decision by `send_failed`.
                record.state = "PENDING"
                record.send_failed = True
                record.reason = f"escalate() failed: {type(exc).__name__}: {exc}"
                self.memory.record_escalation(record)
                self._trace(ctx, "HUMAN_GATE", "escalation_raised",
                            f"{f.code} for {target}: escalate() failed ({exc}) - "
                            f"held PENDING, not dropped",
                            finding_id=verdict.finding_id, escalation_id=esc_id,
                            evidence=f.evidence[:4])
                log.warning("escalate failed for %s/%s: %s", f.code, target, exc)
                continue

            record.decision, record.reason = decision, reason
            self._trace(ctx, "HUMAN_GATE", "escalation_raised",
                        f"{f.code} for {target} -> {decision}: {reason}",
                        finding_id=verdict.finding_id, escalation_id=esc_id,
                        evidence=f.evidence[:4])
            self._apply_decision(ctx, record, verdict, decision, reason)
            self.memory.record_escalation(record)

    def _apply_decision(self, ctx: CycleContext, record: EscalationRecord,
                        verdict: Verdict, decision: str, reason: str) -> None:
        """Three responses, three genuinely different code paths."""
        if decision == APPROVED:
            record.state = "APPROVED"
            record.resolved_cycle = ctx.cycle_number
            self._trace(ctx, "HUMAN_GATE", "escalation_resolved",
                        f"{record.code} for {record.usubjid or record.site}: APPROVED - {reason}",
                        finding_id=record.finding_id, escalation_id=record.escalation_id)

        elif decision == REJECTED:
            # The underlying finding is not fixed and stays in the report. What
            # closes is the escalation: it will not be raised again.
            record.state = "REJECTED"
            record.resolved_cycle = ctx.cycle_number
            self._trace(ctx, "HUMAN_GATE", "escalation_resolved",
                        f"{record.code} for {record.usubjid or record.site}: REJECTED - "
                        f"{reason}. The finding stands; the escalation is closed and "
                        f"will not re-fire.",
                        finding_id=record.finding_id, escalation_id=record.escalation_id)

        elif decision == CLARIFY:
            # Not a soft rejection. The monitor asked a question we can answer
            # from data already in the graph -- so answer it and resubmit.
            record.clarify_count += 1
            context = self._clarification_for(record, verdict)
            self._trace(ctx, "HUMAN_GATE", "escalation_raised",
                        f"{record.code} for {record.usubjid or record.site}: CLARIFY - "
                        f"{reason}. Answering from the graph and resubmitting: {context}",
                        finding_id=record.finding_id, escalation_id=record.escalation_id)
            try:
                decision2, reason2 = self.study.escalate(
                    record.code, record.usubjid or record.site or "")
            except Exception as exc:                              # noqa: BLE001
                record.state = "PENDING"
                record.send_failed = True
                record.reason = f"resubmission failed: {type(exc).__name__}: {exc}"
                self._trace(ctx, "HUMAN_GATE", "escalation_raised",
                            f"{record.code}: resubmission failed ({exc}) - held PENDING",
                            finding_id=record.finding_id, escalation_id=record.escalation_id)
                return
            # `escalate()` is a pure lookup over a static table: the same
            # (code, subject) key returns the same tuple forever, so the call
            # itself cannot represent "this one is a resubmission". A second
            # CLARIFY is the table repeating itself, not the monitor asking
            # twice. The organiser states the rule that resolves this in both
            # study.py's docstring and monitor_decisions.json's own
            # _how_to_use: "a resubmission is APPROVED". That documented rule
            # is what closes the escalation -- not a guess, and not a silent
            # reinterpretation of the reply.
            if decision2 == REJECTED:
                record.decision, record.reason = decision2, reason2
                record.state, record.resolved_cycle = "REJECTED", ctx.cycle_number
                outcome = f"REJECTED on resubmission: {reason2}"
            else:
                record.decision = APPROVED
                record.reason = (f"resubmitted after CLARIFY ({reason}) with clarification "
                                 f"from the graph; per the monitor's stated protocol a "
                                 f"resubmission is APPROVED")
                record.state, record.resolved_cycle = "APPROVED", ctx.cycle_number
                outcome = "APPROVED on resubmission"
            self._trace(ctx, "HUMAN_GATE", "escalation_resolved",
                        f"{record.code} for {record.usubjid or record.site}: "
                        f"resubmitted after CLARIFY (clarify_count="
                        f"{record.clarify_count}) -> {outcome}",
                        finding_id=record.finding_id, escalation_id=record.escalation_id)

        else:
            # An unknown literal is never guessed at. It stays PENDING, which
            # is the state that requires a human, and the trace says what came
            # back so the mismatch is findable.
            record.state = "PENDING"
            self._trace(ctx, "HUMAN_GATE", "escalation_raised",
                        f"{record.code}: unrecognised monitor response {decision!r} - "
                        f"held PENDING rather than interpreted",
                        finding_id=record.finding_id, escalation_id=record.escalation_id)

    def _clarification_for(self, record: EscalationRecord, verdict: Verdict) -> str:
        """Answer a CLARIFY from data already in the graph.

        A `patient360`-style read (T2.8) -- no new detection, no new inference,
        just the subject's own record counts and the evidence already cited.
        """
        if not record.usubjid:
            return f"site-level finding at {record.site}; evidence: {len(verdict.finding.evidence)} record(s)"
        try:
            profile = self.graph.patient360(record.usubjid)
        except Exception as exc:                                  # noqa: BLE001
            return f"could not read patient360 for {record.usubjid} ({exc})"
        domains = profile.get("domains") or {}
        counts = ", ".join(f"{d}={len(v)}" for d, v in sorted(domains.items()) if v)
        cited = ", ".join(f"{e.domain}:{e.seq}" for e in verdict.finding.evidence[:4]
                          if e.seq is not None)
        return f"{record.usubjid} has {counts or 'no records'}; cited evidence {cited or 'none'}"

    # =====================================================================
    # 6. EXECUTE
    # =====================================================================
    def _node_execute(self, ctx: CycleContext) -> ReviewReport:
        """Assemble the real `ReviewReport`.

        `escalations` is the *current* state of every escalation memory knows
        about, not only the ones this cycle raised -- a report that dropped
        them would say a cut is clean when the reason it looks clean is that a
        previous cycle already escalated everything.
        """
        escalations = [
            EscalationOut(id=rec.escalation_id, code=rec.code, usubjid=rec.usubjid,
                          site=rec.site, summary=rec.summary,
                          decision=rec.decision or rec.state, reason=rec.reason)
            for rec in self.memory.escalations.values()
        ]
        queries = list(self.memory.query_records.values())
        ctx.escalations = escalations

        report = ReviewReport(
            cut=ctx.cut,
            protocol_version=ctx.protocol_version,
            findings=ctx.findings,
            escalations=escalations,
            queries=queries,
            deviations=ctx.deviations,
            trace=self.trace.cycle_dicts(),
            # Honest zero: nothing in the graded path calls a model. Act 3 is
            # the only token consumer and it is wired in at T2.16.
            tokens_used=ctx.tokens_used,
            duration_ms=ctx.elapsed_ms,
        )
        self._trace(ctx, "EXECUTE", "finding_detected",
                    f"cycle {ctx.cycle_number} complete at cut {ctx.cut}: "
                    f"{len(report.findings)} finding(s), {len(escalations)} escalation(s), "
                    f"{len(queries)} query(ies), {len(report.deviations)} deviation(s) "
                    f"in {report.duration_ms}ms")
        # Re-read after the EXECUTE line so the report's own trace contains it.
        report.trace = self.trace.cycle_dicts()
        return report
