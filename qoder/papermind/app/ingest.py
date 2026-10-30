"""文档抽取与切片：Markdown / 纯文本 / PDF。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
SUPPORTED = {".md", ".markdown", ".txt", ".pdf"}


@dataclass
class Block:
    text: str
    section: str = ""
    page: int = 0


@dataclass
class Chunk:
    id: str
    doc_id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedDocument:
    doc_id: str
    title: str
    file_name: str
    source_type: str
    year: int
    tags: list[str]
    blocks: list[Block]
    summary: str


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, raw[match.end() :]


def _read_pdf(path: Path) -> tuple[str, list[Block]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    blocks: list[Block] = []
    texts: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(Block(text=text, section=f"第 {i} 页", page=i))
            texts.append(text)
    return "\n".join(texts), blocks


def _read_markdown(text: str) -> list[Block]:
    blocks: list[Block] = []
    matches = list(HEADING.finditer(text))
    if not matches:
        cleaned = text.strip()
        return [Block(text=cleaned, section="正文")] if cleaned else []

    intro = text[: matches[0].start()].strip()
    if intro:
        blocks.append(Block(text=intro, section="引言"))

    for idx, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            blocks.append(Block(text=body, section=title))
    return blocks


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_block(block: Block, size: int, overlap: int) -> list[Block]:
    text = _normalize(block.text)
    if len(text) <= size:
        return [Block(text=text, section=block.section, page=block.page)] if text else []

    pieces: list[Block] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in ("\n\n", "\n", "。", ". ", "；", "; "):
                cut = window.rfind(sep)
                if cut > size * 0.5:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            pieces.append(Block(text=piece, section=block.section, page=block.page))
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def _make_doc_id(file_name: str, raw: str) -> str:
    digest = hashlib.sha1(f"{file_name}:{raw[:4096]}".encode()).hexdigest()[:10]
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", Path(file_name).stem).strip("-").lower() or "doc"
    return f"{stem[:32]}-{digest}"


def parse_document(path: Path, raw_text: str | None = None) -> ParsedDocument:
    suffix = path.suffix.lower()
    file_name = path.name
    blocks: list[Block] | None = None

    if raw_text is not None:
        content = raw_text
    elif suffix == ".pdf":
        content, blocks = _read_pdf(path)
    else:
        content = path.read_text(encoding="utf-8", errors="replace")

    meta, body = _parse_front_matter(content)
    if blocks is None:
        if suffix in {".md", ".markdown"}:
            blocks = _read_markdown(body)
        else:
            plain = _normalize(body)
            blocks = [Block(plain, "正文")] if plain else []
    body = _normalize(body)

    title = meta.get("title") or Path(file_name).stem
    tags = [t.strip() for t in re.split(r"[,，;；]", meta.get("tags", "")) if t.strip()]
    try:
        year = int(meta.get("year", "0"))
    except ValueError:
        year = 0
    source_type = meta.get("type", "paper" if suffix == ".pdf" else "note")

    summary = body[:160]
    doc_id = meta.get("id") or _make_doc_id(file_name, body)
    return ParsedDocument(
        doc_id=doc_id,
        title=title,
        file_name=file_name,
        source_type=source_type,
        year=year,
        tags=tags,
        blocks=blocks,
        summary=summary,
    )


def build_chunks(doc: ParsedDocument) -> list[Chunk]:
    chunks: list[Chunk] = []
    index = 0
    for block in doc.blocks:
        for piece in _split_block(block, settings.chunk_size, settings.chunk_overlap):
            text = piece.text
            if doc.title and doc.title not in text[:40]:
                text = f"《{doc.title}》 · {piece.section}\n{piece.text}"
            chunks.append(
                Chunk(
                    id=f"{doc.doc_id}:{index}",
                    doc_id=doc.doc_id,
                    text=text,
                    metadata={
                        "doc_id": doc.doc_id,
                        "title": doc.title,
                        "section": piece.section or "正文",
                        "page": int(piece.page),
                        "chunk_index": index,
                        "year": doc.year,
                        "source_type": doc.source_type,
                        "tags": ",".join(doc.tags),
                    },
                )
            )
            index += 1
    return chunks
