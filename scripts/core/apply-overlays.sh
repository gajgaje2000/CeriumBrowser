#!/usr/bin/env bash
# Cerium — Universal Mirror Tree Overlay Engine
# (scripts/core/apply-overlays.sh)
#
# Recursively copies file trees from overlays/<name>/ into a target repository,
# ensuring directories exist and preserving file paths directly.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

TARGET_DIR="${1:-}"
OVERLAY_NAME="${2:-brave}"

if [[ -z "${TARGET_DIR}" ]]; then
  echo "Usage: $0 <target-dir> [overlay-name]" >&2
  exit 1
fi

OVERLAY_DIR="${REPO_ROOT}/overlays/${OVERLAY_NAME}"
if [[ ! -d "${OVERLAY_DIR}" ]]; then
  echo "No overlay found at ${OVERLAY_DIR}. Skipping."
  exit 0
fi

echo "Applying '${OVERLAY_NAME}' mirror overlay to ${TARGET_DIR}..."
APPLIED_COUNT=0

while IFS= read -r -d '' src; do
  rel_path="${src#"${OVERLAY_DIR}/"}"
  dst="${TARGET_DIR}/${rel_path}"
  mkdir -p "$(dirname "${dst}")"
  cp -f "${src}" "${dst}"
  APPLIED_COUNT=$((APPLIED_COUNT + 1))
done < <(find "${OVERLAY_DIR}" -type f -print0)

echo " [OK] Successfully applied ${APPLIED_COUNT} overlay files to ${TARGET_DIR}."
