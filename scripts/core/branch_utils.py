#!/usr/bin/env python3
"""
Cerium — Branch & Dynamic Identity Utilities (scripts/core/branch_utils.py)
Provides centralized detection of the active git branch and mapping to
dynamic multi-platform application IDs, product names, and ProgIDs.
"""

import hashlib
import os
import re
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
}


def get_current_branch(repo_root: str = None) -> str:
    """
    Returns the current git branch name.
    Prioritizes CI_COMMIT_BRANCH, then git rev-parse --abbrev-ref HEAD.
    Falls back to 'release' if detached or undetectable.
    """
    if os.environ.get("CI_COMMIT_TAG"):
        return "release"

    ci_branch = os.environ.get("CI_COMMIT_BRANCH", "").strip()
    if ci_branch:
        return ci_branch

    ref_name = os.environ.get("CI_COMMIT_REF_NAME", "").strip()
    if ref_name:
        if re.match(r"^v\d+(\.\d+)+$", ref_name):
            return "release"
        return ref_name

    target_root = repo_root or REPO_ROOT
    cmd = ["git", "-C", target_root, "rev-parse", "--abbrev-ref", "HEAD"]

    try:
        branch = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if branch and branch != "HEAD":
            return branch
    except Exception:
        pass

    return "release"


def get_package_id(branch: str) -> str:
    """
    Returns the Android package ID / Application ID for a given branch:
    - 'release' -> 'org.cerium.browser'
    - other branches -> 'org.cerium.browser.<br_name>' (sanitized without hyphens or dots)
    """
    if not branch or branch == "release":
        return "org.cerium.browser"

    raw = branch.strip().lower()
    clean = raw.replace("/", "_").replace("-", "").replace(".", "")
    clean = re.sub(r"[^a-z0-9_]", "", clean)
    clean = re.sub(r"^[^a-z]+", "", clean)
    if not clean:
        clean = "dev"
    # If sanitization removed characters (e.g. hyphens or dots), append a stable
    # branch-derived distinguishing hash suffix so distinct branches (like feat/a-b vs feat/ab)
    # cannot produce colliding package IDs.
    if re.sub(r"[^a-z0-9_]", "_", raw.replace("/", "_")) != clean:
        suffix = hashlib.sha256(branch.strip().encode()).hexdigest()[:6]
        clean = f"{clean}_{suffix}"
    if clean in JAVA_KEYWORDS:
        clean = f"{clean}_app"
    return f"org.cerium.browser.{clean}"


def get_app_name(branch: str) -> str:
    """
    Returns the user-facing display application name:
    - 'release' -> 'Cerium'
    - other branches -> 'Cerium (<br_name>)'
    """
    if not branch or branch == "release":
        return "Cerium"
    return f"Cerium ({branch})"


def get_windows_product_path(branch: str) -> str:
    """
    Returns Windows kProductPathName (install and user data dir):
    - 'release' -> 'Cerium-Browser'
    - other branches -> 'Cerium-Browser-<br_name>'
    """
    if not branch or branch == "release":
        return "Cerium-Browser"
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', branch.strip())
    return f"Cerium-Browser-{clean}"


def get_windows_app_name(branch: str) -> str:
    """
    Returns Windows base_app_name (sanitized without path separators for shortcuts):
    - 'release' -> 'Cerium'
    - other branches -> 'Cerium (<br_name>)'
    """
    if not branch or branch == "release":
        return "Cerium"
    clean = branch.strip().replace("/", "_").replace("\\", "_")
    return f"Cerium ({clean})"


def get_windows_app_id(branch: str) -> str:
    """
    Returns Windows base_app_id:
    - 'release' -> 'Cerium'
    - other branches -> 'Cerium.<br_name>'
    """
    if not branch or branch == "release":
        return "Cerium"
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", branch.strip())
    if len(clean) > 20:
        suffix = hashlib.sha256(branch.strip().encode()).hexdigest()[:6]
        clean = f"{clean[:13]}_{suffix}"
    return f"Cerium.{clean}"


def get_windows_prog_id(branch: str) -> str:
    """
    Returns Windows browser ProgID prefix (capped to avoid COM 39-character limit):
    - 'release' -> 'CeriumHTML'
    - other branches -> 'Cerium<br_name>HTML'
    """
    if not branch or branch == "release":
        return "CeriumHTML"
    clean = re.sub(r"[^a-zA-Z0-9]", "", branch.strip())
    if len(clean) > 20:
        suffix = hashlib.sha256(branch.strip().encode()).hexdigest()[:6]
        clean = f"{clean[:14]}{suffix}"
    return f"Cerium{clean}HTML"


def get_windows_pdf_prog_id(branch: str) -> str:
    """
    Returns Windows PDF ProgID prefix (capped to avoid COM 39-character limit):
    - 'release' -> 'CeriumPDF'
    - other branches -> 'Cerium<br_name>PDF'
    """
    if not branch or branch == "release":
        return "CeriumPDF"
    clean = re.sub(r"[^a-zA-Z0-9]", "", branch.strip())
    if len(clean) > 20:
        suffix = hashlib.sha256(branch.strip().encode()).hexdigest()[:6]
        clean = f"{clean[:14]}{suffix}"
    return f"Cerium{clean}PDF"


if __name__ == "__main__":
    b = get_current_branch()
    print(f"Branch: {b}")
    print(f"Package ID: {get_package_id(b)}")
    print(f"App Name: {get_app_name(b)}")
    print(f"Windows Product Path: {get_windows_product_path(b)}")
    print(f"Windows ProgID: {get_windows_prog_id(b)}")
