"""Prompt 定义数据结构(公开)。

这个模块只放**与云端资产无关**的通用数据结构,单独拆出来有两个原因:

1. **让私有资产零依赖**:`_pro_assets/prompts_cloud.py` 只需要纯数据
   (name / version / description / variables / template),不必 import 任何模块,
   因此可以用 `importlib` 按文件路径加载,不会和 `prompts.py` 形成循环导入。
2. **让开源仓的公开部分边界清晰**:`prompt_def.py` 不含任何提示词正文,
   可以安全留在公开树里。

`PromptDef` 的字段与 `Prompt` ORM 结构对齐(但不落 DB);
落库由 `prompts.sync_prompts_to_db()` 负责。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .models import Prompt


@dataclass(frozen=True)
class PromptDef:
    """内存版 prompt 定义(与 `Prompt` ORM 结构对齐,但不落 DB)。"""

    name: str
    template: Any  # 允许 str 或 tuple[str, ...];__post_init__ 会归一化
    tier: str  # "cloud" | "basic"
    variables: tuple[str, ...] = ()
    version: str = "1.0.0"
    description: str = ""

    def __post_init__(self) -> None:
        # 源码中 `template=( "a" "b", "c" "d" )` 会被解析成 tuple。
        # 兼容写法:把 tuple 里所有字符串无分隔符拼接(相邻字符串本应自动拼接)。
        if isinstance(self.template, tuple):
            joined = "".join(str(x) for x in self.template)
            object.__setattr__(self, "template", joined)
        if not isinstance(self.template, str):
            raise TypeError(f"template must be str, got {type(self.template)}")
        if self.tier not in {"cloud", "basic"}:
            raise ValueError(f"tier must be 'cloud' or 'basic', got {self.tier!r}")
        if not self.name:
            raise ValueError("name must not be empty")

    def variables_json(self) -> str:
        return json.dumps(list(self.variables), ensure_ascii=False)

    def to_orm(self) -> Prompt:
        return Prompt(
            name=self.name,
            tier=self.tier,
            template=self.template,
            variables_json=self.variables_json(),
            version=self.version,
            is_active=True,
        )

    def render(self, variables: dict[str, Any]) -> str:
        # 延迟 import,避免 prompt_def -> prompts -> prompt_def 的循环。
        from .prompts import render_template

        return render_template(self.template, variables)


__all__ = ["PromptDef"]
