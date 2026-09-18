# Review cycle — demo script

Exactly what to run, what to say, and what should happen. About **8 minutes**.

Every number below was captured from a real run against `hackathon-data/`.
Nothing is staged: the subject ids, the monitor's replies and the panel's
disagreement are all really there. If your numbers differ, something is wrong —
check the troubleshooting section rather than improvising.

---

## Before you start (2 minutes, off camera)

```bash
./run.sh doctor      # everything green
./run.sh serve       # backend :8000 + frontend :5173
```

Open **http://localhost:5173/monitor** and press **Reset**.

Three things to check before an audience sees it:

- **Reset really is pressed.** Memory is persistent and working: if you demoed
  earlier, the gate will correctly be empty and you will have nothing to show.
  This is the one setup step that ruins the demo if skipped.
- **Warm the debate.** The free tier throttles on *tokens per minute*, and one
  deliberation costs ~7.2k against an 8000 ceiling. Run one debate privately
  before you start so you know the window is clear, then leave ~a minute before
  the live one.
- **Have a second terminal** open at the repo root for the closing run.

---

## Act 1 — one command, the whole cycle (1 minute)

Set **cut 1**, **protocol 1**. Press **Run cycle**.

> "Six nodes just ran in order — detect, judge, query, check the protocol,
> escalate, report. That is one review of the study as it stood at the first
> data cut."

Point at the stat row:

```
38 findings · 6 escalation-worthy · 32 watch-only
37 queries · 9 deviations · 105 trace lines · protocol v1 · ~2.3s
```

> "Thirty-eight problems. Only six of them need a human today. That split is
> the entire job — a system that escalated all thirty-eight would be as useless
> as one that escalated none."

---

## Act 2 — why *these* six (1 minute)

This is the beat that shows judgement rather than filtering. Find the two rows
for **042-S08-020**.

> "Inclusion violations are normally watch-only. We raise a query, the site
> fixes it, nobody is woken up."

Then point at that subject:

```
[watch]     042-S04-003: INCLUSION_VIOLATION is monitor-only;
            042-S04-003 carries 1 flagged finding(s) (< 2)

[ESCALATE]  042-S08-020: INCLUSION_VIOLATION is monitor-only alone, but
            042-S08-020 carries 2 flagged finding(s) (>= 2):
            a compounding pattern, not one isolated defect
```

> "Same code. Same rule. Different answer — because this subject also has a
> missing exposure record. One defect is a typo. Two on the same subject is a
> site not following the protocol, and that is a decision, not a query."

---

## Act 3 — the human gate (2 minutes)

> "Every escalation waits here. Nothing is auto-approved and nothing expires."

Take three rows and do one of each. **Do the Clarify one last** — it is the
only one where the system has to *do* something.

```
PROHIBITED_CONMED   042-S12-002   Approve  ->  APPROVED
DOSING_ERROR        042-S09-004   Reject   ->  REJECTED
PROHIBITED_CONMED   042-S09-012   Clarify  ->  APPROVED, clarify_count=1
```

On **Reject**:

> "Rejected does not mean fixed. The finding stays in the report — what closes
> is the escalation, and it will not come back to ask again."

On **Clarify**, read the row as it updates:

> "The monitor asked a question. So it answered from data already in the graph
> — the subject's own record counts and the evidence already cited, nothing
> invented — and resubmitted. That came back approved. `clarify_count` is one.
> Clarify is not a soft rejection; it is the path where the system has to work."

---

## Act 4 — 170 of these is not a demo of patience (30 seconds)

Tick **select all**, then **Approve selected**. Or press **Approve all pending**.

```
3 applied in one call  ->  {'APPROVED': 5, 'REJECTED': 1}
```

> "Each one still went through the same decision code — a bulk clarify really
> does read the graph and resubmit for every row. It is one request, not one
> shortcut."

---

## Act 5 — the property it is actually graded on (1 minute)

