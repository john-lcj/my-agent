#!/usr/bin/env python3
"""Validate a Captain bundle stamp and its expected release identity."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.runtime_identity import parse_bundle_stamp, stamp_integrity_valid


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stamp")
    parser.add_argument("--version", default="")
    parser.add_argument("--trust", default="")
    args = parser.parse_args()

    stamp = parse_bundle_stamp(args.stamp)
    if not stamp_integrity_valid(stamp):
        raise SystemExit("bundle stamp integrity check failed")
    if args.version and stamp.get("version") != args.version:
        raise SystemExit("bundle stamp version mismatch")
    if args.trust and stamp.get("trust") != args.trust:
        raise SystemExit("bundle stamp trust mismatch")
    print(
        "bundle stamp ok: "
        f"version={stamp.get('version', '')} "
        f"commit={stamp.get('commit', '')} "
        f"trust={stamp.get('trust', '')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
