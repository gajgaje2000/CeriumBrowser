"""
WebUI Branding Logo Mutator (scripts/mutators/common/branding_js.py)
Points WebUI chrome_logo_dark.svg override in branding.js to app/theme/brave/product_logo.svg
instead of @brave/leo node_modules so WebUI pages use the colored Cerium logo,
and de-brands version strings and URLs in settings about_page.ts.
"""

import re
from scripts.mutators.context import MutatorContext


def _debrand_about_page(content: str):
    if "Cerium ${braveVersion} ${build}" in content:
        return content, False, True
    if "`Brave ${braveVersion} ${build}`" not in content:
        return content, False, False

    new_content = content.replace(
        "`Brave ${braveVersion} ${build}`",
        "`Cerium ${braveVersion} ${build}`",
    )
    new_content = new_content.replace(
        "https://brave.com/latest/",
        "https://gitlab.com/cerium-browser/cerium/-/releases",
    )
    new_content = new_content.replace(
        "https://support.brave.app/hc/en-us/articles/360042816611-Why-isn-t-Brave-updating-automatically-on-Windows-",
        "https://gitlab.com/cerium-browser/cerium/-/issues",
    )
    new_content = new_content.replace(
        "https://community.brave.app?p=update_error",
        "https://gitlab.com/cerium-browser/cerium/-/issues",
    )
    return new_content, True, True


def apply(ctx: MutatorContext):
    ctx.replace_in_file(
        "build/commands/lib/branding.js",
        re.compile(
            r"path\.join\(\s*config\.braveCoreDir,\s*['\"]node_modules['\"],\s*['\"]@brave['\"],\s*['\"]leo['\"],\s*['\"]icons['\"],\s*config\.getBraveLogoIconName\(\),?\s*\)",
            re.DOTALL
        ),
        """path.join(
      braveAppDir,
      'theme',
      'brave',
      'product_logo.svg',
    )""",
    )
    ctx.mutate_file(
        "browser/resources/settings/br/about_page.ts",
        _debrand_about_page,
    )
