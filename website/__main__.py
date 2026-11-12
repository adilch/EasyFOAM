"""Command line of the tutorials website: ``python -m website shots|build|check``."""

from __future__ import annotations

import argparse
import sys

from website import sitegen
from website.tutorials import ALL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m website", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shots = commands.add_parser("shots", help="operate the application and take the pictures (needs OpenFOAM)")
    shots.add_argument("names", nargs="*", help="tutorials to do (default: all)")
    commands.add_parser("build", help="write the pages into docs/")
    commands.add_parser("check", help="fail if the pages in docs/ are out of date or a picture is missing")
    args = parser.parse_args(argv)

    if args.command == "shots":
        from website.driver import take

        known = {t.slug: t for t in ALL}
        unknown = [n for n in args.names if n not in known]
        if unknown:
            parser.error(f"no such tutorial: {', '.join(unknown)} (there are: {', '.join(known)})")
        for name in args.names or list(known):
            print(f"{name}:", flush=True)
            take(known[name])
        return 0
    if args.command == "build":
        changed = sitegen.build(ALL)
        print(f"{len(changed)} file(s) written to {sitegen.OUT}" if changed else "The pages were already up to date.")
        for name in sitegen.missing_images(ALL):
            print(f"  missing picture: {name}")
        return 0
    stale = sitegen.out_of_date(ALL)
    missing = sitegen.missing_images(ALL)
    for name in stale:
        print(f"out of date: {name}   (run: python -m website build)")
    for name in missing:
        print(f"missing picture: {name}   (run: python -m website shots)")
    return 1 if stale or missing else 0


if __name__ == "__main__":
    sys.exit(main())
