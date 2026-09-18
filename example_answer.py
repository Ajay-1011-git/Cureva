"""A worked example: one question answered end to end, with evidence.

Not a solution. It answers the simplest kind of question in the most direct way,
to show the shape of a valid Answer and how evidence is cited.

    python example_answer.py --data hackathon-data
"""
from __future__ import annotations

import argparse
import time

from schemas import Answer, RecordRef
from study import Study


def answer_count_discontinued_ae(s: Study, site: str) -> Answer:
    """How many subjects at <site> discontinued because of an adverse event?"""
    t0 = time.time()

    rows = s.records("DS", site=site)
    hits = [r for r in rows
            if r.get("DSDECOD") == "DISCONTINUED" and r.get("DSTERM") == "ADVERSE EVENT"]

    # Evidence: the exact records the count rests on. Each one is a real record
    # that shows what we claimed — which is what makes it valid at grading time.
    evidence = [RecordRef(domain="DS", usubjid=r["USUBJID"], seq=int(r["DSSEQ"]))
                for r in hits]

    return Answer(
        question_id="example",
        answer=len(hits),
        text=f"{len(hits)} subjects at site {site} discontinued due to an adverse event.",
        evidence=evidence,
        confidence=0.95,
        steps_used=0,
        tokens_used=0,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="hackathon-data")
    a = ap.parse_args()

    s = Study(a.data)
    site = s.sites()[0]
    ans = answer_count_discontinued_ae(s, site)

    print(ans.text)
    print(f"  evidence : {len(ans.evidence)} records")
    for e in ans.evidence[:5]:
        print(f"     {e.domain} {e.usubjid} #{e.seq}")
    print(f"  valid    : {Answer.model_validate(ans.model_dump()) is not None}")

    print("\nThings this example does NOT do, which the real questions need:")
    print("  - convert laboratory units before comparing to a range")
    print("  - parse the two date formats")
    print("  - handle '<5', 'ND', '12,4' and empty laboratory values")
    print("  - read the protocol version in force at the cut")
    print("  - return [] when the honest answer is nothing")


if __name__ == "__main__":
    main()
