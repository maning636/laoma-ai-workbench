"""
自然语言查询引擎（NL → SQL → 结构化数据）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
将用户的自然语言问题转换为 SQL 查询，执行后返回结构化数据和可视化建议。

数据源：Prism 主数据库（SQLite/MySQL），也可切换到独立 fusion_data.db。
默认查询 Prism 主库，通过环境变量 FUSION_QUERY_SOURCE 切换。
"""

from __future__ import annotations
import os, re, json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from loguru import logger

_DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# 数据源切换：prism（默认）或 fusion
_QUERY_SOURCE = os.environ.get("FUSION_QUERY_SOURCE", "prism")


# ============================================================
# 预设问题（供前端下拉选择）
# ============================================================
PRESET_QUESTIONS: List[Dict[str, Any]] = [
    {
        "category": "内容分析",
        "icon": "📝",
        "questions": [
            "近 30 天发布的内容有多少？",
            "AI 生成 vs 手动内容的比例",
            "各平台发布数量对比",
            "文章字数分布",
            "本周新增内容数量",
        ],
    },
    {
        "category": "发布效果",
        "icon": "🚀",
        "questions": [
            "发布成功率是多少？",
            "哪些平台发布失败最多？",
            "最近 7 天发布趋势",
            "各账号发布数量",
        ],
    },
    {
        "category": "热点追踪",
        "icon": "🔥",
        "questions": [
            "近 24 小时最热门的 10 个话题",
            "微博 vs 知乎热点重合度",
            "抖音热榜 Top 5",
        ],
    },
    {
        "category": "系统健康",
        "icon": "📊",
        "questions": [
            "最近 24 小时的系统错误",
            "各模块调用次数统计",
            "数据库大小和记录数",
        ],
    },
]


# ============================================================
# 数据库 Schema 描述（供 LLM 理解表结构）
# ============================================================
PRISM_DB_SCHEMA = """
数据库：Prism 主库（SQLite 或 MySQL）

核心表：
1. file_records（内容/素材表）
   - id INTEGER PRIMARY KEY
   - filename TEXT          文件名
   - title TEXT            标题
   - description TEXT      描述
   - tags TEXT             标签
   - upload_time DATETIME  上传时间
   - published_at DATETIME 发布时间
   - status TEXT           状态 (pending/published/failed)
   - ai_title TEXT         AI 生成标题
   - ai_description TEXT   AI 生成描述
   - ai_tags TEXT          AI 生成标签
   - ai_generated_at TIMESTAMP

2. ai_model_configs（AI 模型配置）
   - id INTEGER PRIMARY KEY
   - service_type TEXT     服务类型 (chat/image/whisper)
   - provider TEXT         提供商
   - api_key TEXT          API Key（加密）
   - base_url TEXT         API 端点
   - model_name TEXT       模型名
   - is_active INTEGER     是否启用
   - created_at TIMESTAMP
   - updated_at TIMESTAMP

3. publish_tasks（发布任务表）— 若存在
   - id INTEGER PRIMARY KEY
   - article_id INTEGER    关联文章
   - platform TEXT         平台
   - account_name TEXT     账号名
   - status TEXT           pending/running/success/failed
   - scheduled_at DATETIME 计划发布
   - published_at DATETIME 实际发布
   - error_msg TEXT        错误信息
   - result_url TEXT       结果 URL
   - created_at DATETIME

4. hot_topics（热点话题）— 若存在
   - id INTEGER PRIMARY KEY
   - title TEXT
   - source TEXT           来源平台
   - heat_score FLOAT      热度
   - fetched_at DATETIME
"""

CHART_RULES = """
根据查询结果数据特征，建议以下可视化类型：
- 单个数值 → stat_card（数字卡片）
- 两列数据（类别+数值）且类别≤8 → bar（柱状图）
- 两列数据且类别>8 → table（表格）
- 时间序列（日期+数值）→ line（折线图）
- 占比数据（类别+百分比）且类别≤6 → pie（饼图）
- 多列数据 → table
- 对比两组数据 → bar_grouped（分组柱状图）
"""


