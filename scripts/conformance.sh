#!/usr/bin/env bash
# Verify Clearline's Markovian engine against the Meterless conformance suite.
#
#   bash scripts/conformance.sh
#
# The hackathon requires at least one Meterless engine implemented in a working
# feature and demonstrated by a passing test. This is that test, run against
# the upstream suite rather than one we wrote ourselves.
#
# The upstream repo is fetched into engines/.meterless-upstream (gitignored)
# rather than vendored, so this repo carries no copy of someone else's code and
# the check always runs against the current spec. Apache-2.0.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM="$ROOT/engines/.meterless-upstream"
IMPL="$ROOT/engines/markovian/src/index.ts"
REPO="https://github.com/Meterless/Meterless.git"

if [[ ! -f "$IMPL" ]]; then
  echo "error: implementation not found at $IMPL" >&2
  exit 1
fi

if [[ ! -d "$UPSTREAM/.git" ]]; then
  echo "fetching the Meterless engine specs (once)..."
  git clone --depth 1 --quiet "$REPO" "$UPSTREAM"
fi

RUNNER="$UPSTREAM/engines/markovian/conformance/runner.ts"
if [[ ! -f "$RUNNER" ]]; then
  echo "error: conformance runner not found at $RUNNER" >&2
  echo "       try: rm -rf '$UPSTREAM' && bash scripts/conformance.sh" >&2
  exit 1
fi

cd "$ROOT/engines/markovian"
if [[ ! -x node_modules/.bin/tsx ]]; then
  echo "installing tsx (once)..."
  npm install --silent
fi

# Windows paths need forward slashes, per the suite's README.
MARKOVIAN_IMPL="$(echo "$IMPL" | sed 's|\\|/|g')" \
  exec ./node_modules/.bin/tsx "$RUNNER"
