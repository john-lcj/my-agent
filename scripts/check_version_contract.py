#!/usr/bin/env python3
"""Fail when any release surface disagrees with the canonical VERSION file."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.runtime_identity import validate_version_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=ROOT)
    args = parser.parse_args()
    ok, values = validate_version_contract(os.path.abspath(args.root))
    for source, value in values.items():
        print(f"{source}={value or '<missing>'}")
    if not ok:
        print("version contract mismatch", file=sys.stderr)
        return 1
    print(f"version contract ok: {values['VERSION']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
