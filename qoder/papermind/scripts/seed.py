"""把 data/samples 下的示例资料导入 seekdb。

用法：
    python -m scripts.seed              # 导入全部示例
    python -m scripts.seed path/a.md    # 只导入指定文件
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.config import settings
from app.service import ingest_path
from app.store import store


def main(argv: list[str]) -> int:
    store.ensure()
    targets = [Path(p) for p in argv] if argv else sorted(
        (settings.project_root / "data" / "samples").glob("*.md")
    )
    if not targets:
        print("没有找到可导入的资料。")
        return 1

    total = 0
    for path in targets:
        result = ingest_path(path)
        total += result["chunks"]
        print(f"✓ 《{result['title']}》 {result['chunks']} 片 · {result['memory'] or '-'}")
    stats = store.stats()
    print(f"\n完成：{len(targets)} 篇文档 / {total} 片新增；库内共 {stats['documents']} 篇 / {stats['chunks']} 片。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
