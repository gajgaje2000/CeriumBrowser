#!/usr/bin/env python3
"""
Unit and integration tests for Cerium Siso warm cache pipeline:
- scripts/upload-cache.sh
- scripts/download-cache.sh
- scripts/android/build-android.sh
"""

import http.server
import os
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestCacheScriptsSyntax(unittest.TestCase):
    """Verify shell script syntax using bash -n."""

    def test_upload_cache_syntax(self):
        script = REPO_ROOT / "scripts" / "core" / "upload-cache.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_download_cache_syntax(self):
        script = REPO_ROOT / "scripts" / "core" / "download-cache.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_build_android_syntax(self):
        script = REPO_ROOT / "scripts" / "platforms" / "android" / "build.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_package_android_syntax(self):
        script = REPO_ROOT / "scripts" / "platforms" / "android" / "package.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_build_windows_syntax(self):
        script = REPO_ROOT / "scripts" / "platforms" / "windows" / "build.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_package_windows_syntax(self):
        script = REPO_ROOT / "scripts" / "platforms" / "windows" / "package.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_prepare_source_syntax(self):
        script = REPO_ROOT / "scripts" / "core" / "prepare-source.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")

    def test_nativelink_syntax(self):
        script = REPO_ROOT / "scripts" / "core" / "nativelink.sh"
        res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Syntax error in {script}: {res.stderr}")


