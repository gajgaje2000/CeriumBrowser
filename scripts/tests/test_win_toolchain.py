"""
Unit tests for Cerium Windows Cross-Compilation Toolchain Manager
(scripts/tests/test_win_toolchain.py)

Tests:
  - Toolchain SHA1 hash calculation matching depot_tools CalculateHash
  - Prioritized candidate hash resolution (44f9aa3391, 436026023a, upstream hash, env overrides)
  - Toolchain archive content validation (VS_VERSION, VC, Windows Kits)
  - Corrupted archive detection and graceful recovery
  - Mislabeled archive cleanup and renaming
  - SetEnv manifests (x86, x64, arm64, arm) and cl.exe compiler stubs
  - Generation of toolchain.env with proper shell exports
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLCHAIN_SCRIPT = os.path.join(REPO_ROOT, "scripts/core/setup-win-toolchain.py")


def load_toolchain_module():
    spec = importlib.util.spec_from_file_location("setup_win_toolchain", TOOLCHAIN_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestWinToolchainManager(unittest.TestCase):
    def setUp(self):
        self.mod = load_toolchain_module()

    def test_candidate_hash_resolution_priorities(self):
        """Candidate hash resolution must prioritize 44f9aa3391, 436026023a, and upstream hash."""
        candidates = self.mod.resolve_candidate_hashes("3bfcb536c8")
        self.assertIn("44f9aa3391", candidates)
        self.assertIn("436026023a", candidates)
        self.assertIn("3bfcb536c8", candidates)
        # 44f9aa3391 must appear before 436026023a and upstream hash
        self.assertLess(candidates.index("44f9aa3391"), candidates.index("436026023a"))
        self.assertLess(candidates.index("44f9aa3391"), candidates.index("3bfcb536c8"))

    def test_candidate_hash_resolution_env_override(self):
        """Candidate hash resolution must prioritize GYP_MSVS_HASH_<hash> and GYP_MSVS_HASH if set."""
        old_env = os.environ.copy()
        try:
            os.environ["GYP_MSVS_HASH_upstream123"] = "custom_override_hash"
            os.environ["GYP_MSVS_HASH"] = "generic_override_hash"
            candidates = self.mod.resolve_candidate_hashes("upstream123")
            self.assertEqual(candidates[0], "custom_override_hash")
            self.assertEqual(candidates[1], "generic_override_hash")
            self.assertIn("44f9aa3391", candidates)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_toolchain_hash_calculation(self):
        """Directory SHA1 digest must match zip SHA1 digest matching depot_tools format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_tree = os.path.join(tmpdir, "toolchain")
            os.makedirs(os.path.join(test_tree, "VC", "include"), exist_ok=True)
            os.makedirs(os.path.join(test_tree, "Windows Kits", "10", "Include"), exist_ok=True)

            with open(os.path.join(test_tree, "VS_VERSION"), "w") as f:
                f.write("2022\n")
            with open(os.path.join(test_tree, "VC", "include", "stdlib.h"), "w") as f:
                f.write("// mock stdlib\n")
            with open(os.path.join(test_tree, "Windows Kits", "10", "Include", "windows.h"), "w") as f:
                f.write("// mock windows.h\n")

            dir_hash = self.mod.calculate_toolchain_hash_from_dir(test_tree)
            self.assertEqual(len(dir_hash), 40)

            test_zip = os.path.join(tmpdir, "toolchain.zip")
            self.mod.create_toolchain_zip(test_tree, test_zip)
            zip_hash = self.mod.calculate_toolchain_hash_from_zip(test_zip)

            self.assertEqual(dir_hash, zip_hash)
            self.assertEqual(dir_hash[:10], zip_hash[:10])

    def test_toolchain_archive_content_validation(self):
        """is_valid_toolchain_archive must reject zips missing VS_VERSION, VC, Windows Kits, or empty files."""
        import zipfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Missing VS_VERSION
            zip1 = os.path.join(tmpdir, "zip1.zip")
            with zipfile.ZipFile(zip1, "w") as zf:
                zf.writestr("VC/Tools/MSVC/14.44/bin/cl.exe", "fake")
                zf.writestr("Windows Kits/10/Include/windows.h", "fake")
            self.assertFalse(self.mod.is_valid_toolchain_archive(zip1))

            # 2. Missing VC
            zip2 = os.path.join(tmpdir, "zip2.zip")
            with zipfile.ZipFile(zip2, "w") as zf:
                zf.writestr("VS_VERSION", "2022\n")
                zf.writestr("Windows Kits/10/Include/windows.h", "fake")
            self.assertFalse(self.mod.is_valid_toolchain_archive(zip2))

            # 3. Empty 0-byte entries
            zip3 = os.path.join(tmpdir, "zip3.zip")
            with zipfile.ZipFile(zip3, "w") as zf:
                zf.writestr("VS_VERSION", "")
                zf.writestr("VC/Tools/MSVC/14.44/bin/cl.exe", "")
                zf.writestr("Windows Kits/10/Include/windows.h", "")
            self.assertFalse(self.mod.is_valid_toolchain_archive(zip3))

            # 4. Valid complete zip
            zip4 = os.path.join(tmpdir, "zip4.zip")
            with zipfile.ZipFile(zip4, "w") as zf:
                zf.writestr("VS_VERSION", "2022\n")
                zf.writestr("VC/Tools/MSVC/14.44/bin/cl.exe", "fake")
                zf.writestr("Windows Kits/10/Include/windows.h", "fake")
            self.assertTrue(self.mod.is_valid_toolchain_archive(zip4))

    def test_corrupted_archive_recovery(self):
        """calculate_toolchain_hash_from_zip must return empty string for corrupted archives without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupt_zip = os.path.join(tmpdir, "436026023a.zip")
            with open(corrupt_zip, "w") as f:
                f.write("corrupted-not-a-zip")
            hash_result = self.mod.calculate_toolchain_hash_from_zip(corrupt_zip)
            self.assertEqual(hash_result, "")

    def test_cleanup_mislabeled_archive(self):
        """setup-win-toolchain.py must detect mislabeled archive, rename to actual hash, and clean wrong file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_tree = os.path.join(tmpdir, "toolchain")
            os.makedirs(os.path.join(test_tree, "VC", "Tools", "MSVC", "14.44.17.14"), exist_ok=True)
            os.makedirs(os.path.join(test_tree, "Windows Kits", "10"), exist_ok=True)
            with open(os.path.join(test_tree, "VS_VERSION"), "w") as f:
                f.write("2022\n")
            with open(os.path.join(test_tree, "VC", "Tools", "MSVC", "14.44.17.14", "cl.exe"), "w") as f:
                f.write("// stub\n")
            with open(os.path.join(test_tree, "Windows Kits", "10", "sdk.txt"), "w") as f:
                f.write("// stub\n")

            dir_hash = self.mod.calculate_toolchain_hash_from_dir(test_tree)
            actual_prefix = dir_hash[:10]

            out_dir = os.path.join(tmpdir, "pkg")
            os.makedirs(out_dir, exist_ok=True)

            wrong_hash = "5c53cd5814"
            wrong_zip = os.path.join(out_dir, f"{wrong_hash}.zip")
            self.mod.create_toolchain_zip(test_tree, wrong_zip)
            self.assertTrue(os.path.isfile(wrong_zip))

            res = subprocess.run(
                [sys.executable, TOOLCHAIN_SCRIPT, f"--output-dir={out_dir}", f"--target-hash={wrong_hash}"],
                capture_output=True, text=True
            )
            self.assertEqual(res.returncode, 0, f"setup-win-toolchain failed: {res.stderr}")

            actual_zip = os.path.join(out_dir, f"{actual_prefix}.zip")
            self.assertTrue(os.path.isfile(actual_zip))
            self.assertFalse(os.path.isfile(wrong_zip))

            env_file = os.path.join(out_dir, "toolchain.env")
            self.assertTrue(os.path.isfile(env_file))
            with open(env_file, "r") as f:
                self.assertIn(f'export GYP_MSVS_HASH="{actual_prefix}"', f.read())
            self.assertFalse(os.path.exists(os.path.join(out_dir, "toolchain_hash.env")))

    def test_write_toolchain_env(self):
        """write_toolchain_env must produce toolchain.env with proper exports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.mod.write_toolchain_env(tmpdir, "44f9aa3391", "canonical123")

            env_path = os.path.join(tmpdir, "toolchain.env")
            self.assertTrue(os.path.isfile(env_path))
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn('export GYP_MSVS_HASH="44f9aa3391"', content)
            self.assertIn('export GYP_MSVS_HASH_canonical123="44f9aa3391"', content)
            self.assertIn(f'export DEPOT_TOOLS_WIN_TOOLCHAIN_BASE_URL="{tmpdir}"', content)
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "toolchain_hash.env")))

    def test_win_build_toolchain_wiring(self):
        """windows/build.sh and build-common.sh must clean stale toolchain.env, delegate to setup-win-toolchain.py, and propagate failures."""
        build_sh = os.path.join(REPO_ROOT, "scripts/platforms/windows/build.sh")
        build_common = os.path.join(REPO_ROOT, "scripts/core/build-common.sh")
        with open(build_sh, "r", encoding="utf-8") as f:
            b_content = f.read()
        with open(build_common, "r", encoding="utf-8") as f:
            c_content = f.read()
        self.assertIn("start_async_win_toolchain", b_content)
        self.assertIn("await_async_win_toolchain", b_content)
        self.assertIn("setup-win-toolchain.py", c_content)
        self.assertIn("--prepare", c_content)
        self.assertIn('source "${toolchain_env}"', c_content)
        self.assertIn('rm -f "${toolchain_dir}/toolchain.env"', c_content)
        self.assertIn('echo "ERROR: Background Windows toolchain prefetch failed!"', c_content)
        self.assertIn('echo "ERROR: Toolchain generation completed but fresh output archive was not produced."', c_content)
        win_toolchain_slice = c_content[c_content.find("start_async_win_toolchain"):c_content.find("await_async_win_toolchain")]
        self.assertNotIn("--upload", b_content)
        self.assertNotIn("--upload", win_toolchain_slice)
        self.assertNotIn("Ensure Windows toolchain SetEnv manifests and compiler stubs", b_content)

    def test_setenv_manifests_and_stubs(self):
        """build_toolchain_layout must create SetEnv manifests for all arches with VSINSTALLDIR and cl.exe stubs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            splat_dir = os.path.join(tmpdir, "splat")
            assembled_dir = os.path.join(tmpdir, "assembled")
            os.makedirs(os.path.join(splat_dir, "sdk", "include", "um"), exist_ok=True)
            os.makedirs(os.path.join(splat_dir, "sdk", "lib"), exist_ok=True)
            os.makedirs(os.path.join(splat_dir, "crt", "include"), exist_ok=True)
            os.makedirs(os.path.join(splat_dir, "crt", "lib"), exist_ok=True)

            self.mod.build_toolchain_layout(splat_dir, assembled_dir, "436026023a", "10.0.26100")

            bin_dir = os.path.join(assembled_dir, "Windows Kits", "10", "bin")
            for cpu in ["x86", "x64", "arm64", "arm"]:
                manifest_path = os.path.join(bin_dir, f"SetEnv.{cpu}.json")
                self.assertTrue(os.path.isfile(manifest_path), f"Missing {manifest_path}")
                with open(manifest_path, "r") as f:
                    data = json.load(f)
                self.assertIn("env", data)
                self.assertEqual(data["env"]["VSINSTALLDIR"], [["."]])
                self.assertIn("VCINSTALLDIR", data["env"])
                self.assertIn("INCLUDE", data["env"])
                self.assertIn("LIB", data["env"])
                self.assertIn("PATH", data["env"])

            vc_bin = os.path.join(assembled_dir, "VC", "Tools", "MSVC", "14.44.17.14", "bin", "HostX64")
            for arch in ["x64", "x86", "arm64", "arm"]:
                cl_path = os.path.join(vc_bin, arch, "cl.exe")
                self.assertTrue(os.path.isfile(cl_path), f"Missing {cl_path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
