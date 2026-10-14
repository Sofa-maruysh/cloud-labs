#!/usr/bin/env bash
set -uo pipefail

ROOT_MSYS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
    ROOT_NATIVE="$(cygpath -m "$ROOT_MSYS")"
else
    ROOT_NATIVE="$ROOT_MSYS"
fi

COMPOSE_FILE="$ROOT_NATIVE/compose.yaml"
EVIDENCE="$ROOT_NATIVE/evidence"
mkdir -p "$EVIDENCE"

{
    docker version
    docker compose version
} > "$EVIDENCE/docker-version.txt" 2>&1

docker compose -f "$COMPOSE_FILE" config > "$EVIDENCE/compose-config.txt" 2>&1

set +e
bash "$ROOT_MSYS/scripts/check.sh" 2>&1 | tee "$EVIDENCE/check-run.txt"
CHECK_STATUS=${PIPESTATUS[0]}
set -e

docker compose -f "$COMPOSE_FILE" ps > "$EVIDENCE/compose-ps.txt" 2>&1
docker compose -f "$COMPOSE_FILE" images > "$EVIDENCE/images.txt" 2>&1
docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -T > "$EVIDENCE/nginx-test.txt" 2>&1
docker compose -f "$COMPOSE_FILE" logs --no-color > "$EVIDENCE/compose-logs.txt" 2>&1

echo "Материалы сохранены в $EVIDENCE"
exit "$CHECK_STATUS"

