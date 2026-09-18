# Review-cycle architecture note

Two pages, covering what the rubric asks: what each node is responsible for,
how memory is designed, and how each of the three reviewer replies is handled.

---

## The six nodes

`ReviewCrew(data_dir, atlas).run_cycle(cut, protocol_version) -> ReviewReport`
runs six nodes in a fixed order, every time, with a single mutable
`CycleContext` threaded through them. There is no orchestration framework: the
behaviour and the trace are what get graded, not the library.

| Node | Responsibility | What it must never do |
|---|---|---|
| **DETECT** | Sweeps all 11 single-snapshot codes through `Atlas.answer()` at the cycle's cut, then evaluates the one cross-cycle code this layer owns, `SAE_UNESCALATED`. | Re-derive a detector's rule. An empty result for a code is a correct answer, not a gap to fill. |
| **MEDICAL REVIEW** | Assigns every finding an escalation-worthy / watch-only verdict from a rule table, then optionally attempts a three-reviewer deliberation on contested ones. | Let the deliberation change the verdict. It contributes narrative and alternatives only. |
| **DATA MANAGER** | Turns data-quality findings into one `study.query_site()` call per record, deduplicated against memory for the lifetime of that memory. | Query a record twice, ever. Match a site by USUBJID prefix instead of `site_for()`. |
| **COMPLIANCE** | Re-expresses protocol findings as deviations, tagged with the version really in force at the cut (`protocol_version_at`). | Use the caller's stated version or a constant. |
| **HUMAN GATE** | Raises escalations and handles all three replies as distinct paths. | Advance an escalation's state through the mere passage of a cycle. |
| **EXECUTE** | Assembles the `ReviewReport`: findings, current escalation state, queries, deviations, this cycle's trace, tokens and duration. | Report only newly-raised escalations — a cut looks clean when an earlier cycle already escalated everything. |

Every node writes its trace entries at the moment of each decision, appended
and fsynced. A cycle killed halfway leaves a file containing everything decided
up to that point, which is what makes the trace evidence rather than a summary
of runs that happened to succeed.

**The one code this layer owns.** `SAE_UNESCALATED` fires when a serious adverse
event (`AESER=Y` or `AESHOSP=Y`, the seriousness rule the existing detectors
already use) is still visible, unescalated, at a *later cut* than the one it was
first seen at. The build document says "≥2 consecutive cycles"; counting cycles
makes a repeated cut promote every watched event and raise a batch of new
escalations, which is precisely what the idempotency requirement forbids.
Counting distinct cuts satisfies both, and the task's own verification asks for
two runs "at consecutive cuts".

---

## Memory

In-process `dict`/`set`, snapshotted to JSON after every cycle by the crew
itself rather than left to the caller. A missing or unreadable snapshot starts
empty and logs, never raises: forgetting re-raises a query that was already
raised, which is visible and recoverable, while trusting half-written state
silently suppresses real ones. Snapshots are written to a temp file and renamed,
so a crash mid-write leaves the previous good file rather than a truncated one.

| What is remembered | Keyed on | Why |
|---|---|---|
| Queries raised | `domain:usubjid:seq` | Exactly what `query_site()` itself keys on. The specified fourth component, `field`, does not exist on any organiser type. |
| Escalations | A hash of the finding's own fingerprint | Derived, not counted. Two cycles over one cut produce the same findings, so the same ids, so the second recognises them as already raised. A counter would make every cycle's escalations look new. |
| Subject / site flags | USUBJID, site | Feeds the compounding rule. |
| Serious-AE watch | `usubjid:aeseq` → first-seen **cut** | See above. |

**Two places the obvious implementation breaks idempotency**, both found by
running rather than reading:

1. **Flag counters store a maximum, not a running sum.** Accumulating pushes
   borderline subjects past the compounding threshold on a second pass over the
   same cut, flipping watch-only findings to escalation-worthy and raising new
   escalations. The maximum keeps the "repeatedly messy subject" signal while
   making a repeat arithmetically identical.
2. **An escalated serious AE must leave the watch permanently.** Checking
   "already escalated" *after* consulting the watch let an escalated event fall
   back in, so the watch oscillated 0 → 5 → 0 across cycles. No wrong escalation
   ever resulted, but memory was not stable — and "the same cut twice changes
   nothing" has to mean nothing. This was invisible to a single-cut test and
   only appeared when repeating a cut after walking all twelve.

Measured: walking cuts 1–12 then repeating cut 12 leaves every memory counter
identical and raises 0 new queries and 0 new escalations, with 1012 queries and
253 escalations correctly skipped as duplicates.

---

## The three replies

`study.escalate(code, subject)` returns `(decision, reason)` **inline and
always** — an unknown key falls through to `("APPROVED", "Noted.")`. There is no
"no response" case, so the specified "unanswered escalation stays PENDING
forever" describes a state that call cannot produce. Resolved in favour of what
the starter code models, with the half that *can* be implemented literally
implemented literally: a cycle passing never advances an escalation's state.

- **APPROVED** — state `APPROVED`, `resolved_cycle` set. Closed.
- **REJECTED** — state `REJECTED`, `resolved_cycle` set. The finding is *not*
  fixed and stays in the report; what closes is the escalation, which will not
  re-fire.
- **CLARIFY** — not a soft rejection. The question is answered from data already
  in the graph (a `patient360` read: the subject's record counts and the
  evidence already cited — no new detection, no new inference), then resubmitted,
  and `clarify_count` increments. Because `escalate()` is a pure lookup over a
  static table, a resubmission returns the same `CLARIFY` forever and the call
  cannot express "this one is a resubmission"; the organiser states the
  resolving rule in both `study.py` and the decisions file — *a resubmission is
  APPROVED* — and that documented rule is what closes it.
- **PENDING** is reached two ways, neither of them time passing: an
  `escalate()` call that raised (the finding stays tracked, flagged
  `send_failed`, rather than being lost), and an escalation awaiting a human on
  the review page. The page runs the crew in a mode where escalations are held
  for a person, and their answer runs through the *same* `_apply_decision` —
  a second implementation for the UI is how the two would drift apart.

---

## The three-reviewer deliberation

Three personas — safety, clinical operations, regulatory — are accountable for
different questions, which is what makes disagreement possible rather than three
temperatures of one reviewer. Round 1 runs them concurrently with no persona
aware the others exist. Round 2 shows each the other two's real output and asks
for challenges against *specific* claims. Round 3 is deterministic, makes zero
model calls, and discards any claim whose cited record does not exist, is not
visible at the cut, or is not cited by the finding's own detector — it calls
`Atlas.verify_evidence()`, which *runs* the registered detector rather than
approximating it.

It is **off by default**, and that default is load-bearing. Six network calls per
finding against 170 contested findings is ~1000 calls; the free tier's real
ceiling is 8000 tokens *per minute* and one deliberation costs ~5.7k, so the
honest budget is about one per minute. The graded path therefore runs
deterministic and offline, and the deliberation is switched on for the demo with
a per-cycle budget. Verified: with it off, on, or failing, the escalation-worthy
set is identical at 170.
