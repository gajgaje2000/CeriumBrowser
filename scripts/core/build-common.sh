#!/usr/bin/env bash
# Cerium — Shared Build Orchestration Helpers
# (scripts/core/build-common.sh)
#
# Provides modular, reusable shell routines across all platform build scripts
# (Android, Windows, Linux, macOS):
#   - Manifest property extraction
#   - Git compatibility shims for depot_tools
#   - depot_tools resolution and bootstrapping
#   - Host C compiler verification
#   - Ephemeral Chromium source tree initialization
#   - Prepared brave-core verification and dummy git setup
#   - Siso & REAPI environment configuration
#   - Background compilation watchdog with graceful checkpointing
#   - Build log and diagnostic artifact archiving

set -euo pipefail

BUILD_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "${BUILD_COMMON_DIR}/../.." && pwd)}"

# Load centralized toolchain & dependency pins if present
if [[ -f "${REPO_ROOT}/configs/versions.env" ]]; then
  # shellcheck source=configs/versions.env
  source "${REPO_ROOT}/configs/versions.env"
fi

# Load local developer overrides if present (git-ignored)
if [[ -f "${REPO_ROOT}/local.env" ]]; then
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/local.env"
elif [[ -f "${REPO_ROOT}/build.env.local" ]]; then
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/build.env.local"
fi

# -----------------------------------------------------------------------------
# 1. Manifest Utilities
# -----------------------------------------------------------------------------

# Extract a scalar value from a release manifest YAML file.
# Supports both:
#   extract_manifest_val "key" [default]              (uses $MANIFEST)
#   extract_manifest_val "$path" "key" [default]      (explicit path)
extract_manifest_val() {
  local manifest_path key default_val
  if [[ -f "$1" ]]; then
    manifest_path="$1"
    key="$2"
    default_val="${3:-}"
  else
    manifest_path="${MANIFEST:-}"
    key="$1"
    default_val="${2:-}"
  fi

  python3 - "$manifest_path" "$key" "$default_val" <<'PYEOF'
import sys
manifest_path, key, default_val = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    import yaml
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    print(data.get(key, default_val))
except Exception:
    val = default_val
    prefix = key + ':'
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith(prefix):
                val = s[len(prefix):].strip().strip('"\'')
                break
    print(val)
PYEOF
}

# -----------------------------------------------------------------------------
# 2. Toolchain & Environment Prerequisites
# -----------------------------------------------------------------------------

