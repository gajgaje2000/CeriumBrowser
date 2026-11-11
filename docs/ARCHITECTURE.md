# Cerium Browser System Architecture & Modular Design

Cerium is an independent, customized, fully de-branded, debloated, and privacy-hardened downstream distribution of the Brave Browser. It is designed to be built dynamically against upstream Brave and Chromium releases without maintaining a permanent, unwieldy hard-forked Git repository.

---

## 1. Modular Repository Architecture

The repository is organized into distinct, decoupled subsystems with strict separation of concerns:

```
Cerium Repository Structure
├── configs/                        # [Declarative Configuration Center]
│   ├── versions.env                # Pinned toolchain revisions (GN, depot_tools, NativeLink)
│   └── gn/                         # Modular GN configurations (replaces inline bash heredocs)
│       ├── common.gni              # Baseline release & optimization arguments
│       ├── debloat.gni             # Debloated service keys & telemetry suppression
│       ├── android.gni             # Android target arguments, ABIs, and package ID
│       └── windows.gni             # Windows target arguments & toolchain settings
│
├── overlays/                       # [Universal Mirror Trees]
│   └── brave/                      # Directly mirrors brave-core directory layout
│
├── branding/                       # [Module 1] Brand Identity & Assets
│   ├── logo.svg                    # Master vector identity
│   ├── android/                    # Adaptive & themed vector drawables
│   │   ├── drawable/               # 10 core vector logo drawables
│   │   ├── res_brave_base/         # Adaptive launcher & Android 13+ themed icons
│   │   └── shields_drawables/      # Dedicated Cerium Shields toolbar icons (24dp)
│   └── brave-core-static/          # 156 density PNGs & 10 static SVGs for brave-core
│
├── patches/                        # [Module 2 & 3] Standard Unified Patches
│   ├── patches.yaml                # Declarative patch catalog (name, category, reason, effect)
│   ├── common/                     # Cross-platform core C++ & shared BRANDING
│   │   ├── cerium-branding.patch             # Core release BRANDING metadata
│   │   ├── custom-updater-endpoint.patch     # Custom updater & telemetry suppression
│   │   ├── enforce-enterprise-policies.patch # Mandatory enterprise policies
│   │   ├── hide-brave-origin-flag.patch      # Hide origin feature flag
│   │   └── unlock-brave-origin-backend.patch # Unlock backend policy state
│   ├── desktop/                    # Desktop Views UI (Windows, macOS, Linux)
│   │   └── brave-origin-paywall-bypass.patch # Bypass modal paywall view
│   └── android/                    # Android Java & XML resources
│       ├── cerium-branding.patch             # Channel constants & package ID
│       ├── disable-play-in-app-update.patch  # Disable Play Store updates
│       ├── remove-rate-brave.patch           # Remove rating dialogs & menu
│       └── unlock-brave-origin-prefs.patch   # Android origin preferences
│
├── scripts/                        # Operational Scripts & Mutators
│   ├── build.sh                    # Unified developer build entrypoint (android | windows | all)
│   ├── run-container.sh            # Local container runner (podman/docker in CI builder)
│   ├── core/                       # Shared Cross-Platform Scripts
│   │   ├── build-common.sh         # [Module 4] Shared cross-platform build orchestration library
│   │   ├── generate-gn-args.py     # Declarative GN configuration renderer
│   │   ├── apply-overlays.sh       # Universal recursive mirror overlay engine
│   │   ├── create-patch.sh         # Git patch generation helper
│   │   ├── setup-win-toolchain.py  # [Module 4] Hermetic Windows toolchain download & environment setup
│   │   ├── prepare-source.sh       # Dynamic resolution, checkout, patch apply & check, mutators, pipeline cache tarball
│   │   ├── apply-patches.sh        # Unified patch applier with patches.yaml metadata support
│   │   ├── apply-features.py       # [Module 2] Programmatic GN array mutator
│   │   ├── apply-branding.py       # [Module 1] GRD/GRDP string & XTB translation mutator
│   │   ├── apply-assets.sh         # [Module 1] Static asset overlay deployment
│   │   ├── filter-build-log.py     # [Module 4] Real-time CI 4MB stream log filter & heartbeat
│   │   ├── verify-branding.sh      # [Module 1] Standalone branding verification
│   │   ├── verify-all.sh           # [Module 7] Master verification suite
│   │   ├── download-cache.sh       # [Module 6] Generic Package Registry cache restore & Siso sync
│   │   └── upload-cache.sh         # [Module 6] Generic Package Registry cache chunker & upload
│   ├── mutators/                   # Programmatic Mutators Subsystem
│   │   ├── common/                 # Shared cross-platform mutators
│   │   └── platforms/              # Platform-specific mutators & templates
│   │       ├── android/            # Android UI & toolbar mutators
│   │       └── windows/            # Windows branding, installer & templates
│   │           └── templates/      # Standalone C++ templates (version_updater_win.cc)
│   ├── platforms/                  # Modular Platform Build Entry Points
│   │   ├── android/                # Android build and packaging (build.sh, package.sh)
│   │   └── windows/                # Windows build and packaging (build.sh, package.sh)
│   ├── ci/                         # CI Automation Scripts
│   │   ├── check-release-needed.sh # Release tag verification for publish stage
│   │   └── publish-release-direct.sh# Direct release creation via GitLab Releases API
│   └── tests/                      # [Module 7] Automated Unit & Integration Tests
│       ├── test_manifest.py        # Manifest schema & package_id verification
│       ├── test_branding.py        # Asset dimensions, XML syntax, AAPT2 string limits
│       ├── test_mutators.py        # Python 3.11 syntax, mutator idempotence, patch checks
│       ├── test_win_toolchain.py   # Windows toolchain candidates, SetEnv & environment tests
│       ├── test_ci_automation.py   # CI shell scripts & contract validation
│       └── test_cache_scripts.py   # Siso timestamp sync & script syntax tests
│
├── metadata/                       # Upstream Revisions & Release Manifests
│   ├── releases/*.yaml             # Generated release manifests (package_id, commits, arch)
│   └── upstream-*.yaml             # Pinned upstream repositories & GN base arguments
│
└── docs/                           # Architecture, Building, and Release Documentation
```

