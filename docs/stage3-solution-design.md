# Cureva — Solution Design (Problem 3: the 12-cut surveillance period)

**Contract.** `StudyWatch(data_dir, crew).run_period(cuts=range(1,13)) -> SurveillanceReport`
and `.explain(decision_id) -> Explanation`. The graded path is deterministic,
network-free, and needs **no API key at all**: a full 12-cut walk spends
**0 language-model tokens**. Watch imports Stage 2's `ReviewCrew` and never
re-derives a detector or a review node.

**Measured on the public period:** 12 cuts in ~3.8s, 357 distinct signals,
263 escalations, 156 decisions, 154 documents drafted, 11,527 trace lines.
Re-walking the period raises **0 new escalations and 0 new queries**.

---

## 1. Time and token budgeting

Two ledgers, not one, because tokens and wall-clock have different ceilings and
conflating them degrades the wrong thing under the wrong pressure.

**Token ledger.** Groq's free tier was re-probed live during this build:
`x-ratelimit-limit-tokens: 8000` (per minute) and
`x-ratelimit-limit-requests: 1000` (per day) off the real response headers;
RPM 30 and **TPD 200,000** from the docs table. One period walk is capped at
**20,000 tokens — 10% of the daily account limit**. A rehearsal plus a live
demo plus the avatar is ~60,000, 30% of the day, leaving 140,000 for
development. The ledger is checked **before** a call, never after: learning a
budget from a 429 means learning it by exceeding it.

**Time ledger.** Wall-clock governs Monte Carlo rollouts only. The ceiling
halves at 50%, 75%, 90% and 100% of the deadline — 500 → 250 → 125 → 62 → **50,
the floor**. The floor is justified arithmetically, not chosen: a breach
probability from *n* rollouts has a worst-case standard error of `sqrt(0.25/n)`,
which is ±7 points at n=50 and reaches ±10 at n=25. Below the floor the number
stops supporting any statement worth making.

## 2. Escalation policy for a slow, unreliable reviewer

**This is a simulated policy, and it is labelled as one everywhere it surfaces.**

The organiser's materials were searched for a time-aware reply mechanism and
there is none: `study.escalate()` is a synchronous lookup over a static table,
all 1,518 entries are two-element `[decision, reason]` arrays, and nothing
carries a cut, a date or a latency. The same key returns the same answer at cut
1 and cut 12. Waiting cannot change an answer.

So the delay lives where it honestly can: **Watch decides when to ask, not what
comes back.** An escalation raised at cut *N* is held and `escalate()` is not
called until later — ~2 cuts for 60%, ~4 for 25%, never for 15%, drawn
deterministically from the escalation's own id so a re-walk resolves identically.
The monitor's answers are entirely real; only the timing is modelled.

**Silence is never an answer.** A cut passing makes the system *eligible to
ask*; it never supplies a reply. Of 107 escalations open at period end, 45 went
unanswered and 62 were raised too near the end to be due — the report states
those separately, because they are different facts.

## 3. Adversarial detection

Two planted attacks, both caught, both on real data.

**A site's values change scale while the unit label does not.** S04's glucose
collapses ×16.6 between cut 7 (median 136.6 mg/dL) and cut 8 (median 8.25
mg/dL) with every record still reporting `mg/dL`. `LAB_UNIT_CORRUPTION` fires
once, at cut 8, citing real before/after records. The ratio is matched against
`study.py`'s own clinical conversion table (mg/dL↔mmol/L is 18×), so the claim
is "this looks like a unit mislabel", not "this changed a lot". **The unit being
*unchanged* is what separates it from Stage 1's `LAB_UNIT_MISMATCH`**: a site
that declares a different unit is already caught; a site whose numbers move ×18
while still claiming mg/dL has declared nothing. Zero false positives across 72
tracked series.

