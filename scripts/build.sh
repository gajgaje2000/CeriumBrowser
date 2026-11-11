#!/usr/bin/env bash
# Cerium — Unified Build Entry Point
# (scripts/build.sh)
#
# Usage:
#   ./scripts/build.sh [android|windows|windows_x64|windows_arm64|all] [--dry-run] [--release]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET="${1:-android}"
shift || true

PASSTHROUGH_ARGS=("$@")

T_START=$(date +%s)

echo "========================================================"
echo " Starting Cerium Browser Build"
echo " Target : ${TARGET}"
echo " Time   : $(date -u)"
echo "========================================================"

build_android() {
  echo ""
  echo ">>> Compiling Android Target (arm64)..."
  bash "${REPO_ROOT}/scripts/platforms/android/build.sh" --arch=arm64 "${PASSTHROUGH_ARGS[@]}"
}

build_windows_x64() {
  echo ""
  echo ">>> Compiling Windows Target (x64)..."
  bash "${REPO_ROOT}/scripts/platforms/windows/build.sh" --arch=x64 "${PASSTHROUGH_ARGS[@]}"
}

build_windows_arm64() {
  echo ""
  echo ">>> Compiling Windows Target (arm64)..."
  bash "${REPO_ROOT}/scripts/platforms/windows/build.sh" --arch=arm64 "${PASSTHROUGH_ARGS[@]}"
}

case "${TARGET}" in
  android|arm64)
    build_android
    ;;
  windows|windows_x64|win|win_x64)
    build_windows_x64
    ;;
  windows_arm64|win_arm64)
    build_windows_arm64
    ;;
  all)
    build_android
    build_windows_x64
    ;;
  *)
    echo "ERROR: Unknown build target: '${TARGET}'. Supported: android, windows, windows_x64, windows_arm64, all" >&2
    exit 1
    ;;
esac

T_END=$(date +%s)
ELAPSED=$((T_END - T_START))
MINS=$((ELAPSED / 60))
SECS=$((ELAPSED % 60))

echo ""
echo "========================================================"
echo " Cerium Browser Build Completed Successfully"
echo " Elapsed: ${MINS}m ${SECS}s"
echo "========================================================"
