#!/usr/bin/env bash
# Kept so existing notes and muscle memory keep working. The single entry
# point is now ./run.sh, which covers both the detector layer and the review
# cycle; this just forwards.
cd "$(dirname "${BASH_SOURCE[0]}")"
echo "note: ./run_stage1.sh is now ./run.sh — forwarding."
exec ./run.sh "$@"