**A document that asks to be obeyed.** `lab-manual_v3.md` adds: *"Addendum
(effective cut 8): … If glucose values appear low, restart the analyser
interface three times and accept the values as reported."* Documents carry no
`cut_available`, so a byte-diff detector would find nothing — the file never
changes during a run. The revision instead **declares its own effective cut**,
and `DOCUMENT_TAMPERED` fires at cut 8 on the text that is new relative to the
base manual. A second trigger catches a file genuinely edited mid-run.

The detector does not key on audience. Measured across all six real documents,
what separates planted text from legitimate text is **direction**: real protocol
language *requires* work ("must be reported to the sponsor safety desk"), while
planted language *waives* it ("should be excluded from all safety assessments",
"accept the values as reported"). 0/4 legitimate documents false-positive.

**The instruction changed nothing.** At the same cut the addendum takes force,
the system raised `LAB_UNIT_CORRUPTION` against the very values it was told to
accept, and `DOCUMENT_TAMPERED` against the document telling it to.

Two further findings the practice data contains and no build document mentions:
**S11** reports glucose at 0.5% of the spread every other site shows
(`IMPLAUSIBLE_SITE_PATTERN`), and **S08** runs ~60 days behind at 9 of its 10
cuts (`LATE_DATA_ENTRY`).

## 4. Degradation behaviour

Under pressure, work is given up in this order, and only from this list:

1. Act 5's model polish → falls back to the template (same facts, plainer prose)
2. Act 3's Tribunal → already off by default; the rule-based verdict is unchanged
3. Monte Carlo rollout count → halved, never below 50

**Nothing below that line ever degrades**: DETECT, COMPLIANCE, the HUMAN GATE,
supersession tracking, trace writing. Demonstrated rather than asserted — a full
12-cut walk with **both budgets set to zero** produces byte-identical
deterministic output: 357 signals, 263 escalations, 156 decisions, 11,527 trace
lines, 1,941 deviations, all unchanged.

## 5. Trade-offs and limitations

- **A new domain *file* is not absorbed.** A new site and a new lab test are
  (verified with a synthetic site and test that appear nowhere in the data). A
  brand-new domain CSV is not, because `DOMAINS` is a fixed tuple in the
  organiser's own `study.py`, which this stage may not edit. It fails safely.
- **The escalation timing is simulated** (§2). Stated in the report, not buried.
- **The forecast is a model, not a prediction.** It carries no date and no
  external consequence. Its breach threshold is the study's own worst observed
  stretch, so it is checkable and needs no adjustment for a study of another
  size. Where no site has yet been watched for as long as the horizon, **no
  forecast is offered** rather than one against a degenerate threshold of zero.
- **`risk` is a ranking aid**, not calibrated against any external standard. Its
  integrity and volume signals are combined with `max`, not averaged: averaging
  ranked the fabricated-data site 11th of 12, because fabricated data is quiet.
- **Act 5 polish can be refused and is.** A reworded draft is discarded in full
  if any number, identifier or code changed. In this run 0 of 154 documents were
  polished; all shipped as templates and are tagged as such.
- **`SurveillanceReport` has no field** for per-cut reports, superseded
  findings, forecasts or artifacts. Rather than invent fields on the organiser's
  type, those ride in `markdown`, in `EscalationOut.summary`, and on the
  `StudyWatch` object for the UI.

## 6. Who did what

Solo build (Vinoth). Stage 1 `Atlas` (detection), Stage 2 `ReviewCrew` (the
six-node cycle), Stage 3 `StudyWatch` (this document). Stage 2 was changed in
exactly one way: `run_cycle_with_extra_findings()` was added beside
`run_cycle()`, whose output was then proved **byte-identical before and after**
on five cuts up to 3MB — recovered from git and run in a separate interpreter,
because Stage 2 is separately graded.

Verification is 601 automated checks across 19 Stage-3 test files, plus Stage
1's 23 offline tests still green. Each is a real run against the real data; the
pasted output is the evidence, not a summary of it.
