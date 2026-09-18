"""Score yourself against the public questions, using the same rubric as the
hidden grader.

    python run_local_harness.py --module stage1.atlas
    python run_local_harness.py --module stage1.atlas --questions public_questions.json

What it does NOT check: the hidden questions, the mid-stage change, and whether
each record you cite genuinely supports the claim you made about it. That last
one is checked at grading time against the real study — so a clean run here does
not guarantee clean evidence there. Cite the records that show the thing.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time

from schemas import Answer, Question

LIMITS = {"seconds": 120}
GATE = {"score": 60.0, "evidence_pct": 90.0, "traps": 2}


def correctness(kind: str, expected, got) -> float:
    if isinstance(expected, bool) or isinstance(expected, int):
        return 1.0 if got == expected else 0.0
    if isinstance(expected, list):
        e, g = set(expected), set(got or [])
        if e == g:
            return 1.0
        if not e:
            return 0.0
        recall = len(e & g) / len(e)
        return 0.6 if (recall >= 0.8 and not (g - e)) else 0.0
    return 1.0 if got == expected else 0.0


def evidence_shape_ok(a: Answer) -> tuple[float, str]:
    """Local proxy for evidence validity: the references must at least be
    well formed and non-empty where the answer is non-empty."""
    if not a.evidence:
        empty = a.answer in ([], 0, None, "")
        return (1.0, "n/a") if empty else (0.0, "0/0 — non-empty answer with no evidence")
    ok = sum(1 for r in a.evidence if r.domain and (r.usubjid or r.document))
    return ok / len(a.evidence), f"{ok}/{len(a.evidence)}"


def score(rows: list[dict]) -> dict:
    tw = sum(r["weight"] for r in rows) or 1
    weighted = sum(r["score"] * r["weight"] for r in rows) / tw
    clean = sum(1 for r in rows if r["evidence_valid"] == 1.0) / max(1, len(rows)) * 100
    traps = [r for r in rows if r["kind"] == "trap"]
    traps_ok = sum(1 for r in traps if r["correct"] == 1.0)
    g = {
        "score": round(weighted * 100, 1),
        "clean_evidence_pct": round(clean, 1),
        "traps": f"{traps_ok}/{len(traps)}",
        "limits_ok": all(r["limits_ok"] for r in rows),
    }
    g["pass"] = (g["score"] >= GATE["score"] and g["clean_evidence_pct"] >= GATE["evidence_pct"]
                 and traps_ok >= min(GATE["traps"], len(traps)) and g["limits_ok"])
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", default="atlas_solution",
                    help="module exposing Atlas and StudyGraph, e.g. stage1.atlas")
    ap.add_argument("--questions", default=os.path.join(os.path.dirname(__file__), "public_questions.json"))
    ap.add_argument("--cut", type=int, default=None)
    ap.add_argument("--data", default="hackathon-data", help="the hackathon-data folder")
    ap.add_argument("--json", default=None, help="write the result here (submit this as stage1_public.json)")
    a = ap.parse_args()

    bank = json.load(open(a.questions))
    try:
        mod = importlib.import_module(a.module)
    except ImportError as e:
        print(f"could not import {a.module}: {e}\nrun from your repo root, e.g. --module stage1.atlas")
        return 2

    graph = mod.StudyGraph(a.data)
    stats = graph.build(a.cut)
    print(f"graph: {stats}\n")
    atlas = mod.Atlas(graph)

    rows = []
    for q in bank["questions"]:
        truth = q.pop("_answer")
        weight = q.pop("_weight", 1.0)
        question = Question(**q)
        t0 = time.time()
        try:
            ans = atlas.answer(question)
            ans = Answer.model_validate(ans.model_dump() if hasattr(ans, "model_dump") else ans)
            err = ""
        except Exception as e:                                   # schema-invalid or crash = zero
            ans, err = Answer(question_id=question.id, answer=None, confidence=0.0), f"{type(e).__name__}: {e}"
        elapsed = time.time() - t0
        corr = correctness(question.kind, truth, ans.answer) if not err else 0.0
        ev, ev_txt = evidence_shape_ok(ans)
        limits_ok = elapsed <= LIMITS["seconds"]
        penalty = 0.0 if corr > 0 else 0.5 * (ans.confidence ** 2)
        s = max(0.0, corr * ev - penalty) if limits_ok else 0.0
        rows.append({"id": question.id, "kind": question.kind, "weight": weight, "correct": corr,
                     "evidence_valid": ev, "evidence": ev_txt, "limits_ok": limits_ok,
                     "steps": ans.steps_used, "tokens": ans.tokens_used, "seconds": round(elapsed, 1),
                     "score": round(s, 3), "expected": truth, "got": ans.answer, "error": err})
        flag = "" if s == 1 else ("  <-- " + (err or "check this"))
        print(f"{question.id}  {question.kind:<7} score={s:.2f}  correct={corr:.1f}  "
              f"evidence={ev_txt:>7}  {elapsed:>5.1f}s{flag}")
        if s < 1 and not err:
            print(f"      expected: {str(truth)[:80]}")
            print(f"      got     : {str(ans.answer)[:80]}")

    g = score(rows)
    print("\n" + "=" * 62)
    print(f"  weighted score      {g['score']:>6} / 100      (gate: {GATE['score']})")
    print(f"  clean evidence      {g['clean_evidence_pct']:>6} %        (gate: {GATE['evidence_pct']})")
    print(f"  traps honest        {g['traps']:>6}          (gate: {GATE['traps']} of 6 hidden)")
    print(f"  limits respected    {str(g['limits_ok']):>6}")
    print(f"\n  ON THE PUBLIC SET: {'PASS' if g['pass'] else 'DOES NOT PASS'}")
    print("=" * 62)
    print("The hidden set is four times larger, includes the mid-stage change, and")
    print("checks that each record you cite really does support your claim.")

    out = {"rows": rows, "gate": g, "graph": stats}
    if a.json:
        json.dump(out, open(a.json, "w"), indent=1, default=str)
        print(f"\nwritten to {a.json}")
    return 0 if g["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
