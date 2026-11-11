"""
Cerium Mutator Execution Context (scripts/mutators/context.py)
Provides unified file mutation and parsing primitives for component mutators.
"""

import os
import re
import sys


class MutatorContext:
    def __init__(self, brave_dir: str, src_dir: str = None, strict: bool = False,
                 target_os: str = "android", explicit_src_dir: bool = False):
        self.brave_dir = brave_dir
        self.src_dir = src_dir
        self.strict = strict
        self.target_os = target_os
        self.explicit_src_dir = explicit_src_dir

    def has_chromium_src(self) -> bool:
        if not self.src_dir:
            return False
        return os.path.isdir(os.path.join(self.src_dir, "components")) or os.path.isdir(os.path.join(self.src_dir, "chrome"))

    def _fail_or_warn(self, msg: str) -> bool:
        """Exit when strict mode is active, otherwise log a warning."""
        if self.strict:
            print(f"ERROR: {msg}", file=sys.stderr)
            sys.exit(1)
        print(f"WARNING: {msg}")
        return False

    def _load_target_file(self, filepath: str, in_src: bool):
        """Resolve filepath under src or brave root and return (abs_path, content), or (None, None) when skipped/missing."""
        if in_src and not self.has_chromium_src():
            print(f"Skipped (no Chromium src): {filepath}")
            return None, None
        base = self.src_dir if in_src else self.brave_dir
        path = os.path.join(base, filepath)
        if not os.path.exists(path):
            self._fail_or_warn(f"{'MISSING SRC: ' if in_src else 'MISSING: '}{filepath}")
            return None, None
        with open(path, "r", encoding="utf-8") as f:
            return path, f.read()

    def replace_in_file(self, filepath: str, search, replacement: str, check_token: str = None, in_src: bool = False):
        path, content = self._load_target_file(filepath, in_src)
        if content is None:
            return False

        if (check_token and check_token in content) or (isinstance(replacement, str) and replacement in content):
            print(f"Skipped {filepath} (already patched)")
            return True

        if isinstance(search, str) and search in content:
            content = content.replace(search, replacement, 1)
        elif hasattr(search, "search") and search.search(content):
            content = search.sub(lambda _: replacement, content, count=1)
        else:
            pattern_str = search.pattern if hasattr(search, "pattern") else search
            return self._fail_or_warn(f"Search string not found in {filepath}: {pattern_str[:50]}...")

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Patched {filepath}")
        return True

    def replace_in_src(self, filepath: str, search, replacement: str, check_token: str = None):
        return self.replace_in_file(filepath, search, replacement, check_token=check_token, in_src=True)

    def mutate_file(self, filepath: str, mutator_fn, in_src: bool = False):
        path, content = self._load_target_file(filepath, in_src)
        if content is None:
            return False

        new_content, modified, found = mutator_fn(content)
        if modified:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Patched {filepath}")
            return True
        if found:
            print(f"Skipped {filepath} (already patched)")
            return True
        return self._fail_or_warn(f"Search string not found in {filepath}")

    @staticmethod
    def find_matching_char(text: str, start_idx: int, open_char: str = "[", close_char: str = "]") -> int:
        depth = 0
        in_str = False
        escaped = False
        in_comment = False
        i = start_idx
        while i < len(text):
            ch = text[i]
            if in_comment:
                if ch == "\n":
                    in_comment = False
            elif in_str:
                if ch == "\\" and not escaped:
                    escaped = True
                elif ch == '"' and not escaped:
                    in_str = False
                else:
                    escaped = False
            else:
                if ch == "#":
                    in_comment = True
                elif ch == '"':
                    in_str = True
                elif ch == open_char:
                    depth += 1
                elif ch == close_char:
                    depth -= 1
                    if depth == 0:
                        return i
            i += 1
        return -1
