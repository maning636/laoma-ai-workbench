"""
Test configuration and fixtures
"""
import os

import pytest
import sqlite3
import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient

# -- 测试会话数据隔离（必须在 import fastapi_app 之前生效）--------------
# Settings 的 DATABASE_PATH / COOKIE_DB_PATH / AI_LOGS_DB_PATH 等默认值
# 在类定义（即 import fastapi_app.core.config 时）就被求值绑定，
# 之后再改环境变量已经来不及 -> 这段必须放在 fastapi_app 的 import 之前。
#
# 为什么要隔离：
#   1) 不污染开发机 / CI 检出目录里的真实数据目录（CI 会在 checkout 内落 data/）；
#   2) 让测试真正复现「全新安装」场景：空的 SQLite 库，
#      建表完全依赖应用启动时的 ensure_main_db_schema。
#
# 想指定落盘位置（别写 C 盘）就设 PRISM_TEST_DATA_DIR，例如：
#   PRISM_TEST_DATA_DIR=D:\cache\tmp\pytest_data
_TEST_DATA_DIR = (os.environ.get("PRISM_TEST_DATA_DIR") or "").strip()
if not _TEST_DATA_DIR:
    _TEST_DATA_DIR = tempfile.mkdtemp(prefix="prism-pytest-")
os.environ["LAOMA_DATA_DIR"] = _TEST_DATA_DIR

from fastapi_app.main import app
from fastapi_app.db.session import ConnectionPool


@pytest.fixture
def test_db():
    """Create a temporary test database"""
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = temp_db.name
    temp_db.close()

    # Initialize database schema
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create file_records table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filesize REAL NOT NULL,
            file_path TEXT NOT NULL,
            upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            published_at DATETIME,
            last_platform INTEGER,
            last_accounts TEXT,
            note TEXT,
            group_name TEXT
        )
    """)

    # Create accounts table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            platform_code INTEGER NOT NULL,
            name TEXT,
            status TEXT DEFAULT 'pending',
            cookie_file TEXT,
            last_checked DATETIME,
            avatar TEXT,
            original_name TEXT,
            note TEXT,
            user_id TEXT
        )
    """)

    # Insert test data
    cursor.execute("""
        INSERT INTO file_records (filename, filesize, file_path, status)
        VALUES ('test1.mp4', 10.5, 'test1.mp4', 'pending'),
               ('test2.mp4', 20.3, 'test2.mp4', 'published')
    """)

    cursor.execute("""
        INSERT INTO accounts (account_id, platform, platform_code, name, status, user_id)
        VALUES ('test-account-1', 'douyin', 3, 'Test User 1', 'valid', 'user123'),
               ('test-account-2', 'xiaohongshu', 1, 'Test User 2', 'error', 'user456')
    """)

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    # Windows 上 sqlite 句柄释放有延迟，直接 unlink 会报 WinError 32（文件被占用）；
    # POSIX 下首个 unlink 即成功。重试几次再放弃，别让清理失败盖掉真实断言结果。
    for _ in range(5):
        try:
            Path(db_path).unlink(missing_ok=True)
            break
        except PermissionError:
            time.sleep(0.2)


def _ensure_main_db_schema() -> None:
    """建出应用启动时保证存在的主库表结构。

    生产环境里这些表由 main.py 的 startup 事件调用 ensure_main_db_schema 建立。
    测试用的 TestClient 没有走 lifespan（不 with 就不会触发 startup），
    所以这里必须补上同样的前置条件 —— 否则空库下
    /api/v1/publish/stats、/api/v1/ai/model-configs 会因 "no such table" 返回 500。
    """
    from fastapi_app.db.schema import ensure_main_db_schema
    from fastapi_app.db.session import main_db_pool

    with main_db_pool.get_connection() as conn:
        ensure_main_db_schema(conn)


@pytest.fixture
def client():
    """Create test client"""
    _ensure_main_db_schema()
    return TestClient(app)


@pytest.fixture
def test_db_pool(test_db):
    """Create test database connection pool"""
    pool = ConnectionPool(test_db, pool_size=2)
    yield pool
    # 必须先关连接池，再让 test_db fixture 去删库文件：
    # 连接池里的 sqlite 句柄不释放时，Windows 上文件被锁住，unlink 直接失败。
    pool.close_all()