# ============================================================
# NL Query Engine
# ============================================================
class NLQueryEngine:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if api_key:
            self.api_key = api_key
            self.api_base = api_base
            self.model = model or "deepseek-v4-flash"
        else:
            from fusion_ai.provider_registry import detect_provider
            cfg = detect_provider()
            self.api_key = cfg.get("api_key")
            self.api_base = cfg.get("base_url")
            self.model = cfg.get("model", "deepseek-v4-flash")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            kwargs = {"api_key": self.api_key}
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = OpenAI(**kwargs)
        return self._client

    def _nl_to_sql(self, question: str) -> Dict[str, Any]:
        system_prompt = f"""你是数据分析助手，将自然语言问题转换为精确的 SQL 查询。

{PRISM_DB_SCHEMA}

{CHART_RULES}

重要规则：
1. 只能使用 SELECT，禁止 INSERT/UPDATE/DELETE/DROP 等修改操作
2. 时间用 SQLite datetime() 函数，如 datetime('now', '-30 days')
3. 表可能不存在，返回 sql 为空字符串
4. 字段别名用中文（如 COUNT(*) AS 数量）
5. 只允许查询 file_records / ai_model_configs / publish_tasks / hot_topics
6. 成功率：ROUND(SUM(CASE WHEN status='success' THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1)

输出 JSON（不要任何其他文字）：
{{
  "sql": "SELECT ...",
  "explanation": "查询含义",
  "chart_type": "bar|line|pie|table|stat_card|bar_grouped",
  "chart_title": "图表标题",
  "x_field": "X 轴字段",
  "y_field": "Y 轴字段",
  "insight": "数据洞察"
}}"""
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"问题：{question}"},
                ],
                temperature=0.1,
                max_tokens=1000,
            )
            raw = resp.choices[0].message.content.strip()
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                return json.loads(m.group())
            return {"sql": "", "explanation": "解析失败", "chart_type": "table"}
        except Exception as e:
            logger.error(f"NL→SQL 失败: {e}")
            raise

    def _execute_sql(self, sql: str) -> Tuple[List[str], List[List[Any]]]:
        if not sql or not sql.strip():
            return [], []

        sql_clean = sql.strip().upper()
        if not sql_clean.startswith("SELECT"):
            raise ValueError("只允许 SELECT 查询")
        dangerous = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE"]
        for kw in dangerous:
            if kw in sql_clean:
                raise ValueError(f"禁止关键字: {kw}")

        # 使用 SQLite 直接连接主库（如果 prism 用的是 SQLite）
        # 简化处理：默认用 SQLite 的 media_ops.db（CAP 沿用）
        # 生产环境应接入 Prism 主库连接池
        import sqlite3
        db_path = self._get_db_path()
        if not db_path.exists():
            return [], []

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return columns, [list(r) for r in rows]
        finally:
            conn.close()

    def _get_db_path(self) -> Path:
        if _QUERY_SOURCE == "fusion":
            return _DATA_DIR / "fusion_data.db"
        # 尝试使用 Prism 主库
        try:
            from fastapi_app.core.config import settings
            return Path(settings.DATABASE_PATH)
        except Exception:
            return _DATA_DIR / "media_ops.db"

    def query(self, question: str) -> Dict[str, Any]:
        """主入口：自然语言 → SQL → 结果"""
        if not question.strip():
            return {"error": "问题不能为空"}

        # Step 1: NL → SQL
        sql_info = self._nl_to_sql(question)
        sql = sql_info.get("sql", "")

        # Step 2: 执行
        if sql:
            columns, rows = self._execute_sql(sql)
        else:
            columns, rows = [], []

        # Step 3: 格式化
        total = len(rows)
        return {
            "question": question,
            "sql": sql,
            "explanation": sql_info.get("explanation", ""),
            "chart_type": sql_info.get("chart_type", "table"),
            "chart_title": sql_info.get("chart_title", question),
            "x_field": sql_info.get("x_field", ""),
            "y_field": sql_info.get("y_field", ""),
            "insight": sql_info.get("insight", ""),
            "columns": columns,
            "rows": rows,
            "total_rows": total,
            "data": [dict(zip(columns, row)) for row in rows],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def list_presets(self) -> List[Dict[str, Any]]:
        return list(PRESET_QUESTIONS)


def get_engine() -> NLQueryEngine:
    """返回全局引擎实例"""
    return NLQueryEngine()