class TestSisoCachePipeline(unittest.TestCase):
    """Verify NativeLink CAS cache configuration, packaging, chunk extraction, and immediate disk cleanup."""

    def test_nativelink_config_structure(self):
        """Verify .gitlab/ci/nativelink.json is valid JSON and declares CAS and AC stores with 127.0.0.1:50051."""
        import json
        config_path = REPO_ROOT / ".gitlab" / "ci" / "nativelink.json"
        self.assertTrue(config_path.exists(), "nativelink.json must exist")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        self.assertIn("stores", cfg)
        store_names = [s.get("name") for s in cfg["stores"]]
        self.assertIn("CAS_MAIN_STORE", store_names)
        self.assertIn("AC_MAIN_STORE", store_names)

        # Eviction policy limits
        cas_store = next(s for s in cfg["stores"] if s.get("name") == "CAS_MAIN_STORE")
        self.assertIn("filesystem", cas_store)
        self.assertEqual(cas_store["filesystem"]["content_path"], "/tmp/nativelink/cas/content")
        self.assertIn("eviction_policy", cas_store["filesystem"])
        self.assertIn(cas_store["filesystem"]["eviction_policy"]["max_bytes"], ["40gb", "40GB", 40000000000])

        # Server listener
        self.assertIn("servers", cfg)
        server = cfg["servers"][0]
        self.assertEqual(server["listener"]["http"]["socket_address"], "127.0.0.1:50051")
        services = server.get("services", {})
        self.assertIn("cas", services)
        self.assertIn("ac", services)
        self.assertIn("bytestream", services)

    def test_cas_cache_packaging_and_immediate_cleanup(self):
        """
        Verify that CAS cache packaging, chunking, sha256 checksum generation,
        extraction into /tmp/nativelink, and immediate chunk cleanup work end-to-end.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            nativelink_dir = tmp_path / "nativelink"
            cas_dir = nativelink_dir / "cas" / "content"
            ac_dir = nativelink_dir / "ac" / "content"
            cas_dir.mkdir(parents=True)
            ac_dir.mkdir(parents=True)

            # Create sample CAS objects and AC metadata
            blob1 = cas_dir / "0123456789abcdef"
            blob1.write_bytes(b"blob data 1" * 1000)
            blob2 = cas_dir / "fedcba9876543210"
            blob2.write_bytes(b"blob data 2" * 1000)
            ac_entry = ac_dir / "action_result_01"
            ac_entry.write_bytes(b"action metadata" * 100)

            # 1. Simulate upload-cache.sh packaging and chunking
            upload_tmp = tmp_path / "upload_tmp"
            upload_tmp.mkdir()
            tar_cmd = (
                f"tar -czf - -C '{nativelink_dir}' cas ac | split -b 50k - '{upload_tmp}/chunk.tar.gz.'"
            )
            subprocess.run(["bash", "-c", tar_cmd], check=True)

            chunks = sorted(upload_tmp.glob("chunk.tar.gz.*"))
            self.assertGreaterEqual(len(chunks), 1, "Must generate at least one chunk")

            # Checksums generation
            checksums_file = upload_tmp / "checksums.sha256"
            subprocess.run(
                f"cd '{upload_tmp}' && sha256sum chunk.tar.gz.* > checksums.sha256",
                shell=True,
                check=True,
            )
            self.assertTrue(checksums_file.exists())

            # 2. Simulate download-cache.sh extraction into a fresh directory
            restore_nativelink = tmp_path / "restored_nativelink"
            restore_nativelink.mkdir()

            download_tmp = tmp_path / "download_tmp"
            download_tmp.mkdir()
            # Copy chunks and checksums to simulate download
            for c in chunks:
                (download_tmp / c.name).write_bytes(c.read_bytes())
            (download_tmp / "checksums.sha256").write_bytes(checksums_file.read_bytes())

            # Verify checksums
            verify_res = subprocess.run(
                ["sha256sum", "-c", "checksums.sha256"],
                cwd=download_tmp,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify_res.returncode, 0, f"Checksum verification failed: {verify_res.stderr}")

            # Extract into restore_nativelink
            extract_cmd = f"cat chunk.tar.gz.* | tar -xzf - -C '{restore_nativelink}'"
            subprocess.run(["bash", "-c", extract_cmd], cwd=download_tmp, check=True)

            # Immediate cleanup (the core 200 GB runner constraint)
            for c in download_tmp.glob("chunk.tar.gz.*"):
                c.unlink()

            remaining_chunks = list(download_tmp.glob("chunk.tar.gz.*"))
            self.assertEqual(len(remaining_chunks), 0, "All chunks must be immediately deleted after extraction")

            # Verify restored files match originals
            restored_blob1 = restore_nativelink / "cas" / "content" / "0123456789abcdef"
            restored_blob2 = restore_nativelink / "cas" / "content" / "fedcba9876543210"
            restored_ac = restore_nativelink / "ac" / "content" / "action_result_01"

            self.assertTrue(restored_blob1.exists(), "blob1 must be restored in cas/content")
            self.assertTrue(restored_blob2.exists(), "blob2 must be restored in cas/content")
            self.assertTrue(restored_ac.exists(), "action metadata must be restored in ac/content")
            self.assertEqual(restored_blob1.read_bytes(), blob1.read_bytes())
            self.assertEqual(restored_blob2.read_bytes(), blob2.read_bytes())
            self.assertEqual(restored_ac.read_bytes(), ac_entry.read_bytes())

    def test_nativelink_daemon_manager_cli(self):
        """Verify scripts/core/nativelink.sh CLI argument validation."""
        script = REPO_ROOT / "scripts" / "core" / "nativelink.sh"
        res = subprocess.run(["bash", str(script), "invalid_arg"], capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Usage:", res.stderr)

    def test_download_cache_force_cache_rebuild(self):
        """Verify FORCE_CACHE_REBUILD skips registry download, cleans CAS store, and exits 0."""
        script = REPO_ROOT / "scripts" / "core" / "download-cache.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_nativelink = Path(tmpdir) / "nativelink"
            old_cas = fake_nativelink / "cas" / "content"
            old_cas.mkdir(parents=True)
            (old_cas / "stale_blob").write_text("stale data")

            env = os.environ.copy()
            env["FORCE_CACHE_REBUILD"] = "true"
            env["NATIVELINK_DIR"] = str(fake_nativelink)
            env["CI_API_V4_URL"] = "https://gitlab.example.com/api/v4"
            env["CI_JOB_TOKEN"] = "fake-token"
            env["CI_PROJECT_ID"] = "123"

            res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"download-cache failed: {res.stderr}")
            self.assertIn("FORCE_CACHE_REBUILD is set to true", res.stdout)
            self.assertIn("Skipping CAS cache download", res.stdout)
            self.assertFalse((old_cas / "stale_blob").exists())
            self.assertTrue((fake_nativelink / "cas" / "content").is_dir())
            self.assertTrue((fake_nativelink / "cas" / "tmp").is_dir())
            self.assertTrue((fake_nativelink / "ac" / "content").is_dir())
            self.assertTrue((fake_nativelink / "ac" / "tmp").is_dir())

    def test_download_cache_missing_ci_vars(self):
        """Verify download-cache.sh skips cleanly when GitLab CI environment variables are absent."""
        script = REPO_ROOT / "scripts" / "core" / "download-cache.sh"
        env = {k: v for k, v in os.environ.items() if not k.startswith("CI_")}
        env["FORCE_CACHE_REBUILD"] = "false"
        res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("GitLab CI API variables not set. Skipping cache download.", res.stdout)

    def test_upload_cache_missing_ci_vars(self):
        """Verify upload-cache.sh skips cleanly when GitLab CI environment variables are absent."""
        script = REPO_ROOT / "scripts" / "core" / "upload-cache.sh"
        env = {k: v for k, v in os.environ.items() if not k.startswith("CI_")}
        res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("GitLab CI API variables not set. Skipping cache upload.", res.stdout)

    def test_build_scripts_upload_cache_on_failure_wiring(self):
        """Verify android/windows build.sh and shared build-common.sh upload CAS cache before failure exit and on trap."""
        common_content = (REPO_ROOT / "scripts" / "core" / "build-common.sh").read_text(encoding="utf-8")
        idx_upload = common_content.find("upload_cas_cache 0")
        idx_build_res = common_content.find("if [[ ${BUILD_RES} -ne 0 ]]; then")
        self.assertTrue(
            0 <= idx_upload < idx_build_res,
            "build-common.sh::run_siso_compilation must invoke upload_cas_cache before checking BUILD_RES -ne 0",
        )
        self.assertIn("CHECKPOINT_TRIGGERED", common_content, "Missing CHECKPOINT_TRIGGERED in build-common.sh")
        self.assertIn("exit 42", common_content, "Missing exit 42 in build-common.sh")
        self.assertIn('SISO_PROJECT="rbe-chromium-untrusted"', common_content, "Missing SISO_PROJECT export in build-common.sh")
        self.assertIn('SISO_PROJECT=rbe-chromium-untrusted', common_content, "Missing SISO_PROJECT in .sisoenv template")

        for build_script in [
            REPO_ROOT / "scripts" / "platforms" / "android" / "build.sh",
            REPO_ROOT / "scripts" / "platforms" / "windows" / "build.sh",
        ]:
            content = build_script.read_text(encoding="utf-8")
            self.assertIn("upload_cas_cache()", content, f"Missing upload_cas_cache in {build_script}")
            self.assertIn("trap 'upload_cas_cache' EXIT", content, f"Missing EXIT trap in {build_script}")
            self.assertIn("trap 'exit 143' TERM", content, f"Missing TERM trap in {build_script}")
            self.assertIn("trap 'exit 130' INT", content, f"Missing INT trap in {build_script}")
            self.assertIn("configure_siso_environment", content, f"Missing configure_siso_environment call in {build_script}")
            self.assertIn("run_siso_compilation", content, f"Missing run_siso_compilation call in {build_script}")

    def test_build_scripts_sisorc_configuration(self):
        """Verify build-common.sh configures Siso .sisorc with remote caching flags and no local cache."""
        common_content = (REPO_ROOT / "scripts" / "core" / "build-common.sh").read_text(encoding="utf-8")
        self.assertIn("-re_exec_enable=false", common_content, "Missing -re_exec_enable=false in build-common.sh")
        self.assertIn("-re_cache_enable_read=true", common_content, "Missing -re_cache_enable_read=true in build-common.sh")
        self.assertIn("-re_cache_enable_write=true", common_content, "Missing -re_cache_enable_write=true in build-common.sh")
        self.assertIn("-config googlechrome", common_content, "Missing -config googlechrome in build-common.sh")
        self.assertNotIn("-local_cache_enable", common_content, "Unexpected -local_cache_enable in build-common.sh")
        self.assertNotIn("SISO_CACHE_DIR", common_content, "Unexpected SISO_CACHE_DIR in build-common.sh")
        self.assertNotIn("SISO_LOCAL_CACHE_DIR", common_content, "Unexpected SISO_LOCAL_CACHE_DIR in build-common.sh")
        expected_sisorc_line = (
            "ninja -fs_keep_tainted -re_exec_enable=false -re_cache_enable_read=true "
            "-re_cache_enable_write=true -config googlechrome"
        )
        self.assertIn(expected_sisorc_line, common_content, "Exact .sisorc line missing in build-common.sh")

        for build_script in [
            REPO_ROOT / "scripts" / "platforms" / "android" / "build.sh",
            REPO_ROOT / "scripts" / "platforms" / "windows" / "build.sh",
        ]:
            content = build_script.read_text(encoding="utf-8")
            self.assertIn("configure_siso_environment", content, f"Missing configure_siso_environment call in {build_script}")
            self.assertNotIn("-local_cache_enable", content, f"Unexpected -local_cache_enable in {build_script}")
            self.assertNotIn("SISO_CACHE_DIR", content, f"Unexpected SISO_CACHE_DIR in {build_script}")
            self.assertNotIn("SISO_LOCAL_CACHE_DIR", content, f"Unexpected SISO_LOCAL_CACHE_DIR in {build_script}")

    def test_nativelink_resilient_download_options(self):
        """Verify nativelink.sh uses robust curl retries, connection timeouts, and archive integrity checks."""
        script = REPO_ROOT / "scripts" / "core" / "nativelink.sh"
        content = script.read_text(encoding="utf-8")
        self.assertIn("--retry 5", content, "nativelink.sh must retry downloads 5 times")
        self.assertIn("--retry-delay 3", content, "nativelink.sh must use retry-delay 3")
        self.assertIn("--retry-connrefused", content, "nativelink.sh must handle refused connections")
        self.assertIn("--connect-timeout 20", content, "nativelink.sh must configure connect-timeout")
        self.assertIn("--max-time 180", content, "nativelink.sh must configure max-time")
        self.assertIn("tar -tzf", content, "nativelink.sh must validate archive integrity prior to extraction")
        self.assertIn("Runner Host Architecture", content, "nativelink.sh must clearly display host runner architecture")

    def test_build_scripts_host_runner_logging(self):
        """Verify android and windows build scripts log runner host architecture vs target CPU."""
        for build_script in [
            REPO_ROOT / "scripts" / "platforms" / "android" / "build.sh",
            REPO_ROOT / "scripts" / "platforms" / "windows" / "build.sh",
        ]:
            content = build_script.read_text(encoding="utf-8")
            self.assertIn(
                'Starting in-runner NativeLink host daemon on 127.0.0.1:50051 (host: $(uname -m), target: ${TARGET_ARCH})...',
                content,
                f"Missing host runner architecture logging in {build_script}",
            )

    def test_upload_cache_cleans_prior_package_version_wiring(self):
        """Verify upload-cache.sh uses shared gitlab_pkg_cleanup_version to delete prior package versions."""
        common_content = (REPO_ROOT / "scripts" / "core" / "build-common.sh").read_text(encoding="utf-8")
        self.assertIn("packages?package_type=generic&package_name=${package_name}", common_content)
        self.assertIn("curl -s --request DELETE", common_content)
        self.assertIn("Deleting prior package ID", common_content)
        self.assertIn("Checking for existing/partial package entries (${package_name} ${package_version})", common_content)

        script_content = (REPO_ROOT / "scripts" / "core" / "upload-cache.sh").read_text(encoding="utf-8")
        self.assertIn('gitlab_pkg_cleanup_version "cerium-cas"', script_content)

    def test_cache_scripts_auth_header_support(self):
        """Verify upload-cache.sh and download-cache.sh use shared resolve_gitlab_auth_header helper."""
        common_content = (REPO_ROOT / "scripts" / "core" / "build-common.sh").read_text(encoding="utf-8")
        self.assertIn('echo "JOB-TOKEN: ${CI_JOB_TOKEN:-}"', common_content)
        self.assertIn('echo "PRIVATE-TOKEN: ${GITLAB_TOKEN}"', common_content)

        for script_name in ["upload-cache.sh", "download-cache.sh"]:
            content = (REPO_ROOT / "scripts" / "core" / script_name).read_text(encoding="utf-8")
            self.assertIn("resolve_gitlab_auth_header", content, f"{script_name} must call resolve_gitlab_auth_header")

    def test_upload_cache_empty_cas_skipped(self):
        """Verify upload-cache.sh skips cleanly without attempting uploads when CAS store has no objects."""
        script = REPO_ROOT / "scripts" / "core" / "upload-cache.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_nativelink = Path(tmpdir) / "nativelink"
            (fake_nativelink / "cas" / "content").mkdir(parents=True)
            env = os.environ.copy()
            env["CI_API_V4_URL"] = "https://gitlab.example.com/api/v4"
            env["CI_JOB_TOKEN"] = "fake-token"
            env["CI_PROJECT_ID"] = "123"
            env["NATIVELINK_DIR"] = str(fake_nativelink)
            res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertIn("No CAS cache objects found", res.stdout)
            self.assertIn("Skipping cache upload", res.stdout)

    def test_signal_trap_exit_behavior(self):
        """Verify that the trap 'upload_cas_cache' EXIT + trap 'exit 143' TERM terminates on SIGTERM."""
        import signal
        code = """
