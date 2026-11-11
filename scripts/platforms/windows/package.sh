#!/usr/bin/env bash
# Cerium — Windows Packaging Script
# Usage: ./scripts/platforms/windows/package.sh [--out-dir=<path>] [--dest-dir=<path>] [--arch=x64|arm64] [--version=<ver>] [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

WORKSPACE_DIR="${WORKSPACE_DIR:-${REPO_ROOT}/build-workspace}"
OUT_DIR="${WORKSPACE_DIR}/src/out/Release"
DEST_DIR="${REPO_ROOT}/out/packages"
TARGET_ARCH="x64"
VERSION="${DYNAMIC_BRAVE_VERSION:-}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir=*)
      OUT_DIR="${1#*=}"
      shift
      ;;
    --dest-dir=*|--dist-dir=*)
      DEST_DIR="${1#*=}"
      shift
      ;;
    --arch=*)
      TARGET_ARCH="${1#*=}"
      case "${TARGET_ARCH}" in
        all)
          PASS_ARGS=()
          for a in "$@"; do
            [[ "$a" != --arch=* ]] && PASS_ARGS+=("$a")
          done
          "$0" "${PASS_ARGS[@]}" --arch=x64
          "$0" "${PASS_ARGS[@]}" --arch=arm64
          exit 0
          ;;
        x64|arm64) ;;
        x86_64|amd64) TARGET_ARCH="x64" ;;
        aarch64) TARGET_ARCH="arm64" ;;
        *) echo "ERROR: Invalid architecture: ${TARGET_ARCH}" >&2; exit 1 ;;
      esac
      shift
      ;;
    --version=*)
      VERSION="${1#*=}"
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "${VERSION}" ]]; then
  MANIFEST=$(ls -t "${REPO_ROOT}/metadata/releases"/*.yaml 2>/dev/null | head -n 1 || true)
  if [[ -n "${MANIFEST}" && -f "${MANIFEST}" ]]; then
    VERSION=$(python3 -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1])).get('brave_version', ''))" "${MANIFEST}" 2>/dev/null || true)
  fi
  VERSION="${VERSION:-0.0.0}"
fi

echo "========================================================"
echo " Cerium Windows Package"
echo " Version     : ${VERSION}"
echo " Architecture: ${TARGET_ARCH}"
echo " Source Dir  : ${OUT_DIR}"
echo " Output Dir  : ${DEST_DIR}"
echo "========================================================"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Dry-run mode requested. Windows packaging validation complete."
  exit 0
fi

if [[ ! -d "${OUT_DIR}" ]]; then
  echo "ERROR: Windows output directory not found: ${OUT_DIR}" >&2
  exit 1
fi

SEVENZIP_CMD=""
if command -v 7z >/dev/null 2>&1; then
  SEVENZIP_CMD="7z"
elif command -v 7za >/dev/null 2>&1; then
  SEVENZIP_CMD="7za"
else
  echo "ERROR: 7z or 7za is required for Windows packaging." >&2
  exit 1
fi

mkdir -p "${DEST_DIR}"
INSTALLER_NAME="cerium_${TARGET_ARCH}.exe"
ARCHIVE_NAME="cerium_${TARGET_ARCH}.7z"
ARCHIVE_PATH="${DEST_DIR}/${ARCHIVE_NAME}"

# Step 1: Copy 1-Click Installer (mini_installer)
if [[ -f "${OUT_DIR}/mini_installer.exe" ]]; then
  echo "Packaging 1-click Windows installer into ${INSTALLER_NAME}..."
  cp -f "${OUT_DIR}/mini_installer.exe" "${DEST_DIR}/${INSTALLER_NAME}"
  echo " [OK] Saved installer: ${DEST_DIR}/${INSTALLER_NAME} ($(du -h "${DEST_DIR}/${INSTALLER_NAME}" | cut -f1))"
else
  echo "WARNING: mini_installer.exe not found in ${OUT_DIR}. Skipping installer output."
fi

# Step 2: Assemble Clean Standalone Distribution (Ultra LZMA2 .7z)
echo "Assembling standalone Windows distribution into ${ARCHIVE_NAME}..."
STAGE_DIR=$(mktemp -d "${WORKSPACE_DIR}/cerium_win_stage_XXXXXX")
cleanup_stage() {
  rm -rf "${STAGE_DIR}"
}
trap cleanup_stage EXIT

if [[ -f "${OUT_DIR}/chrome.7z" ]]; then
  echo "Found official release archive chrome.7z. Staging runtime files..."
  "${SEVENZIP_CMD}" x -y -o"${STAGE_DIR}" "${OUT_DIR}/chrome.7z" >/dev/null
  if [[ -d "${STAGE_DIR}/Chrome-bin" ]]; then
    # Move files from Chrome-bin to STAGE_DIR root
    find "${STAGE_DIR}/Chrome-bin" -mindepth 1 -maxdepth 1 -exec mv -t "${STAGE_DIR}" {} +
    rmdir "${STAGE_DIR}/Chrome-bin" 2>/dev/null || true
  fi
  if [[ -f "${OUT_DIR}/brave.exe" && ! -f "${STAGE_DIR}/brave.exe" ]]; then
    cp -f "${OUT_DIR}/brave.exe" "${STAGE_DIR}/"
  fi
else
  echo "Staging clean runtime distribution files from ${OUT_DIR}..."
  # Executables
  for exe in brave.exe chrome.exe chrome_proxy.exe notification_helper.exe; do
    [[ -f "${OUT_DIR}/${exe}" ]] && cp -f "${OUT_DIR}/${exe}" "${STAGE_DIR}/"
  done
  # Dynamic Libraries (excluding static libs and symbols)
  for dll in "${OUT_DIR}"/*.dll; do
    [[ -f "$dll" ]] && cp -f "$dll" "${STAGE_DIR}/"
  done
  # Pak files
  for pak in "${OUT_DIR}"/*.pak; do
    [[ -f "$pak" ]] && cp -f "$pak" "${STAGE_DIR}/"
  done
  # Bin, Dat, and JSON data
  for data_file in "${OUT_DIR}"/*.dat "${OUT_DIR}"/*.bin "${OUT_DIR}"/*.json; do
    [[ -f "$data_file" ]] && cp -f "$data_file" "${STAGE_DIR}/"
  done
  # Resource subdirectories
  for sub in locales MEIPreload VisualElements; do
    [[ -d "${OUT_DIR}/${sub}" ]] && cp -r "${OUT_DIR}/${sub}" "${STAGE_DIR}/"
  done
fi

# Provide cerium.exe as the primary launch executable alongside brave.exe and chrome.exe
if [[ -f "${STAGE_DIR}/brave.exe" && ! -f "${STAGE_DIR}/cerium.exe" ]]; then
  cp -f "${STAGE_DIR}/brave.exe" "${STAGE_DIR}/cerium.exe"
elif [[ -f "${STAGE_DIR}/chrome.exe" && ! -f "${STAGE_DIR}/cerium.exe" ]]; then
  cp -f "${STAGE_DIR}/chrome.exe" "${STAGE_DIR}/cerium.exe"
fi

echo "Compressing standalone distribution with ultra LZMA2 (-mx=9)..."
rm -f "${ARCHIVE_PATH}"
(cd "${STAGE_DIR}" && "${SEVENZIP_CMD}" a -t7z -mx=9 -ms=on "${ARCHIVE_PATH}" ./* >/dev/null)
echo " [OK] Saved standalone archive: ${ARCHIVE_PATH} ($(du -h "${ARCHIVE_PATH}" | cut -f1))"

# Step 3: Generate SHA256 Checksums
echo "Generating SHA256SUMS.txt..."
(cd "${DEST_DIR}" && sha256sum cerium_* > SHA256SUMS.txt)

# Step 4: Generate Update Manifest (release.json)
if [[ -f "${REPO_ROOT}/scripts/core/generate-update-manifest.py" ]]; then
  echo "Generating update manifest (release.json)..."
  python3 "${REPO_ROOT}/scripts/core/generate-update-manifest.py" \
    --package-dir="${DEST_DIR}" \
    --version="${VERSION}" \
    --arch="${TARGET_ARCH}" \
    --output="${DEST_DIR}/release.json"
fi

echo "========================================================"
echo " [SUCCESS] Windows packaging completed successfully."
echo " Output artifacts in ${DEST_DIR}"
echo "========================================================"

