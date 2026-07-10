#!/usr/bin/env python3
"""Generate the runtime identity embedded in a Captain desktop bundle."""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.runtime_identity import build_bundle_stamp, write_bundle_stamp


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--output", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--trust", default="development")
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    values = build_bundle_stamp(
        os.path.abspath(args.root),
        target_platform=args.platform,
        trust=args.trust,
        commit=args.commit or None,
    )
    write_bundle_stamp(os.path.abspath(args.output), values)
    print(
        f"bundle stamp: version={values['version']} commit={values['commit'][:12]} "
        f"platform={values['platform']} trust={values['trust']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
