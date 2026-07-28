"""Static checks for the root GitHub Pages landing page."""

from __future__ import annotations

import re
import sys

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"
LANDING_JS = ROOT / "docs" / "landing" / "landing.js"
LANDING_CSS = ROOT / "docs" / "landing" / "landing.css"
SCREENSHOTS = (
    ROOT / "docs" / "landing" / "assets" / "screenshots" / "setup-agent.png",
    ROOT / "docs" / "landing" / "assets" / "screenshots" / "ready-workbench.png",
    ROOT / "docs" / "landing" / "assets" / "screenshots" / "finished-diff.png",
    ROOT / "docs" / "landing" / "assets" / "screenshots" / "permission-panel.png",
)

REQUIRED_TEXT = (
    "YagCode",
    "受约束、可回档、可审计的本地 Coding Agent",
    "GitHub Pages 仅展示产品与下载入口",
    "YagCode Desktop for macOS",
    "YagCode Desktop for Windows",
    "YagCode CLI for macOS",
    "YagCode CLI for Windows",
    "GitHub",
)

REQUIRED_LINKS = (
    "https://github.com/zihenyag/yagcode/releases/download/v0.1.0/yagcode-mac-arm64.dmg",
    "https://github.com/zihenyag/yagcode/releases/download/v0.1.0/yagcode-win-x64.exe",
    "https://github.com/zihenyag/yagcode/releases/download/v0.1.0/yagcode-cli-mac-arm64.tar.gz",
    "https://github.com/zihenyag/yagcode/releases/download/v0.1.0/yagcode-cli-win-x64.zip",
    "https://github.com/zihenyag/yagcode",
)

FORBIDDEN_PATTERNS = (
    r"PublicDemoRuntime",
    r"/demo/",
    r"complete_once\(",
    r"\bfetch\s*\(",
    r"XMLHttpRequest",
    r"WebSocket",
    r"EventSource",
    r"localStorage",
    r"sessionStorage",
    r"indexedDB",
    r"serviceWorker",
    r"document\.cookie",
    r"\beval\s*\(",
    r"new Function",
    r"<form\b",
    r"type=[\"']file[\"']",
)

REQUIRED_CSP = (
    "default-src 'self'",
    "script-src 'none'",
    "style-src 'self'",
    "img-src 'self'",
    "frame-src 'none'",
    "connect-src 'none'",
    "object-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
)


class LandingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp = ""
        self.images: list[tuple[str, str]] = []
        self.iframes = 0
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "meta" and attr.get("http-equiv") == "Content-Security-Policy":
            self.csp = attr.get("content", "")
        if tag == "img":
            self.images.append((attr.get("src", ""), attr.get("alt", "")))
        if tag == "iframe":
            self.iframes += 1
        if tag == "script":
            self.scripts.append(attr.get("src", ""))
        if tag == "link" and attr.get("rel") == "stylesheet":
            self.stylesheets.append(attr.get("href", ""))
        if tag == "a":
            self.links.append(attr.get("href", ""))

def main() -> int:
    problems: list[str] = []
    html = _read(INDEX, problems)
    css = _read(LANDING_CSS, problems)
    if problems:
        return _finish(problems)

    parser = LandingParser()
    parser.feed(html)

    for text in REQUIRED_TEXT:
        if text not in html:
            problems.append(f"missing required text: {text}")
    for href in REQUIRED_LINKS:
        if href not in parser.links:
            problems.append(f"missing required link: {href}")
    for directive in REQUIRED_CSP:
        if directive not in parser.csp:
            problems.append(f"missing CSP directive: {directive}")
    if parser.iframes != 0:
        problems.append("index.html must not contain an iframe")
    if parser.scripts != []:
        problems.append(f"unexpected script sources: {parser.scripts!r}")
    if parser.stylesheets != ["docs/landing/landing.css"]:
        problems.append(f"unexpected stylesheet sources: {parser.stylesheets!r}")

    expected_images = {path.relative_to(ROOT).as_posix() for path in SCREENSHOTS}
    actual_images = {src for src, _alt in parser.images}
    missing_images = expected_images - actual_images
    if missing_images:
        problems.append(f"missing screenshot images: {sorted(missing_images)}")
    for src, alt in parser.images:
        if src in expected_images and len(alt.strip()) < 12:
            problems.append(f"screenshot alt is too short: {src}")
    for screenshot in SCREENSHOTS:
        if not screenshot.is_file():
            problems.append(f"missing screenshot asset: {screenshot.relative_to(ROOT)}")

    combined = html
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, combined, flags=re.IGNORECASE):
            problems.append(f"forbidden executable/static page pattern: {pattern}")
    if "第三方视频" in combined:
        problems.append("landing page must not require a video URL")
    if 'id="security"' in combined or 'id="demo"' in combined:
        problems.append("removed landing sections must not return")
    if LANDING_JS.exists():
        problems.append("landing.js should not exist when the root page has no runtime script")
    if len(css) < 2000:
        problems.append("landing.css unexpectedly small")
    return _finish(problems)


def _read(path: Path, problems: list[str]) -> str:
    if not path.is_file():
        problems.append(f"missing file: {path.relative_to(ROOT)}")
        return ""
    return path.read_text(encoding="utf-8")


def _finish(problems: list[str]) -> int:
    if problems:
        for problem in problems:
            print(f"LANDING_CHECK_FAILED: {problem}", file=sys.stderr)
        return 1
    print("LANDING_CHECK_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
