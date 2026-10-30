"""统一 diff（unified diff）的解析与应用。

模块不依赖外部 ``patch`` / ``git apply`` 命令，因此在任何环境中都能把
MiniMax 产出的补丁应用到工作区，并且对"上下文不匹配"给出明确错误。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")


@dataclass
class Hunk:
    """一个 diff 区块。"""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    """一个文件的补丁。"""

    old_path: str
    new_path: str
    hunks: list[Hunk] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted: bool = False

    @property
    def target_path(self) -> str:
        return self.new_path if self.new_path else self.old_path


class PatchError(RuntimeError):
    """补丁无法解析或无法应用。"""


def _strip_prefix(path: str) -> str:
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def parse_unified_diff(text: str) -> list[FilePatch]:
    """解析 unified diff，返回按文件分组的补丁列表。"""

    patches: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: Hunk | None = None

    for raw_line in (text or "").splitlines():
        line = raw_line
        if line.startswith("\\ No newline"):
            continue
        header = _FILE_HEADER_RE.match(line)
        if header:
            current = FilePatch(old_path=_strip_prefix(header.group(1)), new_path=_strip_prefix(header.group(2)))
            patches.append(current)
            hunk = None
            continue
        if line.startswith("--- "):
            path = _strip_prefix(line[4:].split("\t")[0].strip())
            if current is None:
                current = FilePatch(old_path=path, new_path=path)
                patches.append(current)
            else:
                current.old_path = path
            hunk = None
            continue
        if line.startswith("+++ "):
            path = _strip_prefix(line[4:].split("\t")[0].strip())
            if current is None:
                current = FilePatch(old_path=path, new_path=path)
                patches.append(current)
            else:
                current.new_path = path
            if path == "/dev/null":
                current.is_new_file = True
            hunk = None
            continue
        if line.startswith("new file mode"):
            if current is not None:
                current.is_new_file = True
            continue
        if line.startswith("deleted file mode"):
            if current is not None:
                current.is_deleted = True
            continue
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            if current is None:
                raise PatchError("补丁缺少文件头（diff --git / --- / +++）")
            hunk = Hunk(
                old_start=int(hunk_match.group(1)),
                old_count=int(hunk_match.group(2) or 1),
                new_start=int(hunk_match.group(3)),
                new_count=int(hunk_match.group(4) or 1),
            )
            current.hunks.append(hunk)
            continue
        if hunk is not None and line[:1] in {" ", "+", "-"}:
            hunk.lines.append(line)
            continue
        if hunk is not None and line == "":
            hunk.lines.append(" ")
            continue
        # 其余行（元数据）忽略。

    return [patch for patch in patches if patch.hunks]


def _hunk_old_lines(hunk: Hunk) -> list[str]:
    """hunk 在原始文件中对应的行序列（上下文行 + 被删除行）。"""

    return [line[1:] for line in hunk.lines if line[:1] in {" ", "-"}]


def _locate_hunk(
    original: list[str],
    old_lines: list[str],
    preferred: int,
    floor: int,
    radius: int = 400,
) -> int | None:
    """在原文件中定位 hunk 的起始行。

    模型给出的行号经常有偏差，因此优先按行号定位，失败时按上下文内容就近搜索
    （与 ``patch`` / ``git apply`` 的偏移行为一致）。
    """

    if not old_lines:
        return max(preferred, floor)
    limit = len(original) - len(old_lines)
    candidates: list[int] = [preferred]
    for offset in range(1, radius + 1):
        candidates.append(preferred + offset)
        candidates.append(preferred - offset)
    for candidate in candidates:
        if candidate < floor or candidate < 0 or candidate > limit:
            continue
        if original[candidate : candidate + len(old_lines)] == old_lines:
            return candidate
    return None


def apply_hunks(original: list[str], hunks: list[Hunk], *, path: str) -> list[str]:
    """把区块应用到原始行列表（行不含换行符）。"""

    result: list[str] = []
    cursor = 0
    for hunk in hunks:
        preferred = hunk.old_start - 1
        if preferred < cursor:
            preferred = cursor
        position = _locate_hunk(original, _hunk_old_lines(hunk), preferred, cursor)
        if position is None:
            expected = _hunk_old_lines(hunk)
            actual = original[cursor : cursor + len(expected)]
            raise PatchError(
                f"{path}: 无法在文件中定位第 {hunk.old_start} 行附近的区块\n"
                f"  期望上下文: {expected[:4]}\n  实际内容: {actual[:4]}"
            )
        result.extend(original[cursor:position])
        cursor = position
        for line in hunk.lines:
            marker, text = line[0], line[1:]
            if marker == " ":
                if cursor >= len(original) or original[cursor] != text:
                    actual = original[cursor] if cursor < len(original) else "<EOF>"
                    raise PatchError(
                        f"{path}: 第 {cursor + 1} 行上下文不匹配\n  期望: {text!r}\n  实际: {actual!r}"
                    )
                result.append(original[cursor])
                cursor += 1
            elif marker == "-":
                if cursor >= len(original) or original[cursor] != text:
                    actual = original[cursor] if cursor < len(original) else "<EOF>"
                    raise PatchError(
                        f"{path}: 第 {cursor + 1} 行删除内容不匹配\n  期望: {text!r}\n  实际: {actual!r}"
                    )
                cursor += 1
            elif marker == "+":
                result.append(text)
            else:
                raise PatchError(f"{path}: 未知区块行前缀 {marker!r}")
    result.extend(original[cursor:])
    return result


def _split_lines(text: str) -> list[str]:
    """按行切分，不保留换行符。"""

    if text == "":
        return []
    return text.splitlines()


def apply_unified_diff(text: str, root: Path, *, dry_run: bool = False) -> list[dict[str, str]]:
    """把 unified diff 应用到 ``root`` 下的文件，返回变更摘要。"""

    patches = parse_unified_diff(text)
    if not patches:
        raise PatchError("补丁中没有可应用的区块")

    summary: list[dict[str, str]] = []
    for patch in patches:
        relative = patch.target_path or patch.old_path
        target = (root / relative).resolve()
        root_resolved = root.resolve()
        if not str(target).startswith(str(root_resolved)):
            raise PatchError(f"补丁目标越界：{relative}")

        if patch.is_deleted:
            if target.exists():
                if not dry_run:
                    target.unlink()
                summary.append({"path": relative, "action": "deleted"})
            continue

        if patch.is_new_file or not target.exists():
            original: list[str] = []
        else:
            original = _split_lines(target.read_text(encoding="utf-8"))

        updated = apply_hunks(original, patch.hunks, path=relative)
        content = "\n".join(updated)
        if content and not content.endswith("\n"):
            content += "\n"
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        summary.append(
            {
                "path": relative,
                "action": "created" if patch.is_new_file else "modified",
                "hunks": str(len(patch.hunks)),
            }
        )
    return summary
