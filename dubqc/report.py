"""Write the QC report as HTML, JSON and a marker list."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from .models import CRITICAL, INFO, WARNING, FileResult

SEVERITIES = [CRITICAL, WARNING, INFO]


def overall_pass(results: list[FileResult]) -> bool:
    return all(r.passed for r in results)


def to_json(results: list[FileResult], spec: dict, project: str) -> dict:
    return {
        "project": project,
        "spec": spec.get("name"),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "overall": "PASS" if overall_pass(results) else "FAIL",
        "files": [r.to_dict() for r in results],
    }


def write_reports(results: list[FileResult], spec: dict, out_dir: str | Path = "reports",
                  project: str = "Dub QC") -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = {
        "html": out_dir / f"{stamp}_report.html",
        "json": out_dir / f"{stamp}_report.json",
        "markers": out_dir / f"{stamp}_markers.txt",
    }
    paths["html"].write_text(to_html(results, spec, project), encoding="utf-8")
    paths["json"].write_text(json.dumps(to_json(results, spec, project), indent=2, default=str), encoding="utf-8")
    write_markers(results, paths["markers"])
    return paths


def write_markers(results: list[FileResult], path: Path) -> None:
    """Tab-separated marker list (timecode, name, comment) for dropping QC notes into a session."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["TIMECODE", "NAME", "COMMENT", "FILE", "SEVERITY"])
        for r in results:
            for i in r.issues:
                if i.timecode:
                    w.writerow([i.timecode, f"QC {i.code}", i.message, r.file, i.severity])


# ---------------------------------------------------------------- HTML

CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e1dc;--wave:#9aa3ad;
--crit:#c62828;--crit-bg:#fdecea;--warn:#b26a00;--warn-bg:#fff4e0;--info:#1f5f9e;--info-bg:#e8f1fb;
--pass:#2e7d32;--pass-bg:#e8f5e9;--accent:#3b3b98}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e22;--ink:#ececf0;--muted:#a0a0a8;--line:#33333a;
--wave:#5d6670;--crit:#ff6b6b;--crit-bg:#3a1c1c;--warn:#ffb74d;--warn-bg:#3a2c14;--info:#7ab8ff;--info-bg:#16283d;
--pass:#7bd88f;--pass-bg:#173020;--accent:#a5a5ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.meta{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:12px 0}
.head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;flex-wrap:wrap}
.verdict{font-weight:700;font-size:20px;padding:10px 22px;border-radius:8px;letter-spacing:.04em}
.PASS{background:var(--pass-bg);color:var(--pass)}.FAIL{background:var(--crit-bg);color:var(--crit)}
.pill{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}
.Critical{background:var(--crit-bg);color:var(--crit)}.Warning{background:var(--warn-bg);color:var(--warn)}
.Info{background:var(--info-bg);color:var(--info)}
.Good{background:var(--pass-bg);color:var(--pass)}.Reject{background:var(--crit-bg);color:var(--crit)}
.Acceptable{background:var(--warn-bg);color:var(--warn)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.tc,td.num{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}
.counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.count{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.count b{display:block;font-size:24px}
.fname{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;overflow-wrap:anywhere}
td.fname{white-space:nowrap}
table.files{min-width:820px}
.wave{width:100%;height:90px;display:block;margin-top:8px}
.legend{font-size:12px;color:var(--muted)}
.fix{color:var(--muted);font-size:12px}
table.issues{min-width:860px}
table.issues td:nth-child(5){width:38%}
tr.group td{background:var(--bg);padding-top:10px}
"""


def _pill(text: str, cls: str | None = None) -> str:
    return f'<span class="pill {escape(cls or text)}">{escape(text)}</span>'


def _waveform_svg(r: FileResult, spec: dict) -> str:
    if not r.waveform or not r.duration_s:
        return ""
    from .timecode import tc_to_file_seconds
    w, h = 1000, 90
    mid = h / 2
    n = len(r.waveform)
    top = " ".join(f"{i / (n - 1) * w:.1f},{mid - v * (mid - 4):.1f}" for i, v in enumerate(r.waveform))
    bottom = " ".join(f"{i / (n - 1) * w:.1f},{mid + v * (mid - 4):.1f}" for i, v in reversed(list(enumerate(r.waveform))))
    parts = [f'<svg class="wave" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
             f'aria-label="Waveform of {escape(r.file)} with issue markers">',
             f'<polygon points="{top} {bottom}" fill="var(--wave)"/>']
    reel = spec["reel"]
    for label, tc in (("PIP", reel["pip"]), ("FFOA", reel["ffoa"])):
        x = tc_to_file_seconds(tc, reel["fps"], reel["session_start"]) / r.duration_s * w
        if 0 <= x <= w:
            parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h}" stroke="var(--accent)" '
                         f'stroke-dasharray="3 3" vector-effect="non-scaling-stroke"><title>{label} {tc}</title></line>')
    colour = {CRITICAL: "var(--crit)", WARNING: "var(--warn)", INFO: "var(--info)"}
    for i in r.issues:
        if i.seconds is None:
            continue
        x = i.seconds / r.duration_s * w
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h}" stroke="{colour[i.severity]}" '
                     f'stroke-width="2" vector-effect="non-scaling-stroke"><title>{escape(i.timecode)} '
                     f'{escape(i.code)}</title></line>')
    parts.append("</svg>")
    return "".join(parts)


def to_html(results: list[FileResult], spec: dict, project: str = "Dub QC") -> str:
    verdict = "PASS" if overall_pass(results) else "FAIL"
    issues = [i for r in results for i in r.issues]
    by_sev = Counter(i.severity for i in issues)
    by_check = Counter((i.check, i.severity) for i in issues)
    checks = sorted({i.check for i in issues})
    now = datetime.now().strftime("%d %b %Y, %H:%M")

    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>QC Report – {escape(project)}</title><style>{CSS}</style></head><body><div class='wrap'>"]

    # header
    h.append("<div class='card head'><div>"
             f"<h1>{escape(project)}: Delivery QC</h1>"
             f"<div class='meta'>Spec: <b>{escape(str(spec.get('name')))}</b> · {now} · "
             f"{len(results)} file(s) checked</div></div>"
             f"<div class='verdict {verdict}'>{verdict}</div></div>")

    # summary counts
    h.append("<h2>Summary</h2><div class='counts'>")
    for sev in SEVERITIES:
        h.append(f"<div class='count'>{_pill(sev)}<b>{by_sev.get(sev, 0)}</b></div>")
    h.append("</div>")
    if checks:
        h.append("<div class='card scroll'><table><tr><th>Check</th>"
                 + "".join(f"<th>{s}</th>" for s in SEVERITIES) + "</tr>")
        for c in checks:
            h.append(f"<tr><td>{escape(c)}</td>" + "".join(
                f"<td class='num'>{by_check.get((c, s), 0) or '–'}</td>" for s in SEVERITIES) + "</tr>")
        h.append("</table></div>")

    # files
    h.append("<h2>Files</h2><div class='card scroll'><table class='files'><tr><th>File</th><th>Result</th><th>Format</th>"
             "<th>Loudness</th><th>True peak</th><th>Clips</th><th>Head pip</th></tr>")
    for r in results:
        m = r.metrics
        fmt = (f"{m['sample_rate'] / 1000:g}k / {m['bit_depth']}-bit / {m['channels']}ch"
               if "sample_rate" in m else "–")
        pip = m.get("head_pip") or "missing"
        if m.get("head_pip_offset_frames") is not None:
            pip += f" ({int(round(m['head_pip_offset_frames'])):+d} fr)"
        h.append(f"<tr><td class='fname'>{escape(r.file)}</td>"
                 f"<td>{_pill('PASS', 'Good') if r.passed else _pill('FAIL', 'Reject')}</td>"
                 f"<td class='num'>{fmt}</td>"
                 f"<td class='num'>{m.get('integrated_lufs', '–')} LUFS</td>"
                 f"<td class='num'>{m.get('true_peak_dbtp', '–')} dBTP</td>"
                 f"<td class='num'>{m.get('clip_events', '–')}</td>"
                 f"<td class='num'>{escape(pip)}</td></tr>")
    h.append("</table></div>")

    # issues
    h.append("<h2>Issues</h2>")
    if not issues:
        h.append("<div class='card'>No issues found.</div>")
    else:
        h.append("<div class='card scroll'><table class='issues'><tr><th>#</th><th>Timecode</th><th>Check</th>"
                 "<th>Severity</th><th>Problem / fix</th><th>Expected</th><th>Found</th></tr>")
        n = 0
        for r in results:
            if not r.issues:
                continue
            h.append(f"<tr class='group'><td colspan='7' class='fname'>{escape(r.file)}</td></tr>")
            for i in r.issues:
                n += 1
                h.append(f"<tr><td class='num'>{n}</td><td class='tc'>{escape(i.timecode or '–')}</td>"
                         f"<td>{escape(i.code)}</td><td>{_pill(i.severity)}</td>"
                         f"<td>{escape(i.message)}<div class='fix'>Fix: {escape(i.fix)}</div></td>"
                         f"<td>{escape(i.expected)}</td><td>{escape(i.found)}</td></tr>")
        h.append("</table></div>")

    # load reports + waveforms
    h.append("<h2>Load reports</h2>")
    for r in results:
        rating_cls = r.rating.split()[0] if r.rating else "Info"
        h.append(f"<div class='card'><div class='fname'>{escape(r.file)} {_pill(r.rating, rating_cls)}</div>"
                 f"<p>{escape(r.load_report)}</p>{_waveform_svg(r, spec)}"
                 "<div class='legend'>Dashed: pip and FFOA positions from the spec · "
                 "Solid: issues (red critical, amber warning)</div></div>")

    h.append("<p class='meta'>Generated by dubqc. Timecodes are session timecode at "
             f"{spec['reel']['fps']} fps from {escape(spec['reel']['session_start'])}.</p>")
    h.append("</div></body></html>")
    return "".join(h)
