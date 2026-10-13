"""
各平台登录态统一检查（Phase 1.6）

- PlatformLoginChecker: 统一入口，按平台分发到具体检查器
- 每个平台检查器实现 check_login(cookie_path, browser_context=None) -> LoginCheckResult
- 接入 Phase 0.4 账号健康监控
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from fastapi_app.core.config import settings
from fastapi_app.core.logger import logger
from fastapi_app.core.timezone_utils import now_beijing_iso


class LoginStatus(str, Enum):
    VALID = "valid"
    EXPIRED = "expired"
    LOGIN_REQUIRED = "login_required"
    ERROR = "error"
    UNKNOWN = "unknown"


class LoginCheckResult(BaseModel):
    account_id: str = ""
    platform: int = 0
    platform_name: str = ""
    status: LoginStatus = LoginStatus.UNKNOWN
    checked_at: str = Field(default_factory=now_beijing_iso)
    message: str = ""
    cookie_file: str = ""
    expires_in_seconds: Optional[int] = None
    error: Optional[str] = None


class PlatformLoginChecker:
    """统一登录态检查器"""

    def __init__(self):
        self._checkers = {}  # platform_name -> checker_function
        self._register_defaults()

    def _register_defaults(self) -> None:
        self._checkers["douyin"] = self._check_douyin
        self._checkers["kuaishou"] = self._check_kuaishou
        self._checkers["xiaohongshu"] = self._check_xiaohongshu
        self._checkers["bilibili"] = self._check_bilibili
        self._checkers["channels"] = self._check_channels
        self._checkers["tencent"] = self._check_channels
        self._checkers["baijiahao"] = self._check_baijiahao

    def check_login(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        """统一入口：检查指定账号的登录态"""
        checker = self._checkers.get(platform_name)
        if not checker:
            return LoginCheckResult(
                account_id=account_id, platform=platform, platform_name=platform_name,
                status=LoginStatus.UNKNOWN, message=f"平台 {platform_name} 无登录检查器",
            )
        try:
            result = checker(account_id, platform, platform_name, cookie_file)
        except Exception as e:
            logger.warning(f"[LoginCheck] {account_id} ({platform_name}) 检查异常: {e}")
            result = LoginCheckResult(
                account_id=account_id, platform=platform, platform_name=platform_name,
                status=LoginStatus.ERROR, message=str(e), error=str(e),
            )
        return result

    def check_all_accounts(self, accounts: list[dict]) -> list[LoginCheckResult]:
        """批量检查所有账号的登录态"""
        results = []
        for acc in accounts:
            aid = acc.get("account_id", "")
            plat = acc.get("platform", 0)
            pname = acc.get("platform_name", "")
            cfile = acc.get("cookie_file", "")
            results.append(self.check_login(aid, plat, pname, cfile))
        logger.info(f"[LoginCheck] 批量检查完成: {len(results)} 个账号")
        return results

    def _check_douyin(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        """抖音登录态检查"""
        return _file_based_check(account_id, platform, platform_name, cookie_file,
                                  required_cookies=["sessionid", "passport_csrf_token"],
                                  cookie_paths=settings.COOKIE_FILES_DIR)

    def _check_kuaishou(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        return _file_based_check(account_id, platform, platform_name, cookie_file,
                                  required_cookies=["kuaishou.web.s", "did"],
                                  cookie_paths=settings.COOKIE_FILES_DIR)

    def _check_xiaohongshu(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        return _file_based_check(account_id, platform, platform_name, cookie_file,
                                  required_cookies=["web_session", "a1", "webId"],
                                  cookie_paths=settings.COOKIE_FILES_DIR)

    def _check_bilibili(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        return _file_based_check(account_id, platform, platform_name, cookie_file,
                                  required_cookies=["SESSDATA", "bili_jct", "DedeUserID"],
                                  cookie_paths=settings.COOKIE_FILES_DIR)

    def _check_channels(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        return _file_based_check(account_id, platform, platform_name, cookie_file,
                                  required_cookies=["_wxuin", "uin", "qzone_sig", "wxuin", "wxuin_sig"],
                                  cookie_paths=settings.COOKIE_FILES_DIR)

    def _check_baijiahao(self, account_id: str, platform: int, platform_name: str, cookie_file: str = "") -> LoginCheckResult:
        return _file_based_check(account_id, platform, platform_name, cookie_file,
                                  required_cookies=["BAIDUID", "BAIDUID_BFESS"],
                                  cookie_paths=settings.COOKIE_FILES_DIR)


def _file_based_check(account_id: str, platform: int, platform_name: str, cookie_file: str,
                      required_cookies: list[str], cookie_paths: str) -> LoginCheckResult:
    """基于 cookie 文件的通用登录态检查"""
    import os
    from pathlib import Path

    result = LoginCheckResult(account_id=account_id, platform=platform, platform_name=platform_name)

    # 找到 cookie 文件
    if cookie_file:
        cpath = Path(cookie_file)
    else:
        base = Path(cookie_paths) / platform_name
        if base.exists():
            candidates = list(base.iterdir())
            cpath = candidates[0] if candidates else None
        else:
            cpath = None

    if not cpath or not cpath.exists():
        return LoginCheckResult(account_id=account_id, platform=platform, platform_name=platform_name,
                                status=LoginStatus.LOGIN_REQUIRED, message="Cookie 文件不存在",
                                cookie_file=str(cpath) if cpath else "")

    result.cookie_file = str(cpath)

    # 读取 cookie 并检查关键字段
    try:
        cookie_data = _read_cookies(cpath)
        missing = []
        for req in required_cookies:
            if not cookie_data.get(req):
                missing.append(req)

        if missing:
            return LoginCheckResult(account_id=account_id, platform=platform, platform_name=platform_name,
                                    status=LoginStatus.EXPIRED, message=f"Cookie 关键字段缺失: {missing}",
                                    cookie_file=str(cpath))

        # 检查过期时间
        for req in required_cookies:
            expires = cookie_data.get(f"{req}__expires", "")
            if expires:
                try:
                    from datetime import datetime
                    exp_dt = datetime.fromisoformat(str(expires))
                    now = datetime.now()
                    diff = (exp_dt - now).total_seconds()
                    if diff < 0:
                        return LoginCheckResult(account_id=account_id, platform=platform,
                                                platform_name=platform_name,
                                                status=LoginStatus.EXPIRED,
                                                message=f"Cookie {req} 已过期",
                                                cookie_file=str(cpath), expires_in_seconds=0)
                    result.expires_in_seconds = int(diff)
                except Exception:
                    pass

        return LoginCheckResult(account_id=account_id, platform=platform, platform_name=platform_name,
                                status=LoginStatus.VALID, message="登录态有效",
                                cookie_file=str(cpath), expires_in_seconds=result.expires_in_seconds)

    except Exception as e:
        return LoginCheckResult(account_id=account_id, platform=platform, platform_name=platform_name,
                                status=LoginStatus.ERROR, message=str(e), error=str(e),
                                cookie_file=str(cpath))


def _read_cookies(path) -> dict:
    """读取 cookie 文件（支持 JSON 和 Netscape 格式）"""
    import json
    from pathlib import Path

    content = Path(path).read_text(encoding="utf-8")

    # 尝试 JSON 格式
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return {c.get("name", ""): c for c in data}
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # Netscape cookies.txt 格式
    cookies = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            name = parts[5]
            value = parts[6]
            cookies[name] = value
            # 保存过期时间
            if len(parts) >= 10 and parts[9] and parts[9].isdigit():
                cookies[f"{name}__expires"] = _unix_to_iso(int(parts[9]))

    return cookies


def _unix_to_iso(ts: int) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)


platform_login_checker = PlatformLoginChecker()
