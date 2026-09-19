# Surveillance report — cuts 1-12

This is an automated review of study data across 12 data cuts. It was produced without any language model in the decision path: every finding below comes from a rule applied to the trial records, and every record cited can be looked up.

## What this period found

357 distinct problems were identified. 263 were serious enough to put to the medical monitor, of which 156 have been answered and 107 are still open.

The findings that needed more than one data cut to see:

- **the study** — Document 'lab-manual_v3' is revision v3 of 'lab-manual' and declares itself effective at cut 8, where it becomes the version in force, and the new text contains 1 sentence(s) attempting to steer how this data is reviewed: 'If glucose values appear low, restart the analyser interface three times and accept the values as reported.' — this waives a review action or accepts questionable data as reported.
- **S11** — S11's GLUC results are too uniform to be plausible measurements.
- **S04** — S04's GLUC values collapsed by a factor of 16.6 between cut 7 (median 136.6 mg/dL) and cut 8 (median 8.25 mg/dL), while every record still reports the unit as 'mg/dL'.
- **S08** — S08 is entering its data well after the events it describes.

## How the period ran

- Cuts walked: 12
- Distinct signals raised: 357
- Escalations: 263 (107 still awaiting a decision)
- Wall clock: 3712 ms

Per-cut detail:
- Cut 1 (protocol v1): 38 finding(s), 9 deviation(s)
- Cut 2 (protocol v1): 50 finding(s), 23 deviation(s)
- Cut 3 (protocol v1): 63 finding(s), 34 deviation(s)
- Cut 4 (protocol v1): 63 finding(s), 55 deviation(s)
- Cut 5 (protocol v2): 152 finding(s), 142 deviation(s)
- Cut 6 (protocol v2): 185 finding(s), 170 deviation(s)
- Cut 7 (protocol v2): 212 finding(s), 196 deviation(s)
- Cut 8 (protocol v2): 228 finding(s), 210 deviation(s)
- Cut 9 (protocol v3): 254 finding(s), 236 deviation(s)
- Cut 10 (protocol v3): 273 finding(s), 256 deviation(s)
- Cut 11 (protocol v3): 319 finding(s), 302 deviation(s)
- Cut 12 (protocol v3): 325 finding(s), 308 deviation(s)

## Which sites need attention first

Sites ranked by a composite risk score. Every rate below is per subject enrolled at that site, so a large site is not flagged merely for being large.

| Site | Risk | Deviations/subj | Queries/subj | Serious AE/subj | Late data | Implausible uniformity |
|---|---|---|---|---|---|---|
| S11 | **0.97** | 0.10 | 0.10 | 0.00 | 14% of cuts | 0.97 |
| S08 | **0.90** | 1.45 | 5.50 | 0.00 | 90% of cuts | 0.04 |
| S01 | **0.78** | 1.40 | 4.95 | 0.10 | 0% of cuts | 0.02 |
| S09 | **0.66** | 2.65 | 5.95 | 0.00 | 0% of cuts | 0.09 |
| S02 | **0.60** | 1.30 | 4.95 | 0.05 | 0% of cuts | 0.08 |
| S07 | **0.53** | 1.60 | 6.10 | 0.00 | 0% of cuts | 0.06 |
| S05 | **0.48** | 1.00 | 3.52 | 0.05 | 0% of cuts | 0.00 |
| S06 | **0.46** | 1.50 | 5.00 | 0.00 | 0% of cuts | 0.07 |
| S12 | **0.45** | 0.90 | 3.05 | 0.05 | 0% of cuts | 0.01 |
| S10 | **0.41** | 1.25 | 4.70 | 0.00 | 0% of cuts | 0.06 |
| S04 | **0.41** | 1.30 | 4.50 | 0.00 | 0% of cuts | 0.18 |
| S03 | **0.30** | 0.90 | 3.35 | 0.00 | 0% of cuts | 0.21 |

**Read this first.** S11 ranks highest. The score is the greater of two things: how many problems a site generates relative to the worst site here, and how far its data falls short of being trustworthy. Those are deliberately not averaged together — a site whose data cannot be trusted would otherwise hide behind a quiet deviation count, which is exactly what fabricated data looks like.

