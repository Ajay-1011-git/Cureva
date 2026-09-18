"""Live probe — the three-round deliberation, on a genuinely contested finding.

NOT a test. This never fails the build. Its job is the rehearsal G6 asks for:
show that three personas really do disagree, really do cross-examine each
other's specific claims, and really do face a deterministic fact-check --
before a live defence, not during one.

What is asserted deterministically lives elsewhere and does gate the build:
Round 3's arbitration in `tests/test_t2_15_arbitration.py`, and the
never-blocks-the-cycle guarantee in `tests/test_t2_17_rate_limit.py`. What a
model *chooses to argue* is not a contract and is not asserted here.

DUPLICATE_SUBJECT is the default finding because it is the one that reliably
splits the panel: the same record is a data-integrity problem to operations, a
reporting problem to regulatory, and -- absent any actual harm -- not a safety
problem at all. That is a real disagreement between three defensible
positions, not three models being noisy.

    python probes/probe_tribunal_live.py
    python probes/probe_tribunal_live.py --code HYS_LAW_CANDIDATE --cut 9
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from schemas import Question                                      # noqa: E402
from stage1.atlas import Atlas, StudyGraph                        # noqa: E402

BAR = "=" * 74


def main() -> int:
    ap = argparse.ArgumentParser(prog="python probes/probe_tribunal_live.py")
    ap.add_argument("--data", default=os.environ.get("DATA_DIR", "hackathon-data"))
    ap.add_argument("--code", default="DUPLICATE_SUBJECT")
    ap.add_argument("--cut", type=int, default=12)
    ap.add_argument("--index", type=int, default=0,
                    help="which finding of that code to deliberate on")
    args = ap.parse_args()

    import tribunal

    graph = StudyGraph(args.data)
    graph.build(args.cut)
    atlas = Atlas(graph)

    answer = atlas.answer(Question(id="probe", kind="finding",
                                   text=f"All {args.code}", params={"code": args.code},
                                   cut=args.cut))
    if not answer.findings:
        print(f"no {args.code} findings at cut {args.cut} — nothing to deliberate on.")
        return 0
    finding = answer.findings[min(args.index, len(answer.findings) - 1)]

    print(BAR)
    print(f"FINDING  {finding.code}   {finding.usubjid or finding.site}   "
          f"severity={finding.severity}   cut={args.cut}")
    print(BAR)
    print(finding.rationale)
    print()

    transcript = tribunal.deliberate(atlas, finding, "probe", args.cut)

    if not transcript.ran:
        print(f"Act 3 did not run: {transcript.skip_reason}")
        print()
        print("This is the designed degradation, not a defect. The cycle's verdict is")
        print("rule-based and identical either way. On the free tier the usual cause is")
        print("the 8000 tokens/minute ceiling — one deliberation costs ~5.7k, so a second")
        print("run inside the same minute will say exactly this.")
        return 0

    print(f"ran in {transcript.duration_ms}ms, {transcript.tokens_used} tokens\n")

    print("-" * 74)
    print("ROUND 1 — three independent verdicts, no persona aware of the others")
    print("-" * 74)
    for verdict in transcript.round1:
        cites = ", ".join(f"{e.domain}:{e.usubjid}:{e.seq}" for e in verdict.cited_evidence)
        print(f"  [{verdict.persona:12}] {verdict.verdict}")
        print(f"      {verdict.reasoning}")
        print(f"      cites: {cites or '(nothing)'}")
    positions = {v.verdict for v in transcript.round1}
    print(f"\n  >> the panel {'DISAGREES' if len(positions) > 1 else 'is unanimous'}: {positions}")

    print()
    print("-" * 74)
    print("ROUND 2 — each persona now sees the other two, and challenges specifics")
    print("-" * 74)
    challenges = 0
    for response in transcript.round2:
        for challenge in response.challenges:
            challenges += 1
            print(f"  [{response.persona} -> {challenge.target_persona}]")
            print(f"      disputes : {challenge.claim_challenged}")
            print(f"      because  : {challenge.rebuttal}")
        if response.revised_verdict:
            print(f"  [{response.persona}] revised its verdict to {response.revised_verdict}")
    print(f"\n  >> {challenges} challenge(s) raised")

    print()
    print("-" * 74)
    print("ROUND 3 — deterministic. Zero model calls. Every citation checked.")
    print("-" * 74)
    arb = transcript.round3
    if arb is None:
        print("  arbitration did not complete")
        return 0
    print(f"  method        : {arb.method}")
    print(f"  final verdict : {arb.final_verdict}")
    print(f"  surviving     : {len(arb.surviving_claims)}")
    for claim in arb.surviving_claims:
        print(f"      + {claim[:150]}")
    print(f"  discarded     : {len(arb.discarded_claims)}")
    for bad in arb.discarded_claims:
        print(f"      - [{bad.persona}] {bad.reason_discarded}")
    if not arb.discarded_claims:
        print("      (every citation held up — which is the honest outcome when the")
        print("       personas cited the finding's own evidence. tests/test_t2_15_"
              "arbitration.py")
        print("       proves the discard path bites, using a deliberate mismatch.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