---

## 2. Separation of Concerns

### Module 1: Branding Assets & Localization
- **Assets (`branding/` & `apply-assets.sh`)**: Houses all visual assets. `apply-assets.sh` performs zero dynamic rendering at build time; it copies 100% pre-validated static raster PNGs, SVGs, and Android XML drawables directly into the appropriate resource overlays.
- **Strings (`apply-branding.py`)**: Parses GRD/GRDP XML message definitions safely without naive global regex substitutions. Computes Grit 63-bit fingerprints and remaps XTB translation IDs across all supported locales.
- **Verification (`verify-branding.sh` & `test_branding.py`)**: Enforces AAPT2 ResStringPool limits (<32,767 bytes), intrinsic dimensions (e.g. 24dp for toolbar shields), and verifies the complete absence of upstream Brave lion vector paths.

### Module 2: Enterprise Policies & Radical Debloating
- Rather than maintaining fragile GN build flags that break upstream compiler trees, Cerium compiles modules cleanly but disables them unconditionally via Enterprise Policies.
- `patches/common/enforce-enterprise-policies.patch` injects mandatory policies at browser start:
  - `BraveWalletDisabled = true`
  - `BraveVPNDisabled = true`
  - `BraveAIChatEnabled = false`
  - `BraveNewsDisabled = true`
  - `BraveRewardsDisabled = true`
  - `BraveSearchResultAdsEnabled = false`
  - `BraveStatsPingEnabled = false`
  - `BraveP3AEnabled = false`
  - `BraveWebDiscoveryEnabled = false`
  - `MetricsReportingEnabled = false`
- `apply-features.py` isolates Polymer and WebUI resources so Android builds do not transpile unused desktop-only frontend bundles.

### Module 3: Component Updater & Privacy
- `patches/common/0002-custom-updater-endpoint.patch` points component updates to `https://ceriumbrowser.gitlab.io/cerium-updater/components`.
- Verifies custom Cerium publisher key hashes (`kCeriumPublisherKeyHash`).
- Batches update checks and appends `disable-pings` to component updater invocations.

