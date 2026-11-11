"""
Windows Cross-Compilation Toolchain Mutator (scripts/mutators/platforms/windows/toolchain.py)
Bypasses FUSE ciopfs mount failure in containerized CI environments, fixes
NTDDI_VERSION / NTDDI_WIN11_BR defines, and marks dbghelp.dll as optional for Windows ARM64 builds.
"""

import os
import re
from scripts.mutators.context import MutatorContext


def apply(ctx: MutatorContext):
    re_target_call = re.compile(
        r"            try:\n"
        r"                subprocess\.check_call\(\n"
        r"                    \[\n"
        r"                        ciopfs,\n"
        r"                        '-o',\n"
        r"                        'use_ino',\n"
        r"                        toolchain_dir \+ '\.ciopfs',\n"
        r"                        toolchain_dir,\n"
        r"                    \]\n"
        r"                \)\n"
        r"            except [^\n]+:\n"
        r"[\s\S]*?NOTE: ciopfs mount skipped[\s\S]*?(?:file=sys\.stderr,?\s*\)\s*\n\s+else:\s*\n\s+raise|file=sys\.stderr\))"
        r"|"
        r"            subprocess\.check_call\(\n"
        r"                \[\n"
        r"                    ciopfs,\n"
        r"                    '-o',\n"
        r"                    'use_ino',\n"
        r"                    toolchain_dir \+ '\.ciopfs',\n"
        r"                    toolchain_dir,\n"
        r"                \]\n"
        r"            \)"
    )

    safe_call = """            try:
                subprocess.check_call(
                    [
                        ciopfs,
                        '-o',
                        'use_ino',
                        toolchain_dir + '.ciopfs',
                        toolchain_dir,
                    ]
                )
            except (FileNotFoundError, subprocess.CalledProcessError) as e:
                if (
                    isinstance(e, FileNotFoundError)
                    or not os.path.exists('/dev/fuse')
                    or not os.access('/dev/fuse', os.R_OK | os.W_OK)
                    or getattr(e, 'returncode', None) == 127
                ):
                    print(
                        'NOTE: ciopfs mount skipped (unprivileged container or missing FUSE): %s'
                        % e,
                        file=sys.stderr,
                    )
                else:
                    raise"""

    ctx.replace_in_src("build/vs_toolchain.py", re_target_call, safe_call)

    re_hash_lookup = re.compile(
        r"    toolchain_hash_mapping_key = 'GYP_MSVS_HASH_%s' % TOOLCHAIN_HASH\n"
        r"(?:    return \[os\.environ\.get\(toolchain_hash_mapping_key, TOOLCHAIN_HASH\)\]|"
        r"    mapped_hash = \(\n"
        r"        os\.environ\.get\(toolchain_hash_mapping_key\)\n"
        r"        or os\.environ\.get\('GYP_MSVS_HASH'\)\n"
        r"        or [^\n]+\n"
        r"    \)\n"
        r"(?:    if mapped_hash == TOOLCHAIN_HASH:\n        mapped_hash = [^\n]+\n)?"
        r"    return \[mapped_hash\])"
    )

    safe_hash_lookup = """    toolchain_hash_mapping_key = 'GYP_MSVS_HASH_%s' % TOOLCHAIN_HASH
    mapped_hash = (
        os.environ.get(toolchain_hash_mapping_key)
        or os.environ.get('GYP_MSVS_HASH')
        or '44f9aa3391'
    )
    if mapped_hash == TOOLCHAIN_HASH:
        mapped_hash = os.environ.get('GYP_MSVS_HASH') or '44f9aa3391'
    return [mapped_hash]"""

    ctx.replace_in_src("build/vs_toolchain.py", re_hash_lookup, safe_hash_lookup)

    re_should_update = re.compile(
        r"def ShouldUpdateToolchain\(\):\n"
        r'    """Check if the toolchain should be upgraded."""\n'
        r"    if not os\.path\.exists\(json_data_file\):\n"
        r"        return True\n"
        r"[\s\S]*?"
        r"    return version != env_version"
    )
    safe_should_update = (
        "def ShouldUpdateToolchain():\n"
        "    return not os.path.exists(json_data_file)"
    )
    ctx.replace_in_src("build/vs_toolchain.py", re_should_update, safe_should_update)

    # Ensure dbghelp.dll is marked as optional in _CopyDebugger so Windows ARM64 builds
    # (and toolchains without Debugging Tools) do not fail gn gen when arm64/dbghelp.dll is missing.
    re_dbghelp = re.compile(r"\('dbghelp\.dll',\s*False\)")
    safe_dbghelp = "('dbghelp.dll', True)"
    ctx.replace_in_src(
        "build/vs_toolchain.py",
        re_dbghelp,
        safe_dbghelp,
        check_token="('dbghelp.dll', True)",
    )

    # Ensure Windows build config defines NTDDI_WIN11_BR and numeric NTDDI_VERSION
    # so Windows SDK headers (e.g. minwinbase.h defining FILE_INFO_BY_HANDLE_CLASS)
    # compile cleanly across SDK 26100 and newer.
    re_winver = re.compile(r'"NTDDI_VERSION=[^"]+",\n')
    safe_winver = (
        '"NTDDI_WIN11_BR=0x0A000014",\n'
        '    "NTDDI_VERSION=0x0A000014",\n'
    )
    ctx.replace_in_src(
        "build/config/win/BUILD.gn",
        re_winver,
        safe_winver,
        check_token="NTDDI_WIN11_BR=0x0A000014",
    )

    # Ensure setup_toolchain.py auto-bridges atlmfc/lib/arm64 from spectre/arm64
    # so Windows ARM64 builds do not fail during gn gen due to missing directory.
    re_missing_lib_check = re.compile(
        r"                    for part in setting\.split\(';'\):\n"
        r"                        if not os\.path\.exists\(part\) and len\(part\) != 0:\n"
        r"                            raise Exception\(\n"
        r"                                'Path \"%s\" from environment variable \"%s\" does not exist\. '\n"
        r"                                'Make sure the necessary SDK is installed\.'\n"
        r"                                % \(part, envvar\)\n"
        r"                            \)"
    )
    safe_missing_lib_check = (
        "                    for part in setting.split(';'):\n"
        "                        if not os.path.exists(part) and len(part) != 0:\n"
        "                            if 'atlmfc' in part.lower():\n"
        "                                spectre_cand = part.replace(\n"
        "                                    os.path.join('atlmfc', 'lib', 'arm64'),\n"
        "                                    os.path.join('atlmfc', 'lib', 'spectre', 'arm64'),\n"
        "                                )\n"
        "                                if os.path.isdir(spectre_cand):\n"
        "                                    try:\n"
        "                                        os.symlink(spectre_cand, part)\n"
        "                                    except Exception:\n"
        "                                        import shutil\n"
        "                                        shutil.copytree(spectre_cand, part)\n"
        "                                else:\n"
        "                                    os.makedirs(part, exist_ok=True)\n"
        "                            if not os.path.exists(part):\n"
        "                                raise Exception(\n"
        "                                    'Path \"%s\" from environment variable \"%s\" does not exist. '\n"
        "                                    'Make sure the necessary SDK is installed.'\n"
        "                                    % (part, envvar)\n"
        "                                )"
    )
    setup_toolchain_path = "build/toolchain/win/setup_toolchain.py"
    if ctx.src_dir and os.path.exists(os.path.join(ctx.src_dir, setup_toolchain_path)):
        ctx.replace_in_src(
            setup_toolchain_path,
            re_missing_lib_check,
            safe_missing_lib_check,
            check_token="spectre_cand = part.replace",
        )


