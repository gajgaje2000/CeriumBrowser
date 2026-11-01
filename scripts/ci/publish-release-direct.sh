#!/usr/bin/env bash
# ==============================================================================
# Cerium Browser CI/CD — Direct Release Publisher
# ==============================================================================
# Purpose:
#   Uploads the signed release APK directly to GitLab project uploads and
#   creates an official GitLab Release with a direct download asset link.
#   Automatically creates the Git tag `v<version>` referenced to CI_COMMIT_SHA.
#
# Requirements & Principles:
#   - set -euo pipefail for robust error handling.
#   - CI_JOB_TOKEN for GitLab API authentication (JOB-TOKEN header).
#   - Dynamic versioning without hardcoded release versions.
#   - Safe JSON serialization & parsing via python3 -c to avoid escaping bugs.
#   - Supports --dry-run mode to inspect payloads and actions safely.
#
# Usage:
#   ./scripts/ci/publish-release-direct.sh [--dry-run]
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 1. Parse Arguments & Initialize Options
# ------------------------------------------------------------------------------
DRY_RUN=false

for arg in "$@"; do
  case "${arg}" in
    --dry-run)
      DRY_RUN=true
      ;;
    -h|--help)
      echo "Usage: $0 [--dry-run]"
      echo "Publishes signed APK and creates a GitLab release via the GitLab API."
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: ${arg}" >&2
      echo "Usage: $0 [--dry-run]" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ------------------------------------------------------------------------------
# 2. Validate Environment Variables
# ------------------------------------------------------------------------------
# Version resolution: DYNAMIC_BRAVE_VERSION preferred, fallback to BRAVE_VERSION
DYNAMIC_BRAVE_VERSION="${DYNAMIC_BRAVE_VERSION:-${BRAVE_VERSION:-}}"
COMPILE_TARGET="${COMPILE_TARGET:-}"
if [[ -z "${COMPILE_TARGET}" ]]; then
  if [[ "${CI_COMMIT_REF_NAME:-}" == "release" || "${CI_COMMIT_BRANCH:-}" == "release" ]]; then
    COMPILE_TARGET="all"
  else
    COMPILE_TARGET="${TARGET_PLATFORM:-all}"
  fi
fi

if [[ -z "${TARGET_PLATFORM:-}" ]]; then
  if [[ "${COMPILE_TARGET}" == windows* ]]; then
    TARGET_PLATFORM="windows"
  elif [[ "${COMPILE_TARGET}" == "android" ]]; then
    TARGET_PLATFORM="android"
  else
    TARGET_PLATFORM="all"
  fi
fi

if [[ -z "${TARGET_ARCH:-}" ]]; then
  case "${COMPILE_TARGET}" in
    windows_x64) TARGET_ARCH="x64" ;;
    windows_arm64) TARGET_ARCH="arm64" ;;
    windows|all) TARGET_ARCH="all" ;;
    *) TARGET_ARCH="arm64" ;;
  esac
fi

if [[ "${CI_COMMIT_REF_NAME:-}" == "release" || "${CI_COMMIT_BRANCH:-}" == "release" || -z "${TARGET_PLATFORM:-}" || "${TARGET_PLATFORM}" == "all" ]]; then
  RELEASE_TAG="v${DYNAMIC_BRAVE_VERSION}"
else
  RELEASE_TAG="v${DYNAMIC_BRAVE_VERSION}-${TARGET_PLATFORM}"
fi

DYNAMIC_CHROMIUM_VERSION="${DYNAMIC_CHROMIUM_VERSION:-${CHROMIUM_VERSION:-}}"

if [[ -z "${DYNAMIC_CHROMIUM_VERSION}" && -f "${REPO_ROOT}/metadata/releases/${DYNAMIC_BRAVE_VERSION}.yaml" ]]; then
  DYNAMIC_CHROMIUM_VERSION="$(grep -E '^chromium_version:' "${REPO_ROOT}/metadata/releases/${DYNAMIC_BRAVE_VERSION}.yaml" | awk '{print $2}' | tr -d '"' | tr -d "'" || true)"
fi

declare -a MISSING_VARS=()

if [[ -z "${DYNAMIC_BRAVE_VERSION}" ]]; then
  MISSING_VARS+=("DYNAMIC_BRAVE_VERSION")
fi

