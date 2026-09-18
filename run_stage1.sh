#!/usr/bin/env bash
# =============================================================================
# Cureva Stage 1 — one script to run, check and demo everything.
#
#   ./run_stage1.sh                 doctor + demo + harness + tests  (default)
#   ./run_stage1.sh doctor          check the environment is set up, fix nothing
#   ./run_stage1.sh setup           create .venv and install everything
#   ./run_stage1.sh demo            run stage1/atlas.py's own entry point
#   ./run_stage1.sh harness         score against the public question bank
#   ./run_stage1.sh test            harness + the full gating test suite
#   ./run_stage1.sh quick           harness + offline tests only (no network)
#   ./run_stage1.sh probe           live Sarvam/Groq probes (reports, never gates)
#   ./run_stage1.sh serve           backend :8000 + frontend :5173, Ctrl-C stops
#   ./run_stage1.sh backend         backend only
#   ./run_stage1.sh frontend        frontend only
#   ./run_stage1.sh artifacts       regenerate graph_stats.json + stage1_public.json
#
# Run from the repo root. `doctor` tells you what's missing before anything
# else fails confusingly.
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
    red   "  MISS  python      no virtualenv at .venv/  →  ./run_stage1.sh setup"
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
      red   "  MISS  packages   $missing  →  ./run_stage1.sh setup"
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

  if [ -d webapp/frontend/node_modules ]; then
    green "  ok    frontend    node_modules installed"
  else
    amber "  note  frontend    node_modules missing → ./run_stage1.sh setup (needed only for serve)"
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
  tests/test_t1_33_clinical_intake.py
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

# ------------------------------------------------------------------ serve
start_backend() {
  header "Backend — http://localhost:$BACKEND_PORT"
  "$VENV/uvicorn" webapp.server:app --port "$BACKEND_PORT" &
  BACKEND_PID=$!
}
start_frontend() {
  header "Frontend — http://localhost:$FRONTEND_PORT"
  # the vite binary directly, so $! is the real process (npm wraps a child
  # that a kill on npm's own PID would leave running)
  ( cd webapp/frontend && ./node_modules/.bin/vite --port "$FRONTEND_PORT" ) &
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
  red "No virtualenv at .venv/ — run:  ./run_stage1.sh setup"
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
    dim "Next:  ./run_stage1.sh serve   →  http://localhost:$FRONTEND_PORT/atlas"
    [ $FAIL -eq 0 ]; exit $?
    ;;

  backend)  start_backend;  trap cleanup_serve INT TERM; wait "$BACKEND_PID" ;;
  frontend) start_frontend; trap cleanup_serve INT TERM; wait "$FRONTEND_PID" ;;

  serve)
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
