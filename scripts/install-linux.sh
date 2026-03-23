#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_SOURCE="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE="${1:-${DEFAULT_SOURCE}}"
FORCE_FLAG="${FORCE_FLAG:---force}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

INSTALL_ARGS=(tool install)
if [[ -n "${FORCE_FLAG}" ]]; then
  INSTALL_ARGS+=("${FORCE_FLAG}")
fi

if [[ -e "${SOURCE}" ]]; then
  RESOLVED_SOURCE="$(cd "${SOURCE}" && pwd)"
  INSTALL_ARGS+=(--editable "${RESOLVED_SOURCE}")
else
  INSTALL_ARGS+=("${SOURCE}")
fi

echo "Running: uv ${INSTALL_ARGS[*]}"
uv "${INSTALL_ARGS[@]}"

echo "Updating shell PATH integration..."
uv tool update-shell

echo
echo "Installed commands:"
echo "  pcs"
echo "  pcs-bootstrap"
echo
echo "Open a new shell if the commands are not available immediately."
