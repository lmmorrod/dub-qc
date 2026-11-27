"""Command line:

    python -m dubqc check FILE.wav [FILE.wav ...] --spec spec.yaml [--producers producers.csv] [--baseline old.json]
    python -m dubqc make-demo samples/synthetic
    python -m dubqc make-demo-batch samples/synthetic/batch
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .batch import run_batch
from .redelivery import load_baseline
from .report import write_reports
from .scorecard import load_producers
from .spec import load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dubqc", description="Dub QC: delivery QC for dubbed dialogue.")
    sub = parser.add_subparsers(dest="command", required=True)

    chk = sub.add_parser("check", help="QC a batch: per-file checks, manifest, producer scorecard, redeliveries.")
    chk.add_argument("files", nargs="+", help="WAV files to check")
    chk.add_argument("--spec", help="delivery spec YAML (defaults: EBU R128, 48k/24/mono)")
    chk.add_argument("--producers", help="CSV or YAML mapping file -> producer")
    chk.add_argument("--baseline", help="an earlier JSON report, so redeliveries can be compared with it")
    chk.add_argument("--out", default="reports", help="folder for the reports (default: reports)")
    chk.add_argument("--project", default="Dub QC", help="project name for the report header")

    demo = sub.add_parser("make-demo", help="Write three synthetic single-reel test WAVs.")
    demo.add_argument("folder", nargs="?", default="samples/synthetic")

    demo_batch = sub.add_parser("make-demo-batch", help="Write a synthetic 3-territory batch plus producers.csv.")
    demo_batch.add_argument("folder", nargs="?", default="samples/synthetic/batch")

    args = parser.parse_args(argv)

    if args.command == "make-demo":
        from .demo import write_demo_set
        for p in write_demo_set(args.folder):
            print(f"wrote {p}")
        return 0
    if args.command == "make-demo-batch":
        from .demo import write_demo_batch
        paths, csv_path = write_demo_batch(args.folder)
        print(f"wrote {len(paths)} WAVs and {csv_path}")
        return 0

    spec = load_spec(args.spec)
    files = [Path(f) for f in args.files]
    missing = [f for f in files if not f.exists()]
    if missing:
        print("File(s) not found: " + ", ".join(map(str, missing)), file=sys.stderr)
        return 2

    batch = run_batch(files, spec, producers=load_producers(args.producers),
                      baseline=load_baseline(args.baseline) if args.baseline else None)

    for r in batch.files:
        crit = sum(i.severity == "Critical" for i in r.issues)
        status = "OLD " if r.superseded else ("PASS" if r.passed else "FAIL")
        print(f"{status}  {r.file}  ({len(r.issues)} issue(s), {crit} critical)")
        for i in r.issues:
            print(f"      {i.timecode or '           '}  {i.severity:<8} {i.code}: {i.message}")

    if batch.manifest:
        print("\nDelivery manifest")
        for t in batch.manifest["territories"]:
            print(f"  {t['summary']}")
        for u in batch.manifest["unexpected_other"]:
            print(f"  Not on this delivery: {u['file']} ({u['reason']})")
    if batch.redeliveries:
        print("\nRedelivery check")
        for rd in batch.redeliveries:
            c = rd["counts"]
            print(f"  {rd['old_file']} -> {rd['new_file']}: {rd['verdict']} "
                  f"({c['Fixed']} fixed, {c['Still present']} still present, {c['New issue']} new)")
    if any(r["producer"] != "Unassigned" for r in batch.scorecard):
        print("\nProducer scorecard")
        for r in batch.scorecard:
            print(f"  {r['producer']:<14} {r['files']:>3} files  first-time pass {r['first_time_pass_rate']:.0%}  "
                  f"{r['reject']} reject  | {r['note']}")

    paths = write_reports(batch, spec, args.out, args.project)
    print(f"\nOverall: {'PASS' if batch.passed else 'FAIL'}")
    for kind, p in paths.items():
        print(f"{kind:>8}: {p}")
    return 0 if batch.passed else 1
