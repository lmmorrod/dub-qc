"""The data that every check produces."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CRITICAL = "Critical"
WARNING = "Warning"
INFO = "Info"
SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1, INFO: 2}


@dataclass
class Issue:
    check: str              # broad area, e.g. "Loudness", "Pip"
    code: str               # specific problem, e.g. "PIP OFFSET"
    severity: str           # Critical / Warning / Info
    message: str            # one-line description
    file: str = ""
    seconds: float | None = None   # position in the file
    timecode: str = ""             # session timecode (HH:MM:SS:FF)
    expected: str = ""
    found: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FileResult:
    file: str
    path: str
    metrics: dict = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    load_report: str = ""
    rating: str = ""
    waveform: list[float] = field(default_factory=list)   # peak per bin, 0..1
    duration_s: float = 0.0
    producer: str = ""
    reel_timecodes: dict = field(default_factory=dict)    # the reel's fps/session_start/pip/ffoa used
    superseded: bool = False                               # a later version of this deliverable arrived
    stage: str = ""                                        # RAW / PMX / PMR / FSS
    stem: str = ""                                         # DX / MX / FX / ME / VOX
    version: str = ""                                      # delivery version code used, e.g. R128
    checks_run: list[str] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)        # editor notes that apply, with status

    @property
    def passed(self) -> bool:
        return not any(i.severity == CRITICAL for i in self.issues)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passed"] = self.passed
        d.pop("waveform")
        return d