### Module 4: Release Build Orchestration & Shared Core
- **Shared Build Core (`scripts/core/build-common.sh`)**: Centralizes cross-platform orchestration functions to prevent copy-paste drift:
  - Manifest property parsing (`extract_manifest_val`)
  - Toolchain compatibility (`ensure_git_compatibility_shim`, `ensure_depot_tools`, `ensure_host_c_compiler`, `ensure_gn_binary`)
  - Chromium checkout, `.gclient` generation, sync & patching (`fetch_chromium_git`, `init_clean_chromium_source`, `write_gclient_config`, `sync_and_patch_chromium`, `prepare_brave_branding_and_version`)
  - GN debloating, Siso/REAPI config, compilation, & watchdog (`append_debloated_service_gn_args`, `configure_siso_environment`, `start_build_watchdog`, `stop_build_watchdog`, `run_siso_compilation`)
  - Cross-container NativeLink & GitLab Package Registry helpers (`resolve_nativelink_dir`, `shared_upload_cas_cache`, `finalize_ci_cache_upload`, `resolve_gitlab_auth_header`, `resolve_cas_cache_version`, `download_chunks_parallel`, `gitlab_pkg_cleanup_version`, `gitlab_pkg_upload_file`)
  - Build diagnostics and artifact packaging (`archive_build_artifacts`)
- **Windows Toolchain Centralization (`scripts/core/setup-win-toolchain.py`)**:
  - Encapsulates candidate hash resolution, archive checksumming, extraction, xwin layout generation, and SetEnv manifest generation.
  - Outputs a sourced `toolchain.env` configuration consumed by `scripts/platforms/windows/build.sh`.
- Platform build scripts (`scripts/platforms/android/build.sh`, `scripts/platforms/windows/build.sh`) focus strictly on target-specific GN flags and compilation:
  - `is_debug = false`, `is_official_build = true`, `is_java_debug = false`
  - `symbol_level = 0`, `blink_symbol_level = 0`, `v8_symbol_level = 0`
  - `dcheck_always_on = false`, `enable_java_asserts = false`
  - `exclude_unwind_tables = true`
  - `target_android_output_format = "apk"`
- Build output streams through `scripts/core/filter-build-log.py`, which throttles progress lines (`[50/43210 (0.1%)]`) while immediately flushing 100% of compiler errors, warnings, and failure diagnostics to stdout, fully preventing GitLab CI's 4MB console log truncation limit.

### Module 5: Standalone Release Packaging & Signing
- Platform package scripts (`scripts/platforms/android/package.sh`, `scripts/platforms/windows/package.sh`) operate as independent modules.
- For Android: Strips any intermediate debug v1 signatures, zipaligns APKs to 4-byte boundaries, signs with APK Signature Schemes v1/v2/v3, and verifies cryptographically with `apksigner verify`.
- For Windows: Packages binary outputs into versioned release archives.

### Module 6: Distributed CI Caching (Siso-Aware)
- Chromium compilation involves >43,000 steps. Cerium splits compilation across CI stages and bridges them via GitLab Generic Package Registry.
- `scripts/core/upload-cache.sh` splits the `out/Release` directory into 4.5 GB chunks with SHA256 checksums.
- `scripts/core/download-cache.sh` streams and extracts the cache, removing `build.ninja.d` to prevent spurious manifest regeneration.
- Timestamp synchronization enforces:
  $$T_{\text{source}} \le T_{\text{manifest}} < T_{\text{output}}$$
  ensuring Siso's `inmtime.After(outmtime)` condition evaluates to false, preserving pre-built objects and command hashes.

### Module 7: Master Verification Suite
- `scripts/core/verify-all.sh` orchestrates:
  1. Manifest & upstream metadata schema validation (`test_manifest.py`)
  2. Python 3.11+ syntax compatibility, toolchain & mutator unit tests (`test_mutators.py`, `test_win_toolchain.py`, `test_ci_automation.py`, `test_cache_scripts.py`)
  3. Patch application validation against `brave-core`
  4. Visual branding and AAPT2 asset verification (`verify-branding.sh`, `test_branding.py`)
  5. Multi-platform build and packaging orchestration dry-runs

