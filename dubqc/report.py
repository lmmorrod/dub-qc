"""Write the QC report as HTML, JSON and a marker list."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path

from . import brand
from .batch import BatchResult, analyse
from .models import CRITICAL, INFO, WARNING, FileResult
from .naming import reel_label
from .spec import checklist_for, entry_name

SEVERITIES = [CRITICAL, WARNING, INFO]


def _as_batch(results, spec) -> BatchResult:
    """Accept a BatchResult, or a plain list of FileResults (single-file use)."""
    # Checked by shape rather than isinstance, so a result kept across a code reload still works.
    return results if hasattr(results, "current_files") else analyse(list(results), spec)


def overall_pass(results) -> bool:
    if hasattr(results, "current_files"):
        return results.passed
    return all(r.passed for r in results)


def to_json(results, spec: dict, project: str) -> dict:
    batch = _as_batch(results, spec)
    return {
        "project": project,
        "spec": spec.get("name"),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "overall": "PASS" if batch.passed else "FAIL",
        **batch.to_dict(),
    }


def write_reports(results, spec: dict, out_dir: str | Path = "reports",
                  project: str = "Dub QC") -> dict[str, Path]:
    batch = _as_batch(results, spec)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = {
        "html": out_dir / f"{stamp}_report.html",
        "json": out_dir / f"{stamp}_report.json",
        "markers": out_dir / f"{stamp}_markers.txt",
    }
    paths["html"].write_text(to_html(batch, spec, project), encoding="utf-8")
    paths["json"].write_text(json.dumps(to_json(batch, spec, project), indent=2, default=str), encoding="utf-8")
    write_markers(batch.files, paths["markers"])
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
            for n in r.notes:
                w.writerow([n["timecode"], f"NOTE {n['type']}", f"{n['note']} ({n['status']})", r.file, "Note"])


# ---------------------------------------------------------------- HTML

CSS = f"""
:root{{--slate:{brand.SLATE};--slate-2:{brand.SLATE_2};--bg:{brand.BODY};--card:#fff;--ink:{brand.INK};
--muted:{brand.MUTED};--line:{brand.LINE};--accent:{brand.ACCENT};--accent-soft:{brand.ACCENT_SOFT};--wave:#a3adb8;
--crit:#c2362b;--crit-bg:#fbe9e7;--warn:#a05d00;--warn-bg:#fdf1dc;--info:#255f99;--info-bg:#e7f0fa;
--pass:#1f7a4d;--pass-bg:#e3f3ea;--none:#8a949e;--none-bg:#eeece6}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 {brand.FONT_STACK};-webkit-font-smoothing:antialiased}}
header.brand{{background:var(--slate);color:#fff;border-bottom:3px solid var(--accent)}}
header.brand .inner{{max-width:1200px;margin:0 auto;padding:22px 16px 20px;display:flex;justify-content:space-between;
gap:20px;align-items:center;flex-wrap:wrap}}
.tagline{{color:#9fb0c0;font-size:13px;margin-top:4px}}
.runinfo{{text-align:right;color:#c9d4de;font-size:13px}}
.runinfo b{{color:#fff;font-weight:600}}
.verdict{{display:inline-block;font-weight:700;font-size:15px;padding:6px 16px;border-radius:6px;letter-spacing:.06em;margin-top:6px}}
.verdict.PASS{{background:#1f7a4d;color:#fff}}.verdict.FAIL{{background:#c2362b;color:#fff}}
nav.sections{{background:var(--slate-2)}}
nav.sections .inner{{max-width:1200px;margin:0 auto;padding:8px 16px;display:flex;gap:18px;flex-wrap:wrap}}
nav.sections a{{color:#c9d4de;text-decoration:none;font-size:13px;font-weight:500}}
nav.sections a:hover{{color:#5eead4}}
.wrap{{max-width:1200px;margin:0 auto;padding:8px 16px 60px}}
h2{{font-size:18px;margin:34px 0 4px;letter-spacing:-.01em}}
h2+.sub{{color:var(--muted);margin:0 0 12px;font-size:13px}}
h3{{font-size:15px;margin:0 0 10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:12px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}
.stat{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.stat .label{{color:var(--muted);font-size:12px;font-weight:500}}
.stat b{{display:block;font-size:24px;letter-spacing:-.02em}}
.stat.accent{{border-top:3px solid var(--accent)}}
ul.summary{{margin:0;padding-left:0;list-style:none}}
ul.summary li{{padding:7px 0;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:baseline}}
ul.summary li:last-child{{border-bottom:none}}
.pill{{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}}
.Critical,.Reject,.Missing,.FAIL,.New{{background:var(--crit-bg);color:var(--crit)}}
.Warning,.Acceptable,.Duplicate,.Still{{background:var(--warn-bg);color:var(--warn)}}
.Info{{background:var(--info-bg);color:var(--info)}}
.Good,.PASS,.Fixed,.Delivered,.All,.Both{{background:var(--pass-bg);color:var(--pass)}}
.Passes{{background:var(--accent-soft);color:var(--accent)}}
.Superseded{{background:var(--none-bg);color:var(--none)}}
.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}}
table.sortable th{{cursor:pointer;user-select:none;white-space:nowrap}}
table.sortable th::after{{content:" ↕";color:#c3c9cf}}
table.sortable th[data-dir=asc]::after{{content:" ↑";color:var(--accent)}}
table.sortable th[data-dir=desc]::after{{content:" ↓";color:var(--accent)}}
td.tc,td.num{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;white-space:nowrap}}
.fname{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;overflow-wrap:anywhere}}
td.fname{{white-space:nowrap}}
table.files{{min-width:900px}} table.issues{{min-width:860px}} table.issues td:nth-child(5){{width:38%}}
table.scorecard{{min-width:980px}} table.scorecard td:last-child{{min-width:260px}}
table.scorecard td:first-child{{white-space:nowrap}}
tr.group td{{background:var(--bg);padding-top:10px}}
tr.superseded td{{color:var(--muted)}}
.matrix td,.matrix th{{text-align:center}} .matrix th:first-child,.matrix td:first-child{{text-align:left}}
.cell{{display:inline-block;min-width:88px;padding:5px 8px;border-radius:6px;font-size:12px;font-weight:600}}
.cell small{{display:block;font-weight:500;opacity:.8}}
.terr{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}}
.terr .card{{margin:0}}
.fix,.muted{{color:var(--muted);font-size:12px}}
ul.check{{margin:0;padding-left:18px}} ul.check li{{margin:3px 0}}
.wave{{width:100%;height:80px;display:block;margin-top:8px}}
details.load{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:10px 16px}}
details.load summary{{cursor:pointer;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.rd-head{{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:8px}}
footer{{color:var(--muted);font-size:12px;margin-top:30px}}
"""

SORT_JS = """
document.querySelectorAll('table.sortable').forEach(t=>{const ths=t.tHead.rows[0].cells;
[...ths].forEach((th,i)=>th.addEventListener('click',()=>{const b=t.tBodies[0],rows=[...b.rows],
asc=th.dataset.dir!=='asc';[...ths].forEach(h=>h.dataset.dir='');th.dataset.dir=asc?'asc':'desc';
const v=r=>r.cells[i].dataset.sort??r.cells[i].innerText.trim();
rows.sort((a,c)=>{const x=v(a),y=v(c),nx=parseFloat(x),ny=parseFloat(y);
const d=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);return asc?d:-d});rows.forEach(r=>b.appendChild(r))}))});
"""


def _pill(text: str, cls: str | None = None) -> str:
    return f'<span class="pill {escape((cls or text).split()[0])}">{escape(text)}</span>'


def _waveform_svg(r: FileResult, spec: dict) -> str:
    if not r.waveform or not r.duration_s:
        return ""
    from .timecode import tc_to_file_seconds
    w, h = 1000, 80
    mid = h / 2
    n = len(r.waveform)
    top = " ".join(f"{i / (n - 1) * w:.1f},{mid - v * (mid - 4):.1f}" for i, v in enumerate(r.waveform))
    bottom = " ".join(f"{i / (n - 1) * w:.1f},{mid + v * (mid - 4):.1f}" for i, v in reversed(list(enumerate(r.waveform))))
    parts = [f'<svg class="wave" viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img" '
             f'aria-label="Waveform of {escape(r.file)} with issue markers">',
             f'<polygon points="{top} {bottom}" fill="var(--wave)"/>']
    reel = r.reel_timecodes or spec["reel"]
    for label, key in (("PIP", "pip"), ("FFOA", "ffoa")):
        x = tc_to_file_seconds(reel[key], reel["fps"], reel["session_start"]) / r.duration_s * w
        if 0 <= x <= w:
            parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{h}" stroke="var(--accent)" '
                         f'stroke-dasharray="3 3" vector-effect="non-scaling-stroke"><title>{label} {reel[key]}</title></line>')
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


def _header(batch: BatchResult, spec: dict, project: str) -> str:
    verdict = "PASS" if batch.passed else "FAIL"
    now = datetime.now().strftime("%d %b %Y, %H:%M")
    links = [("summary", "Summary"), ("checklist", "What to listen for")]
    if batch.manifest:
        links.append(("manifest", "Delivery manifest"))
    if batch.redeliveries:
        links.append(("redelivery", "Redelivery check"))
    if any(r["producer"] != "Unassigned" for r in batch.scorecard):
        links.append(("scorecard", "Producer scorecard"))
    if any(r.notes for r in batch.files):
        links.append(("notes", "Editor notes"))
    links += [("files", "Files"), ("issues", "Issues"), ("load", "Load reports")]
    nav = "".join(f'<a href="#{a}">{t}</a>' for a, t in links)
    return (f"<header class='brand'><div class='inner'><div>{brand.wordmark_html(30)}"
            f"<div class='tagline'>{brand.TAGLINE}</div></div>"
            f"<div class='runinfo'><b>{escape(project)}</b> · {escape(str(spec.get('name')))}<br>"
            f"{now} · {len(batch.files)} file(s)<br><span class='verdict {verdict}'>{verdict}</span></div>"
            f"</div></header><nav class='sections'><div class='inner'>{nav}</div></nav>")


def _summary(batch: BatchResult) -> str:
    current = batch.current_files
    issues = [i for r in current for i in r.issues]
    by_sev = Counter(i.severity for i in issues)
    passing = sum(r.passed for r in current)
    h = ["<h2 id='summary'>Summary</h2><p class='sub'>Counts cover the latest version of each file; "
         "earlier versions replaced in this batch are shown as superseded.</p><div class='grid'>"]
    if batch.manifest:
        m = batch.manifest
        h.append(f"<div class='stat accent'><span class='label'>Deliverables in</span>"
                 f"<b>{m['delivered']}/{m['expected']}</b></div>")
    h.append(f"<div class='stat accent'><span class='label'>Files passing QC</span><b>{passing}/{len(current)}</b></div>")
    for sev in SEVERITIES:
        h.append(f"<div class='stat'>{_pill(sev)}<b>{by_sev.get(sev, 0)}</b></div>")
    h.append("</div>")
    if batch.manifest:
        h.append("<div class='card'><h3>Delivery status by territory</h3><ul class='summary'>")
        for t in batch.manifest["territories"]:
            ok = t["delivered"] == t["expected"] and not t["duplicates"] and not t["unexpected"]
            h.append(f"<li>{_pill('Complete', 'Good') if ok else _pill('Attention', 'Warning')}"
                     f"<span><b>{escape(t['summary'])}</b> <span class='muted'>{escape(t['name'])}</span></span></li>")
        if batch.manifest["unexpected_other"]:
            n = len(batch.manifest["unexpected_other"])
            h.append(f"<li>{_pill('Attention', 'Warning')}<span><b>{n} file(s) not on this delivery</b> "
                     "<span class='muted'>unknown territory or unreadable name</span></span></li>")
        h.append("</ul></div>")
    return "".join(h)


def _manifest(batch: BatchResult, spec: dict) -> str:
    m = batch.manifest
    if not m:
        return ""
    by_file = {r.file: r for r in batch.files}
    stems = [str(s) for s in spec["manifest"]["stems"]]
    h = ["<h2 id='manifest'>Delivery manifest</h2><p class='sub'>Expected deliverables from the spec "
         "against what arrived. Colour shows the latest version's QC result.</p><div class='terr'>"]
    for t in m["territories"]:
        h.append(f"<div class='card'><h3>{escape(t['territory'])} <span class='muted'>{escape(t['name'])} · "
                 f"{t['delivered']}/{t['expected']} delivered</span></h3>"
                 "<table class='matrix'><tr><th>Reel</th>" + "".join(f"<th>{escape(s)}</th>" for s in stems) + "</tr>")
        rows = list(dict.fromkeys((s["reel"], s.get("version", "")) for s in t["slots"]))
        for reel, version in rows:
            label = reel_label(reel) + (f" <span class='muted'>{escape(version)}</span>" if version else "")
            h.append(f"<tr><td><b>{label}</b></td>")
            for slot in (s for s in t["slots"] if s["reel"] == reel and s.get("version", "") == version):
                h.append(f"<td>{_slot_cell(slot, by_file)}</td>")
            h.append("</tr>")
        h.append("</table>")
        notes = []
        for d in t["duplicates"]:
            notes.append(f"<li><b>{escape(d['slot'])} duplicate:</b> " + ", ".join(
                f"<span class='fname'>{escape(f)}</span>" for f in d["files"]) +
                ". Confirm which one is final.</li>")
        for u in t["unexpected"]:
            notes.append(f"<li><b>Unexpected:</b> <span class='fname'>{escape(u['file'])}</span> "
                         f"<span class='muted'>({escape(u['reason'])})</span></li>")
        if notes:
            h.append("<ul class='muted' style='margin:10px 0 0;padding-left:18px'>" + "".join(notes) + "</ul>")
        h.append("</div>")
    h.append("</div>")
    if m["unexpected_other"]:
        h.append("<div class='card'><h3>Not on this delivery</h3><table><tr><th>File</th><th>Group</th><th>Why</th></tr>")
        for u in m["unexpected_other"]:
            h.append(f"<tr><td class='fname'>{escape(u['file'])}</td><td>{escape(u['territory'])}</td>"
                     f"<td>{escape(u['reason'])}</td></tr>")
        h.append("</table></div>")
    return "".join(h)


def _slot_cell(slot: dict, by_file: dict) -> str:
    if slot["status"] == "Missing":
        return "<span class='cell Missing'>Missing</span>"
    if slot["status"] == "Duplicate":
        return f"<span class='cell Duplicate'>Duplicate<small>{len(slot['files'])} files</small></span>"
    r = by_file.get(slot["latest"])
    version = slot["latest"].rsplit("_", 1)[-1].removesuffix(".wav")
    rating = r.rating if r else "Delivered"
    label = {"Acceptable with notes": "Notes"}.get(rating, rating)
    older = len(slot["files"]) - 1
    extra = f" · {older} earlier" if older else ""
    return (f"<span class='cell {escape(rating.split()[0])}' title='{escape(slot['latest'])}'>{escape(label)}"
            f"<small>{escape(version)}{extra}</small></span>")


def _redeliveries(batch: BatchResult) -> str:
    if not batch.redeliveries:
        return ""
    h = ["<h2 id='redelivery'>Redelivery check</h2><p class='sub'>Each new version re-checked and compared "
         "with the one before it: what got fixed, what's still there, and anything new.</p>"]
    for rd in batch.redeliveries:
        c = rd["counts"]
        h.append(f"<div class='card'><div class='rd-head'><div><span class='fname'>{escape(rd['old_file'])}</span> "
                 f"→ <span class='fname'>{escape(rd['new_file'])}</span></div><div>"
                 f"{_pill(rd['verdict'], 'Reject' if rd['verdict'] == 'Still failing' else None)} "
                 f"<span class='muted'>{c['Fixed']} fixed · {c['Still present']} still present · "
                 f"{c['New issue']} new</span></div></div>")
        if rd["rows"]:
            h.append("<div class='scroll'><table><tr><th>Status</th><th>Issue</th><th>Severity</th>"
                     "<th>Old TC</th><th>New TC</th><th>Old → new</th></tr>")
            for row in rd["rows"]:
                change = " → ".join(x for x in (row["old_found"], row["new_found"]) if x) or "–"
                h.append(f"<tr><td>{_pill(row['status'])}</td><td>{escape(row['code'])}</td>"
                         f"<td>{_pill(row['severity'])}</td><td class='tc'>{escape(row['old_timecode'] or '–')}</td>"
                         f"<td class='tc'>{escape(row['new_timecode'] or '–')}</td><td>{escape(change)}</td></tr>")
            h.append("</table></div>")
        h.append("</div>")
    return "".join(h)


def _scorecard(batch: BatchResult) -> str:
    rows = batch.scorecard
    if not rows or all(r["producer"] == "Unassigned" for r in rows):
        return ""
    h = ["<h2 id='scorecard'>Producer scorecard</h2><p class='sub'>Click a column to sort. First-time pass = "
         "the first version of each deliverable passed QC. Sync offset is the average pip error in frames.</p>"
         "<div class='card scroll'><table class='scorecard sortable'><thead><tr><th>Producer</th><th>Files</th>"
         "<th>First-time pass</th><th>Good</th><th>Notes</th><th>Reject</th><th>Top issues</th>"
         "<th>Avg sync offset</th><th>Summary</th></tr></thead><tbody>"]
    for r in rows:
        rate = r["first_time_pass_rate"]
        offset = r["avg_sync_offset_frames"]
        h.append(f"<tr><td><b>{escape(r['producer'])}</b></td><td class='num'>{r['files']}</td>"
                 f"<td class='num' data-sort='{rate}'>{rate:.0%}</td>"
                 f"<td class='num'>{r['good']}</td><td class='num'>{r['acceptable']}</td>"
                 f"<td class='num'>{r['reject']}</td>"
                 f"<td>{escape(', '.join(r['top_issues']) or '–')}</td>"
                 f"<td class='num' data-sort='{offset if offset is not None else -1}'>"
                 f"{'–' if offset is None else f'{offset:.1f} fr'}</td>"
                 f"<td>{escape(r['note'])}</td></tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def _files(batch: BatchResult, spec: dict) -> str:
    show_producer = any(r.producer for r in batch.files)
    h = ["<h2 id='files'>Files</h2><div class='card scroll'><table class='files sortable'><thead><tr><th>File</th>"
         + ("<th>Producer</th>" if show_producer else "")
         + "<th>Result</th><th>Stage</th><th>Format</th><th>Loudness</th><th>True peak</th><th>Clips</th><th>Head pip</th>"
           "</tr></thead><tbody>"]
    for r in batch.files:
        m = r.metrics
        fmt = (f"{m['sample_rate'] / 1000:g}k / {m['bit_depth']}-bit / {m['channels']}ch"
               if "sample_rate" in m else "–")
        pip = m.get("head_pip") or "missing"
        if m.get("head_pip_offset_frames") is not None:
            pip += f" ({int(round(m['head_pip_offset_frames'])):+d} fr)"
        result = _pill("Superseded") if r.superseded else (_pill("PASS", "Good") if r.passed else _pill("FAIL", "Reject"))
        h.append(f"<tr class='{'superseded' if r.superseded else ''}'><td class='fname'>{escape(r.file)}</td>"
                 + (f"<td>{escape(r.producer or '–')}</td>" if show_producer else "")
                 + f"<td>{result}</td><td>{escape(' · '.join(x for x in (r.stage, r.stem, r.version) if x) or '–')}</td>"
                   f"<td class='num'>{fmt}</td>"
                   f"<td class='num'>{m.get('integrated_lufs', '–')} LUFS</td>"
                   f"<td class='num'>{m.get('true_peak_dbtp', '–')} dBTP</td>"
                   f"<td class='num'>{m.get('clip_events', '–')}</td>"
                   f"<td class='num'>{escape(pip)}</td></tr>")
    h.append("</tbody></table></div>")
    return "".join(h)


def _issues(batch: BatchResult) -> str:
    files = [r for r in batch.files if r.issues]
    h = ["<h2 id='issues'>Issues</h2>"]
    if not files:
        return h[0] + "<div class='card'>No issues found.</div>"
    h.append("<div class='card scroll'><table class='issues'><tr><th>#</th><th>Timecode</th><th>Check</th>"
             "<th>Severity</th><th>Problem / fix</th><th>Expected</th><th>Found</th></tr>")
    n = 0
    for r in files:
        note = " <span class='muted'>(superseded by a later version)</span>" if r.superseded else ""
        h.append(f"<tr class='group'><td colspan='7'><span class='fname'>{escape(r.file)}</span>{note}</td></tr>")
        for i in r.issues:
            n += 1
            h.append(f"<tr><td class='num'>{n}</td><td class='tc'>{escape(i.timecode or '–')}</td>"
                     f"<td>{escape(i.code)}</td><td>{_pill(i.severity)}</td>"
                     f"<td>{escape(i.message)}<div class='fix'>Fix: {escape(i.fix)}</div></td>"
                     f"<td>{escape(i.expected)}</td><td>{escape(i.found)}</td></tr>")
    h.append("</table></div>")
    return "".join(h)


def _load_reports(batch: BatchResult, spec: dict) -> str:
    h = ["<h2 id='load'>Load reports</h2><p class='sub'>One paragraph per file to send back to the territory. "
         "Waveform: dashed lines are the pip and FFOA from the spec; solid lines are issues "
         "(red critical, amber warning).</p>"]
    many = len(batch.files) > 4
    for r in batch.files:
        is_open = "" if many and (r.passed or r.superseded) else " open"
        h.append(f"<details class='load'{is_open}><summary><span class='fname'>{escape(r.file)}</span> "
                 f"{_pill(r.rating, r.rating)}{' ' + _pill('Superseded') if r.superseded else ''}</summary>"
                 f"<p>{escape(r.load_report)}</p>{_waveform_svg(r, spec)}</details>")
    return "".join(h)


CHECK_NAMES = {"naming": "file naming", "format": "format", "loudness": "loudness", "true_peak": "true peak",
               "clipping": "clipping", "pip": "sync pip", "noise": "noise floor", "voice_in_me": "voice in M&E"}


def _checklist(batch: BatchResult, spec: dict) -> str:
    """What the person doing this QC pass should listen for, per stage and stem in the batch,
    and which technical checks Dub QC has already done for them."""
    groups: dict[tuple, list[FileResult]] = {}
    for r in batch.current_files:
        groups.setdefault((r.stage, r.stem), []).append(r)
    order = {"RAW": 0, "PMX": 1, "PMR": 2, "FSS": 3, "": 9}
    cards = []
    for (stage, stem), files in sorted(groups.items(), key=lambda kv: (order.get(kv[0][0], 5), kv[0][1])):
        items = checklist_for(spec, stage or None, stem or None)
        if not items:
            continue
        title = " · ".join(x for x in (entry_name(spec, "stages", stage) if stage else "",
                                       entry_name(spec, "stems", stem) if stem else "") if x)
        done = ", ".join(CHECK_NAMES[c] for c in files[0].checks_run)
        cards.append(f"<div class='card'><h3>{escape(title.capitalize())} <span class='muted'>{len(files)} file(s)"
                     f"</span></h3><ul class='check'>" + "".join(f"<li>{escape(i)}</li>" for i in items) +
                     f"</ul><p class='muted' style='margin:8px 0 0'>Already checked automatically: {escape(done)}.</p></div>")
    if not cards:
        return ""
    return ("<h2 id='checklist'>What to listen for</h2><p class='sub'>The listening checks for this pass, "
            "by stage and stem. The technical checks are done; these need ears.</p><div class='terr'>"
            + "".join(cards) + "</div>")


def _notes(batch: BatchResult) -> str:
    """Editor notes and whether the noted content is still there in each file."""
    rows: dict[tuple, list] = {}
    for r in batch.current_files:
        for n in r.notes:
            key = (n["reel"], n["timecode"], n["type"], n["note"], n["stem"])
            rows.setdefault(key, []).append((r, n))
    if not rows:
        return ""
    h = ["<h2 id='notes'>Editor notes</h2><p class='sub'>Timecoded notes carried from earlier passes. "
         "Each one is checked in every file it applies to: is the noted content still there?</p>"
         "<div class='card scroll'><table><tr><th>Reel</th><th>Timecode</th><th>Type</th><th>Note</th>"
         "<th>Status by file</th></tr>"]
    for (reel, tc, kind, note, stem), hits in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        cells = " ".join(
            f"{_pill(n['status'], 'Good' if n['status'] == 'Present' else 'Reject' if n['status'] == 'Silent' else 'Info')}"
            f"<span class='muted' style='margin:0 10px 0 4px'>{escape(r.file.split('_')[1] if '_' in r.file else r.file)}</span>"
            for r, n in hits)
        h.append(f"<tr><td>{escape(reel_label(reel))} {escape(stem)}</td><td class='tc'>{escape(tc)}</td>"
                 f"<td>{escape(kind)}</td><td>{escape(note)}</td><td>{cells}</td></tr>")
    h.append("</table></div>")
    return "".join(h)


def to_html(results, spec: dict, project: str = "Dub QC") -> str:
    batch = _as_batch(results, spec)
    body = [_header(batch, spec, project), "<div class='wrap'>", _summary(batch), _checklist(batch, spec),
            _manifest(batch, spec), _redeliveries(batch), _notes(batch), _scorecard(batch),
            _files(batch, spec), _issues(batch),
            _load_reports(batch, spec),
            f"<footer>{brand.NAME} · {brand.TAGLINE}. Timecodes are session timecode at "
            f"{spec['reel']['fps']} fps from each reel's session start.</footer></div>"]
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Dub QC Report</title>{brand.FONT_LINK}<style>{CSS}</style></head><body>"
            + "".join(body) + f"<script>{SORT_JS}</script></body></html>")