if [[ -z "${TARGET_ARCH}" ]]; then
  MISSING_VARS+=("TARGET_ARCH")
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  # In dry-run mode, provide fallback values for CI environment variables if unset
  CI_JOB_TOKEN="${CI_JOB_TOKEN:-dry-run-token}"
  CI_API_V4_URL="${CI_API_V4_URL:-https://gitlab.com/api/v4}"
  CI_PROJECT_ID="${CI_PROJECT_ID:-dry-run-project-id}"
  CI_PROJECT_URL="${CI_PROJECT_URL:-https://gitlab.com/CeriumBrowser/Cerium-Browser}"
  CI_COMMIT_SHA="${CI_COMMIT_SHA:-$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo "0000000000000000000000000000000000000000")}"
else
  # In live execution mode, strictly enforce all required GitLab CI variables
  [[ -z "${CI_JOB_TOKEN:-}" ]] && MISSING_VARS+=("CI_JOB_TOKEN")
  [[ -z "${CI_API_V4_URL:-}" ]] && MISSING_VARS+=("CI_API_V4_URL")
  [[ -z "${CI_PROJECT_ID:-}" ]] && MISSING_VARS+=("CI_PROJECT_ID")
  [[ -z "${CI_PROJECT_URL:-}" ]] && MISSING_VARS+=("CI_PROJECT_URL")
  [[ -z "${CI_COMMIT_SHA:-}" ]] && MISSING_VARS+=("CI_COMMIT_SHA")
fi

