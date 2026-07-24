#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
术语表：翻译 + 解说文案共用注入。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Union


GlossaryItem = Dict[str, Any]


def normalize_glossary(
    items: Optional[Union[Iterable[GlossaryItem], str]] = None,
) -> List[GlossaryItem]:
    if not items:
        return []
    if isinstance(items, str):
        return parse_glossary_text(items)

    normalized: List[GlossaryItem] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("src") or raw.get("source") or "").strip()
        dst = str(raw.get("dst") or raw.get("target") or src).strip()
        if not src:
            continue
        lock = raw.get("lock", True)
        if isinstance(lock, str):
            lock = lock.strip().lower() in {"1", "true", "yes", "y", "是"}
        else:
            lock = bool(lock)
        normalized.append({"src": src, "dst": dst or src, "lock": lock})
    return normalized


def parse_glossary_text(text: str) -> List[GlossaryItem]:
    """
    支持行格式：
      MrBeast = MrBeast
      老干妈 => Lao Gan Ma | lock
      Source|Target|true
    """
    items: List[GlossaryItem] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lock = True
        if "|" in line and "=>" not in line and "=" not in line.split("|")[0]:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                src, dst = parts[0], parts[1]
                if len(parts) >= 3:
                    lock = parts[2].lower() in {"1", "true", "yes", "y", "是", "lock"}
                if src:
                    items.append({"src": src, "dst": dst or src, "lock": lock})
                continue
        sep = "=>" if "=>" in line else ("=" if "=" in line else None)
        if not sep:
            continue
        left, right = line.split(sep, 1)
        src = left.strip()
        right = right.strip()
        if "| lock" in right.lower() or right.lower().endswith("|lock"):
            dst = right.rsplit("|", 1)[0].strip()
            lock = True
        elif right.lower().endswith("| false") or right.lower().endswith("|false"):
            dst = right.rsplit("|", 1)[0].strip()
            lock = False
        else:
            dst = right
        if src:
            items.append({"src": src, "dst": dst or src, "lock": lock})
    return items


def format_glossary_for_prompt(items: Optional[Iterable[GlossaryItem]] = None) -> str:
    normalized = normalize_glossary(list(items) if items else [])
    if not normalized:
        return (
            "## Glossary (MUST follow)\n"
            "(empty — no locked terms)\n\n"
            "Rules:\n"
            "- lock=true: do not translate/transliterate freely; use Target exactly\n"
            "- If entity appears in audio but not in glossary, keep source proper noun "
            "+ short apposition once when helpful\n"
        )

    lines = [
        "## Glossary (MUST follow)",
        "| Source | Target | Lock |",
        "|---|---|---|",
    ]
    for item in normalized:
        lines.append(
            f"| {item['src']} | {item['dst']} | {str(bool(item['lock'])).lower()} |"
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- lock=true: do not translate/transliterate freely; use Target exactly",
            "- If entity appears in audio but not in glossary, keep source proper noun "
            "+ short apposition once when helpful",
        ]
    )
    return "\n".join(lines)


def apply_locked_terms(text: str, items: Optional[Iterable[GlossaryItem]] = None) -> str:
    """轻量替换：把仍出现的 Source 锁词尽量换成 Target（不保证语言学完美）。"""
    if not text:
        return text
    normalized = normalize_glossary(list(items) if items else [])
    result = text
    # 长词优先，避免短词抢匹配
    for item in sorted(normalized, key=lambda x: len(x["src"]), reverse=True):
        if not item.get("lock"):
            continue
        src, dst = item["src"], item["dst"]
        if src and dst and src != dst and src in result:
            result = result.replace(src, dst)
    return result
