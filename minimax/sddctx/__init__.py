"""sddctx —— 面向软件持续演进的 SDD 上下文管理模块。

模块职责：

1. 把规格（spec）、代码（code）、测试（test）导入 seekdb / OceanBase，
   并在数据库中维护倒排索引；
2. 依据开发任务从数据库检索适用资料，组装开发上下文；
3. 把上下文交给 MiniMax（OpenAI 兼容接口）完成一次真实的代码修改；
4. 用 PowerContext 保存任务进展与验证结果，重启后可读回复用。

命令行入口：``python -m sddctx --help``
"""

from .config import Settings, load_settings

__all__ = ("Settings", "load_settings")
