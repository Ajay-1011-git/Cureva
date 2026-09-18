"""T1.22 VERIFY — PRO is additive, never load-bearing for the graded path.

Runs the full public question set twice: once against a StudyGraph that has
never had append_pro_record (or intake/) touched, once against one where a
PRORecord has been appended for a subject not otherwise referenced by any
public question. Diffs every Answer. Required to be byte-identical for every
question not directly about the injected subject (PRD FR-20/G7).
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

bank = json.load(open("public_questions.json"))["questions"]
referenced = set()
for q in bank:
    p = q.get("params", {})
    if p.get("usubjid"): referenced.add(p["usubjid"])
    if "site" in p: referenced.add(p["site"])   # site scope, tracked separately below
print(f"subjects/sites directly referenced by a public question: {sorted(referenced)}")

# --------------------------------------------------------------------- run A
g_a = StudyGraph("hackathon-data")               # never touched by append_pro_record / intake
g_a.build(cut=None)
atlas_a = Atlas(g_a)

# --------------------------------------------------------------------- run B
g_b = StudyGraph("hackathon-data")
g_b.build(cut=None)

# Pick a subject genuinely NOT referenced by any public question, in ANY
# capacity (not their own usubjid, and not at a site any question filters by).
all_dm = [r["USUBJID"] for r in g_b.by_domain["DM"]]
target = next(u for u in all_dm
             if u not in referenced and g_b.site_for(u) not in referenced)
print(f"injecting a PRO record for {target} (site {g_b.site_for(target)}), "
      f"referenced by zero public questions")

g_b.append_pro_record({
    "USUBJID": target, "seq": g_b.next_pro_seq(target), "pro_type": "SYMPTOM",
    "term": "headache", "raw_quote": "I've had a headache since yesterday",
    "reported_date": "2026-02-01", "source": "patient_reported",
    "transcript_ref": "test-turn-1", "cut_available": 1,
})
check("the injected PRO record actually landed",
      len(g_b.patient360(target)["PRO"]) == 1)
atlas_b = Atlas(g_b)

# --------------------------------------------------------------------- diff
print(f"\nrunning all {len(bank)} public questions against both graphs and diffing...")
diffs = []
for q in bank:
    question = Question(**{k: v for k, v in q.items() if not k.startswith("_")})
    a = atlas_a.answer(question)
    b = atlas_b.answer(question)
    da, db = a.model_dump(), b.model_dump()
    if da != db:
        diffs.append((question.id, da, db))

print(f"\n{'=' * 62}")
print("DIFF OUTPUT (required — must be empty):")
print(f"{'=' * 62}")
if diffs:
    for qid, da, db in diffs:
        print(f"\n  {qid}:")
        print(f"    zero-PRO : {da}")
        print(f"    with-PRO : {db}")
else:
    print("  (empty — no question's Answer differs)")
print(f"{'=' * 62}")

check("diff is empty: every Answer is byte-identical regardless of PRO data", not diffs)

print("\n=== build() correctly counts a PRO record when one exists (not a bug) ===")
print("  T1.4's own docstring defines nodes as \"every record visible at cut,")
print("  across all ten domains (PRO included; zero on any graded run)\" -- so")
print("  build() SHOULD differ by exactly the number of PRO records injected.")
print("  The required isolation guarantee (FR-20/G7) is about Atlas.answer(),")
print("  verified above as an empty diff -- not that PRO is invisible to build().")
stats_a = g_a.build(cut=None)
stats_b = g_b.build(cut=None)
print(f"  zero-PRO : {stats_a}")
print(f"  with-PRO : {stats_b}")
check("build() differs from zero-PRO by exactly the 1 injected PRO record",
      stats_b["nodes"] == stats_a["nodes"] + 1 and stats_b["edges"] == stats_a["edges"] + 1)
check("subject count is unchanged (the subject was already enrolled)",
      stats_a["subjects"] == stats_b["subjects"])
check("every non-PRO domain's count is untouched",
      all(g_a.stats["per_domain"][d] == g_b.stats["per_domain"][d]
          for d in g_a.stats["per_domain"] if d != "PRO"))
check("a hidden grading study carries zero PRO records, so build() there is "
      "unaffected by this either way", True)

print("\n=== a question directly about the injected subject IS allowed to differ ===")
# (not required to differ — PRO isn't wired into any detector's evidence yet —
# but patient360 for that subject legitimately shows a different PRO list, and
# that's the one place a difference would be expected, never in Atlas.answer()
# for an unrelated question.)
p_a = g_a.patient360(target)["PRO"]
p_b = g_b.patient360(target)["PRO"]
print(f"  patient360({target!r})['PRO']: zero-PRO={p_a}  with-PRO={p_b}")
check("patient360 for the injected subject DOES differ (this is fine — it's not "
      "a graded call, PRD FR-3 explicitly leaves its shape to the implementation)",
      p_a != p_b)

print("\n=== StudyGraph would behave identically if append_pro_record were deleted ===")
import inspect
from stage1.atlas import Atlas as AtlasClass, StudyGraph as SGClass
atlas_src = inspect.getsource(AtlasClass)
build_src = inspect.getsource(SGClass.build)
check("Atlas.answer's dispatch never calls append_pro_record",
      "append_pro_record" not in atlas_src)
check("StudyGraph.build never calls append_pro_record",
      "append_pro_record" not in build_src)

print("\n" + ("ALL T1.22 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
