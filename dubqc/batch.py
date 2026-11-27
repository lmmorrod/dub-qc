"""Check a whole batch of deliveries: every file, plus manifest, scorecard and redelivery checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .delivery import check_file
from .manifest import check_manifest, latest_versions
from .models import FileResult
from .redelivery import find_redeliveries
from .scorecard import build_scorecard


@dataclass
class BatchResult:
    files: list[FileResult]
    manifest: dict | None = None
    scorecard: list[dict] = field(default_factory=list)
    redeliveries: list[dict] = field(default_factory=list)

    @property
    def current_files(self) -> list[FileResult]:
        """Files that haven't been replaced by a later version in this batch."""
        return [f for f in self.files if not f.superseded]

    @property
    def passed(self) -> bool:
        files_ok = all(f.passed for f in self.current_files)
        manifest_ok = self.manifest is None or self.manifest["complete"]
        return files_ok and manifest_ok

    def to_dict(self) -> dict:
        return {"files": [f.to_dict() for f in self.files], "manifest": self.manifest,
                "scorecard": self.scorecard, "redeliveries": self.redeliveries}


def analyse(results: list[FileResult], spec: dict, baseline: list[FileResult] | None = None) -> BatchResult:
    """Run the batch-level checks on files that have already been QC'd."""
    names = [r.file for r in results]
    _, superseded = latest_versions(names)
    for r in results:
        r.superseded = r.file in superseded
    tolerance = spec.get("redelivery", {}).get("match_tolerance_s", 1.0)
    return BatchResult(
        files=results,
        manifest=check_manifest(names, spec),
        scorecard=build_scorecard(results),
        redeliveries=find_redeliveries(results, baseline, tolerance),
    )


def run_batch(paths, spec: dict, display_names=None, producers: dict[str, str] | None = None,
              baseline: list[FileResult] | None = None) -> BatchResult:
    paths = [Path(p) for p in paths]
    display_names = display_names or [p.name for p in paths]
    producers = producers or {}
    results = [check_file(p, spec, n, producers.get(n, "")) for p, n in zip(paths, display_names)]
    return analyse(results, spec, baseline)
