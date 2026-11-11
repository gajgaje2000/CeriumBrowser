#!/usr/bin/env python3
"""
Cerium Build Stream Filter
Prevents CI log truncation (4MB limit) while preserving progress,
compiler errors, warnings, and failure diagnostics in real-time.

Features:
- Handles both \\r (Siso/Ninja in-place updates) and \\n delimiters
- Writes 100% of raw output to persistent build.log
- Throttles progress updates (step 1, every N steps, and final step)
- Deduplicates rapid in-place updates for identical steps
- Simple 3.5MB safety ceiling to protect GitLab CI's 4MB limit
- Periodic heartbeats so CI web consoles never appear stalled

Usage:
  autoninja -C out/Release chrome_public_apk 2>&1 | python3 -u filter-build-log.py <path_to_build.log> [step_interval] [heartbeat_seconds]
"""

import os
import re
import select
import sys
import time


def format_duration(seconds: float) -> str:
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h}h {m:02d}m {sec:02d}s"
    elif m > 0:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else "build.log"
    step_interval = int(sys.argv[2]) if len(sys.argv) > 2 else int(os.environ.get("CERIUM_LOG_STEP_INTERVAL", "50"))
    heartbeat_interval = int(sys.argv[3]) if len(sys.argv) > 3 else int(os.environ.get("CERIUM_LOG_HEARTBEAT", "20"))

    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Matches Ninja and Siso progress regardless of duration prefixes (seconds, minutes, hours)
    progress_pattern = re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]\s*(.*)$")
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

    start_time = time.time()
    last_output_time = start_time
    last_step = 0
    total_steps = 0
    last_emitted_step = -1
    total_stdout_bytes = 0

    max_bytes = int(os.environ.get("CERIUM_MAX_LOG_BYTES", "3670016"))

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    def write_out(text: str):
        nonlocal total_stdout_bytes, last_output_time
        # Safety ceiling at 3.5MB to protect GitLab CI's 4MB limit, always allowing fatal errors
        if total_stdout_bytes < max_bytes or "FAILED:" in text or "fatal error" in text.lower():
            sys.stdout.write(f"{text}\n")
            sys.stdout.flush()
            total_stdout_bytes += len(text.encode("utf-8", errors="replace")) + 1
            last_output_time = time.time()

    def emit_heartbeat():
        elapsed = format_duration(time.time() - start_time)
        if total_steps > 0:
            pct = (last_step * 100.0) / total_steps
            write_out(f"[heartbeat] Siso active: [{last_step}/{total_steps} ({pct:.1f}%)] ({elapsed} elapsed)")
        else:
            write_out(f"[heartbeat] Siso analyzing build graph... ({elapsed} elapsed)")

    def process_line(raw_line: str, f_out):
        nonlocal last_step, total_steps, last_emitted_step

        # Write 100% of raw lines to persistent build.log
        f_out.write(raw_line + "\n")
        f_out.flush()

        cleaned = ansi_pattern.sub("", raw_line).strip()
        if not cleaned:
            return

        m = progress_pattern.search(cleaned)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            last_step = current
            total_steps = total

            # Throttle progress lines: step 1, every step_interval, and final step (deduplicating identical steps)
            if (current == 1 or current % step_interval == 0 or current == total) and current != last_emitted_step:
                last_emitted_step = current
                pct = (current * 100.0) / total if total > 0 else 0.0
                action = m.group(3)
                elapsed = format_duration(time.time() - start_time)
                write_out(f"[{current}/{total} ({pct:.1f}%)] {action} [{elapsed}]")
        else:
            # Forward compiler errors, warnings, and messages directly
            write_out(cleaned)

    with open(log_path, "w", encoding="utf-8", errors="replace") as f_out:
        buf = ""
        stdin_fd = sys.stdin.fileno()

        while True:
            try:
                r, _, _ = select.select([stdin_fd], [], [], float(heartbeat_interval))
            except (ValueError, OSError):
                break

            if not r:
                emit_heartbeat()
                continue

            try:
                chunk = os.read(stdin_fd, 4096)
            except OSError:
                break

            if not chunk:
                break

            buf += chunk.decode("utf-8", errors="replace")

            while "\r" in buf or "\n" in buf:
                idx_r = buf.find("\r")
                idx_n = buf.find("\n")
                if idx_r != -1 and idx_n != -1:
                    idx = min(idx_r, idx_n)
                elif idx_r != -1:
                    idx = idx_r
                else:
                    idx = idx_n

                line = buf[:idx]
                buf = buf[idx + 1 :]
                if line.strip():
                    process_line(line, f_out)

        if buf.strip():
            process_line(buf, f_out)

        total_elapsed = format_duration(time.time() - start_time)
        if total_steps > 0:
            write_out(f"\n[Build Stream Completed: {last_step}/{total_steps} steps processed in {total_elapsed}]")


if __name__ == "__main__":
    main()
