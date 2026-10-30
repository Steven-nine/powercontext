"""模块配置：环境变量与默认值。

所有配置项都可以用环境变量覆盖，默认值面向"干净环境一键跑通"设计。
缓存目录默认落在 D 盘的 ``D:\\DeepSeek缓存\\minimax-sdd``（Windows），
不存在 D 盘时回退到 ``~/.cache/minimax-sdd``。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: 模块根目录（``minimax/``），即本包的父目录。
DEFAULT_ROOT = Path(__file__).resolve().parent.parent

#: Windows 下 D 盘缓存目录名。
WINDOWS_CACHE_DIR = Path(r"D:\DeepSeek缓存\minimax-sdd")


def default_cache_dir() -> Path:
    """返回缓存目录：优先 D 盘，其次用户目录下的 ``.cache``。"""

    if os.name == "nt" and WINDOWS_CACHE_DIR.parent.exists():
        return WINDOWS_CACHE_DIR
    return Path.home() / ".cache" / "minimax-sdd"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """一次运行所需的全部配置。"""

    root: Path
    cache_dir: Path
    artifacts_dir: Path
    logs_dir: Path

    db_host: str = "127.0.0.1"
    db_port: int = 2881
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "sdd_ctx"

    state_db_path: Path = field(default_factory=Path)

    minimax_base_url: str = "https://api.minimax.cn/v1"
    minimax_model: str = "MiniMax-M3.1-Flash"
    minimax_api_key: str = ""
    minimax_max_tokens: int = 32768
    minimax_reasoning_effort: str = ""

    offline: bool = False

    @property
    def specs_dir(self) -> Path:
        return self.root / "specs"

    @property
    def code_dir(self) -> Path:
        return self.root / "business"

    @property
    def repo_root(self) -> Path:
        """补丁基准目录（``minimax/`` 的上一级，即仓库根）。"""

        return self.root.parent

    @property
    def path_prefix(self) -> str:
        """补丁中项目目录的相对前缀，例如 ``minimax``。"""

        return self.root.name

    @property
    def state_db_url(self) -> str:
        """PowerContext 使用的 SQLite URL（PowerContext 的内置持久化后端）。"""

        return f"sqlite+aiosqlite:///{self.state_db_path.as_posix()}"


def load_settings(root: Path | None = None, **overrides: object) -> Settings:
    """从环境变量装配 :class:`Settings`。"""

    resolved_root = Path(root).resolve() if root else DEFAULT_ROOT
    cache_dir = Path(_env("SDDCTX_CACHE_DIR", str(default_cache_dir())))
    artifacts_dir = Path(_env("SDDCTX_ARTIFACTS_DIR", str(resolved_root / "artifacts")))
    logs_dir = Path(_env("SDDCTX_LOGS_DIR", str(artifacts_dir / "logs")))
    state_db_path = Path(_env("SDDCTX_STATE_DB", str(cache_dir / "state" / "powercontext.db")))

    settings = Settings(
        root=resolved_root,
        cache_dir=cache_dir,
        artifacts_dir=artifacts_dir,
        logs_dir=logs_dir,
        db_host=_env("SDDCTX_DB_HOST", "127.0.0.1"),
        db_port=int(_env("SDDCTX_DB_PORT", "2881")),
        db_user=_env("SDDCTX_DB_USER", "root"),
        db_password=os.environ.get("SDDCTX_DB_PASSWORD", "") or "",
        db_name=_env("SDDCTX_DB_NAME", "sdd_ctx"),
        state_db_path=state_db_path,
        minimax_base_url=_env("SDDCTX_MINIMAX_BASE_URL", "https://api.minimax.cn/v1"),
        minimax_model=_env("SDDCTX_MINIMAX_MODEL", "MiniMax-M3.1-Flash"),
        minimax_api_key=os.environ.get("MINIMAX_API_KEY", "") or "",
        minimax_max_tokens=int(_env("SDDCTX_MINIMAX_MAX_TOKENS", "32768")),
        minimax_reasoning_effort=_env("SDDCTX_MINIMAX_REASONING_EFFORT", ""),
        offline=_env_bool("SDDCTX_OFFLINE", False),
    )

    for key, value in overrides.items():
        if value is not None:
            object.__setattr__(settings, key, value)
    return settings
