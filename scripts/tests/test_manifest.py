#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_upstream_metadata():
    metadata_dir = os.path.join(REPO_ROOT, "metadata")
    if not os.path.isdir(metadata_dir):
        print("SKIP: metadata dir not found (not generated yet)")
        return
    upstream_files = [f for f in os.listdir(metadata_dir) if f.startswith("upstream-") and f.endswith(".yaml")]
    if not upstream_files:
        print("SKIP: No upstream metadata files found")
        return
    for fname in upstream_files:
        upstream_file = os.path.join(metadata_dir, fname)
        with open(upstream_file, "r") as f:
            data = yaml.safe_load(f)
        assert "release" in data, f"Missing release section in {fname}"
        assert "brave_version" in data["release"], f"Missing brave_version in {fname}"
        print(f"PASS: test_upstream_metadata ({fname})")

def test_release_manifest():
    releases_dir = os.path.join(REPO_ROOT, "metadata", "releases")
    if not os.path.isdir(releases_dir):
        print("SKIP: metadata/releases dir not found (not generated yet)")
        return
    release_files = [f for f in os.listdir(releases_dir) if f.endswith(".yaml")]
    for fname in release_files:
        fpath = os.path.join(releases_dir, fname)
        with open(fpath, "r") as f:
            data = yaml.safe_load(f)
        pkg = data.get("package_id", "")
        assert re.match(r"^org\.cerium\.browser(\.[a-zA-Z0-9_]+)?$", pkg), f"Invalid package_id in {fname}: {pkg}"
        print(f"PASS: test_release_manifest ({fname})")

def test_windows_update_manifest():
    generator_script = os.path.join(REPO_ROOT, "scripts", "core", "generate-update-manifest.py")
    assert os.path.isfile(generator_script), "generate-update-manifest.py missing"

    spec = importlib.util.spec_from_file_location("generate_update_manifest", generator_script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_x64 = os.path.join(tmpdir, "cerium_x64.exe")
        pkg_arm64 = os.path.join(tmpdir, "cerium_arm64.exe")
        with open(pkg_x64, "wb") as f:
            f.write(b"dummy-x64-payload-data")
        with open(pkg_arm64, "wb") as f:
            f.write(b"dummy-arm64-payload-data")

        out_json = os.path.join(tmpdir, "release.json")
        data = mod.generate_manifest(
            package_dir=tmpdir,
            version="1.99.55",
            output_path=out_json,
        )

        assert data["version"] == "1.99.55"
        assert "x64" in data["packages"]
        assert "arm64" in data["packages"]
        assert data["packages"]["x64"]["sha256"] == hashlib.sha256(b"dummy-x64-payload-data").hexdigest()
        assert data["packages"]["x64"]["size"] == len(b"dummy-x64-payload-data")
        assert data["packages"]["arm64"]["sha256"] == hashlib.sha256(b"dummy-arm64-payload-data").hexdigest()
        assert data["packages"]["arm64"]["size"] == len(b"dummy-arm64-payload-data")

        # Test incremental arch update
        with open(pkg_x64, "wb") as f:
            f.write(b"updated-x64-payload")
        mod.generate_manifest(
            package_dir=tmpdir,
            version="1.99.56",
            output_path=out_json,
            target_arch="x64",
        )
        with open(out_json, "r") as f:
            updated_data = json.load(f)
        assert updated_data["version"] == "1.99.56"
        assert updated_data["packages"]["x64"]["sha256"] == hashlib.sha256(b"updated-x64-payload").hexdigest()
        # Ensure arm64 was preserved from previous run
        assert updated_data["packages"]["arm64"]["sha256"] == hashlib.sha256(b"dummy-arm64-payload-data").hexdigest()

        print("PASS: test_windows_update_manifest")

if __name__ == "__main__":
    try:
        test_upstream_metadata()
        test_release_manifest()
        test_windows_update_manifest()
        print("ALL MANIFEST TESTS PASSED.")
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)

