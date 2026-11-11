#!/usr/bin/env bash
# Cerium — In-Runner NativeLink Daemon Manager
# Manages the local NativeLink REAPI CAS/Action Cache daemon on 127.0.0.1:50051
#
# Commands:
#   install  Ensure NativeLink binary is downloaded and ready
#   start    Start NativeLink daemon in background listening on 127.0.0.1:50051
#   stop     Gracefully terminate NativeLink daemon
#   status   Check daemon process and socket health

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=scripts/core/build-common.sh
source "${SCRIPT_DIR}/build-common.sh"

NATIVELINK_VERSION="${NATIVELINK_VERSION:-1.8.3}"
WORKSPACE_DIR="${WORKSPACE_DIR:-${REPO_ROOT}/build-workspace}"
NATIVELINK_DIR="$(resolve_nativelink_dir)"
NATIVELINK_PORT="${NATIVELINK_PORT:-50051}"
NATIVELINK_PID_FILE="${NATIVELINK_PID_FILE:-/tmp/nativelink.pid}"
NATIVELINK_LOG="${NATIVELINK_LOG:-${WORKSPACE_DIR}/nativelink.log}"
CONFIG_TEMPLATE="${REPO_ROOT}/.gitlab/ci/nativelink.json"
TOOLS_DIR="${TOOLS_DIR:-${WORKSPACE_DIR}/tools}"
NATIVELINK_BIN="${NATIVELINK_BIN:-${TOOLS_DIR}/nativelink}"

is_listening() {
  python3 -c "import socket; s = socket.socket(); s.settimeout(0.5); s.connect(('127.0.0.1', int('${NATIVELINK_PORT}'))); s.close()" 2>/dev/null
}

cmd_install() {
  if command -v nativelink &>/dev/null; then
    NATIVELINK_BIN="$(command -v nativelink)"
    echo "Using system nativelink binary: ${NATIVELINK_BIN}"
    return 0
  fi

  if [[ -x "${NATIVELINK_BIN}" ]]; then
    echo "Using cached nativelink binary: ${NATIVELINK_BIN}"
    return 0
  fi

  HOST_ARCH=$(uname -m)
  case "${HOST_ARCH}" in
    x86_64|amd64) ARCH_SUFFIX="x86_64-unknown-linux-musl" ;;
    aarch64|arm64) ARCH_SUFFIX="aarch64-unknown-linux-musl" ;;
    *) echo "ERROR: Unsupported host architecture: ${HOST_ARCH}" >&2; exit 1 ;;
  esac

  echo "========================================================"
  echo " NativeLink Host REAPI Daemon"
  echo " Runner Host Architecture : ${HOST_ARCH} (${ARCH_SUFFIX})"
  echo " Daemon Listen Address    : 127.0.0.1:${NATIVELINK_PORT}"
  echo " Note: NativeLink runs on the host runner to serve build cache (CAS/AC)"
  echo "       to Siso during cross-compilation."
  echo "========================================================"

  DOWNLOAD_URL="https://github.com/TraceMachina/nativelink/releases/download/v${NATIVELINK_VERSION}/nativelink-${NATIVELINK_VERSION}-${ARCH_SUFFIX}.tar.gz"
  mkdir -p "$(dirname "${NATIVELINK_BIN}")"
  TMP_TAR=$(mktemp /tmp/nativelink-dl-XXXXXX.tar.gz)
  echo "Downloading NativeLink v${NATIVELINK_VERSION} for host runner (${ARCH_SUFFIX})..."
  if curl --fail --show-error --location \
          --retry 5 --retry-delay 3 --retry-connrefused \
          --connect-timeout 20 --max-time 180 \
          "${DOWNLOAD_URL}" -o "${TMP_TAR}"; then
    if tar -tzf "${TMP_TAR}" nativelink >/dev/null 2>&1; then
      tar -xzf "${TMP_TAR}" -C "$(dirname "${NATIVELINK_BIN}")" nativelink
      rm -f "${TMP_TAR}"
      chmod +x "${NATIVELINK_BIN}"
      echo "NativeLink installed successfully at ${NATIVELINK_BIN}"
    else
      rm -f "${TMP_TAR}"
      echo "ERROR: Downloaded NativeLink archive is corrupted or invalid." >&2
      exit 1
    fi
  else
    rm -f "${TMP_TAR}"
    echo "ERROR: Failed to download NativeLink from ${DOWNLOAD_URL} after 5 retries." >&2
    echo "Please check GitHub connectivity or CDN status." >&2
    exit 1
  fi
}

