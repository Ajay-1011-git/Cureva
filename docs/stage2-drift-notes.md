# Stage 2 drift notes

Where the Stage 2 build documents and the code disagree, and why the code is
what it is. Same purpose as `DRIFT_NOTES.md` did for Stage 1: a reviewer should
be able to tell a deliberate deviation from an oversight without reading the
diff.

Covers T2.0–T2.11 (the graded six-node cycle). Act 3 and `/monitor` are not
built yet.

---

## 1. Where the documents were wrong about the organiser's own contracts

All four were found by reading `schemas.py` and `study.py` in T2.0, before any
node was written. Full excerpts in `docs/stage2-contract-audit.md`.

### 1.1 The memory key is keyed on a field that does not exist

TRD §6 specifies `queries_raised` entries as `"domain:usubjid:seq:field"`.
`study.query_site(domain, usubjid, seq)` has no field parameter, and `RecordRef`
is `(domain, usubjid, seq, document, section)` — also no field. A key with a
`field` component could only ever hold a constant there.

Keyed on `"domain:usubjid:seq"`, which is exactly what `query_site()` itself
keys on, so the dedup guarantee lines up with the call it protects.

### 1.2 `PENDING` forever has no trigger

PRD G4/FR-12 require that an unanswered escalation stays `PENDING` indefinitely
and is never silently approved. But `study.escalate()` is a dictionary lookup
that always returns a value, falling through to `("APPROVED", "Noted.")` on a
miss. **There is no unanswered case.**

Resolved in favour of what the starter code models. The graded path uses the
real inline decision; `PENDING` is reached when `escalate()` raises (the finding
stays tracked, flagged `send_failed`, rather than being lost) and, from T2.21,
when a human on `/monitor` has not yet clicked. The half of FR-12 that *can* be
implemented literally — a cycle passing never advances an escalation's state —
is implemented literally and is asserted in T2.11.

The rejected alternative was to treat the `("APPROVED", "Noted.")` fallback as
silence. On a hidden study, where most `code|subject` pairs will miss the
decisions table, that would leave nearly every escalation permanently
`PENDING` — reporting a cut as unreviewed because the monitor agreed with us.

### 1.3 `ReviewReport` needed no wrapper, and has no `Deviation` type

T2.0 was told to flag it if `ReviewReport` were absent. It is present.
Two knock-on corrections: `trace` is `list[dict]`, so `TraceEntry` is dumped on
the way in (the typed object is what reaches the JSONL file); and `deviations`
is `list[Finding]`, so T2.7's "or a Cureva-defined `Deviation` model if none
exists" branch is dead. A deviation is the finding itself, tagged with the
protocol version it was checked against.

### 1.4 `Question` requires two fields the build document omits

T2.3's prompt writes `Question(kind="finding", params={"code": code})`. `id` and
`text` are required with no defaults; that call raises `ValidationError`.
`DETECT` constructs the full object and sets `cut`, so the sweep is scoped to
the cycle's cut rather than to whatever cut the graph was last built at.

### 1.5 The 17th `FindingCode`

§B.3 accounts for 16 codes across three stages and says to stop and flag a 17th.
Flagged: it is `NO_FINDING`, a sentinel for an honestly-empty answer, not a
detector any stage owns. The 11 / 1 / 4 split is unaffected.

---

## 2. Where two requirements genuinely contradicted each other

### 2.1 `SAE_UNESCALATED` vs. idempotency — the real collision

T2.4 says a serious AE seen for **≥2 consecutive cycles** without escalation
becomes a `SAE_UNESCALATED` finding. T2.5 makes that code always
escalation-worthy. T2.11 says running the same cut twice must raise **zero**
new escalations.

Those cannot all hold if the watch counts cycles. Re-running one cut would
promote every watched serious AE on the second pass and raise a batch of new
escalations — failing the property the whole stage is graded on.

The watch is keyed on **cut**, not cycle: `sae_unescalated_watch[key]` stores
the cut the AE was first seen unescalated at, and the finding fires when a
*later* cut still shows it unescalated. Re-reviewing one cut is the same review;
a genuine later cut still advances the watch. T2.4's own VERIFY asks for two
runs "at consecutive cuts", so this is what that test was already describing.

Verified against the practice study — the behaviour is exactly the specified
shape, on real serious AEs:

```
cut 10: watch=5  SAE_UNESCALATED fired=0     <- first sight: watch, don't fire
cut 11: watch=5  SAE_UNESCALATED fired=5     <- still unescalated one cut later
cut 12: watch=0  SAE_UNESCALATED fired=0     <- all five escalated, watch cleared
```

(Cellulitis, Pneumonia ×2, Myocardial infarction ×2.)

### 2.2 Flag counters had the same problem, quietly

`subject_flags` feeds MEDICAL REVIEW's compounding rule ("this subject already
has ≥2 flagged findings"). The obvious implementation — increment per cycle —
has the same failure mode as 2.1 and is harder to see: a second pass over one
cut pushes borderline subjects past the threshold, flips monitor-only findings
to escalation-worthy, and raises new escalations.

`CrewMemory.note_flags` stores a **maximum**, not a sum. The "repeatedly messy
subject" signal survives; the arithmetic of a repeat cycle does not change.

---

