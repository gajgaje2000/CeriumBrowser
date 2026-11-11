"""
Android Version Display Mutator (scripts/mutators/android/version_display.py)
Removes Chromium major version milestone from APK name and Settings product version string.
"""

import re
from scripts.mutators.context import MutatorContext


def apply(ctx: MutatorContext):
    ctx.replace_in_src(
        "chrome/version.gni",
        re.compile(r"^[ \t]*chrome_version_name\s*=\s*chrome_version_full\b", re.MULTILINE),
        """  declare_args() {
    chrome_version_name =
        "$chrome_version_minor.$chrome_version_build.$chrome_version_patch"
  }""",
    )
