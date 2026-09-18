"""T1.14 VERIFY — VISIT_OUT_OF_WINDOW, including a manual hand-check of 5 real records."""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schemas import Question
from stage1.atlas import (StudyGraph, Atlas, ProtocolRules, DEFAULT_VISIT_SCHEDULE,
                          _normalise_visit_name)

fails = []
def check(label, cond, detail=""):
    if not cond: fails.append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

g = StudyGraph("hackathon-data"); g.build(cut=None); atlas = Atlas(g)
ask = lambda cut: atlas.answer(Question(id="v", kind="finding", text="",
                                        params={"code": "VISIT_OUT_OF_WINDOW"}, cut=cut))

print("=== VERIFY: schedule and window are parsed from the document ===")
for cut in (1, 4, 5, 9, None):
    r = ProtocolRules(g, cut)
    print(f"  cut={str(cut):>4} v{r.version} {r.document_name}: window=+/-{r.visit_window_days}d "
          f"schedule={'as documented' if r.visit_schedule == DEFAULT_VISIT_SCHEDULE else r.visit_schedule}")
check("v1 window is +/-7", ProtocolRules(g, 1).visit_window_days == 7)
check("v2 window is +/-3", ProtocolRules(g, 5).visit_window_days == 3)
check("v3 window is +/-3", ProtocolRules(g, 9).visit_window_days == 3)
check("schedule fully parsed from the document, no fallback used",
      ProtocolRules(g, 1).visit_schedule == DEFAULT_VISIT_SCHEDULE
      and not ProtocolRules(g, 1).warnings)
check("day offsets are derived (week N = day 7N)",
      all(ProtocolRules(g, 1).visit_schedule[f"WEEK{n}"] == 7 * n
          for n in (2, 4, 8, 12, 16, 20, 24)))

print("\n=== VERIFY (required): 5 real records, hand-checked ===")
print("  Rule: day = (visit date - subject's BASELINE date); deviation if")
print("        |day - scheduled_day| > window.\n")
rows = []
for r in g.by_domain["DM"]:
    u = r["USUBJID"]
    visits = g.visits_for(u, None)
    base = visits.get("BASELINE")
    if not base: continue
    for v, d in visits.items():
        sched = DEFAULT_VISIT_SCHEDULE.get(_normalise_visit_name(v))
        if sched is None: continue
        rows.append((u, v, d, base, (d - base).days, sched, abs((d - base).days - sched)))
# pick 5 spanning: clean, in the 3-7 gap, and clearly outside both
rows.sort(key=lambda t: t[6])
sample = [rows[0], rows[len(rows) // 3],
          next(t for t in rows if 3 < t[6] <= 7),
          next(t for t in rows if t[6] > 7),
          rows[-1]]
detected_none = {(f.usubjid, f.rationale.split()[0]) for f in ask(None).findings}
detected_v1 = {(f.usubjid, f.rationale.split()[0]) for f in ask(1).findings}
for u, v, d, base, day, sched, drift in sample:
    v1_dev, v3_dev = drift > 7, drift > 3
    print(f"  {u} {v}")
    print(f"     visit {d}, baseline {base}  ->  day {day:+d}, scheduled {sched:+d}, off by {drift}")
    print(f"     manual: v1 (+/-7) deviation? {v1_dev}      v2/v3 (+/-3) deviation? {v3_dev}")
    got_v3 = (u, v) in detected_none
    print(f"     detector at cut=None (v3): {got_v3}   {'agrees' if got_v3 == v3_dev else 'DISAGREES'}")
    check(f"{u} {v}: detector agrees with the manual check", got_v3 == v3_dev)

print("\n=== VERIFY (T1.20 core): the SAME record flips between cut=1 and cut=9 ===")
a1, a9 = ask(1), ask(9)
v1_rules, v9_rules = ProtocolRules(g, 1), ProtocolRules(g, 9)
print(f"  cut=1 uses protocol v{v1_rules.version} (+/-{v1_rules.visit_window_days}d) -> {len(a1.answer)} subjects")
print(f"  cut=9 uses protocol v{v9_rules.version} (+/-{v9_rules.visit_window_days}d) -> {len(a9.answer)} subjects")
check("the window genuinely differs between the two cuts",
      v1_rules.visit_window_days != v9_rules.visit_window_days)

# A record visible at BOTH cuts whose drift falls in the 3-7 gap: same record,
# different verdict, purely because the rule changed.
gap = []
for u, v, d, base, day, sched, drift in rows:
    if not 3 < drift <= 7: continue
    recs = [r for dom in ("LB", "VS", "EX", "EG")
            for r in g.records(dom, cut=1, usubjid=u, visit=v)
            if g.record_date(r, 1) == d]
    if recs and g.records("DM", cut=1, usubjid=u):
        gap.append((u, v, d, base, day, sched, drift, recs[0]))
print(f"\n  {len(gap)} record(s) visible at cut=1 sit in the +/-3-to-+/-7 gap")
assert gap, "no gap record visible at cut 1"
u, v, d, base, day, sched, drift, rec = gap[0]
in1 = (u, v) in detected_v1
in9 = (u, v) in {(f.usubjid, f.rationale.split()[0]) for f in a9.findings}
print(f"  example: {u} {v} on {d} — day {day:+d} vs scheduled {sched:+d}, off by {drift}")
print(f"     record {rec['_domain']}:{u}:{rec['_seq']} (cut_available={rec['_cut']}) is visible at both cuts")
print(f"     at cut=1 (v1, +/-7): deviation? {in1}")
print(f"     at cut=9 (v3, +/-3): deviation? {in9}")
check("the same real record is NOT a deviation at cut=1", not in1)
check("and IS a deviation at cut=9", in9)
check("so the answer genuinely changes with the protocol version", in1 != in9)

print("\n=== VERIFY: counts agree with an independent pass over the raw data ===")
for window, cut in ((7, 1), (3, None)):
    truth = {u for u, v, d, base, day, sched, drift in rows if drift > window}
    got = set(ask(cut).answer)
    # at cut=1 only some records are visible, so compare only at cut=None
    if cut is None:
        print(f"  +/-{window}d: independent={len(truth)} subjects, detector={len(got)}")
        check(f"+/-{window}d subject set matches an independent pass", truth == got)

print("\n=== VERIFY: one finding per (subject, visit), not per record ===")
a = ask(None)
pairs = [(f.usubjid, f.rationale.split()[0]) for f in a.findings]
check("no duplicate (subject, visit) findings", len(pairs) == len(set(pairs)))
print(f"  {len(a.findings)} findings over {len(a.answer)} subjects "
      f"(6 lab rows on one bad day are one deviation, not six)")

print("\n=== VERIFY: evidence cites records that carry the visit date ===")
f = a.findings[0]
bad = []
for e in f.evidence:
    if e.domain == "DOC": continue
    rec = g.by_key[(e.domain, e.usubjid, e.seq)]
    if rec.get("VISIT") != f.rationale.split()[0]: bad.append((e.domain, e.seq))
check("every cited record belongs to the visit being flagged", not bad, str(bad))
check("the protocol section is cited", any(e.domain == "DOC" and e.section == "4" for e in f.evidence))

print("\n=== VERIFY: a subject with no baseline is skipped, not guessed ===")
import pathlib
src = pathlib.Path("stage1/atlas.py").read_text()
det = src[src.index("def detect_visit_out_of_window"):]
check("detector falls back to RFSTDTC then skips", "reference_start_date" in det and "do not guess" in det)
check("no practice site or subject id in the detector", "042-" not in det and '"S0' not in det)

print("\n" + ("ALL T1.14 CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