## 3. Where the data disagreed with a reasonable assumption

### 3.1 A record with no sequence number is still queryable

`DATA MANAGER`'s first implementation skipped any `RecordRef` with
`seq is None`, on the reasoning that a query needs to name a record.

That dropped **every** `MISSING_EXPOSURE_RECORD` query — 24 of them — because
that detector cites the subject's `DM` row, and `DM` has no sequence column at
all. `query_site()` renders a missing seq as an empty key component, and the
practice study's own reply table contains keys of exactly that shape:

```
DM|042-S02-013|
DM|042-S05-021|
```

Now only refs with no `usubjid` are skipped — a protocol-section reference names
a document, not a record at a site, so there is nobody to query about it.
Queries raised at cut 1 went from 8 to 37.

### 3.2 `escalate()` cannot tell a resubmission from a first submission

`CLARIFY` requires answering from our own data and resubmitting; the organiser
states in two places that "a resubmission is APPROVED". But `escalate()` is a
pure lookup over a static table — the same `(code, subject)` key returns
`CLARIFY` forever. Calling it again and believing the reply would leave every
clarified escalation stuck.

The clarification is answered from the graph (a `patient360` read — subject
record counts and the already-cited evidence, no new detection and no new
inference), the resubmission is made, and the documented rule is what closes the
escalation. A `REJECTED` on resubmission would still be honoured. `clarify_count`
records that it happened, and the trace carries the clarification text.

Verified at cut 9, all three paths on real monitor replies:

```
APPROVED  ESC-472a3deae794  HYS_LAW_CANDIDATE  042-S05-003
          "Consistent with Hy's law; report to safety and hold dosing pending review."
REJECTED  ESC-d1bc52b7006f  HYS_LAW_CANDIDATE  042-S07-001
          "Baseline transaminases were already elevated; monitor, do not escalate."
CLARIFY   ESC-2852380731cf  DOSING_ERROR       042-S09-006   clarify_count=1 -> APPROVED
          "How many subjects at the site are affected and over which visits?"
```

---

## 4. Additions to the specified models, and why

Three, all additive; nothing specified was removed or renamed.

* **`CrewMemorySnapshot.query_records`** — the `QueryOut` for every query ever
  raised. Without it, a repeat cycle's `ReviewReport.queries` comes back empty,
  which reads as "this cut has no queries" rather than the truth, "this cut
  needed no *new* queries".
* **`TraceEntry.decision_type` gains `verdict_assigned` and
  `escalation_skipped_duplicate`.** FR-18 treats an untraced decision as one
  that never happened. Without these two, the reasoning behind every
  monitor-only finding — most of a cycle — would go unrecorded, and a
  deliberate non-escalation would be indistinguishable from an oversight.
* **`EscalationRecord` gains `code`, `usubjid`, `site`, `summary`, `decision`,
  `reason`, `raised_cut`, `send_failed`.** `EXECUTE` has to build `EscalationOut`
  (which needs code/usubjid/site/summary/decision/reason) for escalations raised
  in *earlier* cycles, whose findings are not in the current context.
  `send_failed` keeps a failed send distinguishable from a real pending
  decision, per NFR-2.

---

## 5. Stated design choices that were not specified upstream

Flagged rather than buried, per the build document's instruction to state them
and invite revision.

| Choice | Value | Where |
|---|---|---|
| Compounding threshold for monitor-only codes | ≥2 findings on one subject | `crew.COMPOUNDING_AT` |
| SAE watch advancement | ≥1 later cut, not ≥2 cycles | §2.1 above |
| Which codes are always escalation-worthy | 6 safety/integrity codes | `crew.ALWAYS_ESCALATE` |
| Which codes generate site queries | 4 codes a site can answer from source | `crew.DATA_QUALITY_CODES` |
| An unrecognised `FindingCode` | Escalated, not dropped | `_node_medical_review` |
| An unrecognised monitor reply | Held `PENDING`, not interpreted | `_apply_decision` |

`HYS_LAW_CANDIDATE` is deliberately **not** in `DATA_QUALITY_CODES`: the lab
values are not in doubt, the clinical interpretation is, so there is nothing to
ask the site.

---

## 6. What is verified, and what is not yet

Verified on the practice study, real output in the commit messages and above:

- Stage 1 is unaffected — harness 100.0/100, 25/25 offline tests, and
  `git diff origin/main -- stage1/atlas.py study.py schemas.py` is empty.
- Idempotency (T2.11), including a negative control proving the test can fail.
- Trace liveness under interruption (T2.10) — 87 lines on disk from the three
  nodes that ran, none from the three that did not.
- All three monitor response paths on real replies (§3.2).
- `SAE_UNESCALATED`'s cross-cut behaviour on real serious AEs (§2.1).
- Protocol-version resolution: cut 1 → v1 yields 1 `VISIT_OUT_OF_WINDOW`
  deviation, cut 9 → v3 yields 201, from the same detector and the same data.
- No practice-study subject id, site id or threshold appears in any `stage2/`
  conditional.

Not yet built, and not claimed: Act 3 (the Tribunal, T2.12–T2.17),
`Atlas.verify_evidence()`, the `/monitor` page and its routes (T2.18–T2.21),
and the submission artifacts (T2.22).
