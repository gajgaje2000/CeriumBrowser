#!/usr/bin/env bash
# Cerium — Patch Creation Helper
# (scripts/core/create-patch.sh)
#
# Generates a clean git patch from working directory modifications
# and places it in the appropriate patches/ subdirectory.
#
# Usage:
#   ./scripts/core/create-patch.sh <source-repo-dir> <common|android|desktop> <patch-filename>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SOURCE_DIR="${1:-}"
TARGET_OS="${2:-}"
PATCH_NAME="${3:-}"

if [[ -z "${SOURCE_DIR}" || -z "${TARGET_OS}" || -z "${PATCH_NAME}" ]]; then
  echo "Usage: $0 <source-repo-dir> <common|android|desktop> <patch-filename.patch>" >&2
  exit 1
fi

if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
  echo "ERROR: ${SOURCE_DIR} is not a git repository." >&2
  exit 1
fi

case "${TARGET_OS}" in
  common|android|desktop) ;;
  *)
    echo "ERROR: Invalid target OS '${TARGET_OS}'. Must be: common, android, or desktop." >&2
    exit 1
    ;;
esac

[[ "${PATCH_NAME}" != *.patch ]] && PATCH_NAME="${PATCH_NAME}.patch"
OUTPUT_PATH="${REPO_ROOT}/patches/${TARGET_OS}/${PATCH_NAME}"

mkdir -p "$(dirname "${OUTPUT_PATH}")"

echo "Generating patch from ${SOURCE_DIR}..."
git -C "${SOURCE_DIR}" diff --no-prefix HEAD > "${OUTPUT_PATH}"

if [[ ! -s "${OUTPUT_PATH}" ]]; then
  echo "WARNING: No changes detected in ${SOURCE_DIR}. Patch is empty." >&2
  rm -f "${OUTPUT_PATH}"
  exit 1
fi

echo " [OK] Successfully created patch at: ${OUTPUT_PATH}"
echo "      Remember to document it in patches/patches.yaml!"