if [[ ${#MISSING_VARS[@]} -gt 0 ]]; then
  echo "ERROR: Required environment variable(s) missing: ${MISSING_VARS[*]}" >&2
  exit 1
fi

echo "=========================================================="
echo " Cerium Direct Release Publisher"
echo " Version     : ${DYNAMIC_BRAVE_VERSION}"
echo " Architecture: ${TARGET_ARCH}"
echo " Target      : ${COMPILE_TARGET}"
echo " Dry Run     : ${DRY_RUN}"
echo "=========================================================="

# ------------------------------------------------------------------------------
# 3. Discover Release Artifact Files
# ------------------------------------------------------------------------------
declare -a PACKAGES_FOUND=()

# Search Android APKs (when COMPILE_TARGET is all or android)
if [[ "${COMPILE_TARGET}" == "all" || "${COMPILE_TARGET}" == "android" ]]; then
  for d in "${REPO_ROOT}/out/apks" "${REPO_ROOT}/build-workspace/src/out/Release/apks"; do
    if [[ -d "$d" ]]; then
      for f in "$d"/*.apk; do
        [[ -f "$f" ]] && PACKAGES_FOUND+=("$f")
      done
    fi
  done
fi

# Search Windows packages (when COMPILE_TARGET is all or windows*)
if [[ "${COMPILE_TARGET}" == "all" || "${COMPILE_TARGET}" == windows* ]]; then
  for d in "${REPO_ROOT}/out/packages"; do
    if [[ -d "$d" ]]; then
      for f in "$d"/Cerium-Windows-*.zip "$d"/Cerium-Installer-*.exe "$d"/Braving-Windows-*.zip "$d"/Braving-Installer-*.exe; do
        if [[ -f "$f" ]]; then
          if [[ "${COMPILE_TARGET}" == "windows_x64" && ! "$f" =~ x64 ]]; then
            continue
          fi
          if [[ "${COMPILE_TARGET}" == "windows_arm64" && ! "$f" =~ arm64 ]]; then
            continue
          fi
          PACKAGES_FOUND+=("$f")
        fi
      done
    fi
  done
fi


# Deduplicate packages strictly by basename to prevent duplicate uploads and release links
if [[ ${#PACKAGES_FOUND[@]} -gt 0 ]]; then
  declare -A SEEN_BASENAMES=()
  DEDUPED_PACKAGES=()
  for pkg in "${PACKAGES_FOUND[@]}"; do
    bn="$(basename "$pkg")"
    if [[ -z "${SEEN_BASENAMES[$bn]:-}" ]]; then
      SEEN_BASENAMES["$bn"]=1
      DEDUPED_PACKAGES+=("$pkg")
    fi
  done
  PACKAGES_FOUND=("${DEDUPED_PACKAGES[@]}")
fi

if [[ ${#PACKAGES_FOUND[@]} -eq 0 ]]; then
  if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${COMPILE_TARGET}" == "android" ]]; then
      echo "[DRY-RUN] Simulating Android release package:"
      android_arch="${TARGET_ARCH}"
      [[ "${android_arch}" == "all" || -z "${android_arch}" ]] && android_arch="arm64"
      PACKAGES_FOUND+=("${REPO_ROOT}/out/apks/Cerium-${DYNAMIC_BRAVE_VERSION}-${android_arch}.apk")
    elif [[ "${COMPILE_TARGET}" == "windows_x64" ]]; then
      echo "[DRY-RUN] Simulating Windows x64 release package:"
      PACKAGES_FOUND+=("${REPO_ROOT}/out/packages/Cerium-Windows-x64-v${DYNAMIC_BRAVE_VERSION}.zip")
    elif [[ "${COMPILE_TARGET}" == "windows_arm64" ]]; then
      echo "[DRY-RUN] Simulating Windows arm64 release package:"
      PACKAGES_FOUND+=("${REPO_ROOT}/out/packages/Cerium-Windows-arm64-v${DYNAMIC_BRAVE_VERSION}.zip")
    elif [[ "${COMPILE_TARGET}" == windows* ]]; then
      echo "[DRY-RUN] Simulating Windows release package(s):"
      PACKAGES_FOUND+=(
        "${REPO_ROOT}/out/packages/Cerium-Windows-x64-v${DYNAMIC_BRAVE_VERSION}.zip"
        "${REPO_ROOT}/out/packages/Cerium-Windows-arm64-v${DYNAMIC_BRAVE_VERSION}.zip"
      )
    else
      echo "[DRY-RUN] Simulating full multi-architecture release:"
      PACKAGES_FOUND+=(
        "${REPO_ROOT}/out/apks/Cerium-${DYNAMIC_BRAVE_VERSION}-arm64.apk"
        "${REPO_ROOT}/out/packages/Cerium-Windows-x64-v${DYNAMIC_BRAVE_VERSION}.zip"
        "${REPO_ROOT}/out/packages/Cerium-Windows-arm64-v${DYNAMIC_BRAVE_VERSION}.zip"
      )
    fi
  else
    echo "ERROR: No release packages found in out/apks or out/packages!" >&2
    exit 1
  fi
fi

# ------------------------------------------------------------------------------
# 4. Upload Release Assets to GitLab Generic Package Registry
# ------------------------------------------------------------------------------
PACKAGE_NAME="cerium-release"
PACKAGE_VERSION="${DYNAMIC_BRAVE_VERSION}"
PACKAGE_REGISTRY_BASE="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/packages/generic/${PACKAGE_NAME}/${PACKAGE_VERSION}"

declare -a UPLOADED_ITEMS_JSON=()

echo ""
echo "--- Step 1: Uploading Release Assets to GitLab Generic Package Registry ---"

for pkg in "${PACKAGES_FOUND[@]}"; do
  bname="$(basename "$pkg")"
  pkg_url="${PACKAGE_REGISTRY_BASE}/${bname}"

  # Determine architecture from filename or TARGET_ARCH
  pkg_arch="${TARGET_ARCH}"
  if [[ "$bname" =~ arm64 ]]; then
    pkg_arch="arm64"
  elif [[ "$bname" =~ x64 ]]; then
    pkg_arch="x64"
  elif [[ "$bname" =~ arm ]]; then
    pkg_arch="arm"
  fi

  # Determine platform
  pkg_platform="android"
  if [[ "$bname" =~ \.zip$ || "$bname" =~ \.exe$ ]]; then
    pkg_platform="windows"
  fi

  # Compute or look up SHA256
  pkg_sha=""
  dir="$(dirname "$pkg")"
  if [[ -f "${dir}/SHA256SUMS.txt" ]]; then
    pkg_sha="$(grep "${bname}" "${dir}/SHA256SUMS.txt" 2>/dev/null | awk '{print $1}' || true)"
  fi
  if [[ -z "${pkg_sha}" && -f "${pkg}" ]]; then
    pkg_sha="$(sha256sum "${pkg}" | awk '{print $1}')"
  elif [[ -z "${pkg_sha}" && "${DRY_RUN}" == "true" ]]; then
    pkg_sha="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    echo "[DRY-RUN] Upload ${bname} -> ${pkg_url}"
  else
    echo "Uploading package: ${bname}..."
    curl --fail-with-body --silent --show-error --location \
      --header "JOB-TOKEN: ${CI_JOB_TOKEN}" \
      --upload-file "${pkg}" \
      "${pkg_url}"
    echo "Package upload complete: ${pkg_url}"
  fi

  item_json=$(python3 -c "import json, sys; print(json.dumps({'name': sys.argv[1], 'url': sys.argv[2], 'sha256': sys.argv[3], 'platform': sys.argv[4], 'arch': sys.argv[5]}))" \
    "${bname}" "${pkg_url}" "${pkg_sha}" "${pkg_platform}" "${pkg_arch}")
  UPLOADED_ITEMS_JSON+=("${item_json}")
done

# ------------------------------------------------------------------------------
# 5. Step 2: Build GitLab Release JSON Payload
# ------------------------------------------------------------------------------
RELEASE_PAYLOAD="$(python3 - "${DYNAMIC_BRAVE_VERSION}" "${CI_COMMIT_SHA}" "${DYNAMIC_CHROMIUM_VERSION}" "${RELEASE_TAG}" "${UPLOADED_ITEMS_JSON[@]}" <<'PYEOF'
import json, sys

version = sys.argv[1]
commit_sha = sys.argv[2]
chromium_version = sys.argv[3]
tag_name = sys.argv[4]
raw_items = [json.loads(x) for x in sys.argv[5:]]
seen_item_names = set()
items = []
for it in raw_items:
    if it["name"] not in seen_item_names:
        seen_item_names.add(it["name"])
        items.append(it)

chromium_part = f" and Chromium v{chromium_version}" if chromium_version else ""
description_lines = [f"Updated to v{version}{chromium_part}\n"]

android_items = [it for it in items if it["platform"] == "android"]
windows_items = [it for it in items if it["platform"] == "windows"]

if android_items:
    description_lines.append("### Android")
    for it in android_items:
        description_lines.append(f"- [{it['name']}]({it['url']})")
        description_lines.append(f"  - **Architecture**: `{it['arch']}`")
        if it["sha256"]:
            description_lines.append(f"  - **SHA256**: `{it['sha256']}`")
    description_lines.append("")

if windows_items:
    description_lines.append("### Windows")
    for it in windows_items:
        description_lines.append(f"- [{it['name']}]({it['url']})")
        description_lines.append(f"  - **Architecture**: `{it['arch']}`")
        if it["sha256"]:
            description_lines.append(f"  - **SHA256**: `{it['sha256']}`")
    description_lines.append("")

description_lines.extend([
    "### Debloated Features",
    "- Brave Wallet / Crypto",
    "- AI Chat / Leo",
    "- Brave VPN",
    "- Brave News",
    "- Brave Rewards / BAT Ads",
    "- P3A Telemetry\n",
])

seen_links = set()
links = []
for it in items:
    if it["name"] not in seen_links:
        seen_links.add(it["name"])
        links.append({"name": it["name"], "url": it["url"], "link_type": "package"})

payload = {
    "name": f"Release v{version}",
    "tag_name": tag_name,
    "ref": commit_sha,
    "description": "\n".join(description_lines),
    "assets": {"links": links}
}

print(json.dumps(payload))
PYEOF
)"

# ------------------------------------------------------------------------------
# 7. Step 3: Create GitLab Release via Releases API
# ------------------------------------------------------------------------------
RELEASES_ENDPOINT="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/releases"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo ""
  echo "--- [DRY-RUN] Step 2: Create GitLab Release ---"
  echo "Executing command (simulated):"
  echo "  curl --fail-with-body \\"
  echo "    --header \"JOB-TOKEN: [MASKED]\" \\"
  echo "    --header \"Content-Type: application/json\" \\"
  echo "    --request POST \\"
  echo "    \"${RELEASES_ENDPOINT}\" \\"
  echo "    --data '<PAYLOAD>'"
  echo ""
  echo "Generated JSON Payload:"
  python3 -m json.tool <<< "${RELEASE_PAYLOAD}"
else
  echo ""
  echo "--- Step 2: Creating GitLab Release ${RELEASE_TAG} ---"
  TMP_RESPONSE="$(mktemp /tmp/gitlab-release-response-XXXXXX.json)"
  trap 'rm -f "${TMP_RESPONSE}"' EXIT

  HTTP_CODE="$(curl --silent --show-error --output "${TMP_RESPONSE}" --write-out "%{http_code}" \
    --header "JOB-TOKEN: ${CI_JOB_TOKEN}" \
    --header "Content-Type: application/json" \
    --request POST \
    "${RELEASES_ENDPOINT}" \
    --data "${RELEASE_PAYLOAD}")"

  if [[ "${HTTP_CODE}" == "201" || "${HTTP_CODE}" == "200" ]]; then
    echo "GitLab Release successfully created via API."
  elif [[ "${HTTP_CODE}" == "409" ]]; then
    echo "Release ${RELEASE_TAG} already exists (HTTP 409). Updating release..."
    curl --fail-with-body --silent --show-error \
      --header "JOB-TOKEN: ${CI_JOB_TOKEN}" \
      --header "Content-Type: application/json" \
      --request PUT \
      "${RELEASES_ENDPOINT}/${RELEASE_TAG}" \
      --data "${RELEASE_PAYLOAD}"
    echo "GitLab Release successfully updated via API."
  else
    echo "ERROR: Failed to create release (HTTP ${HTTP_CODE}):" >&2
    cat "${TMP_RESPONSE}" >&2
    rm -f "${TMP_RESPONSE}"
    exit 1
  fi
  rm -f "${TMP_RESPONSE}"
fi

# ------------------------------------------------------------------------------
# 8. Step 3: Create GitHub Release (if github_access is provided)
# ------------------------------------------------------------------------------
GITHUB_TOKEN="${github_access:-${GITHUB_ACCESS:-${GITHUB_TOKEN:-}}}"
GITHUB_REPO="${GITHUB_REPO:-gajgaje2000/CeriumBrowser}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo ""
  echo "--- [DRY-RUN] Step 3: Create GitHub Release in ${GITHUB_REPO} ---"
  echo "Simulated 20s tag synchronization delay."
  echo "[DRY-RUN] Create GitHub Release for ${RELEASE_TAG} -> https://github.com/${GITHUB_REPO}/releases/tag/${RELEASE_TAG}"
  for pkg in "${PACKAGES_FOUND[@]}"; do
    echo "  [DRY-RUN] Upload GitHub Asset -> $(basename "$pkg")"
  done
elif [[ -n "${GITHUB_TOKEN}" ]]; then
  echo ""
  echo "--- Step 3: Creating GitHub Release in ${GITHUB_REPO} ---"
  echo "Waiting 20 seconds for tag mirror synchronization to GitHub..."
  sleep 20

  GH_API="https://api.github.com/repos/${GITHUB_REPO}"
  GH_HEADERS=(
    --header "Authorization: Bearer ${GITHUB_TOKEN}"
    --header "Accept: application/vnd.github+json"
    --header "X-GitHub-Api-Version: 2022-11-28"
  )

  TMP_GH="$(mktemp /tmp/github-release-XXXXXX.json)"
  HTTP_CODE="$(curl --silent --show-error --output "${TMP_GH}" --write-out "%{http_code}" \
    "${GH_HEADERS[@]}" \
    "${GH_API}/releases/tags/${RELEASE_TAG}")"

  GH_RELEASE_ID=""
  if [[ "${HTTP_CODE}" == "200" ]]; then
    echo "GitHub Release for ${RELEASE_TAG} already exists. Updating release..."
    GH_RELEASE_ID="$(python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" < "${TMP_GH}")"
    GH_PATCH_PAYLOAD="$(python3 -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps({
    'name': data['name'],
    'body': data['description'],
    'draft': False,
    'prerelease': False
}))
" <<< "${RELEASE_PAYLOAD}")"
    curl --fail-with-body --silent --show-error \
      "${GH_HEADERS[@]}" \
      --header "Content-Type: application/json" \
      --request PATCH \
      "${GH_API}/releases/${GH_RELEASE_ID}" \
      --data "${GH_PATCH_PAYLOAD}" >/dev/null
  elif [[ "${HTTP_CODE}" == "404" ]]; then
    echo "Creating new GitHub Release for ${RELEASE_TAG}..."
    GH_POST_PAYLOAD="$(python3 -c "
import json, sys
data = json.load(sys.stdin)
print(json.dumps({
    'tag_name': data['tag_name'],
    'name': data['name'],
    'body': data['description'],
    'draft': False,
    'prerelease': False
}))
" <<< "${RELEASE_PAYLOAD}")"
    HTTP_CODE="$(curl --silent --show-error --output "${TMP_GH}" --write-out "%{http_code}" \
      "${GH_HEADERS[@]}" \
      --header "Content-Type: application/json" \
      --request POST \
      "${GH_API}/releases" \
      --data "${GH_POST_PAYLOAD}")"
    if [[ "${HTTP_CODE}" != "201" && "${HTTP_CODE}" != "200" ]]; then
      echo "ERROR: Failed to create GitHub Release (HTTP ${HTTP_CODE}):" >&2
      cat "${TMP_GH}" >&2
      rm -f "${TMP_GH}"
      exit 1
    fi
    GH_RELEASE_ID="$(python3 -c "import json, sys; print(json.load(sys.stdin).get('id', ''))" < "${TMP_GH}")"
  else
    echo "ERROR: Unexpected HTTP status checking GitHub Release (HTTP ${HTTP_CODE}):" >&2
    cat "${TMP_GH}" >&2
    rm -f "${TMP_GH}"
    exit 1
  fi
  rm -f "${TMP_GH}"

  if [[ -n "${GH_RELEASE_ID}" ]]; then
    TMP_ASSETS="$(mktemp /tmp/github-assets-XXXXXX.json)"
    curl --silent --show-error "${GH_HEADERS[@]}" "${GH_API}/releases/${GH_RELEASE_ID}/assets" -o "${TMP_ASSETS}" || true

    for pkg in "${PACKAGES_FOUND[@]}"; do
      bname="$(basename "$pkg")"
      EXISTING_ASSET_ID="$(python3 -c "
import json, sys
try:
    assets = json.load(sys.stdin)
    if isinstance(assets, list):
        match = next((a['id'] for a in assets if isinstance(a, dict) and a.get('name') == sys.argv[1]), '')
        print(match)
    else:
        print('')
except Exception:
    print('')
" "${bname}" < "${TMP_ASSETS}")"

      if [[ -n "${EXISTING_ASSET_ID}" ]]; then
        echo "Asset ${bname} already exists on GitHub (ID: ${EXISTING_ASSET_ID}). Replacing..."
        curl --fail-with-body --silent --show-error \
          "${GH_HEADERS[@]}" \
          --request DELETE \
          "${GH_API}/releases/assets/${EXISTING_ASSET_ID}" >/dev/null
      fi

      echo "Uploading ${bname} to GitHub Release..."
      curl --fail-with-body --silent --show-error \
        "${GH_HEADERS[@]}" \
        --header "Content-Type: application/octet-stream" \
        --request POST \
        --data-binary "@${pkg}" \
        "https://uploads.github.com/repos/${GITHUB_REPO}/releases/${GH_RELEASE_ID}/assets?name=${bname}" >/dev/null
      echo "Uploaded GitHub asset: ${bname}"
    done
    rm -f "${TMP_ASSETS}"
    echo "GitHub Release successfully published: https://github.com/${GITHUB_REPO}/releases/tag/${RELEASE_TAG}"
  fi
else
  echo ""
  echo "Notice: github_access token not set; skipping GitHub release publication."
fi

# ------------------------------------------------------------------------------
# 9. Print Release URL on Success
# ------------------------------------------------------------------------------
RELEASE_WEB_URL="${CI_PROJECT_URL%/}/-/releases/${RELEASE_TAG}"

echo ""
echo "=========================================================="
if [[ "${DRY_RUN}" == "true" ]]; then
  echo " [DRY-RUN] Release publication simulated successfully!"
else
  echo " Release published successfully!"
fi
echo " GitLab URL : ${RELEASE_WEB_URL}"
if [[ -n "${GITHUB_TOKEN}" || "${DRY_RUN}" == "true" ]]; then
  echo " GitHub URL : https://github.com/${GITHUB_REPO}/releases/tag/${RELEASE_TAG}"
fi
echo " Packages   : ${#PACKAGES_FOUND[@]} published to ${PACKAGE_REGISTRY_BASE}"
echo " Tag Created: ${RELEASE_TAG} (ref: ${CI_COMMIT_SHA})"
echo "=========================================================="
