#!/usr/bin/env python3
"""Build the OpenAI Realtime cost-strategy report HTML + PDF from the
canonical .md. Standalone — no project deps. Run with system python3.
(원본 markdown → HTML + PDF — 시스템 python3로 실행)
"""
from __future__ import annotations

import sys
from pathlib import Path

import subprocess

import markdown                # python-markdown

HERE = Path(__file__).parent
# Switch via CLI arg: python _build_pdf.py [base-name-without-extension]
DEFAULT = "openai-realtime-cost-strategy"
BASE = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
MD = HERE / f"{BASE}.md"
HTML_OUT = HERE / f"{BASE}.html"
PDF_OUT = HERE / f"{BASE}.pdf"

CSS = """
@page {
  size: A4;
  margin: 18mm 16mm 22mm 16mm;
  @bottom-center {
    content: "JM Tech One · 2026-05-08 · Page " counter(page) " / " counter(pages);
    font-size: 8pt;
    color: #6b7280;
  }
}
html { font-family: -apple-system, "Apple SD Gothic Neo", "Helvetica Neue", "Segoe UI", sans-serif;
       font-size: 10pt; color: #1a1a1a; }
body { line-height: 1.50; }
h1 { font-size: 22pt; border-bottom: 3px solid #2563eb; padding-bottom: 6px; margin-top: 0; color: #1e3a8a; }
h2 { font-size: 15pt; color: #2563eb; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px;
     margin-top: 22px; page-break-after: avoid; }
h3 { font-size: 12pt; color: #1f2937; margin-top: 14px; page-break-after: avoid; }
h4 { font-size: 11pt; color: #374151; margin-top: 10px; }
p, li { margin: 4px 0; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 12px; font-size: 9pt;
        page-break-inside: avoid; }
th, td { border: 1px solid #d1d5db; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #eff6ff; font-weight: 600; color: #1e3a8a; }
tr:nth-child(even) td { background: #fafbfc; }
code { background: #f3f4f6; padding: 1px 4px; border-radius: 3px;
       font-size: 8.5pt; font-family: "SF Mono", Menlo, Consolas, monospace; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 4px;
      padding: 8px 10px; font-size: 8.5pt; overflow-x: auto; page-break-inside: avoid;
      font-family: "SF Mono", Menlo, Consolas, monospace; line-height: 1.35; }
pre code { background: transparent; padding: 0; }
blockquote { border-left: 3px solid #f59e0b; background: #fef3c7;
             padding: 6px 10px; margin: 8px 0; font-size: 9.5pt; }
blockquote p { margin: 2px 0; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 14px 0; }
ul, ol { margin: 4px 0 8px 22px; padding: 0; }
strong { color: #111827; }
em { color: #4b5563; }
a { color: #2563eb; text-decoration: none; }
.cover-spacer { height: 30mm; }
"""

HEAD = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>OpenAI Realtime Cost Strategy — JM Tech One 2026-05-08</title>
<style>{css}</style>
</head>
<body>
"""

TAIL = """
</body>
</html>"""


def main() -> int:
    md_text = MD.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "attr_list", "sane_lists"],
        output_format="html5",
    )
    html_doc = HEAD.format(css=CSS) + html_body + TAIL
    HTML_OUT.write_text(html_doc, encoding="utf-8")
    print(f"  ↳ HTML written: {HTML_OUT} ({len(html_doc):,} bytes)")

    # Chrome headless print-to-PDF — works on macOS without extra deps.
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_OUT}",
        f"file://{HTML_OUT.resolve()}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  ✗ Chrome PDF failed: {result.stderr[:300]}")
        return 1
    if not PDF_OUT.exists():
        print(f"  ✗ PDF not produced — Chrome may have failed silently")
        return 1
    print(f"  ↳ PDF written:  {PDF_OUT} ({PDF_OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
