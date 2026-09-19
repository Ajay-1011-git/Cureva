"""Helper for T3.5: run one real cycle in whatever repo tree it is invoked from
and print the ReviewReport as canonical JSON.

Used twice — once against the pre-change `stage2/crew.py` from git, once
against the current one — so the two can be diffed. It is a separate process on
purpose: importing two versions of the same module into one interpreter is a
good way to prove nothing at all.

    python tests/_t3_5_runner.py <repo_root> <cut> <state_dir>
"""
import json
import logging
import re
import sys
from pathlib import Path

repo, cut, state = sys.argv[1], int(sys.argv[2]), sys.argv[3]
sys.path.insert(0, repo)
logging.basicConfig(level=logging.CRITICAL)

from stage1.atlas import Atlas, StudyGraph          # noqa: E402
from stage2.crew import ReviewCrew                  # noqa: E402

DATA = str(Path(repo) / "hackathon-data")
crew = ReviewCrew(DATA, Atlas(StudyGraph(DATA)), state_dir=state)
report = crew.run_cycle(cut, crew.graph.protocol_version_at(cut))

payload = report.model_dump(mode="json")
# Three fields are nondeterministic by design and are normalised rather than
# compared: a uuid4 trace id, a wall-clock timestamp, and elapsed milliseconds.
# Everything else — every finding, escalation, query, deviation, and every
# trace line's node/decision_type/summary/evidence — is compared verbatim.
payload["duration_ms"] = "<normalised>"
for line in payload.get("trace", []):
    line["trace_id"] = "<normalised>"
    line["timestamp"] = "<normalised>"
    line["duration_ms"] = "<normalised>"
    # EXECUTE's own summary interpolates the cycle's elapsed milliseconds into
    # its text ("... in 112ms"). That is the same nondeterministic quantity as
    # duration_ms above, just inside a string, so it is normalised the same
    # way. Nothing else in any summary is touched.
    line["summary"] = re.sub(r"\bin \d+ms\b", "in <normalised>ms", line["summary"])
print(json.dumps(payload, indent=2, sort_keys=True))
