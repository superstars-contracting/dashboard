#!/usr/bin/env python3
"""Render the structured Toolbox Talks data (toolbox_talks_data.TALKS)
to per-language HTML files under toolbox_talks_source/.

Outputs are deterministic given the same input data. Re-run after
editing toolbox_talks_data.py.

The HTML is self-contained — inline CSS, no external assets — so the
headless-Edge PDF render is stable. Targets a SINGLE Letter portrait
page per talk (~350 words of content + 12-row sign-in table).
"""
from pathlib import Path

from toolbox_talks_data import TALKS

OUT_DIR = Path(__file__).resolve().parent / "toolbox_talks_source"

# Per-language UI strings (everything that isn't the talk's own content)
I18N = {
    "en": {
        "topic": "Topic",
        "duration": "min",
        "fields_date": "Date",
        "fields_project": "Project",
        "fields_foreman": "Foreman",
        "ch33": "Ch 33",
        "why_title": "Why It Matters",
        "rules_title": "Key Rules (Ch 33)",
        "do_title": "Do",
        "dont_title": "Do Not",
        "questions_title": "Discussion Questions",
        "signin_title": "Worker Sign-In",
        "signin_print": "Print Name",
        "signin_sig": "Signature",
        "signin_date": "Date",
        "foreman_line": "Foreman signature",
    },
    "es": {
        "topic": "Tema",
        "duration": "min",
        "fields_date": "Fecha",
        "fields_project": "Proyecto",
        "fields_foreman": "Capataz",
        "ch33": "Cap. 33",
        "why_title": "Por qué importa",
        "rules_title": "Reglas clave (Cap. 33)",
        "do_title": "Hacer",
        "dont_title": "No hacer",
        "questions_title": "Preguntas de discusión",
        "signin_title": "Lista de Asistencia",
        "signin_print": "Nombre en letra de molde",
        "signin_sig": "Firma",
        "signin_date": "Fecha",
        "foreman_line": "Firma del capataz",
    },
}

CSS = """
  @page { size: Letter portrait; margin: 0.35in 0.4in; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: "Inter", "Segoe UI", Arial, sans-serif;
    color: #1c1c1c;
    font-size: 9.6pt;
    line-height: 1.28;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .title-bar {
    background: #b01e2d;
    color: #fff;
    padding: 6px 12px;
    border-radius: 3px 3px 0 0;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
  }
  .title-bar .title {
    font-family: "Archivo", "Inter", sans-serif;
    font-weight: 800;
    font-size: 13pt;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    line-height: 1.05;
  }
  .title-bar .meta {
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    text-align: right;
    opacity: 0.95;
  }
  .fields {
    display: flex;
    gap: 14px;
    border: 1px solid #c9c5bd;
    border-top: none;
    background: #faf7f1;
    padding: 5px 12px;
    font-size: 9pt;
  }
  .fields .f { flex: 1; display: flex; align-items: baseline; gap: 6px; }
  .fields .lbl {
    font-weight: 700;
    font-size: 8pt;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #54505a;
    white-space: nowrap;
  }
  .fields .ln {
    flex: 1;
    border-bottom: 1px solid #54505a;
    height: 11pt;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 7px;
    margin-top: 6px;
  }
  .sec {
    border: 1px solid #c9c5bd;
    border-radius: 3px;
    padding: 6px 9px 7px;
    break-inside: avoid;
  }
  .sec.full { grid-column: 1 / -1; }
  .sec h3 {
    font-size: 8.5pt;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #b01e2d;
    margin: 0 0 3px;
    border-bottom: 1px solid #c9c5bd;
    padding-bottom: 2px;
  }
  .sec p { margin: 0 0 3px; }
  .sec ul { margin: 0; padding-left: 14px; }
  .sec li { margin-bottom: 1.5px; }
  .sec .ref {
    color: #76777E;
    font-size: 7.8pt;
    font-weight: 600;
  }
  .signin {
    margin-top: 7px;
    border: 1px solid #c9c5bd;
    border-radius: 3px;
    padding: 5px 9px 6px;
  }
  .signin h3 {
    font-size: 8.5pt;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #14161C;
    margin: 0 0 3px;
  }
  table.signin-tbl {
    width: 100%;
    border-collapse: collapse;
    font-size: 8.5pt;
  }
  table.signin-tbl th, table.signin-tbl td {
    border-bottom: 1px solid #54505a;
    padding: 4px 5px;
    text-align: left;
    vertical-align: bottom;
    height: 18pt;
  }
  table.signin-tbl th {
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 7.5pt;
    color: #54505a;
    height: 14pt;
    border-bottom: 1.4px solid #14161C;
  }
  .foreman-row {
    margin-top: 6px;
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 8.5pt;
  }
  .foreman-row .lbl {
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 7.5pt;
    color: #54505a;
    white-space: nowrap;
  }
  .foreman-row .ln {
    flex: 1;
    border-bottom: 1px solid #54505a;
    height: 14pt;
  }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
  <div class="title-bar">
    <div class="title">{topic} {topic_number} · {title}</div>
    <div class="meta">{ch33_label} {ch33_ref}<br>{est_minutes} {duration}</div>
  </div>
  <div class="fields">
    <div class="f"><span class="lbl">{f_date}</span><span class="ln"></span></div>
    <div class="f"><span class="lbl">{f_project}</span><span class="ln"></span></div>
    <div class="f"><span class="lbl">{f_foreman}</span><span class="ln"></span></div>
  </div>
  <div class="grid">
    <div class="sec full">
      <h3>{why_title}</h3>
      <p>{why_text}</p>
    </div>
    <div class="sec">
      <h3>{rules_title}</h3>
      <ul>{rules_items}</ul>
    </div>
    <div class="sec">
      <h3>{do_title}</h3>
      <ul>{do_items}</ul>
    </div>
    <div class="sec">
      <h3>{dont_title}</h3>
      <ul>{dont_items}</ul>
    </div>
    <div class="sec">
      <h3>{questions_title}</h3>
      <ul>{questions_items}</ul>
    </div>
  </div>
  <div class="signin">
    <h3>{signin_title}</h3>
    <table class="signin-tbl">
      <thead><tr>
        <th style="width:34%;">{signin_print}</th>
        <th style="width:38%;">{signin_sig}</th>
        <th style="width:18%;">{signin_date}</th>
      </tr></thead>
      <tbody>
        {signin_rows}
      </tbody>
    </table>
    <div class="foreman-row">
      <span class="lbl">{foreman_line}</span>
      <span class="ln"></span>
    </div>
  </div>
</body>
</html>
"""


