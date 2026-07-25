#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化任务状态机。

状态流转面向 Streamlit 轮询：pipeline 写文件，UI 只读 status/progress。

两种业务模式：
- subtitle（默认，仿 VideoLingo）：asr → translate → burn → completed
- narration（解说文案工厂）：asr → … → packaging → completed
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Optional, Tuple


# 终端态
TERMINAL_STATUSES = frozenset({"completed", "cancelled"})

# 解说工厂完整步骤
NARRATION_STEPS: Tuple[str, ...] = (
    "asr",
    "translate",
    "digest",
    "copy",
    "match",
    "tts",
    "render",
    "packaging",
)

# 字幕本地化轻路径（VideoLingo 风格）
SUBTITLE_STEPS: Tuple[str, ...] = (
    "asr",
    "translate",
    "burn",
)

# 兼容旧代码：默认指解说步骤全集；真正跑流水线时按 mode 选
PIPELINE_STEPS: Tuple[str, ...] = NARRATION_STEPS

ALL_PIPELINE_STEPS: Tuple[str, ...] = tuple(
    dict.fromkeys(list(NARRATION_STEPS) + list(SUBTITLE_STEPS))
)


def steps_for_mode(mode: str) -> Tuple[str, ...]:
    mode = (mode or "subtitle").strip().lower()
    if mode == "narration":
        return NARRATION_STEPS
    return SUBTITLE_STEPS


def _running(step: str) -> str:
    return f"{step}_running"


def _done(step: str) -> str:
    return f"{step}_done"


# 合法边：from -> frozenset(to)
# queued 允许直接进入任意步骤的 running，便于失败后从中途步重试
_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "draft": frozenset({"queued", "cancelled"}),
    "queued": frozenset(
        {_running(step) for step in ALL_PIPELINE_STEPS} | {"cancelled", "failed"}
    ),
}

for i, step in enumerate(NARRATION_STEPS):
    running = _running(step)
    done = _done(step)
    _TRANSITIONS[running] = frozenset({done, "failed", "cancelled"})
    if i + 1 < len(NARRATION_STEPS):
        next_running = _running(NARRATION_STEPS[i + 1])
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
        elif step == "translate":
            # 字幕模式：translate 后可进 burn；解说模式：进 digest
            _TRANSITIONS[done] = frozenset(
                {
                    running,
                    next_running,
                    _running("burn"),
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

# burn 步骤（字幕本地化）
_TRANSITIONS[_running("burn")] = frozenset({_done("burn"), "failed", "cancelled"})
_TRANSITIONS[_done("burn")] = frozenset(
    {"completed", _running("burn"), "failed", "cancelled"}
)

_TRANSITIONS["completed"] = frozenset(
    {
        _running("tts"),  # 换音色重跑
        _running("render"),
        _running("packaging"),
        _running("burn"),  # 重烧字幕
        "cancelled",
    }
)
_TRANSITIONS["failed"] = frozenset(
    {_running(step) for step in ALL_PIPELINE_STEPS} | {"queued", "cancelled", "draft"}
)
_TRANSITIONS["cancelled"] = frozenset({"draft", "queued"})


# 进度粗映射
_PROGRESS: Dict[str, int] = {
    "draft": 0,
    "queued": 2,
    "asr_running": 10,
    "asr_done": 25,
    "translate_running": 40,
    "translate_done": 55,
    # 字幕模式
    "burn_running": 75,
    "burn_done": 95,
    # 解说模式
    "digest_running": 45,
    "digest_done": 50,
    "copy_running": 55,
    "copy_done": 60,
    "match_running": 68,
    "match_done": 75,
    "tts_running": 82,
    "tts_done": 88,
    "render_running": 93,
    "render_done": 96,
    "packaging_running": 98,
    "packaging_done": 99,
    "completed": 100,
    "failed": -1,
    "cancelled": 0,
}


HUMAN_GATES: Dict[str, str] = {
    "translate_done": "可改源/目标字幕后重跑翻译，或继续烧字幕 / 摘要",
    "copy_done": "必经审核点：修改解说文案后继续匹配",
    "match_done": "可改片段 narration/OST 后重跑 TTS/成片",
    "burn_done": "字幕成片已生成，可重烧或导出",
    "completed": "可重导出 / 重烧字幕 / 换音色只重跑 tts+render",
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


def next_running_after(done_status: str, mode: str = "subtitle") -> Optional[str]:
    """给定 *_done 状态，返回下一步 *_running（按模式）。"""
    done_status = normalize_status(done_status)
    if not done_status.endswith("_done"):
        return None
    step = done_status[: -len("_done")]
    steps = steps_for_mode(mode)
    try:
        idx = steps.index(step)
    except ValueError:
        return None
    if idx + 1 >= len(steps):
        # 最后一步 done → completed
        return "completed"
    return _running(steps[idx + 1])


def retry_running_for_failed_step(step: Optional[str]) -> str:
    if step and step in ALL_PIPELINE_STEPS:
        return _running(step)
    return "queued"


def all_statuses() -> Iterable[str]:
    return sorted(_TRANSITIONS.keys())
