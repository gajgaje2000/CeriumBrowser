#!/usr/bin/env python3
"""
Unit tests for Cerium Branch Utilities (scripts/core/branch_utils.py).
"""

import os
import sys
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.core.branch_utils import (
    get_current_branch,
    get_package_id,
    get_app_name,
    get_windows_product_path,
    get_windows_app_name,
    get_windows_app_id,
    get_windows_prog_id,
    get_windows_pdf_prog_id,
)


class TestBranchUtils(unittest.TestCase):
    def test_package_id_release(self):
        self.assertEqual(get_package_id("release"), "org.cerium.browser")
        self.assertEqual(get_package_id(""), "org.cerium.browser")
        self.assertEqual(get_package_id(None), "org.cerium.browser")

    def test_package_id_main(self):
        self.assertEqual(get_package_id("main"), "org.cerium.browser.main")

    def test_package_id_feature_branches(self):
        self.assertEqual(get_package_id("feature_x"), "org.cerium.browser.feature_x")
        self.assertEqual(get_package_id("update_application_id_branch"), "org.cerium.browser.update_application_id_branch")
        self.assertEqual(get_package_id("feat/ab"), "org.cerium.browser.feat_ab")
        # When characters (like hyphens) are sanitized, stable hash suffix prevents collision
        self.assertNotEqual(get_package_id("feat/a-b"), get_package_id("feat/ab"))
        self.assertTrue(get_package_id("feat/a-b").startswith("org.cerium.browser.feat_ab_"))

    def test_app_name(self):
        self.assertEqual(get_app_name("release"), "Cerium")
        self.assertEqual(get_app_name(""), "Cerium")
        self.assertEqual(get_app_name(None), "Cerium")
        self.assertEqual(get_app_name("main"), "Cerium (main)")
        self.assertEqual(get_app_name("feat/test"), "Cerium (feat/test)")

    def test_windows_branding_release(self):
        self.assertEqual(get_windows_product_path("release"), "Cerium-Browser")
        self.assertEqual(get_windows_app_name("release"), "Cerium")
        self.assertEqual(get_windows_app_id("release"), "Cerium")
        self.assertEqual(get_windows_prog_id("release"), "CeriumHTML")
        self.assertEqual(get_windows_pdf_prog_id("release"), "CeriumPDF")

    def test_windows_branding_branch(self):
        self.assertEqual(get_windows_product_path("main"), "Cerium-Browser-main")
        self.assertEqual(get_windows_app_name("main"), "Cerium (main)")
        self.assertEqual(get_windows_app_id("main"), "Cerium.main")
        self.assertEqual(get_windows_prog_id("main"), "CeriummainHTML")
        self.assertEqual(get_windows_pdf_prog_id("main"), "CeriummainPDF")

        self.assertEqual(get_windows_product_path("feat/test"), "Cerium-Browser-feat_test")
        # Slashes and Windows-invalid path characters sanitized
        self.assertEqual(get_windows_product_path("feat/test:dir*name?"), "Cerium-Browser-feat_test_dir_name_")
        self.assertEqual(get_windows_app_name("feat/test"), "Cerium (feat_test)")
        self.assertEqual(get_windows_app_id("feat/test"), "Cerium.feat_test")
        self.assertEqual(get_windows_prog_id("feat/test"), "CeriumfeattestHTML")

    def test_prog_id_length_limit(self):
        long_b1 = "feat/super-long-branch-name-exceeding-thirty-chars-1"
        long_b2 = "feat/super-long-branch-name-exceeding-thirty-chars-2"
        p1 = get_windows_prog_id(long_b1)
        p2 = get_windows_prog_id(long_b2)
        pdf1 = get_windows_pdf_prog_id(long_b1)
        pdf2 = get_windows_pdf_prog_id(long_b2)
        self.assertLessEqual(len(p1), 39)
        self.assertLessEqual(len(p2), 39)
        self.assertLessEqual(len(pdf1), 39)
        self.assertLessEqual(len(pdf2), 39)
        # Distinct branches do not collapse to the same ProgID
        self.assertNotEqual(p1, p2)
        self.assertNotEqual(pdf1, pdf2)

    def test_package_id_java_keywords(self):
        self.assertEqual(get_package_id("native"), "org.cerium.browser.native_app")
        self.assertEqual(get_package_id("default"), "org.cerium.browser.default_app")
        self.assertEqual(get_package_id("switch"), "org.cerium.browser.switch_app")

    def test_get_current_branch_from_env(self):
        with patch.dict(os.environ, {"CI_COMMIT_BRANCH": "release"}, clear=True):
            self.assertEqual(get_current_branch(), "release")

        with patch.dict(os.environ, {"CI_COMMIT_BRANCH": "main"}, clear=True):
            self.assertEqual(get_current_branch(), "main")

        with patch.dict(os.environ, {"CI_COMMIT_REF_NAME": "custom_ref"}, clear=True):
            self.assertEqual(get_current_branch(), "custom_ref")

        with patch.dict(os.environ, {"CI_COMMIT_REF_NAME": "vpn-fix"}, clear=True):
            self.assertEqual(get_current_branch(), "vpn-fix")

        with patch.dict(os.environ, {"CI_COMMIT_REF_NAME": "v2-fix"}, clear=True):
            self.assertEqual(get_current_branch(), "v2-fix")

        with patch.dict(os.environ, {"CI_COMMIT_TAG": "v1.96.61"}, clear=True):
            self.assertEqual(get_current_branch(), "release")

        with patch.dict(os.environ, {"CI_COMMIT_REF_NAME": "v1.96.61"}, clear=True):
            self.assertEqual(get_current_branch(), "release")


if __name__ == "__main__":
    unittest.main()
