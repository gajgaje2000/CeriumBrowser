#!/usr/bin/env bash
# Cerium — Windows Compilation Entry Point
# (scripts/platforms/windows/build.sh)
#
# Compiles Cerium Browser for Windows (x64, arm64) using hermetic toolchains
# and distributed Siso + NativeLink CAS caching.
#
# Usage:
#   ./scripts/platforms/windows/build.sh [OPTIONS]
#
# Options:
#   --manifest=<path>     Path to release manifest YAML (defaults to latest in metadata/releases/)
#   --arch=x64|arm64|all  Target architecture (default: x64)
#   --package             Trigger packaging (mini_installer and .7z archive) after successful build
#   --gn-only             Configure GN build arguments and verify graph, then exit without compiling
#   --release             Compile release build (production default)
#   --dry-run             Validate environment, tools, and manifest without executing build steps

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Source shared cross-platform build orchestration routines
# shellcheck source=scripts/core/build-common.sh
source "${REPO_ROOT}/scripts/core/build-common.sh"

MANIFEST=""
TARGET_ARCH="x64"
DRY_RUN=false
GN_ONLY=false
PACKAGE_OUTPUT=false

# -----------------------------------------------------------------------------
# 1. Argument Parsing
# -----------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest=*)
      MANIFEST="${1#*=}"
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
    --package)
      PACKAGE_OUTPUT=true
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

# -----------------------------------------------------------------------------
# 2. Release Manifest Resolution & Target Revisions
# -----------------------------------------------------------------------------

