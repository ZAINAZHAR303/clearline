#!/usr/bin/env bash
# Verify Clearline's Meterless engine implementations against the upstream
# conformance suites.
#
#   bash scripts/conformance.sh            # both engines
#   bash scripts/conformance.sh markovian  # one
#
# The hackathon requires at least one Meterless engine implemented in a working
# feature and demonstrated by a passing test. These are those tests, run
# against Meterless's own suites rather than ones we wrote.
#
#   markovian  bounds the control-chain walk  (clearline/walker.py)
#   hmem       holds reviewer corrections     (clearline/memory.py)
#
# The upstream repo is fetched into engines/.meterless-upstream (gitignored)
# rather than vendored, so the check always runs against the current spec and
# this repo carries no copy of someone else's code. Apache-2.0.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/engines/.meterless-upstream"
REPO="https://github.com/Meterless/Meterless.git"
WANTED="${1:-all}"

if [[ ! -d "$UPSTREAM/.git" ]]; then
  echo "fetching the Meterless engine specs (once)..."
  git clone --depth 1 --quiet "$REPO" "$UPSTREAM"
fi

run_engine() {
  local engine="$1" env_var="$2"
  local impl="$ROOT/engines/$engine/src/index.ts"
  local runner="$UPSTREAM/engines/$engine/conformance/runner.ts"

  if [[ ! -f "$impl" ]]; then
    echo "SKIP $engine: no implementation at $impl"
    return 0
  fi
  if [[ ! -f "$runner" ]]; then
    echo "FAIL $engine: upstream runner missing at $runner"
    echo "     try: rm -rf '$UPSTREAM' && bash scripts/conformance.sh"
    return 1
  fi

  cd "$ROOT/engines/$engine"
  if [[ ! -x node_modules/.bin/tsx ]]; then
    echo "installing tsx for $engine (once)..."
    npm install --silent
  fi

  # Windows paths need forward slashes, per the suites' READMEs.
  env "$env_var=$(echo "$impl" | sed 's|\\|/|g')" ./node_modules/.bin/tsx "$runner"
}

status=0
case "$WANTED" in
  markovian) run_engine markovian MARKOVIAN_IMPL || status=1 ;;
  hmem)      run_engine hmem HMEM_IMPL || status=1 ;;
  all)
    run_engine markovian MARKOVIAN_IMPL || status=1
    run_engine hmem HMEM_IMPL || status=1
    ;;
  *) echo "usage: bash scripts/conformance.sh [markovian|hmem|all]" >&2; exit 2 ;;
esac

echo
if [[ $status -eq 0 ]]; then
  echo "All requested Meterless engine suites passed."
else
  echo "At least one suite failed." >&2
fi
exit $status
