#!/usr/bin/env bash
# =============================================================================
# Cureva — one script to run, check and demo everything.
#
#   ./run.sh                 doctor + demo + harness + tests  (default)
#   ./run.sh doctor          check the environment is set up, fix nothing
#   ./run.sh setup           create .venv and install everything
#   ./run.sh demo            build the graph and answer a question end to end
#   ./run.sh ask "..."       answer one plain-English question, no model
#   ./run.sh harness         score against the public question bank
#   ./run.sh cycle [cut]     run one review cycle and print its report
#   ./run.sh tokens          how much Act 3 budget is left today
#   ./run.sh test            harness + the full gating test suite
#   ./run.sh quick           harness + offline tests only (no network)
#   ./run.sh probe           live Sarvam/Groq probes (report, never gate)
#   ./run.sh serve           backend :8000 + frontend :5173, Ctrl-C stops
#   ./run.sh backend         backend only
#   ./run.sh frontend        frontend only
#   ./run.sh ports           free :8000 and :5173, change nothing else
#   ./run.sh artifacts       regenerate every submission artifact
#
# Run from the repo root. `doctor` tells you what's missing before anything
# else fails confusingly. `run_stage1.sh` still works and forwards here.
# =============================================================================
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=".venv/bin"
PY="$VENV/python"
DATA="${DATA_DIR:-hackathon-data}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

PASS=0; FAIL=0; FAILED_NAMES=()
LOGDIR="$(mktemp -d "${TMPDIR:-/tmp}/cureva_run_XXXXXX")"