cmd_start() {
  cmd_install

  if is_listening; then
    echo "NativeLink daemon is already running on 127.0.0.1:${NATIVELINK_PORT}."
    return 0
  fi

  # Ensure CAS and AC storage directories exist
  mkdir -p "${NATIVELINK_DIR}/cas/content" "${NATIVELINK_DIR}/cas/tmp" \
           "${NATIVELINK_DIR}/ac/content" "${NATIVELINK_DIR}/ac/tmp" \
           "$(dirname "${NATIVELINK_LOG}")"

  ACTIVE_CONFIG="${CONFIG_TEMPLATE}"
  # If NATIVELINK_DIR or PORT is customized, template config to active location
  if [[ "${NATIVELINK_DIR}" != "/tmp/nativelink" || "${NATIVELINK_PORT}" != "50051" ]]; then
    ACTIVE_CONFIG="${NATIVELINK_DIR}/nativelink.json"
    sed -e "s|/tmp/nativelink|${NATIVELINK_DIR}|g" \
        -e "s|127.0.0.1:50051|127.0.0.1:${NATIVELINK_PORT}|g" \
        "${CONFIG_TEMPLATE}" > "${ACTIVE_CONFIG}"
  fi

  echo "Starting NativeLink daemon on 127.0.0.1:${NATIVELINK_PORT}..."
  nohup "${NATIVELINK_BIN}" "${ACTIVE_CONFIG}" > "${NATIVELINK_LOG}" 2>&1 &
  PID=$!
  echo "${PID}" > "${NATIVELINK_PID_FILE}"

  MAX_WAIT=150
  READY=false
  for ((i=1; i<=MAX_WAIT; i++)); do
    if is_listening; then
      READY=true
      break
    fi
    if ! kill -0 "${PID}" 2>/dev/null; then
      echo "ERROR: NativeLink daemon failed to start. Tail of ${NATIVELINK_LOG}:" >&2
      tail -n 30 "${NATIVELINK_LOG}" >&2 || true
      rm -f "${NATIVELINK_PID_FILE}"
      exit 1
    fi
    sleep 0.2
  done

  if [[ "${READY}" == "true" ]]; then
    echo "NativeLink daemon listening on 127.0.0.1:${NATIVELINK_PORT} (PID: ${PID})"
  else
    echo "ERROR: Timed out waiting for NativeLink daemon to bind to 127.0.0.1:${NATIVELINK_PORT}" >&2
    tail -n 30 "${NATIVELINK_LOG}" >&2 || true
    kill -9 "${PID}" 2>/dev/null || true
    rm -f "${NATIVELINK_PID_FILE}"
    exit 1
  fi
}

cmd_stop() {
  if [[ -f "${NATIVELINK_PID_FILE}" ]]; then
    PID=$(cat "${NATIVELINK_PID_FILE}" 2>/dev/null || true)
    if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
      echo "Stopping NativeLink daemon (PID: ${PID})..."
      kill -INT "${PID}" 2>/dev/null || kill -TERM "${PID}" 2>/dev/null || true
      for ((i=1; i<=50; i++)); do
        if ! kill -0 "${PID}" 2>/dev/null; then
          break
        fi
        sleep 0.1
      done
      if kill -0 "${PID}" 2>/dev/null; then
        echo "Forcing termination (SIGKILL) of NativeLink daemon..."
        kill -9 "${PID}" 2>/dev/null || true
      fi
    fi
    rm -f "${NATIVELINK_PID_FILE}"
  fi

  pkill -f "nativelink.*nativelink.json" 2>/dev/null || true
  echo "NativeLink daemon stopped."
}

cmd_status() {
  if is_listening; then
    echo "NativeLink daemon is healthy and listening on 127.0.0.1:${NATIVELINK_PORT}."
    exit 0
  else
    echo "NativeLink daemon is not running."
    exit 1
  fi
}

case "${1:-}" in
  install)
    cmd_install
    ;;
  start)
    cmd_start
    ;;
  stop)
    cmd_stop
    ;;
  status)
    cmd_status
    ;;
  *)
    echo "Usage: $0 {install|start|stop|status}" >&2
    exit 1
    ;;
esac
