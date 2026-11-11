#!/usr/bin/env bash
# Cerium — In-Runner CAS Cache Download and Extraction
# Restores rolling NativeLink CAS and Action Cache from GitLab Generic Package Registry.
# Immediately cleans up downloaded archive chunks to conserve runner disk space.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/core/build-common.sh
source "${SCRIPT_DIR}/build-common.sh"

CACHE_VERSION="$(resolve_cas_cache_version)"
NATIVELINK_DIR="$(resolve_nativelink_dir)"
rm -f "${NATIVELINK_DIR}/.cache_uploaded"

if [[ "${FORCE_CACHE_REBUILD:-false}" =~ ^([Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])$ ]]; then
  echo "FORCE_CACHE_REBUILD is set to true. Skipping CAS cache download and starting with a clean store."
  rm -rf "${NATIVELINK_DIR}/cas" "${NATIVELINK_DIR}/ac"
  rm -f "${NATIVELINK_DIR}/.cache_restored"
  mkdir -p "${NATIVELINK_DIR}/cas/content" "${NATIVELINK_DIR}/cas/tmp" \
           "${NATIVELINK_DIR}/ac/content" "${NATIVELINK_DIR}/ac/tmp"
  exit 0
fi

if [[ -z "${CI_API_V4_URL:-}" || -z "${CI_JOB_TOKEN:-}" || -z "${CI_PROJECT_ID:-}" ]]; then
  echo "GitLab CI API variables not set. Skipping cache download."
  exit 0
fi

AUTH_HEADER="$(resolve_gitlab_auth_header)"

PKG_URL="${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/packages/generic/cerium-cas/${CACHE_VERSION}"

echo "=========================================="
echo " Restoring Cerium CAS Cache for ${CACHE_VERSION}"
echo " Package URL: ${PKG_URL}"
echo " Target Dir : ${NATIVELINK_DIR}"
echo "=========================================="

DOWNLOAD_TMP_DIR=$(mktemp -d /tmp/cas-download-XXXXXX)
trap 'rm -rf "${DOWNLOAD_TMP_DIR}"' EXIT
cd "${DOWNLOAD_TMP_DIR}"

echo "Fetching checksums from ${PKG_URL}/checksums.sha256..."
HTTP_CODE=$(curl -sL -o checksums.sha256 -w "%{http_code}" --header "${AUTH_HEADER}" "${PKG_URL}/checksums.sha256")

if [[ "${HTTP_CODE}" != "200" ]]; then
  echo "No CAS cache found for ${CACHE_VERSION} (HTTP ${HTTP_CODE}). Starting cold build."
  exit 0
fi

echo "CAS cache manifest found (HTTP ${HTTP_CODE}):"
cat checksums.sha256

echo "Downloading chunks in parallel..."
download_chunks_parallel "${PKG_URL}" "${AUTH_HEADER}"

echo "Verifying SHA256 checksums..."
if ! sha256sum -c checksums.sha256; then
  echo "WARNING: Checksum validation failed! CAS cache is incomplete or corrupted. Falling back to cold build..."
  rm -f chunk.tar.gz.* checksums.sha256
  rm -rf "${NATIVELINK_DIR}"
  exit 0
fi

echo "Extracting CAS cache into ${NATIVELINK_DIR}..."
mkdir -p "${NATIVELINK_DIR}"
cat chunk.tar.gz.* | tar -xzf - -C "${NATIVELINK_DIR}"
mkdir -p "${NATIVELINK_DIR}/cas/tmp" "${NATIVELINK_DIR}/ac/tmp"

# Immediate disk cleanup for 200 GB runner: delete downloaded archive chunks immediately after extraction
echo "Immediately deleting downloaded chunks to free disk space..."
rm -f chunk.tar.gz.* checksums.sha256
touch "${NATIVELINK_DIR}/.cache_restored"

CAS_SIZE=$(du -sh "${NATIVELINK_DIR}" 2>/dev/null | cut -f1 || echo "unknown")
echo "CAS cache restore complete! Restored ${CAS_SIZE} into ${NATIVELINK_DIR}."