if [[ -z "${MANIFEST}" ]]; then
  MANIFEST=$(ls -t "${REPO_ROOT}/metadata/releases"/*.yaml 2>/dev/null | head -n 1 || true)
fi

if [[ -z "${MANIFEST}" || ! -f "${MANIFEST}" ]]; then
  echo "ERROR: Release manifest not found. Run prepare-source.sh first." >&2
  exit 1
fi
MANIFEST="$(cd "$(dirname "${MANIFEST}")" && pwd)/$(basename "${MANIFEST}")"

echo "========================================================"
echo " Cerium Windows Build"
echo " Manifest    : ${MANIFEST}"
echo " Architecture: ${TARGET_ARCH}"
echo " Release Mode: true"
echo "========================================================"

BRAVE_CORE_COMMIT=$(extract_manifest_val "${MANIFEST}" "brave_core_commit")
BRAVE_VERSION=$(extract_manifest_val "${MANIFEST}" "brave_version")
CHROMIUM_COMMIT=$(extract_manifest_val "${MANIFEST}" "chromium_commit")
CHROMIUM_VERSION=$(extract_manifest_val "${MANIFEST}" "chromium_version")

export BRAVE_VERSION
export DYNAMIC_BRAVE_VERSION="${DYNAMIC_BRAVE_VERSION:-${BRAVE_VERSION}}"
export TARGET_ARCH

echo "Manifest Target Revisions:"
echo " - brave-core version: ${BRAVE_VERSION} (${BRAVE_CORE_COMMIT})"
echo " - Chromium version  : ${CHROMIUM_VERSION} (${CHROMIUM_COMMIT})"

# -----------------------------------------------------------------------------
# 3. Environment & Workspace Verification
# -----------------------------------------------------------------------------

echo ""
echo "Verifying build tools..."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 is required." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required." >&2; exit 1; }

WORKSPACE_DIR="${WORKSPACE_DIR:-${REPO_ROOT}/build-workspace}"
SRC_DIR="${WORKSPACE_DIR}/src"
BRAVE_DIR="${SRC_DIR}/brave"
OUT_DIR="${SRC_DIR}/out/Release"
GN_ARGS_FILE="${OUT_DIR}/args.gn"

echo "Build workspace: ${WORKSPACE_DIR}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "Dry-run mode requested. Validation complete."
  exit 0
fi

# Full build requires Node.js, pnpm, and host C compiler/linker
command -v node >/dev/null 2>&1 || { echo "ERROR: node is required." >&2; exit 1; }
command -v pnpm >/dev/null 2>&1 || { echo "ERROR: pnpm is required." >&2; exit 1; }
ensure_host_c_compiler "${WORKSPACE_DIR}"

# Verify prepared brave-core source (Phase 1)
ensure_prepared_brave_source "${BRAVE_DIR}"

# Launch asynchronous background pre-fetches while Chromium source is fetched from Google Source
start_async_depot_tools "${WORKSPACE_DIR}"
start_async_win_toolchain "${REPO_ROOT}" "${WORKSPACE_DIR}" "${SRC_DIR}"
start_async_nativelink_cache "${REPO_ROOT}" "${WORKSPACE_DIR}"

# Initialize or clean Chromium source tree (foreground network I/O from Google Source)
init_clean_chromium_source "${SRC_DIR}" "${CHROMIUM_VERSION}" "${CHROMIUM_COMMIT}"

# Barrier 1: Ensure depot_tools is ready before writing gclient config and syncing DEPS
await_async_depot_tools "${WORKSPACE_DIR}"

# -----------------------------------------------------------------------------
# 4. Chromium DEPS & gclient Sync
# -----------------------------------------------------------------------------

write_gclient_config "${WORKSPACE_DIR}" "win" "${TARGET_ARCH}"
sync_and_patch_chromium "${WORKSPACE_DIR}" "${SRC_DIR}" "${BRAVE_DIR}" "${BRAVE_VERSION}" "win"

# -----------------------------------------------------------------------------
# 5. Windows Cross-Compilation Toolchain Resolution
# -----------------------------------------------------------------------------

# Barrier 2: Ensure Windows toolchain package is ready before gclient runhooks
await_async_win_toolchain "${WORKSPACE_DIR}"

# Run gclient runhooks on patched Chromium tree
echo ""
echo "5. Running gclient hooks on patched Chromium..."
(cd "${WORKSPACE_DIR}" && gclient runhooks)

# Ensure Windows SDK headers define NTDDI_WIN11_BR if not already present
python3 -c "
import glob
for path in glob.glob('${SRC_DIR}/third_party/depot_tools/win_toolchain/vs_files/**/sdkddkver.h', recursive=True):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            c = f.read()
        if 'NTDDI_WIN11_BR' not in c:
            with open(path, 'a', encoding='utf-8') as f:
                f.write('\n#ifndef NTDDI_WIN11_BR\n#define NTDDI_WIN11_BR 0x0A000014\n#endif\n')
            print(f'Injected NTDDI_WIN11_BR into {path}')
    except Exception:
        pass
" 2>/dev/null || true

# Ensure ARM64 atlmfc/lib/arm64 directory exists (bridge from spectre/arm64 if present)
python3 -c "
import os, glob, shutil
for vs_root in glob.glob('${SRC_DIR}/third_party/depot_tools/win_toolchain/vs_files/*'):
    for lib_dir in glob.glob(os.path.join(vs_root, 'VC/Tools/MSVC/*/atlmfc/lib')):
        arm64_dir = os.path.join(lib_dir, 'arm64')
        spectre_arm64 = os.path.join(lib_dir, 'spectre', 'arm64')
        if not os.path.exists(arm64_dir):
            if os.path.isdir(spectre_arm64):
                try:
                    os.symlink('spectre/arm64', arm64_dir)
                    print(f'Symlinked {spectre_arm64} -> {arm64_dir}')
                except Exception:
                    shutil.copytree(spectre_arm64, arm64_dir)
                    print(f'Copied {spectre_arm64} -> {arm64_dir}')
            else:
                os.makedirs(arm64_dir, exist_ok=True)
                print(f'Created directory {arm64_dir}')
" 2>/dev/null || true

# -----------------------------------------------------------------------------
# 6. Branding & Version GN Generation
# -----------------------------------------------------------------------------

prepare_brave_branding_and_version "${BRAVE_DIR}" "${SRC_DIR}" "win" "${TARGET_ARCH}"

# Ensure fallback branding theme paths exist in brave/app/theme for chromium components
for scale in "" "/default_100_percent" "/default_200_percent"; do
  if [[ -d "${BRAVE_DIR}/app/theme${scale}/brave" && ! -e "${BRAVE_DIR}/app/theme${scale}/chromium" ]]; then
    ln -sfn "brave" "${BRAVE_DIR}/app/theme${scale}/chromium"
  fi
done

ensure_gn_binary "${SRC_DIR}"

# -----------------------------------------------------------------------------
# 7. GN Arguments Generation
# -----------------------------------------------------------------------------

mkdir -p "${OUT_DIR}"

echo "Generating Windows args.gn with Cerium branding..."
python3 "${REPO_ROOT}/scripts/core/generate-gn-args.py" \
  --repo-root="${REPO_ROOT}" \
  --platform="windows" \
  --arch="${TARGET_ARCH}" \
  --version="${BRAVE_VERSION}" \
  --out="${GN_ARGS_FILE}"

echo ""
echo "Windows GN arguments configured:"
cat "${GN_ARGS_FILE}"

# -----------------------------------------------------------------------------
# 8. Siso REAPI & NativeLink CAS Cache Setup
# -----------------------------------------------------------------------------

configure_siso_environment "${SRC_DIR}" "win"

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
  # Barrier 3: Ensure NativeLink binary and CAS cache are ready before starting daemon
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

if [[ "${GN_ONLY}" == "true" ]]; then
  echo "========================================================"
  echo " [SUCCESS] Windows GN configuration passed (--gn-only)."
  echo "========================================================"
  exit 0
fi

# -----------------------------------------------------------------------------
# 9. Siso Compilation with Watchdog Checkpointing
# -----------------------------------------------------------------------------

BUILD_TARGET="${BUILD_TARGET:-brave chrome/installer/mini_installer}"
echo "Building Windows target: ${BUILD_TARGET}..."
run_siso_compilation "${WORKSPACE_DIR}" "${SRC_DIR}" "${OUT_DIR}" "${BUILD_TARGET}"

# -----------------------------------------------------------------------------
# 10. Packaging Distribution
# -----------------------------------------------------------------------------

if [[ "${PACKAGE_OUTPUT:-false}" == "true" ]]; then
  echo "Packaging Windows distribution..."
  "${SCRIPT_DIR}/package.sh" --out-dir="${OUT_DIR}" --arch="${TARGET_ARCH}" --version="${DYNAMIC_BRAVE_VERSION}"
fi

echo "Windows build finished successfully."
