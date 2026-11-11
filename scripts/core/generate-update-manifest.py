#!/usr/bin/env python3
"""
Cerium Browser — Windows Update Manifest Generator
(scripts/core/generate-update-manifest.py)

Generates or updates release.json consumed by CeriumVersionUpdaterWin
(chrome/browser/ui/webui/help/version_updater_win.cc).
"""

import argparse
import hashlib
import json
import os
import sys
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BASE_URL = "https://ceriumbrowser.gitlab.io/cerium-updater/windows"


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def resolve_version(version_arg: str | None) -> str:
    if version_arg:
        return version_arg
    for env_var in ("DYNAMIC_BRAVE_VERSION", "BRAVE_VERSION"):
        val = os.environ.get(env_var)
        if val:
            return val
    releases_dir = os.path.join(REPO_ROOT, "metadata", "releases")
    if os.path.isdir(releases_dir):
        files = sorted(
            [f for f in os.listdir(releases_dir) if f.endswith(".yaml")],
            reverse=True,
        )
        if files:
            manifest_path = os.path.join(releases_dir, files[0])
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and "brave_version" in data:
                        return str(data["brave_version"])
            except Exception:
                pass
    return "0.0.0"


def generate_manifest(
    package_dir: str,
    version: str,
    output_path: str,
    base_url: str = DEFAULT_BASE_URL,
    target_arch: str | None = None,
) -> dict:
    data = {
        "version": version,
        "packages": {},
    }

    if os.path.exists(output_path):
        try:
            with open(output_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    if "packages" in existing and isinstance(existing["packages"], dict):
                        data["packages"].update(existing["packages"])
        except Exception as e:
            print(f"Warning: could not parse existing {output_path}: {e}", file=sys.stderr)

    data["version"] = version

    archs = [target_arch] if target_arch and target_arch != "all" else ["x64", "arm64"]
    matched = 0

    for arch in archs:
        installer_file = f"cerium_{arch}.exe"
        installer_path = os.path.join(package_dir, installer_file)
        if os.path.isfile(installer_path):
            file_sha256 = compute_sha256(installer_path)
            file_size = os.path.getsize(installer_path)
            pkg_url = f"{base_url.rstrip('/')}/{installer_file}"
            data["packages"][arch] = {
                "url": pkg_url,
                "sha256": file_sha256,
                "size": file_size,
            }
            matched += 1

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate Cerium Windows update manifest release.json"
    )
    parser.add_argument(
        "--package-dir",
        default=os.path.join(REPO_ROOT, "out", "packages"),
        help="Directory containing packaged Windows installers (default: out/packages)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Release version (defaults to metadata or environment)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: <package-dir>/release.json)",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base download URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--arch",
        choices=["x64", "arm64", "all"],
        default=None,
        help="Target architecture to scan",
    )

    args = parser.parse_args()

    output_path = args.output
    if not output_path:
        output_path = os.path.join(args.package_dir, "release.json")

    ver = resolve_version(args.version)
    manifest = generate_manifest(
        package_dir=args.package_dir,
        version=ver,
        output_path=output_path,
        base_url=args.base_url,
        target_arch=args.arch,
    )

    print(f"Generated Windows update manifest at: {output_path}")
    print(f" - Version : {manifest.get('version')}")
    print(f" - Packages: {list(manifest.get('packages', {}).keys())}")


if __name__ == "__main__":
    main()