# Ensure a compatible Git wrapper is installed when running on older Git versions
# (< 2.43.1) where depot_tools subcommands (checkout/switch/restore) reject
# the unrecognized '--end-of-options' argument.
# Arguments:
#   $1: Workspace root directory
#   $2: depot_tools directory path
ensure_git_compatibility_shim() {
  local workspace_dir="$1"
  local depot_tools_dir="$2"
  local real_git
  real_git=$(command -v git)

  local git_needs_shim
  git_needs_shim=$(python3 -c "
import subprocess
try:
    ver_str = subprocess.check_output(['${real_git}', '--version'], text=True).split()[-1]
    parts = [int(p) for p in ver_str.split('.')[:2] if p.isdigit()]
    if len(parts) >= 2 and (parts[0] < 2 or (parts[0] == 2 and parts[1] < 43)):
        print('true')
    else:
        print('false')
except Exception:
    print('true')
" 2>/dev/null || echo "true")

  if [[ "${git_needs_shim}" == "true" ]]; then
    echo "Detected Git < 2.43.1 (${real_git}). Installing Git compatibility shim for depot_tools..."
    local git_compat_dir="${workspace_dir}/git-compat"
    mkdir -p "${git_compat_dir}"

    cat <<WRAPPER > "${git_compat_dir}/git"
#!/usr/bin/env bash
REAL_GIT="${real_git}"
is_subcmd=false
for arg in "\$@"; do
  if [[ "\$arg" == "checkout" || "\$arg" == "switch" || "\$arg" == "restore" ]]; then
    is_subcmd=true
    break
  fi
done

if [[ "\$is_subcmd" == true ]]; then
  filtered_args=()
  for arg in "\$@"; do
    if [[ "\$arg" != "--end-of-options" ]]; then
      filtered_args+=("\$arg")
    fi
  done
  exec "\$REAL_GIT" "\${filtered_args[@]}"
fi

exec "\$REAL_GIT" "\$@"
WRAPPER

    chmod +x "${git_compat_dir}/git"
    if [[ -d "${depot_tools_dir}" ]]; then
      cp -f "${git_compat_dir}/git" "${depot_tools_dir}/git"
    fi
    export PATH="${git_compat_dir}:${PATH}"
    echo "Git compatibility shim installed at ${git_compat_dir}/git and ${depot_tools_dir}/git"
  fi
}

# Resolve or bootstrap Chromium depot_tools.
# Prioritizes pre-installed depot_tools from the builder image (/opt/depot_tools),
# falls back to workspace directory or shallow clone.
# Arguments:
#   $1: Workspace root directory
ensure_depot_tools() {
  local workspace_dir="$1"

  if [[ -d "/opt/depot_tools" ]]; then
    DEPOT_TOOLS_DIR="/opt/depot_tools"
    echo "Using pre-installed depot_tools from builder image: ${DEPOT_TOOLS_DIR}"
  elif [[ ! -d "${DEPOT_TOOLS_DIR:-${workspace_dir}/depot_tools}" ]]; then
    DEPOT_TOOLS_DIR="${workspace_dir}/depot_tools"
    echo ""
    echo "Fetching depot_tools..."
    git clone --depth 1 "https://chromium.googlesource.com/chromium/tools/depot_tools.git" "${DEPOT_TOOLS_DIR}"
    echo "Bootstrapping depot_tools..."
    "${DEPOT_TOOLS_DIR}/ensure_bootstrap" || "${DEPOT_TOOLS_DIR}/update_depot_tools"
  else
    DEPOT_TOOLS_DIR="${workspace_dir}/depot_tools"
    echo "Using pre-bootstrapped depot_tools from cache: ${DEPOT_TOOLS_DIR}"
  fi

  export PATH="${DEPOT_TOOLS_DIR}:${PATH}"
  export DEPOT_TOOLS_UPDATE=0
}

# Verify that a host C compiler/linker (cc) is available for Rust/Cargo build steps,
# creating a symlink fallback to gcc or clang in ${workspace_dir}/bin if needed.
# Arguments:
#   $1: Workspace root directory
ensure_host_c_compiler() {
  local workspace_dir="$1"

  if ! command -v cc >/dev/null 2>&1; then
    if command -v gcc >/dev/null 2>&1; then
      mkdir -p "${workspace_dir}/bin"
      ln -sf "$(command -v gcc)" "${workspace_dir}/bin/cc"
      export PATH="${workspace_dir}/bin:${PATH}"
    elif command -v clang >/dev/null 2>&1; then
      mkdir -p "${workspace_dir}/bin"
      ln -sf "$(command -v clang)" "${workspace_dir}/bin/cc"
      export PATH="${workspace_dir}/bin:${PATH}"
    else
      echo "ERROR: C compiler / linker (cc) is required for host rust/cargo build steps." >&2
      exit 1
    fi
  fi
}

# -----------------------------------------------------------------------------
# 3. Source Tree Initialization & Hygiene
# -----------------------------------------------------------------------------

# Fetch a shallow single-commit checkout of Chromium source directly from Google Source.
# Arguments:
#   $1: Path to Chromium source root (e.g. build-workspace/src)
#   $2: Chromium version tag (e.g. 136.0.7103.93)
#   $3: Chromium commit hash
fetch_chromium_git() {
  local src_dir="$1"
  local chromium_version="$2"
  local chromium_commit="$3"

  echo "Fetching clean Chromium directly from Google Source (${chromium_version} @ ${chromium_commit})..."
  mkdir -p "${src_dir}"
  if [[ ! -d "${src_dir}/.git" ]]; then
    git init "${src_dir}"
    git -C "${src_dir}" config advice.detachedHead false
    git -C "${src_dir}" remote add origin "https://chromium.googlesource.com/chromium/src.git" 2>/dev/null || \
      git -C "${src_dir}" remote set-url origin "https://chromium.googlesource.com/chromium/src.git"
  fi
  git -C "${src_dir}" fetch --depth 1 origin "refs/tags/${chromium_version}:refs/tags/${chromium_version}" 2>/dev/null || \
    git -C "${src_dir}" fetch --depth 1 origin "${chromium_commit}"
  git -C "${src_dir}" reset --hard FETCH_HEAD
  git -C "${src_dir}" clean -ffd -e brave -e out
}

# Initialize or clean the ephemeral Chromium source tree at the exact target revision.
# Reuses an existing checkout when HEAD already matches the target commit; otherwise fetches directly.
# Arguments:
#   $1: Path to Chromium source root (e.g. build-workspace/src)
#   $2: Chromium version tag (e.g. 136.0.7103.93)
#   $3: Chromium commit hash
init_clean_chromium_source() {
  local src_dir="$1"
  local chromium_version="$2"
  local chromium_commit="$3"

  if [[ -d "${src_dir}/.git" ]]; then
    local current_commit
    current_commit=$(git -C "${src_dir}" rev-parse HEAD 2>/dev/null || echo "")
    if [[ -n "${current_commit}" && "${current_commit}" == "${chromium_commit}" ]]; then
      echo "Chromium source directory already exists and matches target commit ${chromium_commit}. Resetting to clean state..."
      git -C "${src_dir}" reset --hard HEAD
      git -C "${src_dir}" clean -ffd -e brave -e out
      return 0
    fi
    echo "Existing Chromium checkout (${current_commit:-unknown}) does not match target ${chromium_commit}; fetching target revision..."
  fi

  fetch_chromium_git "${src_dir}" "${chromium_version}" "${chromium_commit}"
}

# Generate .gclient configuration in the build workspace for the given platform/CPU.
# Retains third_party/catapult (required by //BUILD.gn typ and Android devil) while
# excluding heavy test/variation repos and clang-format.
# Arguments:
#   $1: Workspace root directory
#   $2: Target OS (e.g. "android" or "win")
#   $3: Target CPU architecture (e.g. "arm64", "x64")
write_gclient_config() {
  local workspace_dir="$1"
  local target_os="$2"
  local target_cpu="$3"
  local gclient_config="${workspace_dir}/.gclient"

  echo ""
  echo "Writing gclient configuration to ${gclient_config} (${target_os}/${target_cpu})..."
  cat <<EOF > "${gclient_config}"
solutions = [
  {
    "name": "src",
    "url": "https://chromium.googlesource.com/chromium/src.git",
    "managed": False,
    "custom_deps": {
      "src/testing/libfuzzer/fuzzers/wasm_corpus": None,
      "src/third_party/chromium-variations": None,
      "src/third_party/clang-format/script": None,
      "src/third_party/blink/web_tests": None,
      "src/third_party/blink/perf_tests": None,
      "src/third_party/angle/third_party/VK-GL-CTS/src": None,
      "src/chrome/test/data": None,
      "src/v8/test": None,
      "src/third_party/perfetto/test": None,
      "src/third_party/dawn/test": None,
      "src/third_party/skia/platform_tools": None,
    },
    "custom_vars": {
      "checkout_pgo_profiles": True,
      "checkout_clang_coverage_tools": False,
      "checkout_clangd": False,
      "download_reclient": False,
      "checkout_telemetry_dependencies": False,
      "checkout_nacl": False,
      "gn_version": "git_revision:${CERIUM_GN_REVISION:-c7ffaf80713afbe5a4f4d95a605c0a98084374de}",
    },
  },
  {
    "name": "src/brave",
    "url": "https://github.com/brave/brave-core.git",
    "managed": False,
  },
]
target_os = ["${target_os}"]
target_cpu = ["${target_cpu}"]
EOF
}

# Export Brave/Chromium hook PYTHONPATH and run gclient sync + upstream Brave
# patches + version.py/Cerium mutators across both trees.
# Arguments:
#   $1: Workspace root directory
#   $2: Chromium src directory
#   $3: Prepared brave-core directory
#   $4: Brave release version (e.g. 1.99.55)
#   $5: Target OS ("android" or "win")
sync_and_patch_chromium() {
  local workspace_dir="$1"
  local src_dir="$2"
  local brave_dir="$3"
  local brave_version="$4"
  local target_os="$5"

  export PYTHONPATH="${brave_dir}/script:${src_dir}/tools/grit/grit/extern:${brave_dir}/vendor/requests:${brave_dir}/third_party/cryptography:${brave_dir}/third_party/macholib:${src_dir}/build:${src_dir}/third_party/depot_tools${PYTHONPATH:+:${PYTHONPATH}}"
  export PYTHONUNBUFFERED="1"
  export GCLIENT_SUPPRESS_GIT_VERSION_WARNING="1"
  export CHROME_HEADLESS="1"

  # Clean stale directory artifacts that block gclient sync
  rm -rf "${src_dir}/third_party/clang-format/script" "${workspace_dir}/_bad_scm"

  echo "1. Syncing Chromium DEPS dependencies via gclient (shallow, no history, NOHOOKS)..."
  (cd "${workspace_dir}" && gclient sync --no-history --shallow --nohooks -j"$(nproc)")

  echo ""
  echo "2. Installing brave-core node dependencies and applying upstream Brave patches to Chromium..."
  (cd "${brave_dir}" && pnpm install --frozen-lockfile)
  (cd "${brave_dir}" && pnpm run apply_patches)

  if [[ -f "${src_dir}/chrome/VERSION" ]]; then
    echo ""
    echo "3. Preparing Chromium VERSION and VERSION.chromium sidecar (Brave ${brave_version})..."
    if [[ -f "${brave_dir}/build/util/version.py" && -n "${brave_version}" ]]; then
      python3 "${brave_dir}/build/util/version.py" update --brave-version "${brave_version}" "${src_dir}/chrome/VERSION"
    fi
    echo "Applying Cerium mutators to brave-core and Chromium src (${target_os})..."
    python3 "${REPO_ROOT}/scripts/core/apply-features.py" "${brave_dir}" --strict --src-dir="${src_dir}" --target-os="${target_os}"
  fi
}

# Propagate brave-core branding theme resources and ensure version.gni exists.
# Arguments:
#   $1: Prepared brave-core directory
#   $2: Chromium src directory
#   $3: Target OS ("android" or "win")
#   $4: Target CPU architecture ("arm64", "x64", etc.)
prepare_brave_branding_and_version() {
  local brave_dir="$1"
  local src_dir="$2"
  local target_os="$3"
  local target_cpu="$4"

  echo ""
  echo "Applying Cerium static branding overlays, vector icons, and node_modules/@brave/leo overrides..."
  bash "${REPO_ROOT}/scripts/core/apply-assets.sh" "${brave_dir}" "${src_dir}"

  echo "Propagating branding from brave-core/app/theme/brave and touching overridden files..."
  (cd "${brave_dir}" && pnpm run build Release --prepare_only --target_os="${target_os}" --target_arch="${target_cpu}" --channel=release)

  echo "Enforcing Cerium branding in Chromium src directory..."
  bash "${REPO_ROOT}/scripts/core/apply-assets.sh" "${brave_dir}" "${src_dir}"

  if [[ -f "${brave_dir}/build/util/version.py" && -f "${src_dir}/chrome/VERSION" && ! -f "${brave_dir}/build/version.gni" ]]; then
    echo "Generating brave/build/version.gni..."
    python3 "${brave_dir}/build/util/version.py" gen "${src_dir}/chrome/VERSION"
  fi
}

# Ensure the hermetic GN binary is installed in buildtools/linux64 and on PATH.
# Arguments:
#   $1: Chromium src directory
ensure_gn_binary() {
  local src_dir="$1"
  mkdir -p "${src_dir}/buildtools/linux64"
  if [[ ! -x "${src_dir}/buildtools/linux64/gn" ]]; then
    echo ""
    echo "Installing hermetic GN binary via CIPD..."
    local host_arch cipd_arch="amd64"
    host_arch=$(uname -m)
    if [[ "${host_arch}" == "aarch64" ]]; then
      cipd_arch="arm64"
    fi
    cipd install "gn/gn/linux-${cipd_arch}" "git_revision:c7ffaf80713afbe5a4f4d95a605c0a98084374de" -root "${src_dir}/buildtools/linux64" || \
      cipd install "gn/gn/linux-${cipd_arch}" "latest" -root "${src_dir}/buildtools/linux64"
    chmod +x "${src_dir}/buildtools/linux64/gn" 2>/dev/null || true
  fi
  export PATH="${src_dir}/buildtools/linux64:${PATH}"
}

# Append standard Cerium debloated proprietary service/key GN overrides to args.gn.
# Arguments:
#   $1: Destination args.gn path
append_debloated_service_gn_args() {
  local args_file="$1"
  if [[ -f "${REPO_ROOT}/configs/gn/debloat.gni" ]]; then
    cat "${REPO_ROOT}/configs/gn/debloat.gni" >> "${args_file}"
    return 0
  fi
  cat <<'EOF' >> "${args_file}"

# Debloated subsystems enforced via Enterprise Policies
brave_services_key = "no-key"
service_key_stt = "no-key"
service_key_aichat = "no-key"
service_key_search = "no-key"
brave_sync_endpoint = "no-key"
brave_variations_server_url = "no-key"
brave_stats_updater_url = "no-key"
bitflyer_production_fee_address = "no-key"
bitflyer_production_url = "no-key"
uphold_production_api_url = "no-key"
uphold_production_fee_address = "no-key"
uphold_production_oauth_url = "no-key"
zebpay_production_api_url = "no-key"
zebpay_production_oauth_url = "no-key"
rewards_grant_dev_endpoint = "no-key"
rewards_grant_staging_endpoint = "no-key"
rewards_grant_prod_endpoint = "no-key"
EOF
}

# Verify that brave-core has been prepared (Phase 1) and contains a minimal git
# identity so downstream build commands (like patch generation or git version checks) succeed.
# Arguments:
#   $1: Path to brave-core directory (e.g. build-workspace/src/brave)
ensure_prepared_brave_source() {
  local brave_dir="$1"

  if [[ ! -d "${brave_dir}" ]]; then
    echo "ERROR: Prepared brave-core not found in ${brave_dir}." >&2
    echo "Please run scripts/core/prepare-source.sh (Phase 1) first." >&2
    exit 1
  fi

  if [[ ! -d "${brave_dir}/.git" ]]; then
    git -C "${brave_dir}" init -q
    git -C "${brave_dir}" config user.name "Cerium Browser Team"
    git -C "${brave_dir}" config user.email "ci@ceriumbrowser.org"
    git -C "${brave_dir}" commit --allow-empty -m "Prepared brave-core" --no-gpg-sign -q
  fi
}

# -----------------------------------------------------------------------------
# 4. Siso & REAPI Build Environment
# -----------------------------------------------------------------------------

# Configure Siso REAPI environment variables and write .sisorc and .sisoenv configs.
# Arguments:
#   $1: Chromium src directory
#   $2: Target OS (e.g. "android" or "win")
configure_siso_environment() {
  local src_dir="$1"
  local target_os="$2"

  export TARGET_OS="${target_os}"
  export SISO_REAPI_ADDRESS="127.0.0.1:50051"
  export SISO_REAPI_INSTANCE="main"
  export SISO_PROJECT="rbe-chromium-untrusted"
  export RBE_project="rbe-chromium-untrusted"
  export RBE_instance="projects/rbe-chromium-untrusted/instances/main"
  export AUTONINJA_SKIP_EXTERNAL_ACCOUNT_CHECK="1"
  export RBE_service_no_security=true

  # Configure Siso runtime settings via .sisorc:
  # -fs_keep_tainted: preserves HashFS cmdhash when local timestamps are newer
  # -re_exec_enable=false: execute actions locally (in-runner NativeLink lacks remote workers)
  # -re_cache_enable_read=true & -re_cache_enable_write=true: enable Action Cache
  # -config googlechrome: enable REAPI caching across all toolchains (Mojo, Grit, V8, Rust)
  mkdir -p "${src_dir}/build/config/siso"
  cat <<EOF > "${src_dir}/build/config/siso/.sisorc"
ninja -fs_keep_tainted -re_exec_enable=false -re_cache_enable_read=true -re_cache_enable_write=true -config googlechrome
EOF

  if [[ -d "${src_dir}/build/config/siso/backend_config" && ! -f "${src_dir}/build/config/siso/backend_config/backend.star" ]]; then
    cp "${src_dir}/build/config/siso/backend_config/template.star" "${src_dir}/build/config/siso/backend_config/backend.star" 2>/dev/null || true
  fi

  cat <<EOF > "${src_dir}/build/config/siso/.sisoenv"
SISO_PROJECT=rbe-chromium-untrusted
SISO_REAPI_INSTANCE=main
EOF
}

# -----------------------------------------------------------------------------
# 5. Compilation Watchdog & Checkpointing
# -----------------------------------------------------------------------------

# Start a background watchdog timer that sends graceful termination signals (SIGINT,
# then SIGTERM after 30s) when compilation approaches runner limits, triggering
# a cache checkpoint (exit 42).
# Arguments:
#   $1: Timeout in seconds (e.g. 9600 for 2h 40m)
#   $2: Build output directory (e.g. src/out/Release)
#   $3: Marker file path touched upon timeout trigger
# Sets global variable:
#   WATCHDOG_PID: PID of the background watchdog process (avoids $() pipe deadlocks)
start_build_watchdog() {
  local timeout_seconds="$1"
  local out_dir="$2"
  local marker_path="$3"

  WATCHDOG_PID=""
  rm -f "${marker_path}"
  if [[ "${timeout_seconds}" -le 0 ]]; then
    return 0
  fi

  (
    local child_pid=""
    trap '[[ -n "${child_pid}" ]] && kill -TERM "${child_pid}" 2>/dev/null || true; exit 0' TERM INT
    sleep "${timeout_seconds}" </dev/null >/dev/null 2>&1 &
    child_pid=$!
    wait "${child_pid}" 2>/dev/null || exit 0

    echo "" >&2
    echo "==========================================================================" >&2
    echo " [WATCHDOG] Compilation reached timeout (${timeout_seconds}s)." >&2
    echo " Triggering graceful checkpoint to preserve CAS cache before runner limit..." >&2
    echo "==========================================================================" >&2
    touch "${marker_path}"
    # Send SIGINT to allow Siso/Ninja to finish active jobs and flush cache state
    pkill -INT -f "autoninja.*${out_dir}" 2>/dev/null || pkill -INT -f "ninja.*${out_dir}" 2>/dev/null || pkill -INT -f "siso.*${out_dir}" 2>/dev/null || true
    sleep 30 </dev/null >/dev/null 2>&1 &
    child_pid=$!
    wait "${child_pid}" 2>/dev/null || exit 0
    # Escalate to SIGTERM if still active
    pkill -TERM -f "autoninja.*${out_dir}" 2>/dev/null || pkill -TERM -f "ninja.*${out_dir}" 2>/dev/null || pkill -TERM -f "siso.*${out_dir}" 2>/dev/null || true
  ) </dev/null >/dev/null &
  WATCHDOG_PID=$!
}

# Stop and terminate the watchdog process and its child sleep timer if still active.
# Arguments:
#   $1: PID of background watchdog process
stop_build_watchdog() {
  local watchdog_pid="${1:-}"
  if [[ -n "${watchdog_pid}" ]]; then
    pkill -TERM -P "${watchdog_pid}" 2>/dev/null || true
    kill "${watchdog_pid}" 2>/dev/null || true
    wait "${watchdog_pid}" 2>/dev/null || true
  fi
}

# Execute Siso/Ninja compilation under watchdog supervision with live filtered
# output, diagnostic artifact archiving, checkpoint detection (exit 42), and
# failure log dumping. Invokes upload_cas_cache before checking BUILD_RES != 0.
# Arguments:
#   $1: Workspace root directory
#   $2: Chromium src directory
#   $3: Build output directory (e.g. src/out/Release)
#   $4: Build targets (space-separated)
run_siso_compilation() {
  local workspace_dir="$1"
  local src_dir="$2"
  local out_dir="$3"
  local build_targets="$4"

  echo "Logging full build output to ${workspace_dir}/build.log..."
  set +e
  set -o pipefail

  cd "${src_dir}"
  BUILD_RES=0
  local build_timeout="${BUILD_TIMEOUT_SECONDS:-9600}"
  local CHECKPOINT_MARKER="${workspace_dir}/.checkpoint_triggered"
  local CHECKPOINT_TRIGGERED=false

  start_build_watchdog "${build_timeout}" "${out_dir}" "${CHECKPOINT_MARKER}"

  local build_cmd="ninja"
  if command -v autoninja &>/dev/null; then
    build_cmd="autoninja"
  fi
  local step_interval="${CERIUM_LOG_STEP_INTERVAL:-50}"
  local heartbeat_interval="${CERIUM_LOG_HEARTBEAT:-20}"
  ${build_cmd} -C "${out_dir}" ${build_targets} 2>&1 | \
    python3 -u "${REPO_ROOT}/scripts/core/filter-build-log.py" "${workspace_dir}/build.log" "${step_interval}" "${heartbeat_interval}" &
  BUILD_PID=$!
  wait "${BUILD_PID}"
  BUILD_RES=$?
  BUILD_PID=""

  stop_build_watchdog "${WATCHDOG_PID}"

  if [[ -f "${CHECKPOINT_MARKER}" ]]; then
    CHECKPOINT_TRIGGERED=true
    rm -f "${CHECKPOINT_MARKER}"
  fi

  for f in /tmp/siso.* /tmp/siso_*; do
    if [[ -f "$f" ]]; then
      cp -f "$f" "${out_dir}/" 2>/dev/null || true
    fi
  done

  if [[ -f "${workspace_dir}/build.log" ]]; then
    gzip -k -f "${workspace_dir}/build.log" || true
  fi

  archive_build_artifacts "${workspace_dir}" "${out_dir}"

  if declare -F upload_cas_cache >/dev/null 2>&1; then
    upload_cas_cache 0
  else
    shared_upload_cas_cache 0
  fi

  if [[ "${CHECKPOINT_TRIGGERED}" == "true" ]]; then
    echo ""
    echo "=========================================================================="
    echo " [CHECKPOINT] Compilation reached 2h 40m timeout."
    echo " CAS cache has been uploaded to GitLab Package Registry."
    echo " Exiting with status 42 for automatic GitLab CI retry."
    echo "=========================================================================="
    exit 42
  fi

  if [[ ${BUILD_RES} -ne 0 ]]; then
    echo "========================================================"
    echo " BUILD FAILED! Exit code: ${BUILD_RES}."
    echo "========================================================"
    if [[ -f "${out_dir}/siso_output" ]]; then
      echo "--- siso_output ---"
      cat "${out_dir}/siso_output"
    fi
    if [[ -f "${out_dir}/siso_failed_commands.sh" ]]; then
      echo "--- siso_failed_commands.sh ---"
      cat "${out_dir}/siso_failed_commands.sh"
    fi
    echo "--- Tail of build.log ---"
    tail -n 150 "${workspace_dir}/build.log" || true
    exit 1
  fi

  set -e
  set -o pipefail
}

# -----------------------------------------------------------------------------
# 6. Artifact & Diagnostic Archiving
# -----------------------------------------------------------------------------

# Compress build logs, args.gn, and Siso diagnostic traces into build-artifacts.tar.gz.
# Arguments:
#   $1: Workspace root directory
#   $2: Output build directory (src/out/Release)
archive_build_artifacts() {
  local workspace_dir="${1:-${WORKSPACE_DIR:-}}"
  local out_dir="${2:-${OUT_DIR:-}}"
  local archive_path="${workspace_dir}/build-artifacts.tar.gz"

  echo "Compressing build logs and diagnostic artifacts to ${archive_path}..."
  local entries=()
  if [[ -f "${workspace_dir}/build.log" ]]; then
    entries+=(-C "${workspace_dir}" "build.log")
  fi
  if [[ -d "${out_dir}" ]]; then
    if [[ -f "${out_dir}/args.gn" ]]; then
      entries+=(-C "${out_dir}" "args.gn")
    fi
    if [[ -f "${out_dir}/.ninja_log" ]]; then
      entries+=(-C "${out_dir}" ".ninja_log")
    fi
    for s_file in "${out_dir}"/siso*; do
      if [[ -e "${s_file}" ]]; then
        entries+=(-C "${out_dir}" "$(basename "${s_file}")")
      fi
    done
  fi

  if [[ ${#entries[@]} -gt 0 ]]; then
    tar -czf "${archive_path}" "${entries[@]}" 2>/dev/null || true
    if [[ -f "${archive_path}" ]]; then
      echo " [OK] Packed build artifacts: ${archive_path} ($(du -h "${archive_path}" | cut -f1))"
    fi
  fi
}

# -----------------------------------------------------------------------------
# 7. Graceful Cancellation & CI After-Script Cache Finalization
# -----------------------------------------------------------------------------

# Gracefully terminate any active compilation processes (autoninja/ninja/siso)
# and the background filter pipeline PID if active.
# Arguments:
#   $1: Output build directory (optional, e.g. src/out/Release)
#   $2: Compilation PID (optional, e.g. BUILD_PID)
stop_compiler_processes() {
  local out_dir="${1:-${OUT_DIR:-}}"
  local build_pid="${2:-${BUILD_PID:-}}"

  if [[ -n "${build_pid}" ]]; then
    kill -INT "${build_pid}" 2>/dev/null || true
    kill -TERM "${build_pid}" 2>/dev/null || true
  fi
  if [[ -n "${out_dir}" ]]; then
    pkill -INT -f "autoninja.*${out_dir}" 2>/dev/null || pkill -INT -f "ninja.*${out_dir}" 2>/dev/null || pkill -INT -f "siso.*${out_dir}" 2>/dev/null || true
    sleep 1
    pkill -TERM -f "autoninja.*${out_dir}" 2>/dev/null || pkill -TERM -f "ninja.*${out_dir}" 2>/dev/null || pkill -TERM -f "siso.*${out_dir}" 2>/dev/null || true
  fi
}

# Resolve NATIVELINK_DIR on persistent workspace storage when available so CAS objects
# survive across GitLab CI script/after_script container boundaries.
resolve_nativelink_dir() {
  if [[ -n "${NATIVELINK_DIR:-}" ]]; then
    echo "${NATIVELINK_DIR}"
  elif [[ -n "${WORKSPACE_DIR:-}" ]]; then
    echo "${WORKSPACE_DIR}/nativelink"
  elif [[ -n "${CI_PROJECT_DIR:-}" ]]; then
    echo "${CI_PROJECT_DIR}/build-workspace/nativelink"
  else
    echo "/tmp/nativelink"
  fi
}

# Shared upload_cas_cache handler invoked by platform build scripts on completion,
# failure, watchdog checkpoint, or signal exit.
# When cancelled via SIGTERM/SIGINT inside GitLab CI (exit code 143 or 130),
# stops compiler processes + watchdog + NativeLink cleanly, packs build logs,
# and defers archive/upload to CI after_script so upload isn't killed by Runner timeout.
# Arguments:
#   $1: Exit code captured at trap/invocation (e.g. $? or 0)
shared_upload_cas_cache() {
  local exit_code="${1:-0}"

  if [[ "${CACHE_UPLOADED:-false}" == "true" ]]; then
    return 0
  fi
  CACHE_UPLOADED=true

  if [[ "${DRY_RUN:-false}" == "true" ]]; then
    return 0
  fi

  export NATIVELINK_DIR
  NATIVELINK_DIR="$(resolve_nativelink_dir)"

  # If cancelled via SIGTERM (143) or SIGINT (130), shut down active compilers immediately
  if [[ "${exit_code}" -eq 143 || "${exit_code}" -eq 130 ]]; then
    echo ""
    echo "Build cancelled (signal exit ${exit_code}). Stopping compiler processes and flushing NativeLink..."
    stop_async_prefetch_tasks
    stop_build_watchdog "${WATCHDOG_PID:-}"
    stop_compiler_processes "${OUT_DIR:-}" "${BUILD_PID:-}"
    if [[ -n "${WORKSPACE_DIR:-}" && -n "${OUT_DIR:-}" ]]; then
      archive_build_artifacts "${WORKSPACE_DIR}" "${OUT_DIR}" || true
    fi
    if [[ -f "${REPO_ROOT}/scripts/core/nativelink.sh" ]]; then
      bash "${REPO_ROOT}/scripts/core/nativelink.sh" stop 2>/dev/null || true
    fi
    if [[ -n "${CI:-}" ]]; then
      echo "Deferring CAS cache compression and upload to GitLab CI after_script."
      return 0
    fi
  fi

  echo ""
  echo "Stopping NativeLink daemon and uploading CAS cache..."
  if [[ -f "${REPO_ROOT}/scripts/core/nativelink.sh" ]]; then
    bash "${REPO_ROOT}/scripts/core/nativelink.sh" stop 2>/dev/null || true
  fi
  if [[ -f "${REPO_ROOT}/scripts/core/upload-cache.sh" ]]; then
    bash "${REPO_ROOT}/scripts/core/upload-cache.sh" || true
  fi
}

# Execute post-build cache finalizer in GitLab CI after_script.
# Checks if NativeLink directory contains CAS cache objects and upload has not
# completed yet (e.g. cancelled build); if yes, compresses and uploads to GitLab
# Generic Package Registry; otherwise skips cleanly.
finalize_ci_cache_upload() {
  export NATIVELINK_DIR
  NATIVELINK_DIR="$(resolve_nativelink_dir)"
  local workspace_dir="${WORKSPACE_DIR:-${CI_PROJECT_DIR:-${REPO_ROOT}}/build-workspace}"
  local cas_dir="${NATIVELINK_DIR}/cas"
  local marker="${NATIVELINK_DIR}/.cache_uploaded"

  # Ensure diagnostic build logs are archived even if script was killed abruptly
  if [[ ! -f "${workspace_dir}/build-artifacts.tar.gz" && -f "${workspace_dir}/build.log" ]]; then
    archive_build_artifacts "${workspace_dir}" "${workspace_dir}/src/out/Release" || true
  fi

  echo "========================================================"
  echo " Post-Build CAS Cache Check (NATIVELINK_DIR=${NATIVELINK_DIR})"
  echo "========================================================"

  if [[ -f "${marker}" ]]; then
    echo "CAS cache already uploaded during main script. Skipping."
    return 0
  fi

  if [[ ! -d "${cas_dir}" ]] || [[ -z "$(find "${cas_dir}" -type f 2>/dev/null | head -n 1)" ]]; then
    echo "No CAS cache objects found in ${cas_dir}. Skipping cache upload."
    return 0
  fi

  echo "Found CAS cache objects in ${cas_dir}. Compressing and pushing to GitLab Package Registry..."
  if [[ -f "${REPO_ROOT}/scripts/core/upload-cache.sh" ]]; then
    bash "${REPO_ROOT}/scripts/core/upload-cache.sh" || true
  fi
}

# -----------------------------------------------------------------------------
# 8. GitLab Generic Package Registry Upload Helpers
# -----------------------------------------------------------------------------

# Resolve GitLab API authentication header (PRIVATE-TOKEN preferred over JOB-TOKEN).
resolve_gitlab_auth_header() {
  if [[ -n "${GITLAB_TOKEN:-}" ]]; then
    echo "PRIVATE-TOKEN: ${GITLAB_TOKEN}"
  else
    echo "JOB-TOKEN: ${CI_JOB_TOKEN:-}"
  fi
}

# Resolve rolling CAS package version tag based on target OS and CPU architecture.
# Arguments:
#   $1: Target OS (optional; falls back to TARGET_OS / OS / TARGET_PLATFORM)
#   $2: Target arch (optional; falls back to TARGET_ARCH or arm64)
resolve_cas_cache_version() {
  local target_os="${1:-${TARGET_OS:-${OS:-${TARGET_PLATFORM:-}}}}"
  local target_arch="${2:-${TARGET_ARCH:-arm64}}"
  if [[ -n "${CACHE_VERSION:-}" ]]; then
    echo "${CACHE_VERSION}"
  elif [[ "${target_os}" == "win" || "${target_os}" == "windows" ]]; then
    echo "latest-win-${target_arch}"
  else
    echo "latest-${target_arch}"
  fi
}

# Download all chunk files listed in ./checksums.sha256 in parallel (up to 4 concurrent streams).
# Arguments:
#   $1: Package URL base
#   $2: HTTP auth header
download_chunks_parallel() {
  local pkg_url="$1"
  local auth_header="$2"
  awk '{sub(/^\*/, "", $NF); print $NF}' checksums.sha256 | \
    xargs -P4 -I{} curl --fail --silent --show-error --location --retry 3 --header "${auth_header}" "${pkg_url}/{}" -o "{}"
}

# Delete all existing GitLab Generic Package Registry entries for a given
# package name and version prior to uploading fresh chunks (prevents duplicates).
# Arguments:
#   $1: Package name (e.g. cerium-cas)
#   $2: Package version (e.g. latest-arm64)
#   $3: HTTP auth header (e.g. "JOB-TOKEN: ...")
gitlab_pkg_cleanup_version() {
  local package_name="$1"
  local package_version="$2"
  local auth_header="$3"
  local existing_pkg_ids

  if [[ -z "${CI_API_V4_URL:-}" || -z "${CI_PROJECT_ID:-}" ]]; then
    return 0
  fi

  echo "Checking for existing/partial package entries (${package_name} ${package_version})..."
  existing_pkg_ids=$(curl -sL --header "${auth_header}" \
    "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/packages?package_type=generic&package_name=${package_name}" \
    | python3 -c "import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        print(' '.join(str(p['id']) for p in data if p.get('version') == sys.argv[1]))
except Exception:
    pass" "${package_version}" 2>/dev/null || true)

  for pkg_id in ${existing_pkg_ids}; do
    if [[ -n "${pkg_id}" ]]; then
      echo "Deleting prior package ID ${pkg_id} for ${package_name} (${package_version})..."
      curl -s --request DELETE --header "${auth_header}" \
        "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/packages/${pkg_id}" >/dev/null || true
    fi
  done
}

# Upload a file to a GitLab Generic Package Registry URL, separating the JSON
# response body from --write-out %{http_code} so HTTP status comparison succeeds.
# Arguments:
#   $1: Path to local file to upload
#   $2: Full destination package URL
#   $3: HTTP auth header
gitlab_pkg_upload_file() {
  local file_path="$1"
  local target_url="$2"
  local auth_header="$3"
  local resp_file
  resp_file=$(mktemp)

  local http_code
  http_code=$(curl --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-connrefused \
    --header "${auth_header}" \
    --upload-file "${file_path}" \
    --output "${resp_file}" \
    --write-out "%{http_code}" \
    "${target_url}" || echo "000")

  if [[ "${http_code}" != "200" && "${http_code}" != "201" ]]; then
    echo "ERROR: Upload of $(basename "${file_path}") failed with HTTP ${http_code}." >&2
    if [[ -s "${resp_file}" ]]; then
      echo "Server response: $(cat "${resp_file}")" >&2
    fi
    rm -f "${resp_file}"
    return 1
  fi

  rm -f "${resp_file}"
  echo "Uploaded $(basename "${file_path}") successfully (HTTP ${http_code})."
}

# -----------------------------------------------------------------------------
# 9. Asynchronous In-Runner Build Pre-Fetching Architecture
# -----------------------------------------------------------------------------

_ASYNC_DEPOT_TOOLS_PID=""
_ASYNC_DEPOT_TOOLS_LOG="/tmp/depot_tools_prefetch.log"
_ASYNC_WIN_TOOLCHAIN_PID=""
_ASYNC_WIN_TOOLCHAIN_LOG="/tmp/win_toolchain_prefetch.log"
_ASYNC_NATIVELINK_PID=""
_ASYNC_NATIVELINK_LOG="/tmp/nativelink_prefetch.log"

# Clean up any active background prefetch processes on exit/signal
stop_async_prefetch_tasks() {
  local pids=("${_ASYNC_DEPOT_TOOLS_PID:-}" "${_ASYNC_WIN_TOOLCHAIN_PID:-}" "${_ASYNC_NATIVELINK_PID:-}")
  for pid in "${pids[@]}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
}

# Start asynchronous pre-fetching of depot_tools and git compatibility shim.
# Arguments:
#   $1: Workspace root directory
start_async_depot_tools() {
  local workspace_dir="$1"
  rm -f "${_ASYNC_DEPOT_TOOLS_LOG}"

  if [[ -d "/opt/depot_tools" ]]; then
    DEPOT_TOOLS_DIR="/opt/depot_tools"
    export PATH="${DEPOT_TOOLS_DIR}:${PATH}"
    export DEPOT_TOOLS_UPDATE=0
    ensure_git_compatibility_shim "${workspace_dir}" "${DEPOT_TOOLS_DIR}"
    return 0
  fi

  echo "Spawning asynchronous depot_tools setup in background..."
  (
    ensure_depot_tools "${workspace_dir}"
    ensure_git_compatibility_shim "${workspace_dir}" "${DEPOT_TOOLS_DIR}"
  ) > "${_ASYNC_DEPOT_TOOLS_LOG}" 2>&1 &
  _ASYNC_DEPOT_TOOLS_PID=$!
}

# Wait for asynchronous depot_tools setup to complete and configure PATH.
# Arguments:
#   $1: Workspace root directory
await_async_depot_tools() {
  local workspace_dir="$1"
  if [[ -n "${_ASYNC_DEPOT_TOOLS_PID:-}" ]]; then
    echo "Synchronizing depot_tools background prefetch (PID: ${_ASYNC_DEPOT_TOOLS_PID})..."
    if ! wait "${_ASYNC_DEPOT_TOOLS_PID}"; then
      echo "ERROR: Background depot_tools prefetch failed!" >&2
      if [[ -f "${_ASYNC_DEPOT_TOOLS_LOG}" ]]; then
        cat "${_ASYNC_DEPOT_TOOLS_LOG}" >&2
      fi
      exit 1
    fi
    _ASYNC_DEPOT_TOOLS_PID=""
    echo "depot_tools background prefetch finished successfully."
  fi

  if [[ -d "/opt/depot_tools" ]]; then
    DEPOT_TOOLS_DIR="/opt/depot_tools"
  else
    DEPOT_TOOLS_DIR="${workspace_dir}/depot_tools"
  fi
  export PATH="${DEPOT_TOOLS_DIR}:${PATH}"
  export DEPOT_TOOLS_UPDATE=0
  if [[ -d "${workspace_dir}/git_compat" ]]; then
    export PATH="${workspace_dir}/git_compat:${PATH}"
  fi
}

# Start asynchronous pre-fetching of Windows cross-compilation toolchain.
# Arguments:
#   $1: Repository root directory
#   $2: Workspace root directory
#   $3: Chromium src directory
start_async_win_toolchain() {
  local repo_root="$1"
  local workspace_dir="$2"
  local src_dir="$3"

  if [[ "$(uname -s)" != "Linux"* ]]; then
    return 0
  fi

  local toolchain_dir="${workspace_dir}/win_toolchain_pkg"
  mkdir -p "${toolchain_dir}"
  rm -f "${toolchain_dir}/toolchain.env" "${_ASYNC_WIN_TOOLCHAIN_LOG}"

  echo "Spawning asynchronous Windows toolchain download in background..."
  (
    python3 "${repo_root}/scripts/core/setup-win-toolchain.py" \
      --output-dir="${toolchain_dir}" \
      --src-dir="${src_dir}" \
      --prepare
  ) > "${_ASYNC_WIN_TOOLCHAIN_LOG}" 2>&1 &
  _ASYNC_WIN_TOOLCHAIN_PID=$!
}

# Wait for asynchronous Windows toolchain download to complete and source toolchain.env.
# Arguments:
#   $1: Workspace root directory
await_async_win_toolchain() {
  local workspace_dir="$1"

  if [[ "$(uname -s)" != "Linux"* ]]; then
    return 0
  fi

  if [[ -n "${_ASYNC_WIN_TOOLCHAIN_PID:-}" ]]; then
    echo "Synchronizing Windows toolchain background prefetch (PID: ${_ASYNC_WIN_TOOLCHAIN_PID})..."
    if ! wait "${_ASYNC_WIN_TOOLCHAIN_PID}"; then
      echo "ERROR: Background Windows toolchain prefetch failed!" >&2
      if [[ -f "${_ASYNC_WIN_TOOLCHAIN_LOG}" ]]; then
        cat "${_ASYNC_WIN_TOOLCHAIN_LOG}" >&2
      fi
      exit 1
    fi
    _ASYNC_WIN_TOOLCHAIN_PID=""
    echo "Windows toolchain background prefetch finished successfully."
  fi

  local toolchain_env="${workspace_dir}/win_toolchain_pkg/toolchain.env"
  if [[ ! -f "${toolchain_env}" ]]; then
    echo "ERROR: Toolchain generation completed but fresh output archive was not produced." >&2
    exit 1
  fi

  # shellcheck disable=SC1090
  source "${toolchain_env}"
  echo "Windows toolchain configured: GYP_MSVS_HASH=${GYP_MSVS_HASH:-}"
}

# Start asynchronous pre-fetching of NativeLink binary and CAS cache restore.
# Arguments:
#   $1: Repository root directory
#   $2: Workspace root directory
start_async_nativelink_cache() {
  local repo_root="$1"
  local workspace_dir="$2"
  rm -f "${_ASYNC_NATIVELINK_LOG}"

  echo "Spawning asynchronous NativeLink & CAS cache prefetch in background..."
  (
    if [[ -f "${repo_root}/scripts/core/nativelink.sh" ]]; then
      bash "${repo_root}/scripts/core/nativelink.sh" install
    fi
    if [[ -f "${repo_root}/scripts/core/download-cache.sh" ]]; then
      bash "${repo_root}/scripts/core/download-cache.sh" || true
    fi
  ) > "${_ASYNC_NATIVELINK_LOG}" 2>&1 &
  _ASYNC_NATIVELINK_PID=$!
}

# Wait for asynchronous NativeLink binary and CAS cache restore to complete.
await_async_nativelink_cache() {
  if [[ -n "${_ASYNC_NATIVELINK_PID:-}" ]]; then
    echo "Synchronizing NativeLink & CAS cache background prefetch (PID: ${_ASYNC_NATIVELINK_PID})..."
    if ! wait "${_ASYNC_NATIVELINK_PID}"; then
      echo "WARNING: Background NativeLink/CAS cache prefetch completed with non-zero exit code." >&2
      if [[ -f "${_ASYNC_NATIVELINK_LOG}" ]]; then
        cat "${_ASYNC_NATIVELINK_LOG}" >&2
      fi
    else
      echo "NativeLink & CAS cache background prefetch finished successfully."
    fi
    _ASYNC_NATIVELINK_PID=""
  fi
}
