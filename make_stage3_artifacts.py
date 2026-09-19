"""Regenerate every Stage 3 submission artifact, from one real period walk.

Nothing here is hand-written. The surveillance report is the `markdown` field
of the real `SurveillanceReport` the graded call returns, and every explanation
in the decision log is a real `explain()` result read back out of the trace
file — `explain()` is called once per decision, for real, however many there
are. A plausible-looking explanation typed into a JSON file would be exactly
the fabrication this whole stage is built to make impossible.

    python make_stage3_artifacts.py
    python make_stage3_artifacts.py --cuts 1-12 --out-dir .

Outputs:
    stage3_surveillance_report.md   the readable report for the public period
    stage3_decision_log.json        every decision + its real explanation
    stage3_public.json              a score-summary row per cut, mirroring
                                    stage1_public.json / stage2_public.json
    stage3_public_trace.jsonl       the trace the explanations were read from

The trace is EXPORTED, not just referenced. `state/` is gitignored, so a
decision log pointing only at `state/stage3/trace/cycle_trace.jsonl` would
invite a reviewer to cross-check its explanations against a file that is not in
the repository — which is the one thing this log exists to make possible.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from stage1.atlas import Atlas, StudyGraph
from stage2.crew import ReviewCrew
from stage3.watch import StudyWatch

log = logging.getLogger("cureva.stage3.artifacts")


def _cut_range(spec: str) -> list[int]:
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(c) for c in spec.split(",") if c.strip()]


def build(data_dir: str, cuts: list[int], state_dir: str) -> dict:
    """Walk the period once; everything else is read off that one walk."""
    started = time.perf_counter()
    graph = StudyGraph(data_dir)
    crew = ReviewCrew(data_dir, Atlas(graph), state_dir=state_dir)
    watch = StudyWatch(data_dir, crew, state_dir=state_dir)
    report = watch.run_period(cuts=cuts)
    walk_s = time.perf_counter() - started

    # --- the decision log: one entry per decision, each with its REAL
    # explanation. `explain()` is called here, once per decision, and reads the
    # trace from disk every time. It is not cached, not batched, and not
    # summarised: what lands in the file is what the graded method returns.
    entries, missing = [], []
    explain_started = time.perf_counter()
    for decision in report.decisions:
        explanation = watch.explain(decision.id)
        if not explanation.evidence_lines:
            missing.append(decision.id)
        entries.append({
            "decision": decision.model_dump(mode="json"),
            "explanation": explanation.model_dump(mode="json"),
            "artifact": (watch.artifacts[decision.id].model_dump(mode="json")
                         if decision.id in watch.artifacts else None),
            "forecast_context": (
                watch.escalation_forecasts[decision.id].model_dump(mode="json")
                if decision.id in watch.escalation_forecasts else None),
        })
    explain_s = time.perf_counter() - explain_started

    escalations = crew.memory.escalations
    states: dict[str, int] = {}
    for record in escalations.values():
        key = "send_failed" if record.send_failed else record.state
        states[key] = states.get(key, 0) + 1

    decision_log = {
        "period": report.period,
        "cuts": report.cuts,
        "generated_by": "make_stage3_artifacts.py — every explanation is a real "
                        "explain() call against the JSONL trace on disk",
        "trace_files": [str(p) for p in watch._trace_paths()],
        "trace_exported_to": "stage3_public_trace.jsonl",
        "how_to_verify": (
            "Pick any entry. grep its decision id in stage3_public_trace.jsonl; "
            "the lines that come back are the lines in its evidence_lines, in "
            "the same order. Nothing was regenerated to produce them."),
        "counts": {
            "decisions": len(entries),
            "with_real_explanation": len(entries) - len(missing),
            "without_explanation": len(missing),
            "with_drafted_artifact": sum(1 for e in entries if e["artifact"]),
            "with_forecast_context": sum(1 for e in entries if e["forecast_context"]),
            "escalations_total": len(escalations),
            "escalation_states": states,
        },
        "explain_seconds": round(explain_s, 2),
        "entries": entries,
    }

    public = {
        "stage": 3,
        "period": report.period,
        "cuts": report.cuts,
        "walk_seconds": round(walk_s, 2),
        "per_cut": [
            {"cut": r.cut, "protocol_version": r.protocol_version,
             "findings": len(r.findings), "deviations": len(r.deviations),
             "queries": len(r.queries), "trace_lines": len(r.trace)}
            for r in watch.reports
        ],
        "signals_by_code": _by_code(report.signals),
        "escalation_states": states,
        "superseded": [e.model_dump(mode="json") for e in watch.memory.superseded],
        "kris": [k.model_dump(mode="json") for k in report.kris],
        "budget": report.budget,
        # Measured in ITS OWN state directory. Run against the shipped one it
        # walks the period two further times, appending to the very trace file
        # the decision log's explanations were read from — so the log would
        # cite nine lines for a decision the file then showed twenty-three of.
        # The artifact and the evidence behind it have to agree, and a
        # measurement that changes what it measures is not a measurement.
        "idempotency": _idempotency(data_dir, cuts, str(Path(state_dir).parent
                                                        / "stage3_idempotency")),
    }
    return {"report": report, "decision_log": decision_log, "public": public,
            "watch": watch}


def _by_code(findings) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        out[f.code] = out.get(f.code, 0) + 1
    return dict(sorted(out.items()))


def _idempotency(data_dir: str, cuts: list[int], state_dir: str) -> dict:
    """Walk the period twice in a throwaway directory and compare.

    The claim `stage3_public.json` makes about idempotency is measured here
    rather than asserted, for the same reason every other number in these
    artifacts is produced by running something. It gets its own state
    directory so that measuring it leaves the shipped trace untouched.
    """
    import shutil
    shutil.rmtree(state_dir, ignore_errors=True)
    graph = StudyGraph(data_dir)
    crew = ReviewCrew(data_dir, Atlas(graph), state_dir=state_dir)
    watch = StudyWatch(data_dir, crew, state_dir=state_dir)
    first = watch.run_period(cuts=cuts)
    before = (len(crew.memory.escalations), len(crew.memory.queries_raised))
    watch.run_period(cuts=cuts)
    after = (len(crew.memory.escalations), len(crew.memory.queries_raised))
    return {
        "escalations_after_first_walk": before[0],
        "escalations_after_second_walk": after[0],
        "queries_after_first_walk": before[1],
        "queries_after_second_walk": after[1],
        "new_escalations_on_re_walk": after[0] - before[0],
        "new_queries_on_re_walk": after[1] - before[1],
        "holds": after == before,
    }


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="hackathon-data")
    ap.add_argument("--cuts", default="1-12")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--state-dir", default="state/stage3")
    args = ap.parse_args()

    cuts = _cut_range(args.cuts)
    out = Path(args.out_dir)
    built = build(args.data, cuts, args.state_dir)
    report, log_payload, public = (built["report"], built["decision_log"],
                                   built["public"])

    paths = {
        "surveillance_report": out / "stage3_surveillance_report.md",
        "decision_log": out / "stage3_decision_log.json",
        "public": out / "stage3_public.json",
        "trace": out / "stage3_public_trace.jsonl",
    }
    # Copy the trace out of the gitignored state directory so the decision
    # log's explanations can actually be checked against it from a clone.
    source_traces = built["watch"]._trace_paths()
    paths["trace"].write_text("".join(p.read_text() for p in source_traces))
    paths["surveillance_report"].write_text(report.markdown)
    paths["decision_log"].write_text(json.dumps(log_payload, indent=2, default=str))
    paths["public"].write_text(json.dumps(public, indent=2, default=str))

    counts = log_payload["counts"]
    print(f"period            : {report.period}")
    print(f"decisions         : {counts['decisions']}")
    print(f"  with a real explanation : {counts['with_real_explanation']}")
    print(f"  without one             : {counts['without_explanation']}")
    print(f"  with drafted paperwork  : {counts['with_drafted_artifact']}")
    print(f"  with forecast context   : {counts['with_forecast_context']}")
    print(f"escalation states : {counts['escalation_states']}")
    print(f"idempotency holds : {public['idempotency']['holds']} "
          f"(new escalations {public['idempotency']['new_escalations_on_re_walk']}, "
          f"new queries {public['idempotency']['new_queries_on_re_walk']})")
    print()
    for name, path in paths.items():
        size = path.stat().st_size
        print(f"  {name:<22} {path}  ({size:,} bytes)")
    return 0 if counts["without_explanation"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