green() { printf '\033[32m%s\033[0m\n' "$1"; }
red()   { printf '\033[31m%s\033[0m\n' "$1"; }
amber() { printf '\033[33m%s\033[0m\n' "$1"; }
dim()   { printf '\033[2m%s\033[0m\n' "$1"; }
header(){ printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# ----------------------------------------------------------------- doctor
doctor() {
  header "Environment check"
  local problems=0

  if [ -x "$PY" ]; then
    green "  ok    python      $("$PY" --version 2>&1)"
  else
    red   "  MISS  python      no virtualenv at .venv/  →  ./run.sh setup"
    problems=$((problems+1))
  fi

  if [ -x "$PY" ]; then
    local missing=""
    for mod in pydantic fastapi uvicorn networkx requests dotenv groq; do
      "$PY" -c "import $mod" 2>/dev/null || missing="$missing $mod"
    done
    if [ -z "$missing" ]; then
      green "  ok    packages    all Python deps importable"
    else
      red   "  MISS  packages   $missing  →  ./run.sh setup"
      problems=$((problems+1))
    fi
  fi

  if [ -d "$DATA/data" ] && [ -d "$DATA/documents" ]; then
    local n; n=$(ls "$DATA"/data/*.csv 2>/dev/null | wc -l | tr -d ' ')
    green "  ok    data        $DATA ($n CSVs, documents/ present)"
  else
    red   "  MISS  data        no $DATA/data + $DATA/documents"
    problems=$((problems+1))
  fi

  # schemas.py must be byte-identical to the organiser's — a modified one
  # scores zero, so this is worth surfacing loudly.
  if [ -f schemas.py ]; then
    if grep -q "DO NOT MODIFY THIS FILE" schemas.py; then
      green "  ok    schemas.py  present, organiser header intact"
    else
      amber "  WARN  schemas.py  header missing — has it been edited?"
    fi
  else
    red   "  MISS  schemas.py"; problems=$((problems+1))
  fi

  # Credentials are optional: everything graded runs without them.
  if [ -f .env ]; then
    local has_groq has_sarvam
    has_groq=$(grep -ci "groq_api_key" .env 2>/dev/null || echo 0)
    has_sarvam=$(grep -ci "sarvam_api_key" .env 2>/dev/null || echo 0)
    if [ "$has_groq" -gt 0 ] && [ "$has_sarvam" -gt 0 ]; then
      green "  ok    .env        Groq + Sarvam keys present"
    else
      amber "  note  .env        exists, but not both keys (Act 1 will degrade)"
    fi
  else
    amber "  note  .env        absent — the graded path still runs; the avatar won't"
  fi

  if [ -x webapp/frontend/node_modules/.bin/vite ]; then
    green "  ok    frontend    node_modules installed"
  elif [ -d webapp/frontend/node_modules ]; then
    amber "  note  frontend    node_modules present but vite missing → ./run.sh setup"
  elif command -v npm >/dev/null 2>&1; then
    amber "  note  frontend    node_modules missing → ./run.sh setup (needed only for serve)"
  else
    amber "  note  frontend    node/npm not installed → brew install node, then ./run.sh setup"
    amber "                    (needed only for serve; the graded path and all tests run without it)"
  fi

  if [ -f webapp/frontend/public/avatar.glb ]; then
    green "  ok    avatar      avatar.glb present"
  else
    amber "  note  avatar      avatar.glb missing — /atlas renders without a figure"
  fi

  echo
  if [ $problems -eq 0 ]; then
    green "  Environment is ready."
  else
    red   "  $problems blocking problem(s) above."
  fi
  return $problems
}

setup() {
  header "Setup"
  [ -x "$PY" ] || { echo "  creating .venv…"; python3 -m venv .venv; }
  echo "  installing Python dependencies…"
  "$VENV/pip" install --quiet --upgrade pip
  "$VENV/pip" install --quiet -r requirements.txt && green "  Python deps installed"
  if command -v npm >/dev/null 2>&1; then
    echo "  installing frontend dependencies…"
    ( cd webapp/frontend && npm install --silent ) && green "  frontend deps installed"
  else
    amber "  npm not found — skipping frontend deps (only needed for serve)"
  fi
}

# ------------------------------------------------------------------- runs
demo() {
  header "Stage 1 entry point — python -m stage1.atlas"
  "$PY" -m stage1.atlas --data "$DATA"
}

run_harness() {
  header "Grading harness (the graded path — no network)"
  "$PY" run_local_harness.py --module stage1.atlas --data "$DATA"
  local rc=$?
  [ $rc -eq 0 ] && green "  Harness: PASS on the public set" \
                || red   "  Harness: DOES NOT PASS"
  return $rc
}

artifacts() {
  header "Regenerating submission artifacts"
  "$PY" - <<PYEOF
import json, sys
sys.path.insert(0, ".")
from stage1.atlas import StudyGraph
g = StudyGraph("$DATA"); g.build(cut=None)
json.dump(g.stats, open("graph_stats.json", "w"), indent=2, default=str)
print("  wrote graph_stats.json")
PYEOF
  "$PY" run_local_harness.py --module stage1.atlas --data "$DATA" \
        --json stage1_public.json >/dev/null 2>&1
  green "  wrote stage1_public.json"
  "$PY" make_artifacts.py
  echo
  dim  "  screenshots are not generated here — they need a browser."
  dim  "  ./run.sh serve, then capture /monitor (human gate + cycle report)."
}

run_one() {
  local label="$1"; shift
  printf '  %-42s ' "$label"
  if "$@" > "$LOGDIR/${label}.log" 2>&1; then
    green "PASS"; PASS=$((PASS+1))
  else
    red "FAIL"; FAIL=$((FAIL+1)); FAILED_NAMES+=("$label")
  fi
}

# Offline: the graded path and its isolation proofs. No network, no API keys.
OFFLINE_TESTS=(
  tests/test_t1_1_parsers.py          tests/test_t1_2_standardise.py
  tests/test_t1_3_indices.py          tests/test_t1_4_build.py
  tests/test_t1_5_patient360.py       tests/test_t1_6_dispatch.py
  tests/test_t1_7_count.py            tests/test_t1_8_lookup.py
  tests/test_t1_9_framework.py        tests/test_t1_10_hys_law.py
  tests/test_t1_11_13_detectors.py    tests/test_t1_14_visit_window.py
  tests/test_t1_15_eligibility.py     tests/test_t1_16_prohibited_conmed.py
  tests/test_t1_17_dosing.py          tests/test_t1_18_missing_exposure.py
  tests/test_t1_19_unit_mismatch.py   tests/test_t1_20_immunity.py
  tests/test_t1_21_calibration.py     tests/test_t1_22_zero_pro.py
  tests/test_t1_24_sarvam_pool.py     tests/test_t1_26_groq_contract.py
  tests/test_t1_28_finding_graph.py   tests/test_t1_32_voice_path.py
  tests/test_t1_33_clinical_intake.py  tests/test_t1_34_plain_question.py
  # The review-cycle layer and Act 3. Offline: the arbitration and
  # rate-limit tests simulate their failure modes rather than firing real
  # calls, so `quick` runs them too.
  tests/test_t2_10_trace.py           tests/test_t2_11_idempotency.py
  tests/test_t2_15_arbitration.py     tests/test_t2_17_rate_limit.py
  tests/test_evidence_integrity.py
)

# These touch the real Sarvam API or spin up the backend in-process. They are
# still deterministic assertions about OUR code — no LLM-output guessing —
# but they need credentials/network, so `quick` skips them.
NETWORKED_TESTS=(
  tests/test_t1_25_sarvam_client_live.py
  tests/test_t1_27_pro_writer.py
  tests/test_t1_29_backend_live.py
)

run_tests() {
  local label="$1"; shift
  header "$label"
  for t in "$@"; do run_one "$(basename "$t")" "$PY" "$t"; done
}

summarize() {
  header "Summary"
  echo "  passed: $PASS   failed: $FAIL"
  if [ $FAIL -gt 0 ]; then
    red "  failed:"
    for n in "${FAILED_NAMES[@]}"; do echo "    - $n"; done
    dim "  logs: $LOGDIR"
  else
    rm -rf "$LOGDIR"
  fi
}

probe() {
  header "Live probes — reporting only, never gate the build"
  dim "  (model wording and rate limits vary run to run; that is expected)"
  [ -f probes/probe_groq_live.py ] && "$PY" probes/probe_groq_live.py
}

# ------------------------------------------------------------------ cycle
review_cycle() {
  local cut="${1:-9}"
  header "Review cycle — cut $cut"
  "$PY" - "$cut" <<'PYEOF'
import sys
from collections import Counter
from stage1.atlas import Atlas, StudyGraph
from stage2 import ReviewCrew

cut = int(sys.argv[1])
graph = StudyGraph("hackathon-data")
atlas = Atlas(graph)
crew = ReviewCrew("hackathon-data", atlas)
version = graph.protocol_version_at(cut)
report = crew.run_cycle(cut=cut, protocol_version=version)

print(f"  cut {report.cut}  protocol v{report.protocol_version}  "
      f"{report.duration_ms}ms  {report.tokens_used} tokens")
print()
print(f"  findings      {len(report.findings)}")
worthy = sum(1 for v in crew.last_verdicts if v.escalate)
print(f"    escalation-worthy {worthy}")
print(f"    watch-only        {len(crew.last_verdicts) - worthy}")
print(f"  escalations   {len(report.escalations)}")
print(f"  queries       {len(report.queries)}")
print(f"  deviations    {len(report.deviations)}")
print(f"  trace lines   {len(report.trace)}")
print()
print("  findings by code")
for code, n in Counter(f.code for f in report.findings).most_common():
    print(f"    {code:26} {n}")
print()
states = Counter(r.state for r in crew.memory.escalations.values())
print(f"  escalation states   {dict(states)}")
clarified = sum(1 for r in crew.memory.escalations.values() if r.clarify_count)
print(f"  answered a clarification then resubmitted: {clarified}")
print(f"  memory              {crew.memory.sizes()}")
PYEOF
}

# -------------------------------------------------------------------- ask
ask_question() {
  local question="$*"
  if [ -z "$question" ]; then
    red "  usage: ./run.sh ask \"Which subjects meet Hy's law criteria?\""
    return 1
  fi
  header "Question"
  "$PY" - "$question" <<'PYEOF'
import sys
from stage1.atlas import Atlas, StudyGraph

graph = StudyGraph("hackathon-data")
graph.build(None)
answer = Atlas(graph).ask(sys.argv[1])

print(f"  Q: {sys.argv[1]}")
print()
value = answer.answer
if isinstance(value, list):
    print(f"  A: {', '.join(map(str, value)) if value else 'nothing — and that is the answer'}")
else:
    print(f"  A: {value}")
print(f"     confidence {answer.confidence}   evidence {len(answer.evidence)} record(s)")
for ref in answer.evidence[:8]:
    if ref.document:
        print(f"       {ref.document}" + (f" §{ref.section}" if ref.section else ""))
    else:
        print(f"       {ref.domain}:{ref.usubjid}:{'' if ref.seq is None else ref.seq}")
if len(answer.evidence) > 8:
    print(f"       ... and {len(answer.evidence) - 8} more")
print()
print(f"  {answer.text[:400]}")
PYEOF
}

# ------------------------------------------------------------------ tokens
token_budget() {
  header "Act 3 token budget"
  "$PY" - <<'PYEOF'
import os
from dotenv import load_dotenv
load_dotenv(".env")

key = os.environ.get("groq_api_key") or os.environ.get("GROQ_API_KEY")
if not key:
    print("  no Groq key configured — Act 3 cannot run at all.")
    print("  Everything else, including the whole graded path, runs without one.")
    raise SystemExit(0)

import httpx

try:
    r = httpx.post("https://api.groq.com/openai/v1/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": "openai/gpt-oss-120b",
                         "messages": [{"role": "user", "content": "hi"}],
                         "max_tokens": 1},
                   timeout=20)
except Exception as exc:
    print(f"  could not reach Groq: {type(exc).__name__}: {exc}")
    raise SystemExit(0)

h = r.headers
def show(label, remaining, limit, reset):
    if remaining is None:
        return
    try:
        left, total = int(remaining), int(limit)
        pct = 100 * left / total if total else 0
        mark = "ok  " if pct > 25 else "LOW " if pct > 5 else "GONE"
        print(f"  {mark} {label:22} {left:>7} of {total:>7} left  ({pct:.0f}%)"
              f"   resets in {reset}")
    except (TypeError, ValueError):
        pass

print(f"  request status: {r.status_code}")
show("tokens per minute", h.get("x-ratelimit-remaining-tokens"),
     h.get("x-ratelimit-limit-tokens"), h.get("x-ratelimit-reset-tokens"))
show("requests per day", h.get("x-ratelimit-remaining-requests"),
     h.get("x-ratelimit-limit-requests"), h.get("x-ratelimit-reset-requests"))

if r.status_code == 429:
    print()
    print("  RATE LIMITED RIGHT NOW:")
    print("  " + r.text[:300])

print()
print("  One deliberation costs roughly 7,200 tokens across 6 calls.")
print()
print("  The ceiling that actually ends a demo is tokens per DAY: 200,000, or")
print("  about 28 deliberations, shared by development, rehearsal and the live")
print("  run. Groq does not report daily tokens in any header — only the two")
print("  figures above — so this check CANNOT tell you how much of the day is")
print("  left. You find out by hitting it.")
print()
print("  If a debate fails with 'tokens per day', it will not recover for hours.")
print("  Rehearse it once, not repeatedly.")
PYEOF
}

# ------------------------------------------------------------------ serve
#
# A previous run that was killed with SIGKILL, closed with the terminal, or
# crashed leaves its server holding the port. The next `serve` then either
# fails to bind or -- worse for a demo -- silently starts vite on 5174 while
# the browser tab is still pointed at 5173, showing yesterday's build. So the
# ports are cleared before anything starts, not only on the way out.
free_port() {
  local port="$1" label="$2" pids
  pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
  [ -z "$pids" ] && return 0

  amber "  port $port ($label) is in use by PID(s) $(echo $pids | tr '\n' ' ')— stopping"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true

  # Give it a moment to shut down cleanly before forcing it. A dev server
  # usually goes on the first signal; anything still holding the port after
  # ~1.5s is not going to.
  local waited=0
  while [ "$waited" -lt 5 ]; do
    sleep 0.3
    pids="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null || true)"
    [ -z "$pids" ] && break
    waited=$((waited + 1))
  done

  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.3
  fi

  if lsof -ti "tcp:$port" -sTCP:LISTEN >/dev/null 2>&1; then
    red "  could not free port $port — something else is holding it"
    return 1
  fi
  green "  port $port freed"
}

free_ports() {
  header "Clearing ports"
  if ! command -v lsof >/dev/null 2>&1; then
    # No lsof: fall back to killing this project's own servers by name. Less
    # precise about the port, but it still clears what we started.
    amber "  lsof not found — stopping our own servers by name instead"
    pkill -f "uvicorn webapp.server" 2>/dev/null || true
    pkill -f "node_modules/.bin/vite" 2>/dev/null || true
    sleep 0.5
    return 0
  fi
  free_port "$BACKEND_PORT"  "backend"
  free_port "$FRONTEND_PORT" "frontend"
  # Stale servers of ours on some *other* port (a previous run with
  # BACKEND_PORT overridden) would still answer to their own name.
  pkill -f "uvicorn webapp.server" 2>/dev/null || true
  pkill -f "node_modules/.bin/vite" 2>/dev/null || true
}

start_backend() {
  header "Backend — http://localhost:$BACKEND_PORT"
  "$VENV/uvicorn" webapp.server:app --port "$BACKEND_PORT" &
  BACKEND_PID=$!
}
# Returns non-zero, with an explanation, when the frontend cannot start.
# Checked before launching rather than after, because the bare shell error
# ("./node_modules/.bin/vite: No such file or directory") names a path and not
# the thing to do about it.
check_frontend_ready() {
  if [ ! -d webapp/frontend/node_modules ]; then
    red "  frontend dependencies are not installed."
    if command -v npm >/dev/null 2>&1; then
      dim  "  Fix:  ./run.sh setup        (npm is available)"
    else
      red  "  node/npm is not installed on this machine either."
      dim  "  Fix:  brew install node   &&   ./run.sh setup"
      dim  "  The graded path and every test run without it; only serve needs it."
    fi
    return 1
  fi
  if [ ! -x webapp/frontend/node_modules/.bin/vite ]; then
    red "  node_modules exists but vite is missing or not executable."
    dim "  Fix:  ./run.sh setup      (re-installs frontend dependencies)"
    return 1
  fi
  return 0
}

start_frontend() {
  check_frontend_ready || return 1
  header "Frontend — http://localhost:$FRONTEND_PORT"
  # --strictPort so a busy port is an error rather than a silent move to
  # 5174. After free_ports() the port is ours; if it somehow is not, saying
  # so beats serving the demo from an address nobody is looking at.
  ( cd webapp/frontend && ./node_modules/.bin/vite --port "$FRONTEND_PORT" --strictPort ) &
  FRONTEND_PID=$!
}
cleanup_serve() {
  echo; dim "Stopping…"
  [ -n "${BACKEND_PID:-}" ]  && kill "$BACKEND_PID"  2>/dev/null
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null
  pkill -f "uvicorn webapp.server" 2>/dev/null
  pkill -f "node_modules/.bin/vite" 2>/dev/null
  wait 2>/dev/null
}

# ------------------------------------------------------------------- main
MODE="${1:-all}"

case "$MODE" in
  doctor)  doctor; exit $? ;;
  setup)   setup; echo; doctor; exit $? ;;
esac

# Every remaining mode needs a working venv.
if [ ! -x "$PY" ]; then
  red "No virtualenv at .venv/ — run:  ./run.sh setup"
  exit 1
fi

case "$MODE" in
  demo)      demo ;;
  harness)   run_harness; exit $? ;;
  artifacts) artifacts ;;
  probe)     probe ;;

  quick)
    run_harness || true
    run_tests "Offline tests (no network needed)" "${OFFLINE_TESTS[@]}"
    summarize; [ $FAIL -eq 0 ]; exit $?
    ;;

  test)
    run_harness || true
    run_tests "Offline tests (no network needed)" "${OFFLINE_TESTS[@]}"
    run_tests "Networked tests (real Sarvam / in-process backend)" "${NETWORKED_TESTS[@]}"
    summarize; [ $FAIL -eq 0 ]; exit $?
    ;;

  all)
    doctor || true
    demo
    run_harness || true
    run_tests "Offline tests (no network needed)" "${OFFLINE_TESTS[@]}"
    run_tests "Networked tests (real Sarvam / in-process backend)" "${NETWORKED_TESTS[@]}"
    summarize
    echo
    dim "Next:  ./run.sh serve   →  http://localhost:$FRONTEND_PORT/atlas"
    [ $FAIL -eq 0 ]; exit $?
    ;;

  backend)  free_port "$BACKEND_PORT" backend
            start_backend;  trap cleanup_serve INT TERM; wait "$BACKEND_PID" ;;
  frontend) free_port "$FRONTEND_PORT" frontend
            start_frontend; trap cleanup_serve INT TERM; wait "$FRONTEND_PID" ;;

  ports)    free_ports; exit $? ;;
  cycle)    review_cycle "${2:-9}"; exit $? ;;
  tokens)   token_budget; exit $? ;;
  ask)      shift; ask_question "$@"; exit $? ;;

  serve)
    free_ports
    # Checked before the backend starts, so a missing frontend does not leave
    # a half-served demo and an orphaned uvicorn behind.
    check_frontend_ready || exit 1
    start_backend; sleep 2; start_frontend
    echo
    green "  Backend   http://localhost:$BACKEND_PORT/api/health"
    green "  Demo page http://localhost:$FRONTEND_PORT/atlas"
    dim   "  Ctrl-C stops both."
    trap cleanup_serve INT TERM
    wait
    ;;

  *)
    echo "Unknown mode: $MODE"
    sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 2
    ;;
esac
