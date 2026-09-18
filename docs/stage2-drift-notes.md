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

---

# Act 3 (T2.12–T2.17)

## 7. Where the APIs had moved since the earlier build

### 7.1 `reasoning_format` is no longer required

The inherited ground truth is emphatic: JSON-mode calls to this model family
return **empty content** unless `reasoning_format` is set alongside
`reasoning_effort`, discovered live during the previous build and carried
forward as a rule every new call must follow.

Re-verified before writing a single call, as the build instructions require.
It no longer reproduces:

```
A: JSON mode, reasoning_format OMITTED  -> '{"verdict":"ESCALATE","why":"The patient presents with...'
   EMPTY? False
B: JSON mode, reasoning_format=hidden   -> '{"verdict":"MONITOR","why":"The patient has mild...'
```

Both fields are still set on every call — `hidden` keeps chain-of-thought out
of a transcript a human reads, which is worth having for its own sake. But the
code no longer *depends* on a requirement that has since lapsed, and the reason
for setting it is now the real one.

`openai/gpt-oss-120b` was confirmed present in Groq's live model list at the
same time. It is still current.

### 7.2 The binding rate limit is tokens, not requests

The PRD and TRD both plan around Groq's free-tier **30 requests/minute**
ceiling, and size the Tribunal's budget against it.

The limit that actually binds is **tokens per minute**, and it binds an order
of magnitude sooner:

```
RateLimitError: 429 — Rate limit reached for model `openai/gpt-oss-120b` ...
on tokens per minute (TPM): Limit 8000, Used 7535, Requested 1094
```

One full deliberation (3 Round-1 calls + 3 Round-2 calls) costs ~5.7k tokens
after dropping `reasoning_effort` to `low` — ~7.4k before. Against an 8000 TPM
ceiling that is **roughly one deliberation per minute**, not the six-calls-per-
finding-across-several-findings the risk table assumed. A budget of 3 spends
two of its three attempts collecting 429s.

Two consequences: `tribunal_budget` defaults to **1**, and a 429 is never
retried — retrying spends the exact window the retry is waiting on.

### 7.3 There are *two* ceilings, and the second one is the one that bites

Correcting §7.2, which named only the per-minute limit. The free tier meters
both:

```
tokens per minute (TPM): Limit   8,000
tokens per day   (TPD): Limit 200,000
```

At ~7k tokens per deliberation that is **about 28 deliberations per day, in
total, across every run** — development, rehearsal and the live demo share one
budget. TPM is a delay of seconds; TPD is a wall until the rolling window
clears, and it is silent until you hit it.

This cost real time to find, because the skip reason said "tokens per minute"
whatever had actually happened. Groq's own message names the ceiling, the usage
and the retry interval; it is now passed through instead of summarised:

```
Groq rate limit: tokens per day (TPD) — used 199117 of 200000, retry in 5m18s
```

Completion length is also capped (`MAX_COMPLETION_TOKENS = 900`). Groq reserves
against the bucket using the completion *allowance*, not the eventual response,
so three uncapped parallel calls can reserve past the minute ceiling while the
account genuinely has most of its tokens free.

## 8. Where the architecture could not survive the real data volume

TNFR-1 asks that `run_cycle()` stay inside its time budget *"even when every
escalation-worthy finding attempts a full Tribunal round"*.

At this study's real volume that is not reachable. Cut 9 produces **170**
escalation-worthy findings; a full round each is ~1020 network calls and, at the
measured TPM ceiling, several hours. Implementing TNFR-1 literally ships a
graded run that times out.

Act 3 is therefore **off by default**, with a per-cycle budget when on. The
graded path stays deterministic and offline exactly as the detector layer's
was; the demo switches Act 3 on deliberately. This is the TRD's own isolation
principle applied honestly to the volume the data has, and it makes G7 true by
construction rather than by hope — verified, not asserted:

| | findings | escalation-worthy | tokens | duration |
|---|---|---|---|---|
| Act 3 off | 251 | 170 | 0 | ~330ms |
| Act 3 on, working key | 251 | 170 | 7703 | 16.3s |
| Act 3 on, revoked key | 251 | 170 | 0 | 1.0s |

The escalation-worthy set is byte-identical across all three.

## 9. Model gaps in the specified Tribunal shapes

* **`CrossExamChallenge` carries no `RecordRef`s.** So a Round-2 challenge
  cannot be evidence-checked the way a Round-1 verdict can — there is nothing
  to look up. Round 3 checks challenges *structurally* (does the target persona
  exist and did it actually make a claim) and reports that as a structural
  check. Presenting it as a fact-check would be the exact overstatement Round 3
  exists to prevent.
* **`TribunalTranscript.round3` is `Arbitration | None`, not `Arbitration`.** A
  transcript that was skipped has no arbitration to carry, and a required field
  would force a fabricated one — an empty `Arbitration` with a `final_verdict`
  nobody reached is worse than an explicit absence beside `ran=False`.
* **`tokens_used` and `duration_ms` added to the transcript.** `EXECUTE` has to
  report honest token counts, and the per-finding cost is what made the TPM
  ceiling in §7.2 visible at all.

## 10. Why the rule-based verdict stays authoritative — observed, not assumed

The same borderline prompt, run twice against the same model minutes apart,
returned `ESCALATE` once and `MONITOR` once. Genuine nondeterminism on exactly
the kind of judgment the Tribunal is for.

This is the concrete case for the design the TRD already mandates: Act 3
contributes narrative and alternatives, and `verdict.escalate` is computed by
rule before Act 3 is attempted and never modified by it. A Tribunal that could
overturn the rule would make the cycle's correctness a function of which way a
model leaned that minute.

## 11. What is verified for Act 3

- `verify_evidence()` is additive: 81 insertions, **zero deletions**, exactly
  one new `def`, no existing signature touched. `schemas.py` and `study.py`
  remain untouched.
- Round 1 isolation: three real personas, real field values quoted, real record
  refs cited, and no persona references another (checked mechanically).
- Round 3 discards **exactly** the deliberately-mismatched claim and keeps both
  well-cited ones — and losing that vote flips the verdict to ESCALATE, so the
  check demonstrably changes an outcome rather than just logging one.
- Round 3 contains no model call at all (asserted against its own source, not
  just its docstring).
- All four real failure modes — 429, timeout, schema failure, and an exception
  thrown straight out of the module — leave all 251 findings with a verdict and
  nothing escaping into `run_cycle()`.
- Stage 1 still scores 100.0/100 with 25/25 offline tests passing.

Still not built, and not claimed: the review page and its routes (T2.18–T2.21)
and the submission artifacts (T2.22).
