#!/usr/bin/env bash
# Cureva Stage 1 — one script to run everything built so far.
#
# Usage:
#   ./run_stage1.sh              same as `test`
#   ./run_stage1.sh test         harness + full test suite (default)
#   ./run_stage1.sh quick        harness + graded-path tests only (T1.1-T1.22,
#                                 skips the live Sarvam/Groq/backend calls —
#                                 fast, no network, no API cost)
#   ./run_stage1.sh harness      just run_local_harness.py, nothing else
#   ./run_stage1.sh serve        start backend (:8000) + frontend (:5173)
#                                 together for manual browsing; Ctrl-C stops both
#   ./run_stage1.sh backend      start only the FastAPI backend
#   ./run_stage1.sh frontend     start only the Vite dev server
#
# Run from the repo root (where this file lives).

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=".venv/bin"
PY="$VENV/python"
PASS=0
FAIL=0
FAILED_NAMES=()

# ---------------------------------------------------------------- helpers
c_green() { printf '\033[32m%s\033[0m\n' "$1"; }
c_red()   { printf '\033[31m%s\033[0m\n' "$1"; }
c_dim()   { printf '\033[2m%s\033[0m\n' "$1"; }
header()  { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

check_venv() {
  if [ ! -x "$PY" ]; then
    c_red "No virtualenv found at .venv/. Create one first:"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r requirements.txt"
    exit 1
  fi
}

run_one() {
  # run_one <label> <command...>
  local label="$1"; shift
  printf '  %-42s ' "$label"
  if "$@" > "/tmp/cureva_run_$$_$(echo "$label" | tr -c 'a-zA-Z0-9' '_').log" 2>&1; then
    c_green "PASS"
    PASS=$((PASS+1))
  else
    c_red "FAIL"
    FAIL=$((FAIL+1))
    FAILED_NAMES+=("$label")
  fi
}

run_harness() {
  header "Local harness (the graded path — Atlas/StudyGraph, no network)"
  "$PY" run_local_harness.py --module stage1.atlas --data hackathon-data
  local rc=$?
  if [ $rc -eq 0 ]; then
    c_green "Harness: PASS on the public set"
  else
    c_red "Harness: DOES NOT PASS — see output above"
  fi
  return $rc
}

# Tests that never touch the network — the graded path plus its isolation
# proofs (T1.1-T1.22). Safe to run with zero API keys configured.
GRADED_TESTS=(
  tests/test_t1_1_parsers.py
  tests/test_t1_2_standardise.py
  tests/test_t1_3_indices.py
  tests/test_t1_4_build.py
  tests/test_t1_5_patient360.py
  tests/test_t1_6_dispatch.py
  tests/test_t1_7_count.py
  tests/test_t1_8_lookup.py
  tests/test_t1_9_framework.py
  tests/test_t1_10_hys_law.py
  tests/test_t1_11_13_detectors.py
  tests/test_t1_14_visit_window.py
  tests/test_t1_15_eligibility.py
  tests/test_t1_16_prohibited_conmed.py
  tests/test_t1_17_dosing.py
  tests/test_t1_18_missing_exposure.py
  tests/test_t1_19_unit_mismatch.py
  tests/test_t1_20_immunity.py
  tests/test_t1_21_calibration.py
  tests/test_t1_22_zero_pro.py
)

# Tests that make REAL calls against Sarvam/Groq/the local backend — need a
# working .env and (for test_t1_29) will spin up a TestClient in-process.
LIVE_TESTS=(
  tests/test_t1_24_sarvam_pool.py
  tests/test_t1_25_sarvam_client_live.py
  tests/test_t1_26_groq_client_live.py
  tests/test_t1_27_pro_writer.py
  tests/test_t1_28_finding_graph.py
  tests/test_t1_29_backend_live.py
)

run_tests() {
  # run_tests <header label> <test-file> [test-file...]
  # (plain args, not a nameref — /bin/bash on macOS is 3.2 and lacks `local -n`)
  local label="$1"; shift
  header "$label"
  for t in "$@"; do
    run_one "$(basename "$t")" "$PY" "$t"
    # Groq's free tier is 30 req/min; several live tests in a row (T1.25's
    # real STT/TTS calls, T1.26's ~7 live Groq calls, T1.27's PRO-writer
    # call) can trip it back-to-back. A short pause between live-test files
    # keeps a full `test` run from spuriously hitting the rate limit — this
    # is a real operational constraint, not a code bug: when it does fire,
    # groq_client.py's designed fallback path returns a valid degraded
    # response rather than crashing, which is what TRD §8 asks for.
    case "$t" in tests/test_t1_2[4-9]*) sleep 3 ;; esac
  done
}

summarize() {
  header "Summary"
  echo "  passed: $PASS   failed: $FAIL"
  if [ $FAIL -gt 0 ]; then
    c_red "  failed tests:"
    for n in "${FAILED_NAMES[@]}"; do echo "    - $n"; done
    echo
    c_dim "  full output for a failed test: /tmp/cureva_run_${$}_<name>.log"
  fi
}

# ------------------------------------------------------------------- serve
start_backend() {
  header "Starting backend — FastAPI on http://localhost:8000"
  "$VENV/uvicorn" webapp.server:app --port 8000 &
  BACKEND_PID=$!
  echo "  backend PID $BACKEND_PID"
}

start_frontend() {
  header "Starting frontend — Vite dev server on http://localhost:5173"
  # Calling the vite binary directly (not via `npm run dev`) so $! is the
  # actual vite/node process — `npm run dev &` captures npm's own wrapper
  # PID, and killing that alone leaves the real vite process running.
  ( cd webapp/frontend && ./node_modules/.bin/vite ) &
  FRONTEND_PID=$!
  echo "  frontend PID $FRONTEND_PID"
}

cleanup_serve() {
  echo
  c_dim "Stopping…"
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null
  # Belt-and-suspenders: catch anything the PID-based kill above missed
  # (a wrapped child process that didn't die with its parent).
  pkill -f "uvicorn webapp.server" 2>/dev/null
  pkill -f "vite$" 2>/dev/null
  wait 2>/dev/null
}

# -------------------------------------------------------------------- main
check_venv
MODE="${1:-test}"

case "$MODE" in
  harness)
    run_harness
    exit $?
    ;;

  quick)
    run_harness || true
    run_tests "Graded-path tests (no network, T1.1-T1.22)" "${GRADED_TESTS[@]}"
    summarize
    [ $FAIL -eq 0 ]
    exit $?
    ;;

  test)
    run_harness || true
    run_tests "Graded-path tests (no network, T1.1-T1.22)" "${GRADED_TESTS[@]}"
    run_tests "Live tests — real Sarvam/Groq/backend calls, T1.24-T1.29" "${LIVE_TESTS[@]}"
    summarize
    [ $FAIL -eq 0 ]
    exit $?
    ;;

  backend)
    start_backend
    trap cleanup_serve INT TERM
    wait "$BACKEND_PID"
    ;;

  frontend)
    start_frontend
    trap cleanup_serve INT TERM
    wait "$FRONTEND_PID"
    ;;

  serve)
    start_backend
    sleep 2
    start_frontend
    echo
    c_green "Backend:  http://localhost:8000  (try http://localhost:8000/api/health)"
    c_green "Frontend: http://localhost:5173/atlas"
    c_dim   "Ctrl-C to stop both."
    trap cleanup_serve INT TERM
    wait
    ;;

  *)
    echo "Unknown mode: $MODE"
    echo "Usage: $0 [test|quick|harness|serve|backend|frontend]"
    exit 2
    ;;
esac
