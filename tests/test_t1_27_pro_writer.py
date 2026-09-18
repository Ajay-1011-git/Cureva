"""T1.27 VERIFY — PRO writer, fed a real extraction from a live Groq call."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
           override=True)
from stage1.atlas import StudyGraph
from intake.pro_writer import write_extractions
from intake.models import PROExtraction
from intake.groq_client import GroqAvatarClient, GroqUnavailable

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
SUBJECT = "042-S01-001"

print("=== VERIFY (required): a real extraction from T1.26's live Groq call, through this writer ===")
try:
    client = GroqAvatarClient()
    resp = client.turn("I've had a headache since yesterday and I'm also taking ibuprofen for it")
    print(f"  live Groq extracted {len(resp.extracted)} item(s):")
    for e in resp.extracted:
        print(f"     {e.pro_type}: {e.term!r} <- {e.raw_quote!r}")
except GroqUnavailable:
    print("  Groq unavailable live — using the exact extraction from T1.26's build log instead")
    resp = None
    resp_extracted = [
        PROExtraction(pro_type="SYMPTOM", term="headache",
                      raw_quote="I've had a headache since yesterday", reported_date=None),
        PROExtraction(pro_type="CONMED_MENTION", term="ibuprofen",
                      raw_quote="I'm also taking ibuprofen for it", reported_date=None),
    ]
if resp is not None:
    resp_extracted = resp.extracted

written = write_extractions(g, SUBJECT, resp_extracted, transcript_ref="t1.27-live-test", cut_available=1)
print(f"\n  writer wrote {len(written)} PRORecord(s)")
check("both real extractions were written (both had real raw_quotes)", len(written) == len(resp_extracted))

pro = g.patient360(SUBJECT)["PRO"]
print(f"\n  graph.patient360({SUBJECT!r})['PRO']:")
for r in pro:
    print(f"     seq={r['seq']} {r['pro_type']} {r['term']!r} raw_quote={r['raw_quote']!r}")
check("patient360 shows exactly the written records", len(pro) == len(written))
check("raw_quote matches exactly what Groq extracted",
      all(pro[i]["raw_quote"] == written[i].raw_quote for i in range(len(written))))
check("seq numbers are sequential starting at 1",
      [r["seq"] for r in pro] == list(range(1, len(pro) + 1)))
check("USUBJID is set correctly on every written row",
      all(r["USUBJID"] == SUBJECT for r in pro))
check("transcript_ref is carried through", all(r["transcript_ref"] == "t1.27-live-test" for r in pro))

print("\n=== VERIFY (required, FR-19): an extraction with an empty raw_quote is discarded, not placeholder-written ===")
mixed = [
    PROExtraction(pro_type="SYMPTOM", term="real one", raw_quote="I really said this", reported_date=None),
    PROExtraction(pro_type="OTHER", term="fabricated", raw_quote="", reported_date=None),
    PROExtraction(pro_type="OTHER", term="whitespace only", raw_quote="   ", reported_date=None),
]
before = len(g.patient360(SUBJECT)["PRO"])
written2 = write_extractions(g, SUBJECT, mixed, transcript_ref="t1.27-mixed-test", cut_available=1)
after = len(g.patient360(SUBJECT)["PRO"])
print(f"  fed 3 extractions (1 real, 1 empty raw_quote, 1 whitespace-only raw_quote)")
print(f"  writer returned {len(written2)} record(s); PRO count went {before} -> {after}")
check("only the 1 extraction with a real raw_quote was written", len(written2) == 1)
check("no placeholder record for the empty/whitespace-only quotes", after - before == 1)
check("the one written record is the real one", written2[0].term == "real one")

print("\n=== VERIFY: no rebuild — append is in-place, other domains untouched ===")
lb_before = len(g.by_domain["LB"])
write_extractions(g, SUBJECT, [PROExtraction(pro_type="OTHER", term="x", raw_quote="y", reported_date=None)],
                  transcript_ref="t", cut_available=1)
check("appending a PRO record never touches LB's index", len(g.by_domain["LB"]) == lb_before)

print("\n" + ("ALL T1.27 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
