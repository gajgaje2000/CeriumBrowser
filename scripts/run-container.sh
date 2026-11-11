#!/usr/bin/env bash
# Cerium — Containerized Local Build & Shell Launcher
# (scripts/run-container.sh)
#
# Runs an interactive shell or build command inside the official Cerium builder container
# using podman or docker, with the current repository mounted.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE="${CERIUM_BUILDER_IMAGE:-registry.gitlab.com/ceriumbrowser/cerium-browser/builder:latest}"

ENGINE="${CONTAINER_ENGINE:-}"
if [[ -z "${ENGINE}" ]]; then
  if command -v podman &>/dev/null; then
    ENGINE="podman"
  elif command -v docker &>/dev/null; then
    ENGINE="docker"
  else
    echo "ERROR: Neither podman nor docker found in PATH." >&2
    exit 1
  fi
fi

CONTAINER_WORKDIR="/builds/CeriumBrowser/Cerium-Browser"

EXTRA_ARGS=()
if [[ "${ENGINE}" == "podman" ]]; then
  EXTRA_ARGS+=(--userns=keep-id)
fi

echo "========================================================"
echo " Launching Cerium Builder Container"
echo " Engine : ${ENGINE}"
echo " Image  : ${IMAGE}"
echo " Mount  : ${REPO_ROOT} -> ${CONTAINER_WORKDIR}"
echo "========================================================"

if [[ $# -eq 0 ]]; then
  exec "${ENGINE}" run --rm -it \
    "${EXTRA_ARGS[@]}" \
    -v "${REPO_ROOT}:${CONTAINER_WORKDIR}:z" \
    -w "${CONTAINER_WORKDIR}" \
    "${IMAGE}" /bin/bash
else
  exec "${ENGINE}" run --rm -it \
    "${EXTRA_ARGS[@]}" \
    -v "${REPO_ROOT}:${CONTAINER_WORKDIR}:z" \
    -w "${CONTAINER_WORKDIR}" \
    "${IMAGE}" "$@"
fi
