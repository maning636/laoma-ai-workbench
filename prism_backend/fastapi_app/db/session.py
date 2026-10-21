"""
数据库连接管理
"""
import sqlite3
import queue
import threading
from contextlib import contextmanager
from typing import Generator
from pathlib import Path
from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger


class ConnectionPool:
    """SQLite连接池"""

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self.pool = queue.Queue(maxsize=pool_size)
        self.lock = threading.Lock()

        # 确保数据库文件目录存在
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # 初始化连接池
        for _ in range(pool_size):
            conn = self._create_connection()
            self.pool.put(conn)

        logger.info(f"数据库连接池初始化完成: {db_path} (池大小: {pool_size})")

    def _create_connection(self) -> sqlite3.Connection:
        """创建新的数据库连接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # 支持字典访问
        return conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）"""
        conn = self.pool.get()
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作错误: {e}")
            raise
        finally:
            self.pool.put(conn)

    def close_all(self):
        """关闭所有连接"""
        while not self.pool.empty():
            conn = self.pool.get()
            conn.close()
        logger.info("数据库连接池已关闭")


# 创建全局连接池实例
main_db_pool = ConnectionPool(settings.DATABASE_PATH, pool_size=17)
cookie_db_pool = ConnectionPool(settings.COOKIE_DB_PATH, pool_size=17)
ai_logs_db_pool = ConnectionPool(settings.AI_LOGS_DB_PATH, pool_size=17)


# 依赖注入函数
def get_main_db() -> Generator[sqlite3.Connection, None, None]:
    """获取主数据库连接（依赖注入）"""
    with main_db_pool.get_connection() as conn:
        yield conn


def open_main_db() -> sqlite3.Connection:
    """打开一个独立的主数据库连接（业务层直连用，**非** FastAPI 依赖注入）。

    与 `get_main_db` 的区别：`get_main_db` 是 FastAPI 依赖注入用的生成器，只能以
    `Depends(get_main_db)` 形式使用；直接调用它拿到的是生成器对象而非连接
    （表现为 `AttributeError: 'generator' object has no attribute 'cursor'`）。
    业务层代码请统一使用本函数：

        conn = open_main_db()
        conn.execute(...)
        conn.commit()

    生命周期：CPython 引用计数会在局部变量离开作用域时自动关闭连接，
    调用方无需显式 close()（也不要跨函数长期持有）。
    """
    conn = sqlite3.connect(settings.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # 与连接池保持一致，支持字典访问
    return conn


def get_cookie_db() -> Generator[sqlite3.Connection, None, None]:
    """获取Cookie数据库连接（依赖注入）"""
    with cookie_db_pool.get_connection() as conn:
        yield conn


def get_ai_logs_db() -> Generator[sqlite3.Connection, None, None]:
    """获取AI日志数据库连接（依赖注入）"""
    with ai_logs_db_pool.get_connection() as conn:
        yield conn
