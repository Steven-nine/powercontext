"""FastAPI 应用：资料库、混合检索问答、记忆面板。"""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service
from .config import PROJECT_ROOT, settings
from .memory import memory
from .store import StoreError, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("papermind")

app = FastAPI(title="PaperMind", version="1.0.0", description="seekdb + PowerContext 研读助手")

STATIC_DIR = PROJECT_ROOT / "app" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    user_id: str = Field(default="demo", max_length=64)
    filters: dict | None = None


class TextIngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    type: str = "note"
    year: int | None = None
    tags: str = ""


class MemoryRequest(BaseModel):
    user_id: str = Field(default="demo", max_length=64)
    kind: str = "fact"
    text: str = Field(min_length=1, max_length=4000)


@app.exception_handler(StoreError)
async def _store_error(_request, exc: StoreError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    info = {"app": "ok", "seekdb": {"ok": False}, "powercontext": memory.status(), "llm": settings.has_llm}
    try:
        info["seekdb"] = {"ok": True, **store.stats()}
    except Exception as exc:  # noqa: BLE001
        info["seekdb"] = {"ok": False, "error": str(exc)}
    return info


@app.get("/api/documents")
async def list_documents():
    return {"documents": store.list_documents()}


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    type: str = Form(""),
    year: str = Form(""),
    tags: str = Form(""),
):
    data = await file.read()
    override = {"title": title, "type": type, "year": year, "tags": tags}
    try:
        return service.save_upload(file.filename or "upload.md", data, override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/documents/text")
async def ingest_text(payload: TextIngestRequest):
    try:
        override = {"type": payload.type, "tags": payload.tags}
        if payload.year:
            override["year"] = str(payload.year)
        return service.ingest_text(payload.title, payload.content, override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    store.delete_document(doc_id)
    return {"deleted": doc_id}


@app.post("/api/ask")
async def ask(payload: AskRequest):
    try:
        return service.ask(payload.user_id, payload.question, payload.filters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/memory")
async def list_memory(user_id: str = "demo", limit: int = 50):
    if not memory.available():
        return {"available": False, "memories": [], "error": memory.last_error}
    try:
        scope_id = memory.ensure_scope(user_id)
        return {
            "available": True,
            "scope_id": scope_id,
            "memories": memory.list_memories(scope_id, limit=limit),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "memories": [], "error": str(exc)}


@app.post("/api/memory")
async def add_memory(payload: MemoryRequest):
    if not memory.available():
        raise HTTPException(status_code=503, detail=f"PowerContext 不可用：{memory.last_error}")
    scope_id = memory.ensure_scope(payload.user_id)
    records = memory.remember(scope_id, payload.kind, payload.text, reason="用户在界面手动保存")
    return {"scope_id": scope_id, "records": records}
