"""Phase 0.2 · 幂等任务状态机 —— 盘点既有实现 + 补缺口。

覆盖（对齐 PLAN_verification_measures.md · Phase 0.2 验收标准）：
  1. 状态枚举完整性：draft/awaiting_review/approved/scheduled/queued/running/
     succeeded/failed_retryable/failed_final/cancelled 全部可实例化，值集合固定
  2. 状态转换合法性矩阵：穷举 10×10=100 对（PLAN 文本写 9 态，实际列 10 名字；
     以现有枚举为准），合法集合写死在测试里作为契约：
       - 合法路径 transition_state() 返回目标态
       - 非法路径 transition_state() 抛 InvalidTransition
       - can_transition() 谓词与矩阵一致
  3. 幂等键格式稳定：campaign:{c}:variant:{v}:account:{a}
     - 相同输入 → 相同 key
     - 任一组成部分不同 → 不同 key
     - fallback: video:{hash}:account:{a}
  4. failed_retryable → running 重入：
     - task_id 不变、attempt + 1、状态变为 running
  5. 旧状态名映射：processing / success / failed / pending / retryable
     等旧名自动映射到新枚举；未识别名抛 ValueError

约定：
  - 本文件不启 DB（状态机核心逻辑纯函数，持久化在既有代码里）；
  - 契约测试写死在测试里：合法集合以 VALID_TRANSITIONS 当前实现为基线，
    补 InvalidTransition / retry_task / LEGACY_STATUS_MAP 缺口后仍然成立。

用法：
  cd prism_backend && python -m pytest tests/test_phase02_task_state.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from itertools import product

os.environ.setdefault("FEATURE_FLAGS_DISABLED", "1")

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from prism_core.task_state_machine import (
    TaskStatus,
    VALID_TRANSITIONS,
    can_transition,
    transition_state,
    build_idempotency_key,
)


# ──────────────────────────────────────────────────────────────
# 常量：Phase 0.2 契约（写死在测试里作为验收基线）
# ──────────────────────────────────────────────────────────────

EXPECTED_STATUS_VALUES = {
    "draft",
    "awaiting_review",
    "approved",
    "scheduled",
    "queued",
    "running",
    "succeeded",
    "failed_retryable",
    "failed_final",
    "cancelled",
}

# 合法转换集合（frozenset 契约，PLAN 验收：矩阵 100% 通过）
LEGAL_TRANSITIONS: set = {
    (TaskStatus.DRAFT, TaskStatus.AWAITING_REVIEW),
    (TaskStatus.DRAFT, TaskStatus.APPROVED),
    (TaskStatus.DRAFT, TaskStatus.CANCELLED),
    (TaskStatus.AWAITING_REVIEW, TaskStatus.APPROVED),
    (TaskStatus.AWAITING_REVIEW, TaskStatus.CANCELLED),
    (TaskStatus.AWAITING_REVIEW, TaskStatus.DRAFT),
    (TaskStatus.APPROVED, TaskStatus.SCHEDULED),
    (TaskStatus.APPROVED, TaskStatus.QUEUED),
    (TaskStatus.APPROVED, TaskStatus.CANCELLED),
    (TaskStatus.SCHEDULED, TaskStatus.QUEUED),
    (TaskStatus.SCHEDULED, TaskStatus.CANCELLED),
    (TaskStatus.QUEUED, TaskStatus.RUNNING),
    (TaskStatus.QUEUED, TaskStatus.CANCELLED),
    (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
    (TaskStatus.RUNNING, TaskStatus.FAILED_RETRYABLE),
    (TaskStatus.RUNNING, TaskStatus.FAILED_FINAL),
    (TaskStatus.FAILED_RETRYABLE, TaskStatus.RUNNING),
    (TaskStatus.FAILED_RETRYABLE, TaskStatus.FAILED_FINAL),
    (TaskStatus.FAILED_RETRYABLE, TaskStatus.CANCELLED),
}

# 旧状态名 → 新枚举（PLAN 验收：processing 等旧名自动映射）
LEGACY_MAP_EXPECTED = {
    "processing": TaskStatus.RUNNING,
    "success": TaskStatus.SUCCEEDED,
    "success": TaskStatus.SUCCEEDED,
    "done": TaskStatus.SUCCEEDED,
    "completed": TaskStatus.SUCCEEDED,
    "failed": TaskStatus.FAILED_FINAL,
    "retryable": TaskStatus.FAILED_RETRYABLE,
    "pending": TaskStatus.DRAFT,
    "review": TaskStatus.AWAITING_REVIEW,
    "submit": TaskStatus.AWAITING_REVIEW,
    "cancel": TaskStatus.CANCELLED,
}


# ──────────────────────────────────────────────────────────────
# 1. 状态枚举完整性
# ──────────────────────────────────────────────────────────────

class TestStatusEnum:
    def test_all_expected_values_instantiable(self):
        """PLAN：9 态（实际 10 名字）全部可实例化，值集合恰为预期。"""
        for v in EXPECTED_STATUS_VALUES:
            TaskStatus(v)  # 不抛异常即可
        assert {s.value for s in TaskStatus} == EXPECTED_STATUS_VALUES

    def test_enum_member_count_matches_plan(self):
        """TaskStatus 有 10 个成员（PLAN 文本 9 态含 succeeded/failed_retryable/
        failed_final 三终态并列，实际命名 10 个，此处以现有实现为准）。"""
        assert len(list(TaskStatus)) == 10

    def test_status_is_str_enum(self):
        """TaskStatus 应为 str Enum，可 JSON 序列化。"""
        import enum
        assert issubclass(TaskStatus, enum.Enum)
        assert issubclass(TaskStatus, str)


# ──────────────────────────────────────────────────────────────
# 2. 转换合法性矩阵：穷举 10×10=100 对
# ──────────────────────────────────────────────────────────────

class TestTransitionMatrix:
    def test_valid_transitions_table_matches_contract(self):
        """实现里的 VALID_TRANSITIONS 展开后与写死契约完全一致。"""
        actual = {
            (cur, tgt)
            for cur, tgts in VALID_TRANSITIONS.items()
            for tgt in tgts
        }
        assert actual == LEGAL_TRANSITIONS, (
            f"VALID_TRANSITIONS 与契约不一致\n"
            f"  缺: {LEGAL_TRANSITIONS - actual}\n"
            f"  多: {actual - LEGAL_TRANSITIONS}"
        )

    def test_can_transition_predicate_matches_matrix(self):
        """can_transition() 对 100 对穷举结果与合法集合完全一致。"""
        mismatches = []
        for cur, tgt in product(TaskStatus, TaskStatus):
            expected = (cur, tgt) in LEGAL_TRANSITIONS
            actual = can_transition(cur, tgt)
            if actual != expected:
                mismatches.append((cur.value, tgt.value, expected, actual))
        assert not mismatches, f"can_transition 与契约不符: {mismatches}"

    @pytest.mark.parametrize(
        "src,tgt", sorted(LEGAL_TRANSITIONS, key=lambda t: (t[0].value, t[1].value))
    )
    def test_legal_transition_returns_target(self, src, tgt):
        """穷举合法路径：transition_state 返回目标态。"""
        result = transition_state(src, tgt)
        assert result is tgt or result == tgt

    def test_illegal_transition_raises_invalid_transition(self):
        """穷举非法路径：transition_state 抛 InvalidTransition。

        自环（same→same）视为非法（状态机不允许自旋），
        终态出边为非法，跨阶段跳跃为非法。
        """
        from prism_core.task_state_machine import InvalidTransition

        illegal = [
            (cur, tgt)
            for cur, tgt in product(TaskStatus, TaskStatus)
            if (cur, tgt) not in LEGAL_TRANSITIONS
        ]
        assert len(illegal) == 10 * 10 - len(LEGAL_TRANSITIONS)
        for cur, tgt in illegal:
            with pytest.raises(InvalidTransition):
                transition_state(cur, tgt)

    def test_terminal_states_have_no_outgoing_edges(self):
        """终态（succeeded / failed_final / cancelled）合法出边为空。"""
        for term in (TaskStatus.SUCCEEDED, TaskStatus.FAILED_FINAL, TaskStatus.CANCELLED):
            assert VALID_TRANSITIONS[term] == []
            assert can_transition(term, TaskStatus.DRAFT) is False


# ──────────────────────────────────────────────────────────────
# 3. 幂等键格式稳定
# ──────────────────────────────────────────────────────────────

class TestIdempotencyKey:
    def test_campaign_form_format(self):
        """PLAN：campaign:{cmp}:variant:{v}:account:{acc}。"""
        k = build_idempotency_key(
            campaign_id="cmp_001",
            variant_id="v_1",
            account_id="acc_7",
        )
        assert k == "campaign:cmp_001:variant:v_1:account:acc_7"

    def test_same_inputs_same_key(self):
        """PLAN：相同输入 → 相同 key（稳定幂等）。"""
        a = build_idempotency_key("cmp_001", "v_1", "acc_7")
        b = build_idempotency_key(campaign_id="cmp_001", variant_id="v_1", account_id="acc_7")
        assert a == b

    def test_different_campaign_yields_different_key(self):
        a = build_idempotency_key("cmp_A", "v_1", "acc_1")
        b = build_idempotency_key("cmp_B", "v_1", "acc_1")
        assert a != b

    def test_different_variant_yields_different_key(self):
        a = build_idempotency_key("cmp_1", "v_1", "acc_1")
        b = build_idempotency_key("cmp_1", "v_2", "acc_1")
        assert a != b

    def test_different_account_yields_different_key(self):
        a = build_idempotency_key("cmp_1", "v_1", "acc_A")
        b = build_idempotency_key("cmp_1", "v_1", "acc_B")
        assert a != b

    def test_video_fallback_format(self):
        """无 campaign/variant 时用 video:{hash}:account:{a}。"""
        k = build_idempotency_key(video_hash="abc123", account_id="acc_1")
        assert k == "video:abc123:account:acc_1"


# ──────────────────────────────────────────────────────────────
# 4. failed_retryable → running 重入
# ──────────────────────────────────────────────────────────────

class TestRetryReentry:
    def test_retry_increments_attempt_and_keeps_task_id(self):
        """PLAN：failed_retryable→running 重入 task_id 不变、attempt 递增。"""
        from prism_core.task_state_machine import TaskState, retry_task

        s = TaskState(
            task_id="task_retry_001",
            status=TaskStatus.FAILED_RETRYABLE,
            idempotency_key="campaign:c:variant:v:account:a",
            attempt=1,
            max_attempts=3,
        )
        retried = retry_task(s, error_message="upload timeout")

        # 契约：task_id 不变
        assert retried.task_id == "task_retry_001"
        # 契约：attempt + 1
        assert retried.attempt == 2
        # 契约：状态变为 running
        assert retried.status == TaskStatus.RUNNING
        # error_message 被清空（重试语义：新一次尝试）
        assert retried.error_message is None or retried.error_message == ""

    def test_retry_respects_max_attempts(self):
        """attempt 已达 max_attempts → 应转 failed_final（不循环重试）。"""
        from prism_core.task_state_machine import TaskState, retry_task

        s = TaskState(
            task_id="task_max",
            status=TaskStatus.FAILED_RETRYABLE,
            idempotency_key="k",
            attempt=3,
            max_attempts=3,
        )
        advanced = retry_task(s, error_message="again timeout")
        # attempt 已耗尽 → 转 failed_final
        assert advanced.status == TaskStatus.FAILED_FINAL

    def test_retry_rejects_non_retryable_source(self):
        """非 failed_retryable 状态调用 retry_task 应拒绝。"""
        from prism_core.task_state_machine import TaskState, retry_task

        s = TaskState(
            task_id="task_draft",
            status=TaskStatus.DRAFT,
            idempotency_key="k",
            attempt=1,
        )
        with pytest.raises(Exception):
            retry_task(s, error_message="x")


# ──────────────────────────────────────────────────────────────
# 5. 旧状态名映射
# ──────────────────────────────────────────────────────────────

class TestLegacyStatusMapping:
    def test_legacy_names_map_to_new_enum(self):
        """PLAN：processing 等旧名自动映射到新枚举。"""
        from prism_core.task_state_machine import TaskStatus, TaskState

        cases = {
            "processing": TaskStatus.RUNNING,
            "success": TaskStatus.SUCCEEDED,
            "done": TaskStatus.SUCCEEDED,
            "completed": TaskStatus.SUCCEEDED,
            "failed": TaskStatus.FAILED_FINAL,
            "retryable": TaskStatus.FAILED_RETRYABLE,
            "pending": TaskStatus.DRAFT,
            "review": TaskStatus.AWAITING_REVIEW,
            "cancel": TaskStatus.CANCELLED,
        }
        for legacy_name, expected in cases.items():
            st = TaskState(status=legacy_name)
            assert st.status == expected, f"{legacy_name} 未映射为 {expected.value}"

    def test_current_enum_names_pass_through(self):
        """新枚举名（值字符串）也直接可用，无歧义。"""
        from prism_core.task_state_machine import TaskState
        for v in EXPECTED_STATUS_VALUES:
            TaskState(status=v)  # 不抛

    def test_unknown_status_raises_valueerror(self):
        """未识别状态名 → ValueError（不静默）。"""
        from prism_core.task_state_machine import TaskState

        with pytest.raises(ValueError):
            TaskState(status="not_a_real_status")
