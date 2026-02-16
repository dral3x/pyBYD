#!/usr/bin/env python3
"""Compare two BYD dump files and show what changed.

Usage
-----
    python scripts/diff_dumps.py old.txt new.txt
    python scripts/diff_dumps.py --include-raw old.txt new.txt
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SKIP_KEYS = {"raw", "traceback"}
MAX_VAL_WIDTH = 60
MISSING = "<missing>"


def _truncate(val: Any, width: int = MAX_VAL_WIDTH) -> str:
    s = str(val)
    if len(s) <= width:
        return s
    return s[: width - 3] + "..."


def _diff(
    old: Any,
    new: Any,
    path: str,
    results: list[tuple[str, Any, Any]],
    skip_keys: set[str],
) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = dict.fromkeys(list(old.keys()) + list(new.keys()))
        for key in all_keys:
            if key in skip_keys:
                continue
            child_path = f"{path}.{key}" if path else key
            if key not in old:
                _collect_leaves(new[key], child_path, results, side="new", skip_keys=skip_keys)
            elif key not in new:
                _collect_leaves(old[key], child_path, results, side="old", skip_keys=skip_keys)
            else:
                _diff(old[key], new[key], child_path, results, skip_keys)
    elif isinstance(old, list) and isinstance(new, list):
        for i in range(max(len(old), len(new))):
            child_path = f"{path}[{i}]"
            if i >= len(old):
                _collect_leaves(new[i], child_path, results, side="new", skip_keys=skip_keys)
            elif i >= len(new):
                _collect_leaves(old[i], child_path, results, side="old", skip_keys=skip_keys)
            else:
                _diff(old[i], new[i], child_path, results, skip_keys)
    else:
        if old != new:
            results.append((path, old, new))


def _collect_leaves(
    obj: Any,
    path: str,
    results: list[tuple[str, Any, Any]],
    side: str,
    skip_keys: set[str],
) -> None:
    """Collect all leaf values for an object that exists only on one side."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in skip_keys:
                continue
            _collect_leaves(val, f"{path}.{key}", results, side, skip_keys)
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            _collect_leaves(val, f"{path}[{i}]", results, side, skip_keys)
    else:
        if side == "new":
            results.append((path, MISSING, obj))
        else:
            results.append((path, obj, MISSING))


def main() -> None:
    parser = argparse.ArgumentParser(description="Diff two BYD dump files.")
    parser.add_argument("old", help="Older dump file")
    parser.add_argument("new", help="Newer dump file")
    parser.add_argument("--include-raw", action="store_true", help="Include 'raw' sub-dicts in comparison")
    args = parser.parse_args()

    file_old, file_new = Path(args.old), Path(args.new)

    print(f"Old: {file_old.name}")
    print(f"New: {file_new.name}")
    print()

    old = json.loads(file_old.read_text(encoding="utf-8"))
    new = json.loads(file_new.read_text(encoding="utf-8"))

    skip_keys = set() if args.include_raw else SKIP_KEYS

    results: list[tuple[str, Any, Any]] = []
    _diff(old, new, "", results, skip_keys)

    if not results:
        print("No differences found.")
        return

    # Calculate column widths
    path_w = max(len(r[0]) for r in results)
    old_w = max(len(_truncate(r[1])) for r in results)
    new_w = max(len(_truncate(r[2])) for r in results)

    path_w = max(path_w, 4)
    old_w = max(old_w, 3)
    new_w = max(new_w, 3)

    header = f"{'Path':<{path_w}}  {'Old':<{old_w}}  {'New':<{new_w}}"
    print(header)
    print("─" * len(header))

    for path, old_val, new_val in results:
        print(f"{path:<{path_w}}  {_truncate(old_val):<{old_w}}  {_truncate(new_val):<{new_w}}")

    print(f"\n{len(results)} difference(s) found.")


if __name__ == "__main__":
    main()
