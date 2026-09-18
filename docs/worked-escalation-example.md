# One escalation, end to end

`ESC-2852380731cf` — the `CLARIFY → resubmit → APPROVED` path, which is the most
demonstrative of the three because it is the only one where the system has to do
something rather than record something.

Reproduce it with `./run.sh cycle 9`. Every line below is from the real trace
file (`stage2_public_trace.jsonl`), not a reconstruction.

---

## 1. DETECT — the finding

The dosing-error detector runs via `Atlas.answer()`, at cut 9, protocol v3:

```
DOSING_ERROR / 042-S09-006
  WEEK2: administered dose is 10 for EXTRT=PLACEBO, but the protocol
  specifies 0 (PLACEBO arm). Protocol §8.
```

**Evidence:** `EX:042-S09-006:2` — one exposure record. Site resolved as `S09`
through `site_for()`, never a prefix match on the subject id.

Nothing about this rule lives in the review cycle. The detector is the existing
one; this layer only asked it.

## 2. MEDICAL REVIEW — the verdict

```
[MEDICAL_REVIEW] verdict_assigned
  DOSING_ERROR / 042-S09-006: ESCALATION-WORTHY
  — DOSING_ERROR is always escalation-worthy (safety-critical)
```

Rule-based, computed before any deliberation is attempted, and recorded before
too. A subject receiving the wrong dose is a clinical decision, not a data
defect — so it never depends on the compounding rule and never depends on a
model being reachable.

## 3. DATA MANAGER — no query

`DOSING_ERROR` is not in the set of codes a site can resolve by checking source
documents. The dose that was administered is not in doubt; whether it should
have been is a clinical question for a human. So no query is raised, and that
absence is deliberate rather than an omission.

## 4. COMPLIANCE — the deviation

```
[COMPLIANCE] deviation_flagged
  DOSING_ERROR for 042-S09-006 is a deviation from protocol v3 (protocol_v3)
```

Tagged with the version resolved from the cut by `protocol_version_at(9)`, not
the version the caller passed. The deviation cites the same evidence as the
finding — a deviation citing different records would be a second claim, not a
re-expression of the first.

## 5. HUMAN GATE — the reviewer asks a question

```
[HUMAN_GATE] escalation_raised
  DOSING_ERROR for 042-S09-006 -> CLARIFY:
  How many subjects at the site are affected and over which visits?
```

This is a real reply from the organiser's decisions file, not a scripted demo
path. It is also the reply that separates a system that handles three responses
from one that handles two and treats the third as a rejection.

## 6. HUMAN GATE — the system answers, from data it already has

```
[HUMAN_GATE] escalation_raised
  DOSING_ERROR for 042-S09-006: CLARIFY — Answering from the graph and
  resubmitting: 042-S09-006 has AE=4, CM=1, DM=1, EG=4, EX=7, LB=48, MH=1, VS=24; cited evidence EX:2
```

The clarification is a `patient360` read: the subject's own record counts and
the evidence already cited. No new detection, no new inference, nothing invented
to satisfy the question. If the answer is not already in the graph, it is not
given.

## 7. HUMAN GATE — resubmitted and closed

```
[HUMAN_GATE] escalation_resolved
  DOSING_ERROR for 042-S09-006: resubmitted after CLARIFY (clarify_count=1)
  -> APPROVED on resubmission
```

Final state:

```json
{
  "escalation_id": "ESC-2852380731cf",
  "code": "DOSING_ERROR",
  "usubjid": "042-S09-006",
  "state": "APPROVED",
  "clarify_count": 1,
  "resolved_cycle": 1
}
```

**Why the resubmission closes it rather than looping.** `escalate()` is a pure
lookup over a static table: the same `(code, subject)` key returns `CLARIFY`
forever, so the call itself cannot express "this one is a resubmission". The
organiser states the resolving rule in two places — `study.py`'s docstring and
`monitor_decisions.json`'s own usage note — *"a resubmission is APPROVED"*. That
documented rule is what closes it. A `REJECTED` on resubmission would still be
honoured.

## 8. On the next cycle — nothing

Running cut 9 again raises **zero** new queries and **zero** new escalations.
This escalation is recognised by an id derived from the finding's own
fingerprint, so the second cycle knows it as one already raised and writes an
`escalation_skipped_duplicate` line instead of asking the reviewer again.

```
memory after the walk : queries 1037, escalations 259, watch 0
memory after a repeat : queries 1037, escalations 259, watch 0
changed               : nothing
```

---

## The same flow through a person

On the review page the crew runs in a mode where escalations are held `PENDING`
rather than answered inline, so a reviewer clicks Approve / Reject / Clarify
themselves. Clicking **Clarify** runs steps 6 and 7 above — the same
`_apply_decision` code, not a UI copy of it — and the row updates from what the
server returned:

```
POST /api/monitor/escalations/ESC-...  {"decision": "CLARIFY"}
  -> state APPROVED, clarify_count 1
  gate: 170 PENDING -> 169 PENDING, 1 APPROVED
```
