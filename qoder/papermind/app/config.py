"""应用配置：全部来自环境变量 / .env，不写死任何凭据。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path

    # 模型服务
    dashscope_api_key: str
    dashscope_base_url: str
    chat_model: str
    embedding_model: str
    embedding_dim: int
    embedding_backend: str
    local_embedding_dim: int

    # seekdb
    seekdb_mode: str
    seekdb_path: str
    seekdb_database: str
    seekdb_host: str
    seekdb_port: int
    seekdb_user: str
    seekdb_password: str
    doc_collection: str
    chunk_collection: str

    # PowerContext
    powercontext_url: str
    powercontext_token: str
    powercontext_scope_prefix: str

    # 应用
    app_host: str
    app_port: int
    chunk_size: int
    chunk_overlap: int
    top_k: int
    candidates: int

    @property
    def seekdb_is_embedded(self) -> bool:
        return self.seekdb_mode.lower() == "embedded"

    @property
    def has_llm(self) -> bool:
        return bool(self.dashscope_api_key) and not self.dashscope_api_key.startswith("sk-replace")

    @property
    def is_local_embedding(self) -> bool:
        return self.embedding_backend.lower() == "local"

    @property
    def has_embedding(self) -> bool:
        return self.is_local_embedding or self.has_llm

    @property
    def effective_embedding_dim(self) -> int:
        return self.local_embedding_dim if self.is_local_embedding else self.embedding_dim

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    if not data_dir.is_absolute():
        data_dir = (PROJECT_ROOT / data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    seekdb_path = os.getenv("SEEKDB_PATH", "./data/seekdb")
    if not seekdb_path.startswith(":"):
        p = Path(seekdb_path)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        seekdb_path = str(p)

    return Settings(
        project_root=PROJECT_ROOT,
        data_dir=data_dir,
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        dashscope_base_url=os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/"),
        chat_model=os.getenv("CHAT_MODEL", "qwen-plus"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-v3"),
        embedding_dim=_get_int("EMBEDDING_DIM", 1024),
        embedding_backend=os.getenv("EMBEDDING_BACKEND", "dashscope"),
        local_embedding_dim=_get_int("LOCAL_EMBEDDING_DIM", 384),
        seekdb_mode=os.getenv("SEEKDB_MODE", "embedded"),
        seekdb_path=seekdb_path,
        seekdb_database=os.getenv("SEEKDB_DATABASE", "papermind"),
        seekdb_host=os.getenv("SEEKDB_HOST", "127.0.0.1"),
        seekdb_port=_get_int("SEEKDB_PORT", 2881),
        seekdb_user=os.getenv("SEEKDB_USER", "root"),
        seekdb_password=os.getenv("SEEKDB_PASSWORD", ""),
        doc_collection=os.getenv("SEEKDB_DOC_COLLECTION", "docs"),
        chunk_collection=os.getenv("SEEKDB_CHUNK_COLLECTION", "chunks"),
        powercontext_url=os.getenv("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/"),
        powercontext_token=os.getenv("POWERCONTEXT_TOKEN", ""),
        powercontext_scope_prefix=os.getenv("POWERCONTEXT_SCOPE_PREFIX", "papermind"),
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=_get_int("APP_PORT", 8080),
        chunk_size=_get_int("CHUNK_SIZE", 700),
        chunk_overlap=_get_int("CHUNK_OVERLAP", 120),
        top_k=_get_int("RETRIEVE_TOP_K", 6),
        candidates=_get_int("RETRIEVE_CANDIDATES", 24),
    )


settings = get_settings()
