#!/usr/bin/env bash
# Serve data/sample to Zetaris.
#
# Zetaris cannot read a file sitting on your host filesystem. The documented
# answer is object storage such as S3, but you do not need an AWS account: put
# the files on the same Docker network and register them as REST tables, which
# reuses the pattern already proven by the PokeAPI recipe.
#
# This touches nothing in the Zetaris bundle -- no compose edits, no volumes on
# their containers. It also works offline, which keeps SAMPLE_MODE honest.
#
#   bash scripts/sidecar.sh          start (or restart) the sidecar
#   bash scripts/sidecar.sh stop     remove it
#
# Run from the repo root. On Windows run it from the Ubuntu/WSL shell, where
# docker is on PATH.

set -euo pipefail

NAME=clearline-data
DATA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/sample"

if [[ "${1:-start}" == "stop" ]]; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  echo "removed $NAME"
  exit 0
fi

if [[ ! -f "$DATA_DIR/vendor_master.json" ]]; then
  echo "error: $DATA_DIR/vendor_master.json missing" >&2
  echo "run:   python scripts/gen_vendor_master.py" >&2
  exit 1
fi

# The Zetaris compose project creates its own network; find it rather than
# hardcoding a name that differs between bundle versions.
NETWORK="$(docker network ls --format '{{.Name}}' | grep -i zetaris | head -1 || true)"
if [[ -z "$NETWORK" ]]; then
  echo "error: no docker network matching 'zetaris' found." >&2
  echo "is the platform running?  cd ~/zetaris-platform && docker compose ps" >&2
  exit 1
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --network "$NETWORK" \
  -v "$DATA_DIR:/usr/share/nginx/html:ro" \
  nginx:alpine >/dev/null

echo "sidecar '$NAME' on network '$NETWORK'"
echo "serving $(ls "$DATA_DIR" | tr '\n' ' ')"
echo
echo "Zetaris can now reach:"
echo "  http://$NAME/vendor_master.json"
echo "  http://$NAME/sanctions_sample.json"
echo
echo "verify from inside the network:"
echo "  docker run --rm --network $NETWORK curlimages/curl -s -o /dev/null -w '%{http_code}\\n' http://$NAME/vendor_master.json"
