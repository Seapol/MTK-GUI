#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the User Guide as a static HTML site into docs/help/_build/.

    python scripts/build_help.py

每章渲染为带样式 + 章节导航 + 上一章/下一章的独立 HTML 页，截图复制
为相对路径（_build/images/）。_open_help 在应用内是实时渲染，本脚本
只用于发布 / 离线浏览。docs/help/*.md 改完后重跑即可。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "help" / "_build"


def main() -> int:
    from mtkgui.gui.help_content import CHAPTERS, HELP_ROOT, topic_page_html

    if OUT.exists():                          # regen from scratch
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(HELP_ROOT / "images", OUT / "images", dirs_exist_ok=True)

    for key, _label, filename in CHAPTERS:
        page = topic_page_html(key)
        # temp-dir file:// image URIs -> relative _build/images/ paths
        page = re.sub(
            r'src="file://[^"]*/images/([^"]+)"',
            r'src="images/\1"', page)
        # temp-dir sibling chapter links -> relative html files
        page = page.replace('href="mtkgui-help://', 'href="')
        (OUT / filename.replace(".md", ".html")).write_text(
            page, encoding="utf-8")
        print(f"built {filename.replace('.md', '.html')}")

    print(f"\nDone -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
