#!/usr/bin/env python3
"""
Unit tests for Cerium Patch Registry (patches/patches.yaml)
Ensures full synchronization between disk patch files and catalog metadata.
"""

import os
import unittest
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PATCH_DIR = os.path.join(REPO_ROOT, "patches")
REGISTRY_FILE = os.path.join(PATCH_DIR, "patches.yaml")


class TestPatchRegistry(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.path.isfile(REGISTRY_FILE), f"Missing {REGISTRY_FILE}")
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

    def test_registry_schema(self):
        """Registry must define categories and patches with required fields."""
        categories = self.data.get("categories", [])
        self.assertGreater(len(categories), 0, "No categories defined in patches.yaml")
        category_names = {c["name"] for c in categories if "name" in c}

        patches = self.data.get("patches", [])
        self.assertGreater(len(patches), 0, "No patches defined in patches.yaml")

        required_fields = ["file", "name", "category", "target_os", "description", "reason", "effect"]
        for p in patches:
            for field in required_fields:
                self.assertIn(field, p, f"Patch {p.get('file', 'UNKNOWN')} missing field '{field}'")
                self.assertTrue(str(p[field]).strip(), f"Patch {p.get('file')} has empty field '{field}'")
            self.assertIn(p["category"], category_names, f"Unknown category '{p['category']}' in {p['file']}")
            self.assertIn(p["target_os"], ["common", "android", "desktop"], f"Invalid target_os in {p['file']}")

    def test_all_patches_on_disk_are_cataloged(self):
        """Every .patch file on disk in patches/ must be registered in patches.yaml."""
        disk_patches = set()
        for root, _, files in os.walk(PATCH_DIR):
            for f in files:
                if f.endswith(".patch"):
                    rel = os.path.relpath(os.path.join(root, f), PATCH_DIR)
                    disk_patches.add(rel)

        catalog_patches = {p["file"] for p in self.data.get("patches", [])}

        missing_from_catalog = disk_patches - catalog_patches
        self.assertEqual(missing_from_catalog, set(), f"Patches on disk but missing from patches.yaml: {missing_from_catalog}")

    def test_all_catalog_patches_exist_on_disk(self):
        """Every patch registered in patches.yaml must exist on disk."""
        for p in self.data.get("patches", []):
            patch_path = os.path.join(PATCH_DIR, p["file"])
            self.assertTrue(os.path.isfile(patch_path), f"Cataloged patch does not exist on disk: {patch_path}")


if __name__ == "__main__":
    unittest.main()
