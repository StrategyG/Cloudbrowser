#!/usr/bin/env python3
"""Syntax-check each inline JavaScript bundle in the shipped MorphGLB HTML."""
from __future__ import annotations

import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.buffer: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            if dict(attrs).get("src"):
                raise ValueError("MorphGLB must remain self-contained.")
            self.active, self.buffer = True, []

    def handle_data(self, data):
        if self.active:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.scripts.append("".join(self.buffer))
            self.active = False


def main():
    html = Path(__file__).resolve().parents[1] / "cloudbrowser/morphglb/MorphGLB_AI_Studio_v3.3.0.html"
    parser = Scripts()
    parser.feed(html.read_text(encoding="utf-8"))
    if len(parser.scripts) != 13:
        raise ValueError(f"Expected 13 inline scripts; found {len(parser.scripts)}.")
    with tempfile.TemporaryDirectory() as directory:
        for index, script in enumerate(parser.scripts):
            path = Path(directory) / f"bundle-{index:02d}.js"
            path.write_text(script, encoding="utf-8")
            subprocess.run(["node", "--check", str(path)], check=True)
    print(f"PASS: all {len(parser.scripts)} embedded editor scripts parse.")


if __name__ == "__main__":
    main()
