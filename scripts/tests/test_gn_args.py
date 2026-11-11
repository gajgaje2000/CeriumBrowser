#!/usr/bin/env python3
"""
Unit tests for Cerium Declarative GN Arguments Generator
(scripts/core/generate-gn-args.py)
"""

import os
import tempfile
import unittest

from scripts.core.generate_gn_args import generate_gn_args

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


class TestGenerateGNArgs(unittest.TestCase):
    def test_android_gn_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "args.gn")
            content = generate_gn_args(
                repo_root=REPO_ROOT,
                platform="android",
                arch="arm64",
                version="1.99.55",
                package_id="org.ceriumbrowser.cerium",
                out_file=out_file,
            )
            self.assertTrue(os.path.isfile(out_file))
            self.assertIn('target_os = "android"', content)
            self.assertIn('target_cpu = "arm64"', content)
            self.assertIn('chrome_version_name = "1.99.55"', content)
            self.assertIn('chrome_public_manifest_package = "org.ceriumbrowser.cerium"', content)
            self.assertIn('is_official_build = true', content)
            self.assertIn('brave_services_key = "no-key"', content)
            self.assertIn('service_key_aichat = "no-key"', content)

    def test_windows_gn_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "args.gn")
            content = generate_gn_args(
                repo_root=REPO_ROOT,
                platform="windows",
                arch="x64",
                version="1.99.55",
                out_file=out_file,
            )
            self.assertTrue(os.path.isfile(out_file))
            self.assertIn('target_os = "win"', content)
            self.assertIn('target_cpu = "x64"', content)
            self.assertIn('is_brave_origin_branded = true', content)
            self.assertIn('skip_signing = true', content)
            self.assertIn('is_official_build = true', content)
            self.assertIn('brave_services_key = "no-key"', content)


if __name__ == "__main__":
    unittest.main()
