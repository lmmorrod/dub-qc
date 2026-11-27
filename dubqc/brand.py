"""Dub QC brand: colours, font and wordmark, shared by the HTML report and the Streamlit app."""

NAME = "Dub QC"
TAGLINE = "Delivery QC for dubbed dialogue"

SLATE = "#16202a"        # header
SLATE_2 = "#243241"
BODY = "#f7f6f2"         # off-white page
INK = "#18212b"
MUTED = "#5d6975"
LINE = "#e5e2da"
ACCENT = "#0f9488"       # teal
ACCENT_SOFT = "#e0f2ef"

FONT_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" '
             'rel="stylesheet">')
FONT_STACK = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif'


def logo_svg(size: int = 30) -> str:
    """A teal tile with a waveform and a tick: audio in, checked."""
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 32 32" aria-hidden="true">'
            f'<rect width="32" height="32" rx="8" fill="{ACCENT}"/>'
            '<g stroke="#fff" stroke-width="2.4" stroke-linecap="round">'
            '<line x1="7" y1="13" x2="7" y2="19"/><line x1="11.5" y1="9" x2="11.5" y2="23"/>'
            '<line x1="16" y1="12" x2="16" y2="20"/></g>'
            '<path d="M19.5 16.5l3 3 5-6.5" fill="none" stroke="#fff" stroke-width="2.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>')


def wordmark_html(size: int = 30) -> str:
    return (f'<span style="display:inline-flex;align-items:center;gap:10px">{logo_svg(size)}'
            f'<span style="font-weight:700;font-size:{int(size * 0.8)}px;letter-spacing:-0.02em;color:#fff">'
            f'Dub <span style="color:#5eead4">QC</span></span></span>')
