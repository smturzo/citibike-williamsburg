#!/usr/bin/env python3
"""Nightly rollup: repair weather gaps, compact, rebuild, refresh stats.

Deliberately Python rather than the shell script this replaced. Under launchd,
`/bin/zsh <script>` failed with "can't open input file" even though the path was
correct and the file executable - launchd agents run in a restricted context that
did not grant zsh read access to this directory, while the Python framework
binary the collector already uses works fine. Invoking that same interpreter
sidesteps the problem instead of fighting it.

Each step runs even if an earlier one fails, so one bad step can't silently
cancel the rest of the night's work; the exit code reflects any failure.
"""
import os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

STEPS = [
    ("weather backfill", ["collect/weather.py", "--days", "7"]),
    ("compact",          ["collect/compact.py"]),
    ("build db",         ["db/build_db.py"]),
    ("build stats",      ["analysis/build_stats.py"]),
    ("health",           ["ops/health.py"]),
    ("size guard",       ["ops/sizecheck.py"]),
]


def main():
    failures = []
    for label, args in STEPS:
        print(f"\n===== {label} =====", flush=True)
        r = subprocess.run([PY, os.path.join(ROOT, *args[0].split("/"))] + args[1:],
                           cwd=ROOT)
        if r.returncode != 0:
            print(f"!! {label} exited {r.returncode}", file=sys.stderr, flush=True)
            failures.append(label)
    if failures:
        print(f"\nFAILED STEPS: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nrollup complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
