"""Command line:

    python -m dubqc check FILE.wav [FILE.wav ...] --spec spec.yaml
    python -m dubqc make-demo samples/synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .delivery import check_files
from .report import overall_pass, write_reports
from .spec import load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dubqc", description="QC checks for dubbed dialogue deliveries.")
    sub = parser.add_subparsers(dest="command", required=True)

    chk = sub.add_parser("check", help="Delivery check: naming, format, loudness, clipping, pip.")
    chk.add_argument("files", nargs="+", help="WAV files to check")
    chk.add_argument("--spec", help="delivery spec YAML (defaults: EBU R128, 48k/24/mono)")
    chk.add_argument("--out", default="reports", help="folder for the reports (default: reports)")
    chk.add_argument("--project", default="Dub QC", help="project name for the report header")

    demo = sub.add_parser("make-demo", help="Write synthetic test WAVs.")
    demo.add_argument("folder", nargs="?", default="samples/synthetic")

    args = parser.parse_args(argv)

    if args.command == "make-demo":
        from .demo import write_demo_set
        for p in write_demo_set(args.folder):
            print(f"wrote {p}")
        return 0

    spec = load_spec(args.spec)
    files = [Path(f) for f in args.files]
    missing = [f for f in files if not f.exists()]
    if missing:
        print("File(s) not found: " + ", ".join(map(str, missing)), file=sys.stderr)
        return 2

    results = check_files(files, spec)
    for r in results:
        crit = sum(i.severity == "Critical" for i in r.issues)
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.file}  ({len(r.issues)} issue(s), {crit} critical)")
        for i in r.issues:
            print(f"      {i.timecode or '           '}  {i.severity:<8} {i.code}: {i.message}")
    paths = write_reports(results, spec, args.out, args.project)
    print(f"\nOverall: {'PASS' if overall_pass(results) else 'FAIL'}")
    for kind, p in paths.items():
        print(f"{kind:>8}: {p}")
    return 0 if overall_pass(results) else 1
