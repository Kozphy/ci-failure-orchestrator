"""Dependency-free checks for the commercial static site and audit documents."""

from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site/landing-page/index.html"
CSS = ROOT / "site/landing-page/styles.css"
REQUIRED = {
    "business/service-offer.md",
    "business/delivery-sop.md",
    "business/acceptance-criteria.md",
    "business/terms.md",
    "business/pilot-tracker.md",
    "business/intake.md",
    ".github/ISSUE_TEMPLATE/ci-audit-inquiry.yml",
}
BANNED = ("YOUR-PAYMENT-LINK", "YOUR-HANDLE", "buy.stripe.com/YOUR", "cal.com/YOUR", "YOUR-EMAIL", "sk_live_", "ghp_")

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.headings = []
        self.title = False

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if "id" in props:
            self.ids.add(props["id"])
        if tag == "a":
            self.links.append(props.get("href", ""))
        if tag == "title":
            self.title = True
        if tag in ("h1", "h2"):
            self.headings.append(tag)

def validate():
    for rel in REQUIRED:
        assert (ROOT / rel).is_file(), f"Missing {rel}"
    html = PAGE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    docs = {p: (ROOT / p).read_text(encoding="utf-8") for p in REQUIRED}
    for name, content in [("page", html), ("css", css), *docs.items()]:
        for banned in BANNED:
            # The checker may name banned placeholders; the content files must not.
            assert banned not in content, f"Placeholder or credential pattern in {name}"
    parser = PageParser()
    parser.feed(html)
    assert parser.title and parser.headings.count("h1") == 1
    assert "scope" in parser.ids and "main" in parser.ids
    assert 'name="viewport"' in html and 'name="description"' in html
    assert 'rel="stylesheet" href="styles.css"' in html
    assert "US$149" in html and "US$149" in docs["business/service-offer.md"]
    assert "5 workflows" in html and "30 runs" in html
    assert "3 business days" in html and "read-only" in html
    assert "no paid pilot" in html.lower() and "no live payment" in docs["business/intake.md"].lower()
    assert not re.search(r"href=[\x22\x27](?:javascript:|data:)", html, flags=re.I)
    for url in parser.links:
        assert url and (url.startswith("https://github.com/Kozphy/ci-failure-orchestrator") or url.startswith("#")), f"Unexpected link: {url}"
        if url.startswith("#"):
            assert url[1:] in parser.ids, f"Missing anchor: {url}"
    assert not re.search(r"<script\b|<form\b|<iframe\b", html, re.I)
    assert "prefers-reduced-motion" in css and ":focus-visible" in css
    print(f"PASS: landing page, {len(REQUIRED)} supporting files, accessibility and checkout guardrails")

if __name__ == "__main__":
    validate()
