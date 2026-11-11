#!/usr/bin/env bash
# Cerium — Android Compilation Entry Point
# Usage: ./scripts/platforms/android/build.sh [--manifest=<path>] [--arch=arm64|arm|x86_64] [--release]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Source shared cross-platform build orchestration routines
# shellcheck source=scripts/core/build-common.sh
source "${REPO_ROOT}/scripts/core/build-common.sh"

MANIFEST=""
TARGET_ARCH="arm64"
DRY_RUN=false
GN_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest=*)
      MANIFEST="${1#*=}"
      shift
      ;;
    --arch=*)
      TARGET_ARCH="${1#*=}"
      case "${TARGET_ARCH}" in
        arm64|arm|x86|x64) ;;
        x86_64) TARGET_ARCH="x64" ;;
        *) echo "ERROR: Invalid architecture: ${TARGET_ARCH}" >&2; exit 1 ;;
      esac
      shift
      ;;
    --gn-only)
    GN_ONLY=true
    shift
    ;;
    --release)
      shift
      ;;
    --debug)
      echo "ERROR: Debug builds are disabled for production releases. Only --release is supported." >&2
      exit 1
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

# Step 1: Verify Release Manifest
if [[ -z "${MANIFEST}" ]]; then
  MANIFEST=$(ls -t "${REPO_ROOT}/metadata/releases"/*.yaml 2>/dev/null | head -n 1 || true)
fi

if [[ -z "${MANIFEST}" || ! -f "${MANIFEST}" ]]; then
  echo "ERROR: Release manifest not found. Run prepare-source.sh first." >&2
  exit 1
fi
# Resolve to absolute path so later cd commands cannot break manifest lookups
MANIFEST="$(cd "$(dirname "${MANIFEST}")" && pwd)/$(basename "${MANIFEST}")"


echo "========================================================"
echo " Cerium Android Build"
echo " Manifest    : ${MANIFEST}"
echo " Architecture: ${TARGET_ARCH}"
echo " Release Mode: true"
echo "========================================================"

BRAVE_CORE_COMMIT=$(extract_manifest_val "${MANIFEST}" "brave_core_commit")
BRAVE_VERSION=$(extract_manifest_val "${MANIFEST}" "brave_version")
CHROMIUM_COMMIT=$(extract_manifest_val "${MANIFEST}" "chromium_commit")
CHROMIUM_VERSION=$(extract_manifest_val "${MANIFEST}" "chromium_version")
PACKAGE_ID=$(extract_manifest_val "${MANIFEST}" "package_id" "org.cerium.browser")

export BRAVE_VERSION
export DYNAMIC_BRAVE_VERSION="${DYNAMIC_BRAVE_VERSION:-${BRAVE_VERSION}}"
export TARGET_ARCH

echo "Manifest Target Revisions:"
echo " - brave-core version: ${BRAVE_VERSION} (${BRAVE_CORE_COMMIT})"
echo " - Chromium version  : ${CHROMIUM_VERSION} (${CHROMIUM_COMMIT})"
echo " - Package ID        : ${PACKAGE_ID}"

# Step 2: Verify Required Tools
echo ""
echo "Verifying build tools..."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required." >&2; exit 1; }

# Step 3 & 4: Workspace Setup
WORKSPACE_DIR="${WORKSPACE_DIR:-${REPO_ROOT}/build-workspace}"
SRC_DIR="${WORKSPACE_DIR}/src"
BRAVE_DIR="${SRC_DIR}/brave"

echo "Build workspace: ${WORKSPACE_DIR}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Dry-run mode requested. Validation complete."
  exit 0
fi

# Full build requires node, pnpm, and host C compiler/linker (cc)
command -v node >/dev/null 2>&1 || { echo "ERROR: node is required." >&2; exit 1; }
command -v pnpm >/dev/null 2>&1 || { echo "ERROR: pnpm is required." >&2; exit 1; }
ensure_host_c_compiler "${WORKSPACE_DIR}"

# --- SYSTEM RESOURCES CHECK ---
echo "========================================================"
echo " System Resources Check"
echo "========================================================"
lscpu | grep -E "^CPU\(s\):|^Model name:|^Socket\(s\):|^Core\(s\) per socket:|^Thread\(s\) per core:" || true
echo ""
free -m || true
echo ""
df -h "${WORKSPACE_DIR}" || true
echo "========================================================"

T_START=$(date +%s)
T_CHECKOUT_START=${T_START}

# Phase 2: Verify brave-core
ensure_prepared_brave_source "${BRAVE_DIR}"

# Launch asynchronous background pre-fetches while Chromium source is fetched from Google Source
start_async_depot_tools "${WORKSPACE_DIR}"
start_async_nativelink_cache "${REPO_ROOT}" "${WORKSPACE_DIR}"

# Initialize or clean Chromium source tree (foreground network I/O from Google Source)
init_clean_chromium_source "${SRC_DIR}" "${CHROMIUM_VERSION}" "${CHROMIUM_COMMIT}"

T_SYNC_START=$(date +%s)
echo "Disk usage before gclient sync:"
du -sh "${WORKSPACE_DIR}" || true

# Barrier 1: Ensure depot_tools is ready before writing gclient config and syncing DEPS
await_async_depot_tools "${WORKSPACE_DIR}"

# Step 7b: Generate .gclient configuration, sync Chromium DEPS, and apply patches/mutators
write_gclient_config "${WORKSPACE_DIR}" "android" "${TARGET_ARCH}"
sync_and_patch_chromium "${WORKSPACE_DIR}" "${SRC_DIR}" "${BRAVE_DIR}" "${BRAVE_VERSION}" "android"

# Step 7c: Install Android build dependencies if missing from builder image
echo ""
echo "Installing Chromium Android build dependencies..."
if [[ -f "${SRC_DIR}/build/install-build-deps.sh" ]]; then
  if bash "${SRC_DIR}/build/install-build-deps.sh" --android --quick-check --no-prompt >/dev/null 2>&1; then
    echo "All Chromium Android build dependencies are already satisfied in builder image; skipping apt install."
  else
    bash "${SRC_DIR}/build/install-build-deps.sh" --android --no-prompt
  fi
fi

echo ""
echo "4. Running gclient hooks on patched Chromium..."
(cd "${WORKSPACE_DIR}" && gclient runhooks)

prepare_brave_branding_and_version "${BRAVE_DIR}" "${SRC_DIR}" "android" "${TARGET_ARCH}"
ensure_gn_binary "${SRC_DIR}"

T_GN_START=$(date +%s)

# Step 8: Configure Android Build Arguments
OUT_DIR="${SRC_DIR}/out/Release"
mkdir -p "${OUT_DIR}"

GN_ARGS_FILE="${OUT_DIR}/args.gn"
echo ""
echo "Generating Android GN build arguments to ${GN_ARGS_FILE}..."
python3 "${REPO_ROOT}/scripts/core/generate-gn-args.py" \
  --repo-root="${REPO_ROOT}" \
  --platform="android" \
  --arch="${TARGET_ARCH}" \
  --version="${BRAVE_VERSION}" \
  --package-id="${PACKAGE_ID}" \
  --out="${GN_ARGS_FILE}"

echo ""
echo "Android GN arguments configured:"
cat "${GN_ARGS_FILE}"

# Configure Siso REAPI and cache environment variables
configure_siso_environment "${SRC_DIR}" "android"

# Step 9: Restore CAS Cache and Start Local NativeLink Daemon
export NATIVELINK_DIR
NATIVELINK_DIR="$(resolve_nativelink_dir)"
CACHE_UPLOADED=false
BUILD_PID=""
WATCHDOG_PID=""
upload_cas_cache() {
  local trap_rc=$?
  shared_upload_cas_cache "${1:-${trap_rc}}"
}

if [[ "${DRY_RUN}" != "true" ]]; then
  # Barrier 2: Ensure NativeLink binary and CAS cache are ready before starting daemon
  await_async_nativelink_cache

  echo "Starting in-runner NativeLink host daemon on 127.0.0.1:50051 (host: $(uname -m), target: ${TARGET_ARCH})..."
  if [[ -f "${REPO_ROOT}/scripts/core/nativelink.sh" ]]; then
    bash "${REPO_ROOT}/scripts/core/nativelink.sh" start
    trap 'upload_cas_cache' EXIT
    trap 'exit 143' TERM
    trap 'exit 130' INT
  fi
fi

echo ""
echo "Running gn gen from source root..."
cd "${SRC_DIR}" && gn gen "${OUT_DIR}"

if [[ "${GN_ONLY:-false}" == "true" ]]; then
  echo ""
  echo "========================================================"
  echo " [SUCCESS] GN configuration passed! Skipping compilation (--gn-only)."
  echo "========================================================"
  exit 0
fi

T_NINJA_START=$(date +%s)

# Step 10: Build chrome_public_bundle (or custom BUILD_TARGET)
BUILD_TARGET="${BUILD_TARGET:-chrome_public_bundle}"
echo ""
echo "Building target: ${BUILD_TARGET}"
echo "This will take a long time (hours on first build)..."
run_siso_compilation "${WORKSPACE_DIR}" "${SRC_DIR}" "${OUT_DIR}" "${BUILD_TARGET}"

T_PKG_START=$(date +%s)

# Step 11: Collect and Optimize Artifacts (AAB Bundle & Standalone Universal APK)
CERIUM_VERSION=$(extract_manifest_val "cerium_version" "${BRAVE_VERSION:-unknown}")
OUTPUT_APK_DIR="${REPO_ROOT}/out/apks"
mkdir -p "${OUTPUT_APK_DIR}"
OUTPUT_NAME="cerium_${TARGET_ARCH}.apk"
OUTPUT_AAB_NAME="cerium_${TARGET_ARCH}.aab"

BUILT_AAB=$(find "${OUT_DIR}/apks" -name "*.aab" -type f 2>/dev/null | sort | head -n 1 || true)
BUILT_APK=""

if [[ -n "${BUILT_AAB}" ]]; then
  echo ""
  echo "Found Android App Bundle: ${BUILT_AAB}"
  cp -f "${BUILT_AAB}" "${OUTPUT_APK_DIR}/${OUTPUT_AAB_NAME}"
  echo " [OK] Saved App Bundle artifact: ${OUTPUT_APK_DIR}/${OUTPUT_AAB_NAME}"

  # Step 11a: Convert AAB to Universal Standalone APK via bundletool
  BUNDLETOOL_JAR="${SRC_DIR}/third_party/android_build_tools/bundletool/cipd/bundletool.jar"
  if [[ ! -f "${BUNDLETOOL_JAR}" ]]; then
    BUNDLETOOL_JAR=$(find "${SRC_DIR}" -name "bundletool*.jar" -type f 2>/dev/null | head -n 1 || true)
  fi

  if [[ -f "${BUNDLETOOL_JAR}" ]]; then
    echo "Converting AAB to Universal Standalone APK with compressed native libraries (bundletool)..."
    APKS_ARCHIVE="${OUT_DIR}/apks/universal.apks"
    rm -f "${APKS_ARCHIVE}"

    java -jar "${BUNDLETOOL_JAR}" build-apks \
      --bundle="${BUILT_AAB}" \
      --output="${APKS_ARCHIVE}" \
      --mode=universal

    RAW_UNIVERSAL="${OUT_DIR}/apks/universal.apk"
    rm -f "${RAW_UNIVERSAL}"
    unzip -q -o "${APKS_ARCHIVE}" "universal.apk" -d "${OUT_DIR}/apks/"

    # Step 11b: 4-byte alignment via zipalign
    ZIPALIGN_BIN=$(find "${SRC_DIR}/third_party/android_sdk" -name "zipalign" -type f -perm /111 2>/dev/null | head -n 1 || command -v zipalign || true)
    FINAL_UNSIGNED="${OUT_DIR}/apks/${OUTPUT_NAME}.unsigned"
    if [[ -n "${ZIPALIGN_BIN}" && -x "${ZIPALIGN_BIN}" ]]; then
      echo "Aligning package with zipalign..."
      "${ZIPALIGN_BIN}" -p -f 4 "${RAW_UNIVERSAL}" "${FINAL_UNSIGNED}"
    else
      cp -f "${RAW_UNIVERSAL}" "${FINAL_UNSIGNED}"
    fi

    BUILT_APK="${FINAL_UNSIGNED}"
  else
    echo "WARNING: bundletool.jar not found at ${BUNDLETOOL_JAR}. Falling back to pre-existing APKs."
  fi
fi

# Search for direct APK outputs
if [[ -z "${BUILT_APK}" ]]; then
  BUILT_APK=$(find "${OUT_DIR}/apks" -name "*.apk" -type f 2>/dev/null | sort | head -n 1 || true)
fi

if [[ -z "${BUILT_APK}" ]]; then
  echo "ERROR: No built APK found in ${OUT_DIR}/apks." >&2
  exit 1
fi

if [[ "${BUILT_APK}" != "${OUTPUT_APK_DIR}/${OUTPUT_NAME}" ]]; then
  cp -f "${BUILT_APK}" "${OUTPUT_APK_DIR}/${OUTPUT_NAME}"
fi
ln -sf "${OUTPUT_NAME}" "${OUTPUT_APK_DIR}/Cerium-${CERIUM_VERSION}-${TARGET_ARCH}.apk" 2>/dev/null || cp -f "${OUTPUT_APK_DIR}/${OUTPUT_NAME}" "${OUTPUT_APK_DIR}/Cerium-${CERIUM_VERSION}-${TARGET_ARCH}.apk"

# Step 12: Release APK Signing (when KEY_PASSWORD_ANDROID or keystore is configured)
if [[ -n "${KEY_PASSWORD_ANDROID:-}" || -n "${ANDROID_KEYSTORE_PASSWORD:-}" || -n "${ANDROID_KEYSTORE_PATH:-}" || -s "${REPO_ROOT}/.secure_files/${ANDROID_KEYSTORE_FILE:-braving_android.jks}" ]]; then
  echo ""
  echo "Signing release APK via package.sh..."
  "${SCRIPT_DIR}/package.sh" --apk="${OUTPUT_APK_DIR}/${OUTPUT_NAME}"
fi

  # Final refresh of diagnostics archive
  archive_build_artifacts

  T_END=$(date +%s)
  echo ""
  echo "========================================================"
  echo " BUILD SUCCESSFUL"
  echo " APK: ${OUTPUT_APK_DIR}/${OUTPUT_NAME}"
  echo " Size: $(du -h "${OUTPUT_APK_DIR}/${OUTPUT_NAME}" | cut -f1)"
  echo "========================================================"
  echo " [TIMING] chromium_checkout=$((T_SYNC_START - T_CHECKOUT_START))s"
  echo " [TIMING] gclient_sync_and_hooks=$((T_GN_START - T_SYNC_START))s"
  echo " [TIMING] gn_gen=$((T_NINJA_START - T_GN_START))s"
  echo " [TIMING] ninja=$((T_PKG_START - T_NINJA_START))s"
  echo " [TIMING] packaging=$((T_END - T_PKG_START))s"
  echo " [TIMING] total=$((T_END - T_START))s"
  echo "========================================================"
