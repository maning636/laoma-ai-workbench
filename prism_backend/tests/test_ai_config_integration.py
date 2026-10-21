import sqlite3
import sys
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.append(str(_BASE_DIR))

# 必须先 import settings（用于确定 get_ai_config 实际读取的 DB 路径），
# 再 import get_ai_config，保证两侧 settings 走同一份初始化状态。
from fastapi_app.core.config import settings
from fastapi_app.api.v1.ai.router import get_ai_config

# 测试必须使用**隔离库**，绝不写入开发者真实配置库 <repo>/data/db/database.db。
#
# get_ai_config 在**调用时**读取 settings.DATABASE_PATH
# （见 prism_backend/fastapi_app/api/v1/ai/router.py:74 `sqlite3.connect(settings.DATABASE_PATH)`），
# 所以只要在 import 之后覆盖 settings.DATABASE_PATH，被测代码与测试数据就指向同一个库，
# 既能读到测试数据，又不会污染真实配置。
#
# 早期版本曾把 DB_PATH 直接设成 settings.DATABASE_PATH（真实库），
# 导致跑一次 pytest 就会把开发者的 chat / cover_generation / function_calling
# 三条 AI 配置 DELETE 掉并替换成 sk-test-* 占位值 —— 不可接受。
TEST_DB_PATH = str(_BASE_DIR / "db" / "database.db")
settings.DATABASE_PATH = TEST_DB_PATH
DB_PATH = TEST_DB_PATH

# ai_model_configs 表结构（与 prism_backend/fastapi_app/db/schema.py 中定义一致）。
# 用于首次运行测试时自建表 —— 老 DB 若尚未被 app 启动过则缺表，
# setup_test_db 需要能独立把测试跑通，不能依赖 __main__ 分支或应用启动副作用。
_AI_MODEL_CONFIGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS ai_model_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service_type TEXT NOT NULL UNIQUE,
        provider TEXT NOT NULL,
        api_key TEXT NOT NULL,
        base_url TEXT,
        model_name TEXT,
        extra_config TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""


def setup_test_db():
    """准备 ai_model_configs 测试数据。

    幂等设计：
    - CREATE TABLE IF NOT EXISTS：重复调用不会报 duplicate table。
    - DELETE 后再 INSERT：即使上一轮已经写过 3 行，本次先删再插，
      UNIQUE(service_type) 约束不会触发冲突。

    因此本函数既可在 pytest 收集时（模块导入副作用）被调用一次，
    也可在 `python test_ai_config_integration.py` 的 __main__ 分支被调用一次，
    两条路径相互不冲突。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(_AI_MODEL_CONFIGS_SCHEMA)
    cursor.execute(
        "DELETE FROM ai_model_configs WHERE service_type IN "
        "('chat', 'cover_generation', 'function_calling')"
    )
    cursor.execute(
        """
        INSERT INTO ai_model_configs (service_type, provider, api_key, base_url, model_name, is_active)
        VALUES
        ('chat', 'siliconflow', 'sk-test-chat-key', 'https://api.siliconflow.cn/v1', 'deepseek-ai/DeepSeek-V2.5', 1),
        ('cover_generation', 'volcengine', 'sk-test-cover-key', NULL, 'jimeng-4.0', 1),
        ('function_calling', 'openai', 'sk-test-func-key', 'https://api.openai.com/v1', 'gpt-4o', 1)
        """
    )
    conn.commit()
    conn.close()
    print(f"Inserted test data into ai_model_configs (db={DB_PATH})")


# 模块导入即准备测试数据 —— pytest 收集路径不依赖 __main__ 分支。
# __main__ 分支若再调一次也安全（幂等，见 setup_test_db 的说明）。
setup_test_db()


def test_get_ai_config():
    print("\n--- Test get_ai_config ---")
    config = get_ai_config("cover_generation")
    if config:
        print(f"Loaded cover config: provider={config['provider']}, model={config.get('model_name')}")
        assert config["provider"] == "volcengine"
        assert config["api_key"] == "sk-test-cover-key"
    else:
        raise AssertionError("cover_generation config not found")


def test_get_ai_config_chat():
    print("\n--- Test get_ai_config(chat) ---")
    config = get_ai_config("chat")
    if config:
        print(f"Loaded chat config: provider={config['provider']}, model={config.get('model_name')}")
        assert config["provider"] == "siliconflow"
        assert config["api_key"] == "sk-test-chat-key"
        assert config["base_url"] == "https://api.siliconflow.cn/v1"
        assert config.get("model_name") == "deepseek-ai/DeepSeek-V2.5"
    else:
        raise AssertionError("chat config not found")


def test_openclaw_agent_config():
    """同步用例。

    历史版本该函数是 `async def` 但内部没有任何 `await`，纯 sqlite3 查询。
    在 prismenv 里未安装 pytest-asyncio 时 pytest 会报
    "async def functions are not natively supported"。
    改成同步 `def` 与旧的 asyncio.run() 语义等价，且不需要新增任何依赖。
    """
    print("\n--- Test OpenClaw agent config ---")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM ai_model_configs WHERE service_type = 'function_calling' AND is_active = 1"
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise AssertionError("Function-calling config not found")

    db_config = dict(row)
    print("Loaded function-calling config:")
    print(f"  Provider: {db_config['provider']}")
    print(f"  Model: {db_config.get('model_name')}")
    print(f"  API Key: {db_config['api_key'][:10]}...")
    assert db_config["provider"] == "openai"
    assert db_config["api_key"] == "sk-test-func-key"


if __name__ == "__main__":
    # 脚本式运行路径：模块导入时 setup_test_db 已经跑过一次，此处再调一次
    # 是幂等的（DELETE+INSERT），保持与旧版本行为一致，不影响 pytest 收集路径。
    setup_test_db()
    test_get_ai_config()
    test_get_ai_config_chat()
    test_openclaw_agent_config()
    print("\nALL TESTS PASSED")

