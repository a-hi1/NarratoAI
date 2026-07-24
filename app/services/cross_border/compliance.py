#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
合规与改造度粗分。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def estimate_original_audio_ratio(items: Optional[List[Dict[str, Any]]]) -> float:
    """按 timestamp 时长估算 OST=1 占比（0-100）。无法解析时返回 -1。"""
    if not items:
        return -1.0

    def _parse_ts(ts: str) -> float:
        # HH:MM:SS,mmm
        ts = ts.replace(".", ",")
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    total = 0.0
    ost1 = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("timestamp") or "")
        if "-" not in raw:
            continue
        start_s, end_s = raw.split("-", 1)
        try:
            dur = max(0.0, _parse_ts(end_s.strip()) - _parse_ts(start_s.strip()))
        except Exception:
            continue
        total += dur
        if int(item.get("OST", 0) or 0) == 1:
            ost1 += dur
    if total <= 0:
        return -1.0
    return round(100.0 * ost1 / total, 2)


def score_transform_level(
    *,
    narration_copy: str = "",
    items: Optional[List[Dict[str, Any]]] = None,
    target_original_ratio: float = 30.0,
    source_credit: bool = True,
) -> Dict[str, Any]:
    """
    粗分改造度，不做法务结论。

    level:
      low    — 高原片 + 文案很短/近似旁白贴片
      medium — 常见本地化解说
      high   — 文案重写明显 + 原片占比较低
    """
    ratio = estimate_original_audio_ratio(items)
    copy = (narration_copy or "").strip()
    # CJK 与英文混排：非空白字符近似
    copy_len = len([c for c in copy if not c.isspace()])

    rewrite_score = 0
    if copy_len >= 120:
        rewrite_score += 2
    elif copy_len >= 40:
        rewrite_score += 1

    ost_score = 0
    effective_ratio = ratio if ratio >= 0 else target_original_ratio
    if effective_ratio <= 25:
        ost_score += 2
    elif effective_ratio <= 45:
        ost_score += 1

    total = rewrite_score + ost_score
    if total >= 3:
        level = "high"
    elif total >= 1:
        level = "medium"
    else:
        level = "low"

    warnings: List[str] = []
    if not source_credit:
        warnings.append("来源声明关闭：发布前请自行确认授权与平台规则")
    if level == "low":
        warnings.append("改造度偏低：更接近搬运，请谨慎发布并确认版权")
    if ratio >= 0 and abs(ratio - target_original_ratio) > 15:
        warnings.append(
            f"实际原片占比 {ratio}% 与目标 {target_original_ratio}% 偏差超过 15%"
        )

    return {
        "level": level,
        "original_audio_ratio_actual": ratio,
        "original_audio_ratio_target": target_original_ratio,
        "narration_char_count": copy_len,
        "rewrite_score": rewrite_score,
        "ost_score": ost_score,
        "source_credit": bool(source_credit),
        "warnings": warnings,
        "disclaimer": (
            "本分仅为产品内粗检，不构成法律意见；版权与平台合规由使用者负责。"
        ),
    }


def default_credit_line(direction: str, hint: str = "") -> str:
    hint = (hint or "").strip()
    if direction == "outbound":
        base = "Original content credit"
    else:
        base = "原片来源"
    if hint:
        return f"{base}：{hint}" if direction != "outbound" else f"{base}: {hint}"
    return f"{base}：请填写频道/作品名" if direction != "outbound" else f"{base}: add channel/title"
