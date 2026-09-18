"""T1.28 VERIFY — FindingNode/FindingEdge + clustering, real findings."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import StudyGraph, Atlas
from graph.finding_graph import FindingGraph

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None)
atlas = Atlas(g)
fg = FindingGraph(g)

print("=== VERIFY (required): feed 3-4 real findings from earlier tasks' test runs ===")
codes = ["HYS_LAW_CANDIDATE", "PROHIBITED_CONMED", "VISIT_OUT_OF_WINDOW", "INCLUSION_VIOLATION"]
total_findings = 0
for code in codes:
    ans = atlas.answer(Question(id="q", kind="finding", text="", params={"code": code}))
    nodes = fg.observe_all(ans.findings, cut=None)
    total_findings += len(ans.findings)
    print(f"  {code:22} {len(ans.findings):>3} real finding(s) -> {len(nodes)} new node(s)")

snap = fg.snapshot()
print(f"\n  total real findings fed in: {total_findings}")
print(f"  graph nodes: {len(snap['nodes'])}   edges: {len(snap['edges'])}")
check("nodes were created", len(snap["nodes"]) > 0)
check("deduplication: node count <= findings fed in (some subjects share codes)",
      len(snap["nodes"]) <= total_findings)

print("\n=== VERIFY (required): at least one edge forms, clustering groups sensibly ===")
check("at least one edge formed", len(snap["edges"]) > 0, str(len(snap["edges"])))
relations = {e["relation"] for e in snap["edges"]}
print(f"  relation types observed: {relations}")

print("\n  edges, by relation:")
for e in snap["edges"]:
    print(f"     {e['from_finding_id']} --[{e['relation']}]--> {e['to_finding_id']}")

print(f"\n  clusters: {snap['clusters']}")
check("clustering returns a list of lists", isinstance(snap["clusters"], list)
      and all(isinstance(c, list) for c in snap["clusters"]))
n_in_clusters = sum(len(c) for c in snap["clusters"])
check("every node appears in exactly one cluster", n_in_clusters == len(snap["nodes"]))

print(f"\n  centrality: {snap['centrality']}")
check("centrality has one score per node", set(snap["centrality"]) == set(fg.nodes))
check("centrality scores are non-negative", all(v >= 0 for v in snap["centrality"].values()))

print("\n=== VERIFY: TEMPORAL_PROXIMITY connects a real subject's own findings ===")
# Confirmed above: 042-S09-001 and 042-S09-013 each have a real
# VISIT_OUT_OF_WINDOW finding and a real PROHIBITED_CONMED finding whose
# evidence dates fall within the 14-day window, for the SAME subject.
temporal_edges = [e for e in fg.edges if e.relation == "TEMPORAL_PROXIMITY"]
print(f"  real TEMPORAL_PROXIMITY edges found: {len(temporal_edges)}")
for e in temporal_edges:
    print(f"     {e.from_finding_id} <-> {e.to_finding_id}")
check("at least one real same-subject TEMPORAL_PROXIMITY edge formed", len(temporal_edges) > 0)
if temporal_edges:
    e = temporal_edges[0]
    subj_a = e.from_finding_id.split("|")[1]
    subj_b = e.to_finding_id.split("|")[1]
    check("both ends of a TEMPORAL_PROXIMITY edge share the same subject",
          subj_a == subj_b, f"{subj_a} vs {subj_b}")

print("\n=== VERIFY: SAME_DRUG_CLASS connects findings sharing a real CMCLAS ===")
drug_edges = [e for e in fg.edges if e.relation == "SAME_DRUG_CLASS"]
print(f"  real SAME_DRUG_CLASS edges found: {len(drug_edges)}")
check("at least one real SAME_DRUG_CLASS edge formed", len(drug_edges) > 0)
if drug_edges:
    e = drug_edges[0]
    n1, n2 = fg.nodes[e.from_finding_id], fg.nodes[e.to_finding_id]
    classes_1, classes_2 = fg._cmclas_of(n1), fg._cmclas_of(n2)
    print(f"  {e.from_finding_id}: CMCLAS={classes_1}")
    print(f"  {e.to_finding_id}: CMCLAS={classes_2}")
    check("the two findings genuinely share a CMCLAS", bool(classes_1 & classes_2))

print("\n=== VERIFY: SHARED_PROTOCOL_SECTION only connects DIFFERENT codes (not a same-code clique) ===")
section_edges = [e for e in fg.edges if e.relation == "SHARED_PROTOCOL_SECTION"]
print(f"  SHARED_PROTOCOL_SECTION edges: {len(section_edges)} "
      f"(0 expected here -- no two DIFFERENT codes among HYS_LAW/PROHIBITED_CONMED/"
      f"VISIT_OUT_OF_WINDOW/INCLUSION_VIOLATION share a topic in this fed set)")
check("no same-code-to-same-code SHARED_PROTOCOL_SECTION edge exists",
      not any(e.from_finding_id.split("|")[0] == e.to_finding_id.split("|")[0]
             for e in section_edges))
check("the fix actually mattered: same-code reading would have produced 11254+ edges here",
      len(fg.edges) < 100, f"got {len(fg.edges)} total edges")

print("\n=== VERIFY: never crashes on an empty graph ===")
empty = FindingGraph(g)
esnap = empty.snapshot()
check("empty graph returns empty lists, not an error",
      esnap == {"nodes": [], "edges": [], "clusters": [], "centrality": {}})

print("\n=== VERIFY: SHARED_PROTOCOL_SECTION fires when a DIFFERENT code shares the topic ===")
excl_ans = atlas.answer(Question(id="e", kind="finding", text="", params={"code": "EXCLUSION_VIOLATION"}))
before_edges = len(fg.edges)
fg.observe_all(excl_ans.findings, cut=None)
new_section_edges = [e for e in fg.edges if e.relation == "SHARED_PROTOCOL_SECTION"]
print(f"  adding {len(excl_ans.findings)} real EXCLUSION_VIOLATION finding(s) "
      f"(topic 'eligibility', same as INCLUSION_VIOLATION)")
print(f"  SHARED_PROTOCOL_SECTION edges now: {len(new_section_edges)}")
check("EXCLUSION_VIOLATION connects to the existing INCLUSION_VIOLATION nodes "
      "(both eligibility)", len(new_section_edges) > 0)
if new_section_edges:
    e = new_section_edges[0]
    codes = {e.from_finding_id.split("|")[0], e.to_finding_id.split("|")[0]}
    print(f"  e.g. {e.from_finding_id} <-> {e.to_finding_id}")
    check("the connected pair really is two DIFFERENT codes",
          codes == {"INCLUSION_VIOLATION", "EXCLUSION_VIOLATION"})

print("\n=== VERIFY: re-observing the same finding is a no-op (idempotent) ===")
before = len(fg.nodes)
fg.observe_all(excl_ans.findings, cut=None)     # same findings again
check("observing the same findings twice does not duplicate nodes", len(fg.nodes) == before)


print("\n=== patient-reported data maps ONTO the subject, not into new nodes ===")
# An earlier version made a new node per utterance, which grew a constellation
# of disconnected dots beside the subject and said nothing. What a person
# reports is more of the same subject's story, so it folds into one node.
fg3 = FindingGraph(g)
hys3 = atlas.answer(Question(id="h", kind="finding", text="",
                             params={"code": "HYS_LAW_CANDIDATE"}))
fg3.observe_all(hys3.findings, cut=None)
seeded = len(fg3.nodes)
SUBJ = "042-S07-001"
utterances = [
    {"usubjid": SUBJ, "seq": 1, "term": "headache",
     "raw_quote": "my head hurts", "pro_type": "SYMPTOM"},
    {"usubjid": SUBJ, "seq": 2, "term": "ibuprofen",
     "raw_quote": "taking ibuprofen", "pro_type": "CONMED_MENTION"},
    {"usubjid": SUBJ, "seq": 3, "term": "jaundice",
     "raw_quote": "my eyes look yellow", "pro_type": "SYMPTOM"},
]
for u in utterances:
    fg3.observe_pro_record(u, cut=None)

pro_nodes = [n for n in fg3.nodes.values() if n.code == "PATIENT_REPORTED"]
print(f"  {len(utterances)} utterances -> {len(pro_nodes)} patient-reported node(s)")
check("three utterances produce ONE node, not three", len(pro_nodes) == 1)
check("total node count grew by exactly one", len(fg3.nodes) == seeded + 1)

node = pro_nodes[0]
check("the node belongs to the subject spoken to", node.usubjid == SUBJ)
check("it cites every PRO record", len(node.evidence) == 3)
check("it is marked as derived from PRO", node.derived_from == ["PRO"])

snap3 = fg3.snapshot()
rendered = next(n for n in snap3["nodes"] if n["code"] == "PATIENT_REPORTED")
terms = [r["term"] for r in rendered["reported"]]
quotes = [r["quote"] for r in rendered["reported"]]
print(f"  accumulated terms: {terms}")
check("every reported term is carried on the one node",
      terms == ["headache", "ibuprofen", "jaundice"])
check("each keeps its verbatim quote — a PRO record without one is "
      "indistinguishable from a fabricated one",
      quotes == ["my head hurts", "taking ibuprofen", "my eyes look yellow"])

linked = [e for e in fg3.edges
          if node.finding_id in (e.from_finding_id, e.to_finding_id)]
targets = {e.to_finding_id for e in linked} | {e.from_finding_id for e in linked}
check("it links to that subject's existing Hy's law finding",
      f"HYS_LAW_CANDIDATE|{SUBJ}" in targets, str(sorted(targets)))
check("it does not link to other subjects' findings",
      all(fg3.nodes[t].usubjid == SUBJ for t in targets if t in fg3.nodes))

print("\n=== a second subject speaking gets their own node ===")
fg3.observe_pro_record({"usubjid": "042-S05-003", "seq": 1, "term": "nausea",
                        "raw_quote": "feeling sick", "pro_type": "SYMPTOM"}, cut=None)
pro_nodes = [n for n in fg3.nodes.values() if n.code == "PATIENT_REPORTED"]
check("two subjects -> two patient-reported nodes", len(pro_nodes) == 2)
check("each node holds only its own subject's words",
      all(len(fg3.reported_terms[n.finding_id]) == (3 if n.usubjid == SUBJ else 1)
          for n in pro_nodes))

print("\n" + ("ALL T1.28 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
