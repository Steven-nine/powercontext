"""把工程资料解析成文档记录并导入 seekdb / OceanBase。

支持三类资料：

* ``spec``：Markdown 规格文件，按 ``## SPEC-XXX-NNN`` 拆成规格条目；
* ``code``：Python 业务代码，用 ``ast`` 抽取函数 / 类符号；
* ``test``：pytest 测试文件，用 ``ast`` 抽取测试函数并记录其引用的规格编号。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .store import DocRecord, SpecEntryRecord, SymbolRecord, relative_path

#: 规格条目编号，例如 ``SPEC-SHIP-002``。
SPEC_ID_RE = re.compile(r"\bSPEC-[A-Z0-9]+-\d+\b")

#: 规格文件中的一级条目标题，例如 ``## SPEC-SHIP-002 偏远地区运费``。
SPEC_HEADING_RE = re.compile(r"^##\s+(SPEC-[A-Z0-9]+-\d+)\s*(.*)$")


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """解析 ``---`` 包裹的简单 ``key: value`` 前置元数据。"""

    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].lstrip("\n")


def extract_spec_entries(text: str) -> list[SpecEntryRecord]:
    """把规格 Markdown 拆成 ``SPEC-XXX-NNN`` 条目。"""

    entries: list[SpecEntryRecord] = []
    current_id: str | None = None
    current_title = ""
    buffer: list[str] = []

    def flush() -> None:
        if current_id:
            entries.append(
                SpecEntryRecord(
                    entry_id=current_id,
                    title=current_title.strip(),
                    body="\n".join(buffer).strip(),
                )
            )

    for line in text.splitlines():
        match = SPEC_HEADING_RE.match(line)
        if match:
            flush()
            current_id = match.group(1)
            current_title = match.group(2)
            buffer = []
            continue
        if current_id is not None:
            if line.startswith("## ") and not SPEC_HEADING_RE.match(line):
                flush()
                current_id = None
                current_title = ""
                buffer = []
                continue
            buffer.append(line)
    flush()
    return entries


def _signature(node: ast.AST) -> str:
    args = getattr(node, "args", None)
    if args is None:
        return ""
    names = [arg.arg for arg in args.posonlyargs] + [arg.arg for arg in args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names.extend(arg.arg for arg in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return f"{node.name}({', '.join(names)})"


def extract_python_symbols(path: Path, rel_path: str) -> list[SymbolRecord]:
    """用 ``ast`` 抽取 Python 文件中的顶层函数与类。"""

    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    symbols: list[SymbolRecord] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            docstring = ast.get_docstring(node) or ""
            symbols.append(
                SymbolRecord(
                    symbol_id=f"{rel_path}::{node.name}",
                    name=node.name,
                    kind="function",
                    signature=_signature(node),
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    content=body,
                    docstring=docstring,
                    cited_specs=",".join(
                        sorted(set(SPEC_ID_RE.findall(docstring)) | set(SPEC_ID_RE.findall(body)))
                    ),
                )
            )
        elif isinstance(node, ast.ClassDef):
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            docstring = ast.get_docstring(node) or ""
            symbols.append(
                SymbolRecord(
                    symbol_id=f"{rel_path}::{node.name}",
                    name=node.name,
                    kind="class",
                    signature=f"class {node.name}",
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    content=body,
                    docstring=docstring,
                    cited_specs=",".join(sorted(set(SPEC_ID_RE.findall(docstring)))),
                )
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_body = "\n".join(lines[child.lineno - 1 : child.end_lineno])
                    method_doc = ast.get_docstring(child) or ""
                    symbols.append(
                        SymbolRecord(
                            symbol_id=f"{rel_path}::{node.name}.{child.name}",
                            name=f"{node.name}.{child.name}",
                            kind="method",
                            signature=f"{node.name}.{_signature(child)}",
                            line_start=child.lineno,
                            line_end=child.end_lineno or child.lineno,
                            content=method_body,
                            docstring=method_doc,
                            cited_specs=",".join(
                                sorted(
                                    set(SPEC_ID_RE.findall(method_doc)) | set(SPEC_ID_RE.findall(method_body))
                                )
                            ),
                        )
                    )
    return symbols


def build_spec_record(path: Path, root: Path) -> DocRecord:
    """把规格 Markdown 转换成文档记录。"""

    rel = relative_path(path, root)
    text = path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(text)
    doc_id = meta.get("sdd_doc_id") or rel
    title = meta.get("sdd_title") or path.stem
    version = meta.get("sdd_version", "")
    return DocRecord(
        doc_id=doc_id,
        kind="spec",
        path=rel,
        title=title,
        version=version,
        content=body,
        spec_entries=extract_spec_entries(body),
    )


def build_code_record(path: Path, root: Path) -> DocRecord:
    """把 Python 源文件转换成文档记录。"""

    rel = relative_path(path, root)
    text = path.read_text(encoding="utf-8")
    return DocRecord(
        doc_id=rel,
        kind="code",
        path=rel,
        title=path.name,
        content=text,
        symbols=extract_python_symbols(path, rel),
    )


def build_test_record(path: Path, root: Path) -> DocRecord:
    """把测试文件转换成文档记录。"""

    rel = relative_path(path, root)
    text = path.read_text(encoding="utf-8")
    return DocRecord(
        doc_id=rel,
        kind="test",
        path=rel,
        title=path.name,
        content=text,
        symbols=extract_python_symbols(path, rel),
    )


def discover_specs(root: Path, *, include_history: bool = False) -> list[Path]:
    """发现规格文件；``specs/versions/`` 下的历史版本默认跳过。"""

    specs_dir = root / "specs"
    if not specs_dir.exists():
        return []
    paths: list[Path] = []
    for path in sorted(specs_dir.rglob("*.md")):
        if not include_history and "versions" in path.relative_to(specs_dir).parts:
            continue
        paths.append(path)
    return paths


def discover_code(root: Path) -> list[Path]:
    """发现业务代码文件。"""

    code_dir = root / "business"
    if not code_dir.exists():
        return []
    return sorted(p for p in code_dir.rglob("*.py") if "tests" not in p.parts)


def discover_tests(root: Path) -> list[Path]:
    """发现测试文件。"""

    code_dir = root / "business"
    if not code_dir.exists():
        return []
    return sorted(p for p in code_dir.rglob("test_*.py"))


def collect_records(root: Path, *, include_history: bool = False) -> list[DocRecord]:
    """收集全部资料（规格 + 代码 + 测试）。"""

    records: list[DocRecord] = []
    for path in discover_specs(root, include_history=include_history):
        records.append(build_spec_record(path, root))
    for path in discover_code(root):
        records.append(build_code_record(path, root))
    for path in discover_tests(root):
        records.append(build_test_record(path, root))
    return records