upload_cas_cache() {
    echo 'UPLOAD_CALLED'
}
trap 'upload_cas_cache' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

sleep 5
echo 'UNREACHABLE'
"""
        proc = subprocess.Popen(["bash", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 143)
        self.assertIn("UPLOAD_CALLED", out)
        self.assertNotIn("UNREACHABLE", out)

    def test_after_script_finalizer_skips_if_empty_or_uploaded(self):
        """Verify finalize_ci_cache_upload skips cleanly when CAS is empty or .cache_uploaded marker exists."""
        build_common = REPO_ROOT / "scripts" / "core" / "build-common.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            nativelink_dir = Path(tmpdir) / "nativelink"
            (nativelink_dir / "cas" / "content").mkdir(parents=True)

            env = os.environ.copy()
            env["NATIVELINK_DIR"] = str(nativelink_dir)

            # 1. Empty CAS directory -> should skip
            res1 = subprocess.run(
                ["bash", "-c", f"source '{build_common}' && finalize_ci_cache_upload"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res1.returncode, 0)
            self.assertIn("No CAS cache objects found", res1.stdout)
            self.assertIn("Skipping cache upload", res1.stdout)

            # 2. Populated CAS + .cache_uploaded marker -> should skip duplicate upload
            (nativelink_dir / "cas" / "content" / "blob123").write_text("dummy")
            (nativelink_dir / ".cache_uploaded").write_text("")
            res2 = subprocess.run(
                ["bash", "-c", f"source '{build_common}' && finalize_ci_cache_upload"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res2.returncode, 0)
            self.assertIn("already uploaded during main script", res2.stdout)

    def test_after_script_finalizer_triggers_upload_when_cas_present(self):
        """Verify finalize_ci_cache_upload invokes upload-cache.sh when CAS has objects and marker is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_repo = Path(tmpdir) / "repo"
            (fake_repo / "scripts" / "core").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "scripts" / "core" / "build-common.sh", fake_repo / "scripts" / "core" / "build-common.sh")

            upload_script = fake_repo / "scripts" / "core" / "upload-cache.sh"
            upload_script.write_text("#!/usr/bin/env bash\necho 'MOCK_UPLOAD_EXECUTED'\n")
            os.chmod(upload_script, 0o755)

            nativelink_dir = Path(tmpdir) / "nativelink"
            (nativelink_dir / "cas" / "content").mkdir(parents=True)
            (nativelink_dir / "cas" / "content" / "blob123").write_text("dummy")

            env = os.environ.copy()
            env["NATIVELINK_DIR"] = str(nativelink_dir)
            env["REPO_ROOT"] = str(fake_repo)
            res = subprocess.run(
                ["bash", "-c", f"source '{fake_repo}/scripts/core/build-common.sh' && finalize_ci_cache_upload"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("Found CAS cache objects", res.stdout)
            self.assertIn("MOCK_UPLOAD_EXECUTED", res.stdout)

    def test_shared_upload_cas_cache_defers_to_after_script_on_ci_cancel(self):
        """Verify SIGTERM/SIGINT cancellation in CI stops compilers/NativeLink fast and defers upload to after_script."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_repo = Path(tmpdir) / "repo"
            (fake_repo / "scripts" / "core").mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "scripts" / "core" / "build-common.sh", fake_repo / "scripts" / "core" / "build-common.sh")
            (fake_repo / "scripts" / "core" / "nativelink.sh").write_text("#!/usr/bin/env bash\necho 'NATIVELINK_STOPPED'\n")
            (fake_repo / "scripts" / "core" / "upload-cache.sh").write_text("#!/usr/bin/env bash\necho 'SHOULD_NOT_RUN_IN_SCRIPT'\n")

            env = os.environ.copy()
            env["CI"] = "true"
            env["REPO_ROOT"] = str(fake_repo)
            res = subprocess.run(
                ["bash", "-c", f"source '{fake_repo}/scripts/core/build-common.sh' && shared_upload_cas_cache 143"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("NATIVELINK_STOPPED", res.stdout)
            self.assertIn("Deferring CAS cache compression and upload to GitLab CI after_script", res.stdout)
            self.assertNotIn("SHOULD_NOT_RUN_IN_SCRIPT", res.stdout)

    def test_ci_yaml_after_script_and_target_os_wiring(self):
        """Verify CI configs define after_script finalizer and explicit TARGET_OS for cache naming."""
        common_yml = (REPO_ROOT / ".gitlab" / "ci" / "common.yml").read_text(encoding="utf-8")
        self.assertIn("after_script:", common_yml)
        self.assertIn("finalize_ci_cache_upload", common_yml)
        self.assertIn('NATIVELINK_DIR: "${CI_PROJECT_DIR}/build-workspace/nativelink"', common_yml)

        win_yml = (REPO_ROOT / ".gitlab" / "ci" / "windows.yml").read_text(encoding="utf-8")
        self.assertIn('TARGET_OS: "win"', win_yml)

        android_yml = (REPO_ROOT / ".gitlab" / "ci" / "android.yml").read_text(encoding="utf-8")
        self.assertIn('TARGET_OS: "android"', android_yml)

        upload_script = (REPO_ROOT / "scripts" / "core" / "upload-cache.sh").read_text(encoding="utf-8")
        self.assertIn('touch "${NATIVELINK_DIR}/.cache_uploaded"', upload_script)

    def test_watchdog_returns_immediately_without_pipe_deadlock(self):
        """Ensure start_build_watchdog never blocks waiting on background sleep and stop_build_watchdog cleans up."""
        build_common = REPO_ROOT / "scripts" / "core" / "build-common.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = Path(tmpdir) / ".checkpoint"
            t0 = time.monotonic()
            res = subprocess.run(
                [
                    "bash",
                    "-c",
                    f"source '{build_common}' && start_build_watchdog 60 '{tmpdir}' '{marker}' && "
                    'echo "PID=${WATCHDOG_PID}" && stop_build_watchdog "${WATCHDOG_PID}"',
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            elapsed = time.monotonic() - t0
            self.assertEqual(res.returncode, 0, f"Watchdog failed: {res.stderr}")
            self.assertIn("PID=", res.stdout)
            self.assertLess(elapsed, 2.0, "start_build_watchdog blocked instead of returning immediately")

        # Verify shared build-common.sh and platform build scripts do NOT wrap start_build_watchdog in $() command substitution
        common_content = build_common.read_text(encoding="utf-8")
        self.assertNotIn("$(start_build_watchdog", common_content, "Command substitution deadlock risk in build-common.sh")
        self.assertIn("start_build_watchdog ", common_content, "Missing start_build_watchdog call in build-common.sh")
        for build_script in [
            REPO_ROOT / "scripts" / "platforms" / "android" / "build.sh",
            REPO_ROOT / "scripts" / "platforms" / "windows" / "build.sh",
        ]:
            content = build_script.read_text(encoding="utf-8")
            self.assertNotIn("$(start_build_watchdog", content, f"Command substitution deadlock risk in {build_script}")
            self.assertIn("run_siso_compilation ", content, f"Missing run_siso_compilation call in {build_script}")

    def test_resolve_nativelink_dir_prefers_workspace(self):
        """Verify resolve_nativelink_dir places store inside WORKSPACE_DIR for cross-container CI persistence."""
        build_common = REPO_ROOT / "scripts" / "core" / "build-common.sh"
        env = {k: v for k, v in os.environ.items() if k not in ("NATIVELINK_DIR", "WORKSPACE_DIR", "CI_PROJECT_DIR")}
        env["WORKSPACE_DIR"] = "/builds/org/repo/build-workspace"
        res = subprocess.run(
            ["bash", "-c", f"source '{build_common}' && resolve_nativelink_dir"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "/builds/org/repo/build-workspace/nativelink")


class TestBraveSourceTransport(unittest.TestCase):
    """Verify brave-core source artifact packaging, unpacking, and git clean exclusions."""

    def test_git_clean_preserves_brave_and_out(self):
        """Verify that git clean -ffd -e brave -e out preserves brave and out while cleaning untracked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir(parents=True)
            subprocess.run(["git", "init", str(src_dir)], check=True, capture_output=True)
            (src_dir / "tracked.txt").write_text("tracked")
            subprocess.run(["git", "-C", str(src_dir), "config", "user.name", "Test"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(src_dir), "config", "user.email", "test@example.com"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(src_dir), "add", "tracked.txt"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(src_dir), "commit", "-m", "initial", "--no-gpg-sign"], check=True, capture_output=True)

            # Untracked brave and out
            brave_dir = src_dir / "brave"
            brave_dir.mkdir(parents=True)
            (brave_dir / "dummy.txt").write_text("brave content")
            out_dir = src_dir / "out"
            out_dir.mkdir(parents=True)
            (out_dir / "build.txt").write_text("out content")
            (src_dir / "untracked.txt").write_text("remove me")

            subprocess.run(
                ["git", "-C", str(src_dir), "clean", "-ffd", "-e", "brave", "-e", "out"],
                check=True,
                capture_output=True,
            )

            self.assertTrue((brave_dir / "dummy.txt").exists(), "brave directory must be preserved")
            self.assertTrue((out_dir / "build.txt").exists(), "out directory must be preserved")
            self.assertFalse((src_dir / "untracked.txt").exists(), "untracked files must be removed")

    def test_brave_cache_workspace_preservation(self):
        """Verify build-workspace/src/brave restoration, git initialization, and repository integrity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            src = workspace / "src"
            brave = src / "brave"
            brave.mkdir(parents=True)
            (brave / "DEPS").write_text("vars = {}")
            (brave / "package.json").write_text("{}")

            # Run the verification and git-init script snippet from build.sh
            verify_cmd = (
                f'BRAVE_DIR="{brave}"\n'
                'if [[ -d "${BRAVE_DIR}" && ! -d "${BRAVE_DIR}/.git" ]]; then\n'
                '  git -C "${BRAVE_DIR}" init -q\n'
                '  git -C "${BRAVE_DIR}" config user.name "Cerium Browser Team"\n'
                '  git -C "${BRAVE_DIR}" config user.email "ci@ceriumbrowser.org"\n'
                '  git -C "${BRAVE_DIR}" commit --allow-empty -m "Prepared brave-core" --no-gpg-sign -q\n'
                'fi\n'
                'if [[ ! -d "${BRAVE_DIR}" ]]; then\n'
                '  echo "ERROR: Prepared brave-core not found in ${BRAVE_DIR}." >&2\n'
                '  exit 1\n'
                'fi\n'
            )
            res = subprocess.run(["bash", "-c", verify_cmd], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Verify/init failed: {res.stderr}")
            self.assertTrue((brave / "DEPS").exists(), "DEPS must exist in cached brave-core")
            # Verify git repo and commit exist so gclient skips unmanaged solution
            rev_res = subprocess.run(["git", "-C", str(brave), "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
            self.assertEqual(rev_res.returncode, 0, f"Git rev-parse HEAD failed: {rev_res.stderr}")

    def test_brave_missing_fails_fast(self):
        """Verify that missing src/brave triggers immediate failure in build.sh Phase 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            brave = workspace / "src" / "brave"
            verify_cmd = (
                f'BRAVE_DIR="{brave}"\n'
                'if [[ ! -d "${BRAVE_DIR}" ]]; then\n'
                '  echo "ERROR: Prepared brave-core not found in ${BRAVE_DIR}." >&2\n'
                '  exit 1\n'
                'fi\n'
            )
            res = subprocess.run(["bash", "-c", verify_cmd], capture_output=True, text=True)
            self.assertEqual(res.returncode, 1)
            self.assertIn("ERROR: Prepared brave-core not found", res.stderr)

    def test_archive_build_artifacts_tar_gz(self):
        """Verify archive_build_artifacts creates fast .tar.gz archive containing logs and configs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "build-workspace"
            out_dir = workspace / "src" / "out" / "Release"
            out_dir.mkdir(parents=True)
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "build.log").write_text("build log content")
            (out_dir / "args.gn").write_text("is_debug = false")
            (out_dir / ".ninja_log").write_text("# ninja log")
            (out_dir / "siso_output").write_text("siso output")

            archive_cmd = (
                f'WORKSPACE_DIR="{workspace}"\n'
                f'OUT_DIR="{out_dir}"\n'
                'archive_build_artifacts() {\n'
                '  local archive_path="${WORKSPACE_DIR}/build-artifacts.tar.gz"\n'
                '  local entries=()\n'
                '  if [[ -f "${WORKSPACE_DIR}/build.log" ]]; then\n'
                '    entries+=(-C "${WORKSPACE_DIR}" "build.log")\n'
                '  fi\n'
                '  if [[ -d "${OUT_DIR}" ]]; then\n'
                '    if [[ -f "${OUT_DIR}/args.gn" ]]; then\n'
                '      entries+=(-C "${OUT_DIR}" "args.gn")\n'
                '    fi\n'
                '    if [[ -f "${OUT_DIR}/.ninja_log" ]]; then\n'
                '      entries+=(-C "${OUT_DIR}" ".ninja_log")\n'
                '    fi\n'
                '    for s_file in "${OUT_DIR}"/siso*; do\n'
                '      if [[ -e "${s_file}" ]]; then\n'
                '        entries+=(-C "${OUT_DIR}" "$(basename "${s_file}")")\n'
                '      fi\n'
                '    done\n'
                '  fi\n'
                '  if [[ ${#entries[@]} -gt 0 ]]; then\n'
                '    tar -czf "${archive_path}" "${entries[@]}" 2>/dev/null || true\n'
                '  fi\n'
                '}\n'
                'archive_build_artifacts\n'
            )
            res = subprocess.run(["bash", "-c", archive_cmd], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"archive_build_artifacts failed: {res.stderr}")
            archive_path = workspace / "build-artifacts.tar.gz"
            self.assertTrue(archive_path.exists(), "build-artifacts.tar.gz must exist")
            list_res = subprocess.run(["tar", "-tzf", str(archive_path)], capture_output=True, text=True, check=True)
            self.assertIn("build.log", list_res.stdout)
            self.assertIn("args.gn", list_res.stdout)
            self.assertIn(".ninja_log", list_res.stdout)
            self.assertIn("siso_output", list_res.stdout)

    def test_init_clean_chromium_source_reuses_matching_commit_and_fetches_on_mismatch(self):
        """Verify init_clean_chromium_source reuses matching HEAD, preserves brave/out, and refetches on mismatch."""
        build_common = REPO_ROOT / "scripts" / "core" / "build-common.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            src_dir = Path(tmpdir) / "src"
            src_dir.mkdir(parents=True)
            subprocess.run(["git", "init", str(src_dir)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(src_dir), "config", "user.name", "Test"], check=True)
            subprocess.run(["git", "-C", str(src_dir), "config", "user.email", "test@test.com"], check=True)
            (src_dir / "tracked.txt").write_text("clean")
            subprocess.run(["git", "-C", str(src_dir), "add", "tracked.txt"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(src_dir), "commit", "-m", "init", "--no-gpg-sign"], check=True, capture_output=True)
            commit = subprocess.check_output(["git", "-C", str(src_dir), "rev-parse", "HEAD"], text=True).strip()

            (src_dir / "tracked.txt").write_text("dirty")
            (src_dir / "stale.txt").write_text("remove")
            (src_dir / "brave").mkdir()
            (src_dir / "brave" / "keep.txt").write_text("brave")
            (src_dir / "out").mkdir()
            (src_dir / "out" / "keep.txt").write_text("out")

            reuse_cmd = (
                f"source '{build_common}' && "
                "fetch_chromium_git() { echo 'SHOULD_NOT_FETCH'; return 1; } && "
                f"init_clean_chromium_source '{src_dir}' '157.0.0.1' '{commit}'"
            )
            res = subprocess.run(["bash", "-c", reuse_cmd], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Reuse failed: {res.stderr}\n{res.stdout}")
            self.assertIn("matches target commit", res.stdout)
            self.assertEqual((src_dir / "tracked.txt").read_text(), "clean")
            self.assertFalse((src_dir / "stale.txt").exists())
            self.assertTrue((src_dir / "brave" / "keep.txt").exists())
            self.assertTrue((src_dir / "out" / "keep.txt").exists())

            mismatch_cmd = (
                f"source '{build_common}' && "
                "fetch_chromium_git() { echo \"FETCHED:$2:$3\"; } && "
                f"init_clean_chromium_source '{src_dir}' '157.0.0.2' 'deadbeef1234'"
            )
            res2 = subprocess.run(["bash", "-c", mismatch_cmd], capture_output=True, text=True)
            self.assertEqual(res2.returncode, 0, f"Mismatch refetch failed: {res2.stderr}")
            self.assertIn("FETCHED:157.0.0.2:deadbeef1234", res2.stdout)


class TestGitLabPackageUpload(unittest.TestCase):
    """Verify gitlab_pkg_upload_file properly separates HTTP response body from %{http_code}."""

    def test_gitlab_pkg_upload_file_succeeds_with_201_json_body(self):
        """Reproduce GitLab 201 Created response body {'message':'201 Created'} and ensure helper parses HTTP 201 cleanly."""
        class UploadHandler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                length = int(self.headers.get("Content-Length", "0"))
                _ = self.rfile.read(length)
                body = b'{"message":"201 Created"}'
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = socketserver.TCPServer(("127.0.0.1", 0), UploadHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever)
        t.daemon = True
        t.start()

        chunk_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                tf.write(b"mock-chunk-data")
                chunk_path = tf.name

            build_common = REPO_ROOT / "scripts" / "core" / "build-common.sh"
            url = f"http://127.0.0.1:{port}/chunk.tar.gz.00"
            res = subprocess.run(
                ["bash", "-c", f"source '{build_common}' && gitlab_pkg_upload_file '{chunk_path}' '{url}' 'JOB-TOKEN: fake'"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"Upload helper failed: {res.stderr}\nStdout: {res.stdout}")
            self.assertIn("successfully (HTTP 201)", res.stdout)
        finally:
            if chunk_path and os.path.exists(chunk_path):
                os.unlink(chunk_path)
            server.shutdown()
            server.server_close()

    def test_gitlab_pkg_upload_file_fails_cleanly_on_403(self):
        """Verify HTTP 403 prints clean error code and server response body."""
        class ForbiddenHandler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                length = int(self.headers.get("Content-Length", "0"))
                _ = self.rfile.read(length)
                body = b'{"message":"403 Forbidden"}'
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        server = socketserver.TCPServer(("127.0.0.1", 0), ForbiddenHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever)
        t.daemon = True
        t.start()

        chunk_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False) as tf:
                tf.write(b"mock-chunk-data")
                chunk_path = tf.name

            build_common = REPO_ROOT / "scripts" / "core" / "build-common.sh"
            url = f"http://127.0.0.1:{port}/chunk.tar.xz.00"
            res = subprocess.run(
                ["bash", "-c", f"source '{build_common}' && gitlab_pkg_upload_file '{chunk_path}' '{url}' 'JOB-TOKEN: fake'"],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("failed with HTTP 403", res.stderr)
            self.assertIn('{"message":"403 Forbidden"}', res.stderr)
        finally:
            if chunk_path and os.path.exists(chunk_path):
                os.unlink(chunk_path)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