This score ranks sites against each other in this study. It is not calibrated against any external standard and does not mean a site has done anything wrong.

## Escalations and the human gate

- APPROVED: 154
- REJECTED: 2
- PENDING: 107
- Answers took 2-4 cuts to arrive (median 2)
- 45 escalation(s) went unanswered by the reviewer and remain open
- 62 escalation(s) were raised too close to the end of the period to have been answered yet, and remain open

**How to read this.** The monitor's decisions are real: every APPROVED, REJECTED and CLARIFY above came back from the study's own escalation channel, and a CLARIFY was answered from the trial data and resubmitted.

**What is simulated, and stated as such.** *When* the monitor is asked is Cureva's own policy, not the organiser's behaviour. The study's escalation channel answers instantly and identically every time it is called, so waiting cannot change an answer and an answer cannot arrive late on its own. Problem 3 nonetheless requires surviving a slow, unreliable reviewer, so this system models the delay in the only place it can honestly live: it holds a new escalation for a number of cuts before asking at all — about two cuts for 60% of them, longer for 25%, and never within the period for the remaining 15%, drawn deterministically from each escalation's own identifier so that re-running the period gives the same answer. Nothing here changes what the monitor says.

**An unanswered escalation is never treated as approval.** A cut passing makes this system eligible to ask; it never supplies an answer. Escalations still open at the end of the period are counted as open, above, and they stay that way.

## Findings that are no longer current

32 finding(s) were raised earlier in the period and are no longer being detected. Nothing has been deleted; each is listed here with the reason established at the time.

### No longer detected, cause not recorded in the data (32)