def _esc(s):
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _li(items, with_ref=False):
    out = []
    for it in items:
        if with_ref and isinstance(it, (list, tuple)) and len(it) == 2:
            text, ref = it
            out.append(f'<li>{_esc(text)} <span class="ref">{_esc(ref)}</span></li>')
        else:
            out.append(f'<li>{_esc(it)}</li>')
    return "".join(out)


def _signin_rows(n=12):
    return "".join("<tr><td></td><td></td><td></td></tr>" for _ in range(n))


def render_talk(talk, lang):
    s = I18N[lang]
    title = talk[f"title_{lang}"]
    return HTML_TEMPLATE.format(
        lang=lang,
        css=CSS,
        topic=s["topic"],
        topic_number=talk["topic_number"],
        title=_esc(title),
        ch33_label=s["ch33"],
        ch33_ref=_esc(talk["ch33_ref"]),
        est_minutes=talk["est_minutes"],
        duration=s["duration"],
        f_date=s["fields_date"],
        f_project=s["fields_project"],
        f_foreman=s["fields_foreman"],
        why_title=s["why_title"],
        why_text=_esc(talk[f"why_{lang}"]),
        rules_title=s["rules_title"],
        rules_items=_li(talk[f"rules_{lang}"], with_ref=True),
        do_title=s["do_title"],
        do_items=_li(talk[f"do_{lang}"]),
        dont_title=s["dont_title"],
        dont_items=_li(talk[f"dont_{lang}"]),
        questions_title=s["questions_title"],
        questions_items=_li(talk[f"questions_{lang}"]),
        signin_title=s["signin_title"],
        signin_print=s["signin_print"],
        signin_sig=s["signin_sig"],
        signin_date=s["signin_date"],
        signin_rows=_signin_rows(12),
        foreman_line=s["foreman_line"],
    )


def main():
    if not TALKS:
        print("[toolbox-gen] no talks defined yet — populate toolbox_talks_data.TALKS")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for t in TALKS:
        for lang in ("en", "es"):
            path = OUT_DIR / f"{t['slug']}_{lang}.html"
            path.write_text(render_talk(t, lang), encoding="utf-8")
            print(f"[toolbox-gen] wrote {path.name}")
    print(f"[toolbox-gen] {len(TALKS)} talks x 2 languages = {len(TALKS)*2} HTMLs")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
