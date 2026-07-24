#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化任务状态机。

状态流转面向 Streamlit 轮询：pipeline 写文件，UI 只读 status/progress。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Optional, Tuple


# 终端态
TERMINAL_STATUSES = frozenset({"completed", "cancelled"})

# 有序步骤（不含 draft/queued/failed/cancelled）
PIPELINE_STEPS: Tuple[str, ...] = (
    "asr",
    "translate",
    "digest",
    "copy",
    "match",
    "tts",
    "render",
    "packaging",
)


def _running(step: str) -> str:
    return f"{step}_running"


def _done(step: str) -> str:
    return f"{step}_done"


# 合法边：from -> frozenset(to)
_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "draft": frozenset({"queued", "cancelled"}),
    "queued": frozenset({_running("asr"), "cancelled", "failed"}),
}

for i, step in enumerate(PIPELINE_STEPS):
    running = _running(step)
    done = _done(step)
    _TRANSITIONS[running] = frozenset({done, "failed", "cancelled"})
    if i + 1 < len(PIPELINE_STEPS):
        next_running = _running(PIPELINE_STEPS[i + 1])
        # packaging_done 后进入 completed；其余 done 可进入下一步或人工卡点后重跑本步
        if step == "copy":
            # copy_done 是强制人工审核点：可重跑 copy，或继续 match
            _TRANSITIONS[done] = frozenset(
                {running, next_running, "failed", "cancelled"}
            )
        elif step == "match":
            _TRANSITIONS[done] = frozenset(
                {
                    running,
                    next_running,
                    _running("tts"),
                    "failed",
                    "cancelled",
                }
            )
        else:
            _TRANSITIONS[done] = frozenset(
                {running, next_running, "failed", "cancelled"}
            )
    else:
        # packaging_done
        _TRANSITIONS[done] = frozenset({"completed", "failed", "cancelled", running})

_TRANSITIONS["completed"] = frozenset(
    {
        _running("tts"),  # 换音色重跑
        _running("render"),
        _running("packaging"),
        "cancelled",
    }
)
_TRANSITIONS["failed"] = frozenset(
    {_running(step) for step in PIPELINE_STEPS} | {"queued", "cancelled", "draft"}
)
_TRANSITIONS["cancelled"] = frozenset({"draft", "queued"})


# 进度粗映射
_PROGRESS: Dict[str, int] = {
    "draft": 0,
    "queued": 2,
    "asr_running": 8,
    "asr_done": 15,
    "translate_running": 20,
    "translate_done": 28,
    "digest_running": 35,
    "digest_done": 42,
    "copy_running": 50,
    "copy_done": 55,
    "match_running": 62,
    "match_done": 70,
    "tts_running": 78,
    "tts_done": 85,
    "render_running": 90,
    "render_done": 95,
    "packaging_running": 97,
    "packaging_done": 99,
    "completed": 100,
    "failed": -1,
    "cancelled": 0,
}


HUMAN_GATES: Dict[str, str] = {
    "translate_done": "可改源/目标字幕后重跑翻译或继续摘要",
    "copy_done": "必经审核点：修改解说文案后继续匹配",
    "match_done": "可改片段 narration/OST 后重跑 TTS/成片",
    "completed": "可重导出或换音色只重跑 tts+render",
}


class InvalidTransitionError(ValueError):
    """非法状态迁移"""


@dataclass(frozen=True)
class TransitionResult:
    status: str
    step: Optional[str]
    progress: int


def normalize_status(status: str) -> str:
    return (status or "").strip().lower()


def step_of(status: str) -> Optional[str]:
    status = normalize_status(status)
    if status.endswith("_running") or status.endswith("_done"):
        return status.rsplit("_", 1)[0]
    if status in {"draft", "queued", "completed", "failed", "cancelled"}:
        return None
    return None


def progress_of(status: str) -> int:
    status = normalize_status(status)
    return _PROGRESS.get(status, 0)


def can_transition(current: str, target: str) -> bool:
    current = normalize_status(current)
    target = normalize_status(target)
    if current == target:
        return True
    allowed = _TRANSITIONS.get(current)
    if not allowed:
        return False
    return target in allowed


def assert_transition(current: str, target: str) -> TransitionResult:
    current = normalize_status(current)
    target = normalize_status(target)
    if not can_transition(current, target):
        raise InvalidTransitionError(f"illegal transition: {current} -> {target}")
    return TransitionResult(
        status=target,
        step=step_of(target),
        progress=progress_of(target),
    )


def next_running_after(done_status: str) -> Optional[str]:
    """给定 *_done 状态，返回下一步 *_running。"""
    done_status = normalize_status(done_status)
    if not done_status.endswith("_done"):
        return None
    step = done_status[: -len("_done")]
    try:
        idx = PIPELINE_STEPS.index(step)
    except ValueError:
        return None
    if idx + 1 >= len(PIPELINE_STEPS):
        return "completed" if step == "packaging" else None
    return _running(PIPELINE_STEPS[idx + 1])


def retry_running_for_failed_step(step: Optional[str]) -> str:
    if step and step in PIPELINE_STEPS:
        return _running(step)
    return "queued"


def all_statuses() -> Iterable[str]:
    return sorted(_TRANSITIONS.keys())