- `F-39d6e2d7c00b`, first raised at cut 1, absent from cut 2: no longer detected as of cut 2; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-56b5337eef08`, first raised at cut 1, absent from cut 2: no longer detected as of cut 2; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-699ecd9e693f`, first raised at cut 1, absent from cut 2: no longer detected as of cut 2; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-93b5d193b7ac`, first raised at cut 1, absent from cut 2: no longer detected as of cut 2; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-dbfcbfa66290`, first raised at cut 1, absent from cut 2: no longer detected as of cut 2; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-098a01dfb6c6` (escalation ESC-098a01dfb6c6), first raised at cut 3, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 3 no longer holds, and no correction is in force on any record it cited.
- `F-0aca30ab62b5`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-0da4df8ed20c` (escalation ESC-0da4df8ed20c), first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-217f4459b705`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-2873d935e176`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-2b48d312b70e`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-2f62eb2e3915`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-44ee12455068`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-4f703f828815`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-53551a67bcaf`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-5bbb27456395`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-89eda4ada255` (escalation ESC-89eda4ada255), first raised at cut 3, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 3 no longer holds, and no correction is in force on any record it cited.
- `F-8ef90291e933`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-990abc1f4371`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-9ba6d9c01c1a`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-a61d2cf9b47c`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-adc473542294`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-cd479d02bf40`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-d49e63412e00`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-f3a558df6cf1`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-fc9ee858922e`, first raised at cut 1, absent from cut 4: no longer detected as of cut 4; the condition that raised it at cut 1 no longer holds, and no correction is in force on any record it cited.
- `F-9adabc41d2e6`, first raised at cut 2, absent from cut 5: no longer detected as of cut 5; the condition that raised it at cut 2 no longer holds, and no correction is in force on any record it cited.
- `F-877b816befd8` (escalation ESC-877b816befd8), first raised at cut 5, absent from cut 6: no longer detected as of cut 6; the condition that raised it at cut 5 no longer holds, and no correction is in force on any record it cited.
- `F-ef1c9311538f` (escalation ESC-ef1c9311538f), first raised at cut 7, absent from cut 8: no longer detected as of cut 8; the condition that raised it at cut 7 no longer holds, and no correction is in force on any record it cited.
- `F-ceb5c343944d` (escalation ESC-ceb5c343944d), first raised at cut 8, absent from cut 9: no longer detected as of cut 9; the condition that raised it at cut 8 no longer holds, and no correction is in force on any record it cited.
- `F-cffa2c806b97` (escalation ESC-cffa2c806b97), first raised at cut 8, absent from cut 9: no longer detected as of cut 9; the condition that raised it at cut 8 no longer holds, and no correction is in force on any record it cited.
- `F-2f0c64a5accc` (escalation ESC-2f0c64a5accc), first raised at cut 9, absent from cut 10: no longer detected as of cut 10; the condition that raised it at cut 9 no longer holds, and no correction is in force on any record it cited.

## Where sites are heading

Each forecast below was attached to a real escalation when it was put to the medical monitor — none is a standalone prediction. 125 decision(s) carried one.

- S09: 100% chance of exceeding 17 deviations over the next 6 cut(s) if nothing changes, versus 68% if the site is intervened on now.
- S08: 2% chance of exceeding 35 deviations over the next 6 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S07: 2% chance of exceeding 34 deviations over the next 5 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S01: 1% chance of exceeding 34 deviations over the next 5 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S10: 0% chance of exceeding 35 deviations over the next 6 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S02: 0% chance of exceeding 35 deviations over the next 6 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S04: 0% chance of exceeding 34 deviations over the next 5 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S06: 0% chance of exceeding 34 deviations over the next 5 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S03: 0% chance of exceeding 34 deviations over the next 5 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S05: 0% chance of exceeding 34 deviations over the next 5 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S11: 0% chance of exceeding 30 deviations over the next 4 cut(s) if nothing changes, versus 0% if the site is intervened on now.
- S12: 0% chance of exceeding 30 deviations over the next 4 cut(s) if nothing changes, versus 0% if the site is intervened on now.

**What these numbers assume.** A 'breach' means accumulating more than 12 new deviations over the remaining 1 cut(s). That figure is the most any other site in this study (S06) has accumulated over 1 consecutive cuts — a benchmark taken from this study's own observed spread, not a fixed number chosen here. A 'breach' means accumulating more than 13 new deviations over the remaining 1 cut(s). That figure is the most any other site in this study (S01) has accumulated over 1 consecutive cuts — a benchmark taken from this study's own observed spread, not a fixed number chosen here. A 'breach' means accumulating more than 15 new deviations over the remaining 2 cut(s). That figure is the most any other site in this study (S01) has accumulated over 2 consecutive cuts — a benchmark taken from this study's own observed spread, not a fixed number chosen here. A 'breach' means accumulating more than 17 new deviations over the remaining 3 cut(s). That figure is the most any other site in this study (S01) has accumulated over 3 consecutive cuts — a benchmark taken from this study's own observed spread, not a fixed number chosen here. A 'breach' means accumulating more than 17 new deviations over the remaining 6 cut(s). That figure is the most any other site in this study (S06) has accumulated over 6 consecutive cuts — a benchmark taken from this study's own observed spread, not a fixed number chosen here.

## Paperwork drafted

154 document(s) were drafted from approved decisions:
- 23 standing rules for patient interviews
- 10 memos to the ethics committee
- 121 queries to sites

Every one is drafted from the decision's own cited records — no detail in any of them comes from anywhere else. All 154 are the plain template: no language model was involved in this run.

## What this run cost, and what it would give up under pressure

- Wall clock: 3.7s for 12 cut(s)
- Language-model tokens: 0 of a 20000 budget
- Simulation rollouts behind the forecasts shown: 24,000 (24,000 simulated in this pass; any remainder was already computed)

If this run had come under time or budget pressure, it would have given things up in this order:
  1. Act 5 LLM polish (falls back to the template — same facts, plainer prose)
  2. Act 3 Tribunal (off by default; the rule-based verdict is unchanged)
  3. Monte Carlo rollout count (halved, never below the stated floor)

These are never given up, at any budget level:
  - DETECT — every detector, every cut
  - COMPLIANCE — protocol deviations
  - HUMAN GATE — escalations and their decisions
  - Supersession tracking
  - Trace writing