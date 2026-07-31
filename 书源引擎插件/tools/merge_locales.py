#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""合并书源引擎 i18n 片段到 MyBooks 目标 locale 文件（幂等）。

用法:
    python tools/merge_locales.py <mybooks-root>

将本插件目录 locales/{zh,en,zh-TW}.json 中的 "bookSource" 键合并进
<mybooks-root>/app/locales/{zh,en,zh-TW}.json 顶层，已存在时覆盖更新，
其余键保持不变。
"""
import json
import sys
from pathlib import Path

LOCALE_NAMES = ["zh", "en", "zh-TW"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    mybooks_root = Path(sys.argv[1]).resolve()
    delta_dir = Path(__file__).resolve().parent.parent / "locales"
    target_dir = mybooks_root / "app" / "locales"

    for name in LOCALE_NAMES:
        delta_file = delta_dir / f"{name}.json"
        target_file = target_dir / f"{name}.json"
        if not delta_file.exists() or not target_file.exists():
            print(f"[skip] {name}: {delta_file.name if not delta_file.exists() else target_file.name} 不存在")
            continue
        delta = json.loads(delta_file.read_text(encoding="utf-8"))
        target = json.loads(target_file.read_text(encoding="utf-8"))
        added = sum(1 for k in delta if k not in target)
        target.update(delta)
        target_file.write_text(
            json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"[ok] {name}: 合并 {len(delta)} 个键（新增 {added}，更新 {len(delta) - added}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
