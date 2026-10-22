"""只读模式守卫(D4):注册码过期且宽限期满 → 写操作拦截,读操作放行。

用法(在写路由上加一个依赖):

    from fastapi_app.api.v1.license.guard import require_write_allowed

    @router.post("/campaigns", ...)
    async def create_campaign(
        request: Request,
        _guard: None = Depends(require_write_allowed),
    ):
        ...

语义要点:
  - **从未有过注册码** → 不是只读(社区版照常用)。D4 的"到期只读"针对的是
    "曾经是 Pro、现在到期了"的用户,不是把社区版也锁成只读。
  - **宽限期内** → 仍可写(只是提示即将到期)。
  - **过期且宽限期满** → 写操作 403,读操作不受影响。
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from fastapi_app.core.license import load_license


def read_only_state() -> tuple[bool, str]:
    """返回 (是否只读, 原因说明)。"""
    state = load_license()
    if state.read_only:
        return True, state.message or "注册码已过期,当前为只读模式"
    return False, state.message


async def require_write_allowed(request: Request) -> None:
    """写操作守卫。只读模式下抛 403。"""
    read_only, message = read_only_state()
    if read_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason": "license_expired_read_only",
                "message": message,
                "readOnly": True,
                "upgrade": "请续费注册码以继续新增内容",
            },
        )


__all__ = ["require_write_allowed", "read_only_state"]
