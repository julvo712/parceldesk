#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export XDG_CONFIG_HOME="$ROOT/.secrets/coding-config"
export XDG_STATE_HOME="$ROOT/runs/coding-state"
export PATH="$ROOT/tools/bin:$PATH"
export AGENTO11Y_CONTENT_CAPTURE_MODE=metadata_only
export AGENTO11Y_AUTO_CODING_AGENT_TAGS=true
export AGENTO11Y_AUTO_CODING_AGENT_TAGS_NAMES=repo,branch
export AGENTO11Y_TAGS="team=parceldesk,project=parceldesk${AGENTO11Y_TAGS:+,$AGENTO11Y_TAGS}"
# This wrapper is intentionally local to ParcelDesk and never exports inherited
# OTLP headers, which may target another stack.
unset OTEL_EXPORTER_OTLP_HEADERS OTEL_EXPORTER_OTLP_ENDPOINT
if [[ "${1:-}" == cursor && "${2:-}" == hook ]]; then
  exec python3 "$ROOT/tools/coding/scoped_hook.py"
fi
exec "$ROOT/tools/bin/agento11y" "$@"
