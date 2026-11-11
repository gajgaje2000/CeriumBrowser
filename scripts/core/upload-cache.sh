#!/usr/bin/env bash
# Cerium — In-Runner CAS Cache Packaging and Upload
# Packages rolling NativeLink CAS and Action Cache into 4000M chunks and uploads to GitLab Package Registry.
# Immediately cleans up chunk archives to conserve runner disk space.

set -euo pipefail

if [[ -z "${CI_API_V4_URL:-}" || -z "${CI_JOB_TOKEN:-}" || -z "${CI_PROJECT_ID:-}" ]]; then
  echo "GitLab CI API variables not set. Skipping cache upload."
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=scripts/core/build-common.sh
source "${SCRIPT_DIR}/build-common.sh"

CACHE_VERSION="$(resolve_cas_cache_version)"
AUTH_HEADER="$(resolve_gitlab_auth_header)"
PKG_URL="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/packages/generic/cerium-cas/${CACHE_VERSION}"
NATIVELINK_DIR="$(resolve_nativelink_dir)"

echo "=========================================="
echo " Packaging Cerium CAS Cache for ${CACHE_VERSION}"
echo " Package URL: ${PKG_URL}"
echo " Source Dir : ${NATIVELINK_DIR}"
echo "=========================================="

# Ensure NativeLink daemon is terminated before packaging so all files are flushed
if [[ -f "${REPO_ROOT}/scripts/core/nativelink.sh" ]]; then
  bash "${REPO_ROOT}/scripts/core/nativelink.sh" stop 2>/dev/null || true
else
  pkill -f "nativelink.*nativelink.json" 2>/dev/null || true
fi

if [[ ! -d "${NATIVELINK_DIR}/cas" ]] || [[ -z "$(find "${NATIVELINK_DIR}/cas" -type f 2>/dev/null | head -n 1)" ]]; then
  echo "Warning: No CAS cache objects found in ${NATIVELINK_DIR}/cas. Skipping cache upload."
  exit 0
fi

# Ensure ac directory exists before archiving
mkdir -p "${NATIVELINK_DIR}/ac"

UPLOAD_TMP_DIR=$(mktemp -d /tmp/cas-upload-XXXXXX)
trap 'rm -rf "${UPLOAD_TMP_DIR}"' EXIT
cd "${UPLOAD_TMP_DIR}"

echo "Compressing and splitting CAS and Action Cache into 4000M chunks (gzip -6)..."
GZIP="-6" tar -czf - -C "${NATIVELINK_DIR}" \
  --exclude="cas/tmp" \
  --exclude="cas/tmp/*" \
  --exclude="ac/tmp" \
  --exclude="ac/tmp/*" \
  cas ac | split -b 4000M - chunk.tar.gz.

echo "Generating SHA256 checksums..."
sha256sum chunk.tar.gz.* > checksums.sha256
cat checksums.sha256

# Clean up prior package version to prevent duplicate chunk files and registry bloat
gitlab_pkg_cleanup_version "cerium-cas" "${CACHE_VERSION}" "${AUTH_HEADER}"

for chunk in chunk.tar.gz.*; do
  [[ -f "${chunk}" ]] || continue
  echo "Uploading ${chunk} to Generic Package Registry (${PKG_URL}/${chunk})..."
  gitlab_pkg_upload_file "${chunk}" "${PKG_URL}/${chunk}" "${AUTH_HEADER}"
  # Immediate disk cleanup: delete each chunk file as soon as it is uploaded
  rm -f "${chunk}"
done

echo "Uploading checksums.sha256..."
gitlab_pkg_upload_file "checksums.sha256" "${PKG_URL}/checksums.sha256" "${AUTH_HEADER}"
rm -f checksums.sha256

touch "${NATIVELINK_DIR}/.cache_uploaded"
echo "CAS cache upload complete!"
