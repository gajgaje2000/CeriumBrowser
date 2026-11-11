"""
Windows Desktop Branding & Identity Mutator
(scripts/mutators/platforms/windows/branding.py)
Remaps company path, product path, app name, and ProgIDs in
chromium_install_modes.h and brave_shell_util.cc to Cerium.
"""

import re
from scripts.core.branch_utils import (
    get_current_branch,
    get_windows_product_path,
    get_windows_app_name,
    get_windows_app_id,
    get_windows_prog_id,
    get_windows_pdf_prog_id,
)
from scripts.mutators.context import MutatorContext


def escape_cpp_wide_string(s: str) -> str:
    """Escapes backslashes and double quotes for C++ wide string literal emission."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def apply(ctx: MutatorContext):
    branch = get_current_branch()
    product_path = get_windows_product_path(branch)
    app_name = get_windows_app_name(branch)
    app_id = get_windows_app_id(branch)
    prog_id = get_windows_prog_id(branch)
    pdf_prog_id = get_windows_pdf_prog_id(branch)

    cpp_product_path = escape_cpp_wide_string(product_path)
    cpp_app_name = escape_cpp_wide_string(app_name)
    cpp_app_id = escape_cpp_wide_string(app_id)
    cpp_prog_id = escape_cpp_wide_string(prog_id)
    cpp_pdf_prog_id = escape_cpp_wide_string(pdf_prog_id)

    # 1. Update company, product paths, and install modes in chromium_install_modes.h
    def mutate_install_modes(content: str):
        patterns = [
            (r'inline constexpr wchar_t kCompanyPathName\[\] = L"(?:BraveSoftware|Cerium)";',
             'inline constexpr wchar_t kCompanyPathName[] = L"Cerium";'),
            (r'inline constexpr wchar_t kProductPathName\[\] = L"(?:Brave-Origin|Brave-Browser|Cerium-Browser(?:-[^"]*)?)";',
             f'inline constexpr wchar_t kProductPathName[] = L"{cpp_product_path}";'),
            (r'inline constexpr wchar_t kProductPathName\[\] = L"(?:Brave-Browser-Development|Cerium-Development)";',
             'inline constexpr wchar_t kProductPathName[] = L"Cerium-Development";'),
            (r'\.base_app_name = L"(?:Brave Origin|Brave|Cerium(?: \([^)]+\))?)"',
             f'.base_app_name = L"{cpp_app_name}"'),
            (r'\.base_app_id = L"(?:BraveOrigin|Brave|Cerium(?:\.[^"]+)?)"',
             f'.base_app_id = L"{cpp_app_id}"'),
            (r'\.browser_prog_id_prefix = L"(?:BraveOHTML|BraveHTML|Cerium[^"]*HTML)"',
             f'.browser_prog_id_prefix = L"{cpp_prog_id}"'),
            (r'\.browser_prog_id_description =\s*L"(?:Brave Origin|Brave|Cerium(?: \([^)]+\))?) HTML Document"',
             f'.browser_prog_id_description =\n            L"{cpp_app_name} HTML Document"'),
            (r'\.pdf_prog_id_prefix = L"(?:BraveOPDF|BravePDF|Cerium[^"]*PDF)"',
             f'.pdf_prog_id_prefix = L"{cpp_pdf_prog_id}"'),
            (r'\.pdf_prog_id_description =\s*L"(?:Brave Origin|Brave|Cerium(?: \([^)]+\))?) PDF Document"',
             f'.pdf_prog_id_description =\n            L"{cpp_app_name} PDF Document"'),
        ]

        new_content = content
        for pat, rep in patterns:
            new_content, _ = re.subn(pat, rep, new_content)

        found = (f'inline constexpr wchar_t kProductPathName[] = L"{cpp_product_path}";' in new_content and
                 f'.base_app_name = L"{cpp_app_name}"' in new_content)

        if not found:
            return content, False, False

        modified = (new_content != content)
        return new_content, modified, found

    ctx.mutate_file(
        "chromium_src/chrome/install_static/chromium_install_modes.h",
        mutate_install_modes,
    )

    # 2. File type ProgIDs in brave_shell_util.cc
    # 2. File type ProgIDs in brave_shell_util.cc
    def mutate_shell_util(content: str):
        replacements = [
            ('return L"BraveFile";', 'return L"CeriumFile";'),
            ('return L"BraveBFile";', 'return L"CeriumBFile";'),
            ('return L"BraveDFile";', 'return L"CeriumDFile";'),
            ('return L"BraveSSFile";', 'return L"CeriumSSFile";'),
        ]
        modified = False
        new_content = content
        for old, new in replacements:
            if old in new_content:
                new_content = new_content.replace(old, new)
                modified = True
            elif new not in new_content:
                return content, False, False
        all_satisfied = all(new in new_content for _, new in replacements)
        return new_content, modified, all_satisfied

    ctx.mutate_file("installer/util/brave_shell_util.cc", mutate_shell_util)

    # 3. Windows Updater & Installer Registry De-Branding (Software\Cerium\Update)
    # File 1: google_update_constants.cc
    ctx.replace_in_file(
        "chromium_src/chrome/installer/util/google_update_constants.cc",
        'const wchar_t kGoogleUpdateSetupExe[] = L"BraveUpdateSetup.exe";',
        'const wchar_t kGoogleUpdateSetupExe[] = L"CeriumUpdateSetup.exe";',
    )
    for old, new in [
        (
            'const wchar_t kRegPathClients[] = L"Software\\\\BraveSoftware\\\\Update\\\\Clients";',
            'const wchar_t kRegPathClients[] = L"Software\\\\Cerium\\\\Update\\\\Clients";',
        ),
        (
            'const wchar_t kRegPathClientState[] =\n    L"Software\\\\BraveSoftware\\\\Update\\\\ClientState";',
            'const wchar_t kRegPathClientState[] =\n    L"Software\\\\Cerium\\\\Update\\\\ClientState";',
        ),
        (
            'const wchar_t kRegPathClientStateMedium[] =\n    L"Software\\\\BraveSoftware\\\\Update\\\\ClientStateMedium";',
            'const wchar_t kRegPathClientStateMedium[] =\n    L"Software\\\\Cerium\\\\Update\\\\ClientStateMedium";',
        ),
        (
            'const wchar_t kRegPathGoogleUpdate[] = L"Software\\\\BraveSoftware\\\\Update";',
            'const wchar_t kRegPathGoogleUpdate[] = L"Software\\\\Cerium\\\\Update";',
        ),
    ]:
        ctx.replace_in_file(
            "chromium_src/chrome/installer/util/google_update_constants.cc",
            old,
            new,
        )

    # File 2: install_modes.cc
    for old, new in [
        (
            'L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\"',
            'L"Software\\\\Cerium\\\\Update\\\\Clients\\\\"',
        ),
        (
            'L"Software\\\\BraveSoftware\\\\Update\\\\ClientState\\\\"',
            'L"Software\\\\Cerium\\\\Update\\\\ClientState\\\\"',
        ),
        (
            'L"Software\\\\BraveSoftware\\\\Update\\\\ClientStateMedium\\\\"',
            'L"Software\\\\Cerium\\\\Update\\\\ClientStateMedium\\\\"',
        ),
    ]:
        ctx.replace_in_file(
            "chromium_src/chrome/install_static/install_modes.cc",
            old,
            new,
        )

    # File 3: mini_installer_constants.cc
    for old, new in [
        (
            'const wchar_t kClientsKeyBase[] = L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\";',
            'const wchar_t kClientsKeyBase[] = L"Software\\\\Cerium\\\\Update\\\\Clients\\\\";',
        ),
        (
            'const wchar_t kClientStateKeyBase[] =\n    L"Software\\\\BraveSoftware\\\\Update\\\\ClientState\\\\";',
            'const wchar_t kClientStateKeyBase[] =\n    L"Software\\\\Cerium\\\\Update\\\\ClientState\\\\";',
        ),
        (
            'const wchar_t kCleanupRegistryKey[] =\n    L"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\Brave";',
            'const wchar_t kCleanupRegistryKey[] =\n    L"Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Uninstall\\\\Cerium";',
        ),
        (
            'const wchar_t kClientsKeyBase[] = L"Software\\\\Brave-Browser-Development";',
            'const wchar_t kClientsKeyBase[] = L"Software\\\\Cerium-Development";',
        ),
        (
            'const wchar_t kClientStateKeyBase[] = L"Software\\\\Brave-Browser-Development";',
            'const wchar_t kClientStateKeyBase[] = L"Software\\\\Cerium-Development";',
        ),
        (
            'const wchar_t kCleanupRegistryKey[] = L"Software\\\\Brave-Browser-Development";',
            'const wchar_t kCleanupRegistryKey[] = L"Software\\\\Cerium-Development";',
        ),
    ]:
        ctx.replace_in_file(
            "chromium_src/chrome/installer/mini_installer/mini_installer_constants.cc",
            old,
            new,
        )

    # File 4: chrome_launcher_support.cc
    ctx.replace_in_file(
        "chromium_src/chrome/installer/launcher_support/chrome_launcher_support.cc",
        'const wchar_t kInstallationRegKey[] =\n    L"Software\\\\BraveSoftware\\\\Update\\\\ClientState";',
        'const wchar_t kInstallationRegKey[] =\n    L"Software\\\\Cerium\\\\Update\\\\ClientState";',
    )

    # File 5: updater_state_win.cc
    for old, new in [
        (
            'const wchar_t kGoogleUpdatePoliciesKey[] =\n    L"SOFTWARE\\\\Policies\\\\BraveSoftware\\\\Update";',
            'const wchar_t kGoogleUpdatePoliciesKey[] =\n    L"SOFTWARE\\\\Policies\\\\Cerium\\\\Update";',
        ),
        (
            'const wchar_t kRegPathGoogleUpdate[] = L"Software\\\\BraveSoftware\\\\Update";',
            'const wchar_t kRegPathGoogleUpdate[] = L"Software\\\\Cerium\\\\Update";',
        ),
        (
            'const wchar_t kRegPathClientsGoogleUpdate[] =\n    L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\"',
            'const wchar_t kRegPathClientsGoogleUpdate[] =\n    L"Software\\\\Cerium\\\\Update\\\\Clients\\\\"',
        ),
    ]:
        ctx.replace_in_file(
            "chromium_src/chrome/browser/component_updater/updater_state_win.cc",
            old,
            new,
        )

    # File 6: google_update_util.cc
    for old, new in [
        (
            'L"Software\\\\BraveSoftware\\\\Update\\\\Clients\\\\"',
            'L"Software\\\\Cerium\\\\Update\\\\Clients\\\\"',
        ),
        (
            'L"Software\\\\BraveSoftware\\\\Update\\\\ClientState\\\\"',
            'L"Software\\\\Cerium\\\\Update\\\\ClientState\\\\"',
        ),
    ]:
        ctx.replace_in_file(
            "chromium_src/chrome/installer/gcapi/google_update_util.cc",
            old,
            new,
        )