Change to **cut 2**. Press **Run cycle**.

```
cut 2: 50 findings, 12 escalation-worthy in total
the gate shows: {'APPROVED': 5, 'REJECTED': 1, 'PENDING': 6}
```

> "Twelve escalation-worthy findings. Six new ones in the gate. The other six
> are the ones you just answered, and they are not raised again."

Then, to make it undeniable, run **cut 1** again:

> "Same cut, second review: zero new queries, zero new escalations. Not
> filtered on the way out — never raised. That is what makes this a reviewer
> rather than a scanner. A tool that forgets what it flagged yesterday is worse
> than a slow human, because at least the human remembers."

---

## Act 6 — the debate (2 minutes) — *the showpiece*

Change to **cut 6**, **protocol 2**. Run cycle. Find the **DUPLICATE_SUBJECT**
row and press **debate this**.

> "This takes about forty seconds — three reviewers, two rounds, six calls."

While it runs:

> "Three reviewers, each accountable for a different question. Safety asks
> whether a participant is being harmed. Operations asks whether a site is
> failing. Regulatory asks whether the record survives inspection. They cannot
> see each other in round one."

When it opens — **the panel is split, 2–1**:

```
SAFETY        MONITOR   — no ICH E2A seriousness criterion is met
CLINICAL_OPS  ESCALATE  — a major protocol deviation under ICH E6(R2)
REGULATORY    MONITOR   — an ALCOA+ data-integrity breach, not a filing
```

> "They disagree, and they disagree for reasons from their own discipline."

Then round two lands — watch the arguments get struck through:

> "Operations attacks Safety directly: a duplicate can double-count exposure
> and mask a safety signal. Regulatory attacks Operations back: one instance is
> a breach, not an escalation. This is an argument, not three summaries."

Then round three:

> "And now the part that matters. Every record they cited is checked against
> the study — and that check makes **no model call at all**. Asking a model
> whether a model was right just moves the trust one step along."

**The line to land:**

> "The panel concluded monitor. The rule-based verdict was escalate. The rule
> wins — it was computed before the panel ever ran and the panel cannot change
> it. The debate is here to inform the human, never to overrule the system."

Point at the caveat box at the bottom:

> "And we are explicit that the guideline numbers they cite are their own
> reasoning, not verified citations. The evidence check covers study records.
> We do not pretend it covers more."

---

## Act 7 — the honest close (1 minute)

Second terminal:

```bash
./run.sh quick
```

```
weighted score   100.0 / 100      clean evidence 100.0 %
passed: 31   failed: 0
```

> "The earlier layer is untouched — still a hundred out of a hundred."

Then the one that matters:

> "We ran this same cycle with the API key revoked."

```
working key   findings=184  escalation-worthy=108  12394ms
revoked key   findings=184  escalation-worthy=108    567ms
identical escalation-worthy set: True (108 vs 108)
```

> "Identical. Every verdict is rule-based and computed before the panel is ever
> attempted. If the model is down, the demo gets quieter and the review stays
> correct. That is why we were willing to put a network call inside the graded
> path at all."

---

## If something goes wrong

| Symptom | Cause | Do this |
|---|---|---|
| Gate is empty after Run cycle | Memory from an earlier run — working as designed | Press **Reset**, run again |
| Debate says "timed out" or "rate limit" | Tokens-per-minute ceiling; one deliberation ≈ 7.2k of 8000 | Wait a minute. Say so out loud — it is the designed degradation and Act 7 is about exactly this |
| Debate panel says no deliberation ran | That finding was never deliberated | Use **debate this** on the row |
| Page will not load | Frontend deps missing | `./run.sh setup`, then `./run.sh serve` |
| Port already in use | An old server survived | `./run.sh ports` |

## If you have only 3 minutes

Act 1 (the cycle) → Act 5 (the repeat raises nothing) → Act 6 (the split
panel). Those three carry the argument. Everything else is supporting detail.
