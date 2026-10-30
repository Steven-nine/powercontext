"""sddctx 模块自身的单元测试（不依赖数据库与网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from sddctx.agent import extract_patch
from sddctx.diffutil import PatchError, apply_unified_diff, parse_unified_diff
from sddctx.ingest import extract_spec_entries, parse_front_matter
from sddctx.store import tokenize

SAMPLE_DIFF = """diff --git a/demo/module.py b/demo/module.py
--- a/demo/module.py
+++ b/demo/module.py
@@ -1,4 +1,5 @@
 def value() -> int:
-    return 1
+    return 2
+
+
+def other() -> int:
+    return 3
"""


def test_tokenize_splits_identifiers_and_chinese():
    tokens = tokenize("shipping_fee 偏远地区运费")
    assert "shipping_fee" in tokens
    assert "shipping" in tokens
    assert "fee" in tokens
    assert "偏" in tokens and "远" in tokens


def test_tokenize_drops_stopwords():
    assert "the" not in tokenize("the order")


def test_parse_front_matter_reads_metadata():
    text = "---\nsdd_doc_id: settlement-spec\nsdd_version: \"1.2\"\n---\n\n# 正文\n"
    meta, body = parse_front_matter(text)
    assert meta["sdd_doc_id"] == "settlement-spec"
    assert meta["sdd_version"] == "1.2"
    assert body.strip().startswith("# 正文")


def test_extract_spec_entries_splits_spec_sections():
    text = (
        "# 规格\n\n"
        "## SPEC-SHIP-001 普通地区运费\n"
        "- 满 99 免运费。\n\n"
        "## SPEC-SHIP-002 偏远地区运费\n"
        "- 固定 20 元。\n\n"
        "## 其他章节\n"
        "- 不属于规格条目。\n"
    )
    entries = extract_spec_entries(text)
    assert [entry.entry_id for entry in entries] == ["SPEC-SHIP-001", "SPEC-SHIP-002"]
    assert "固定 20 元。" in entries[1].body


def test_parse_unified_diff_reads_hunks():
    patches = parse_unified_diff(SAMPLE_DIFF)
    assert len(patches) == 1
    assert patches[0].old_path == "demo/module.py"
    assert patches[0].new_path == "demo/module.py"
    assert patches[0].hunks[0].old_start == 1


def test_apply_unified_diff_writes_expected_content(tmp_path: Path):
    target = tmp_path / "demo" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
    apply_unified_diff(SAMPLE_DIFF, tmp_path)
    assert target.read_text(encoding="utf-8") == (
        "def value() -> int:\n    return 2\n\n\ndef other() -> int:\n    return 3\n"
    )


def test_apply_unified_diff_locates_hunk_when_line_numbers_are_wrong(tmp_path: Path):
    """模型给出的行号有偏差时，应按上下文内容就近定位。"""

    target = tmp_path / "demo" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("\n".join(f"line{index}" for index in range(1, 21)) + "\n", encoding="utf-8")
    patch = (
        "diff --git a/demo/module.py b/demo/module.py\n"
        "--- a/demo/module.py\n"
        "+++ b/demo/module.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line10\n"
        "-line11\n"
        "+line11-changed\n"
        " line12\n"
    )
    apply_unified_diff(patch, tmp_path)
    content = target.read_text(encoding="utf-8")
    assert "line11-changed" in content
    assert "line10" in content


def test_apply_unified_diff_reports_mismatch(tmp_path: Path):
    target = tmp_path / "demo" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("completely different\n", encoding="utf-8")
    with pytest.raises(PatchError):
        apply_unified_diff(SAMPLE_DIFF, tmp_path)


def test_extract_patch_from_plain_response():
    response = "好的，下面是补丁：\n\n" + SAMPLE_DIFF + "\n说明完毕。"
    patch = extract_patch(response)
    assert patch.startswith("diff --git a/demo/module.py")
    assert "def other() -> int:" in patch


def test_extract_patch_from_fenced_response():
    response = "```diff\n" + SAMPLE_DIFF + "```"
    patch = extract_patch(response)
    assert patch.startswith("diff --git a/demo/module.py")


def test_extract_patch_returns_empty_without_diff():
    assert extract_patch("我无法完成这个任务") == ""
