#!/usr/bin/env bash
# Cerium — Patch Application & Verification Engine
# Applies or validates the Cerium patch set against a target repository.
# Applies cross-platform patches (patches/common) first, followed by platform patches.
# Supports clean forward application, strict idempotency (reverse-check),
# platform targeting (--target-os={all,android,windows,desktop}),
# and -C1 fuzzy context fallback across upstream version bumps.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PATCH_DIR="${REPO_ROOT}/patches"

TARGET_DIR=""
CHECK_ONLY=false
TARGET_OS="all"

for arg in "$@"; do
  case "${arg}" in
    --check)
      CHECK_ONLY=true
      ;;
    --target-os=*)
      TARGET_OS="${arg#*=}"
      ;;
    --platform=*)
      TARGET_OS="${arg#*=}"
      ;;
    --*)
      echo "ERROR: Unknown option: ${arg}" >&2
      exit 1
      ;;
    *)
      if [[ -n "${TARGET_DIR}" ]]; then
        echo "ERROR: Only one target git directory may be specified." >&2
        exit 1
      fi
      TARGET_DIR="${arg}"
      ;;
  esac
done

if [[ -z "${TARGET_DIR}" ]]; then
  echo "Usage: $0 <target-git-directory> [--check] [--target-os=all|android|windows|desktop]" >&2
  exit 1
fi

if [[ ! -e "${TARGET_DIR}/.git" ]]; then
  echo "ERROR: Target directory is not a git repository: ${TARGET_DIR}" >&2
  exit 1
fi

if [[ ! -d "${PATCH_DIR}" ]]; then
  echo "No patches directory found at ${PATCH_DIR}."
  exit 0
fi

PATCHES=()

# 1. Common core patches first (applied across all platforms)
if [[ -d "${PATCH_DIR}/common" ]]; then
  while IFS= read -r -d $'\0' file; do
    PATCHES+=("$file")
  done < <(find "${PATCH_DIR}/common" -name "*.patch" -print0 | sort -z)
fi

# 2. Platform-specific modular patches
case "${TARGET_OS}" in
  android)
    if [[ -d "${PATCH_DIR}/android" ]]; then
      while IFS= read -r -d $'\0' file; do
        PATCHES+=("$file")
      done < <(find "${PATCH_DIR}/android" -name "*.patch" -print0 | sort -z)
    fi
    ;;
  win|windows|desktop|linux|mac|macos)
    if [[ -d "${PATCH_DIR}/desktop" ]]; then
      while IFS= read -r -d $'\0' file; do
        PATCHES+=("$file")
      done < <(find "${PATCH_DIR}/desktop" -name "*.patch" -print0 | sort -z)
    fi
    ;;
  all|"")
    if [[ -d "${PATCH_DIR}/desktop" ]]; then
      while IFS= read -r -d $'\0' file; do
        PATCHES+=("$file")
      done < <(find "${PATCH_DIR}/desktop" -name "*.patch" -print0 | sort -z)
    fi
    if [[ -d "${PATCH_DIR}/android" ]]; then
      while IFS= read -r -d $'\0' file; do
        PATCHES+=("$file")
      done < <(find "${PATCH_DIR}/android" -name "*.patch" -print0 | sort -z)
    fi
    while IFS= read -r -d $'\0' file; do
      [[ "$file" == "${PATCH_DIR}/common/"* ]] && continue
      [[ "$file" == "${PATCH_DIR}/desktop/"* ]] && continue
      [[ "$file" == "${PATCH_DIR}/android/"* ]] && continue
      PATCHES+=("$file")
    done < <(find "${PATCH_DIR}" -name "*.patch" -print0 | sort -z)
    ;;
  *)
    echo "ERROR: Unknown target-os '${TARGET_OS}'. Supported: android, windows, desktop, all" >&2
    exit 1
    ;;
esac

if [[ ${#PATCHES[@]} -eq 0 ]]; then
  echo "No patches found in ${PATCH_DIR} (all modifications handled via mutators)."
  exit 0
fi

resolve_patch_title() {
  local pfile="$1"
  local yaml_file="${PATCH_DIR}/patches.yaml"
  if [[ -f "${yaml_file}" ]]; then
    python3 -c "
import sys
target = sys.argv[1]
try:
    import yaml
    with open('${yaml_file}', 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    for p in data.get('patches', []):
        if p.get('file') == target:
            print(p.get('name', ''))
            sys.exit(0)
except Exception:
    pass
" "${pfile}" 2>/dev/null || true
  fi
}

for patch in "${PATCHES[@]}"; do
  pname="${patch#${PATCH_DIR}/}"
  ptitle="$(resolve_patch_title "${pname}")"
  label="${pname}${ptitle:+ ($ptitle)}"

  if [[ "${CHECK_ONLY}" == "true" ]]; then
    if git -C "${TARGET_DIR}" apply --check "$patch" 2>/dev/null || \
       git -C "${TARGET_DIR}" apply --check --reverse "$patch" 2>/dev/null || \
       git -C "${TARGET_DIR}" apply -C1 --check "$patch" 2>/dev/null || \
       git -C "${TARGET_DIR}" apply -C1 --check --reverse "$patch" 2>/dev/null; then
      echo "      [PASS] ${label} applies cleanly"
    else
      echo "      [FAIL] ${label} failed to apply to ${TARGET_DIR}" >&2
      git -C "${TARGET_DIR}" apply --check -v "$patch" >&2 || true
      exit 1
    fi
  else
    echo " - Applying ${label}..."
    if git -C "${TARGET_DIR}" apply --check --reverse "$patch" 2>/dev/null || \
       git -C "${TARGET_DIR}" apply -C1 --check --reverse "$patch" 2>/dev/null; then
      echo "   [OK] Patch ${pname} already applied."
    elif git -C "${TARGET_DIR}" apply --check "$patch" 2>/dev/null; then
      git -C "${TARGET_DIR}" apply "$patch"
      echo "   [OK] Patch ${pname} successfully applied."
    elif git -C "${TARGET_DIR}" apply -C1 --check "$patch" 2>/dev/null; then
      git -C "${TARGET_DIR}" apply -C1 "$patch"
      echo "   [OK] Patch ${pname} successfully applied (with -C1 context)."
    else
      echo "ERROR: Patch ${label} failed to apply and is not already applied. Aborting to fail closed." >&2
      git -C "${TARGET_DIR}" apply --check -v "$patch" >&2 || true
      exit 1
    fi
  fi
done
