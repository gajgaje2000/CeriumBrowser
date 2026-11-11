# Building Cerium Browser

This guide describes how to build Cerium Browser from source in a clean environment.

---

## 1. System Requirements & Prerequisites

### Hardware
- **Operating System**: Linux (Ubuntu 22.04 / 24.04 or Debian 12 recommended)
- **RAM**: Minimum 32 GB (64 GB strongly recommended for parallel linking)
- **Disk Space**: At least 150 GB of free space on a fast SSD (ext4/btrfs)
- **CPU**: Multi-core (8+ cores / 16+ threads recommended)

### Software & Toolchains
- `git` (2.35+)
- `python3` (3.10+) and `python3-yaml` (install testing dependencies via `pip install -r requirements-dev.txt`)
- `node` (>= 24.16.0) and `pnpm` (>= 11.11.0)
- `openjdk-17-jdk`
- `curl`, `patch`, `ninja-build`

---

## 2. Environment Setup

Set up a dedicated Chromium / Brave project directory:

```bash
export WORKSPACE_DIR="${HOME}/cerium-workspace"
export CERIUM_DIR="${WORKSPACE_DIR}/Cerium"
export BRAVING_DIR="${CERIUM_DIR}"
export SRC_DIR="${WORKSPACE_DIR}/src"
```

Clone the Cerium repository:
```bash
git clone https://gitlab.com/CeriumBrowser/Cerium-Browser.git "${CERIUM_DIR}"
```

---

## 3. Version Selection & Source Preparation (Phase 1)

Select the target Brave version or omit to resolve latest upstream stable automatically:

```bash
cd "${CERIUM_DIR}"
./scripts/core/prepare-source.sh
# Or specify a target version:
# ./scripts/core/prepare-source.sh <version>
```

What `prepare-source.sh` performs:
1. Dynamically resolves latest stable Brave version from GitHub API and Google Gitiles.
2. Generates `metadata/upstream-<version>.yaml` and release manifest at `metadata/releases/<version>.yaml`, exporting environment to `build.env`.
3. Fetches `brave-core` at exact release commit (`--depth 1` zero-history clone/checkout).
4. Applies Cerium unified patches (`patches/common/` and platform patches) via `apply-patches.sh`.
5. Verifies patch set integrity (`apply-patches.sh --check`) ensuring all patches apply cleanly.
6. Executes programmatic Python mutators and Cerium branding overlays (`apply-features.py`, `apply-assets.sh`, `apply-branding.py`).
7. Prepares `build-workspace/src/brave` in place for immediate compilation or GitLab CI pipeline runner cache transfer.

---

## 4. Building Cerium (Quick Start)

Cerium provides a unified build entry point for all platforms:

```bash
cd "${CERIUM_DIR}"

# Build Android (arm64):
./scripts/build.sh android

# Build Windows (x64):
./scripts/build.sh windows_x64

# Build Windows (arm64):
./scripts/build.sh windows_arm64

# Build All Targets:
./scripts/build.sh all
```

### Building in the Official CI Container (Podman / Docker)

You can run identical builds inside the reproducible builder container locally with one command:

```bash
# Open interactive shell in builder container:
./scripts/run-container.sh

# Or run a build command directly:
./scripts/run-container.sh ./scripts/build.sh android
```

### Local Developer Overrides (`local.env`)

To customize settings (e.g. Siso cache flags, debug options, compiler paths) without modifying tracked repository files, create a `local.env` at the repository root (ignored by git):

```bash
# Example local.env:
export CERIUM_BUILD_TIMEOUT_DEFAULT="18000"
export CERIUM_LOG_STEP_INTERVAL="5"
```

### Creating Downstream Patches

To export changes made to a working checkout into a clean `.patch` file:

```bash
./scripts/core/create-patch.sh build-workspace/src/brave common my-new-feature.patch
```
After creating the patch, document it in `patches/patches.yaml`.

---

## 5. Declarative Build Arguments (`configs/gn/`)

Build arguments are declared in modular `.gni` files under `configs/gn/` rather than hardcoded in shell scripts:
- `configs/gn/common.gni`: Base optimization, symbols, official release settings.
- `configs/gn/debloat.gni`: Overridden service keys, analytics, ads, and telemetry endpoints.
- `configs/gn/android.gni`: Android architecture, channels, and package IDs.
- `configs/gn/windows.gni`: Windows targets and toolchains.

---

## 6. Master Verification Suite

Run all verification tiers (171 tests, syntax checks, patch validation, and build dry-runs):
```bash
./scripts/core/verify-all.sh
```

---

## 7. Standalone APK Release Signing

To sign an existing or newly compiled APK using release credentials:
```bash
./scripts/platforms/android/package.sh --apk="out/apks/Cerium-<version>-arm64.apk"
```

---

## 7. Troubleshooting

- **Out of Memory during linking**:
  `args.gn` already configures `symbol_level = 0` to minimize linker memory pressure.
- **GitLab CI 4MB log truncation**:
  `build-android.sh` automatically routes compilation stdout through `filter-build-log.py`, throttling step progress while passing 100% of compiler errors and warnings unbuffered.

