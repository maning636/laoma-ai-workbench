"""
OTP验证码路由（FastAPI版）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
from pathlib import Path
from loguru import logger

# 添加platforms模块到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from platforms.verification import verification_manager

router = APIRouter(prefix="/verification", tags=["验证码"])


class SubmitCodeRequest(BaseModel):
    """提交验证码请求"""
    account_id: str
    code: str




@router.get("/otp-events")
async def list_otp_events():
    """
    列出当前待处理的验证码事件（前端轮询接口）。

    与 submit-code 配套：发布流程触发短信验证时，由
    platforms.verification.verification_manager 登记事件，前端轮询本接口取回，
    用户输入后调用 submit-code 回填。

    注意：使用 peek 而非 get_pending_events —— 后者取回即清空，
    会导致轮询方之间互相抢事件（前端轮询 + AI 工具 get_otp_events 同时取）。
    """
    events = verification_manager.peek_pending_events()
    return {
        "success": True,
        "data": {
            "events": events,
            "total": len(events),
        },
    }


@router.post("/submit-code")
async def submit_verification_code(request: SubmitCodeRequest):
    """
    提交验证码
    前端用户输入验证码后调用此接口
    """
    success = verification_manager.submit_code(
        account_id=request.account_id,
        code=request.code
    )

    if success:
        return {
            "success": True,
            "message": "验证码已提交"
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="提交验证码失败"
        )
