#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
导出打包：口播稿、标题、合规结果写入 export/。
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional

from .compliance import default_credit_line, score_transform_level
from .task_store import artifact_path, read_text_artifact, write_json_artifact, write_text_artifact


def build_packaging_payload(
    *,
    direction: str,
    narration_copy: str,
    titles: Optional[List[str]] = None,
    cover_text: str = "",
    description: str = "",
    tags: Optional[List[str]] = None,
    caption: str = "",
    credit_line: str = "",
    credit_hint: str = "",
    source_credit: bool = True,
    script_items: Optional[List[Dict[str, Any]]] = None,
    original_audio_ratio_target: float = 30.0,
) -> Dict[str, Any]:
    if source_credit and not credit_line:
        credit_line = default_credit_line(direction, credit_hint)

    compliance = score_transform_level(
        narration_copy=narration_copy,
        items=script_items,
        target_original_ratio=original_audio_ratio_target,
        source_credit=source_credit,
    )

    return {
        "titles": titles or [],
        "cover_text": cover_text or "",
        "description": description or "",
        "tags": tags or [],
        "caption": caption or "",
        "credit_line": credit_line if source_credit else "",
        "compliance": compliance,
        "narration_copy": narration_copy or "",
    }


def write_export_bundle(task_id: str, payload: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, str]:
    export_dir = artifact_path(task_id, "export")
    os.makedirs(export_dir, exist_ok=True)

    paths: Dict[str, str] = {}

    narration_path = os.path.join(export_dir, "narration_copy.txt")
    with open(narration_path, "w", encoding="utf-8") as f:
        f.write(payload.get("narration_copy") or "")
    paths["narration_copy"] = narration_path

    packaging_path = os.path.join(export_dir, "packaging.json")
    with open(packaging_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "titles": payload.get("titles") or [],
                "cover_text": payload.get("cover_text") or "",
                "description": payload.get("description") or "",
                "tags": payload.get("tags") or [],
                "caption": payload.get("caption") or "",
                "credit_line": payload.get("credit_line") or "",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    paths["packaging"] = packaging_path

    compliance_path = os.path.join(export_dir, "compliance.json")
    with open(compliance_path, "w", encoding="utf-8") as f:
        json.dump(payload.get("compliance") or {}, f, ensure_ascii=False, indent=2)
    paths["compliance"] = compliance_path

    # 同步任务根目录的关键产物到 export（若存在）
    artifacts = meta.get("artifacts") or {}
    for key, filename in (
        ("source_srt", "source.srt"),
        ("target_srt", "target.srt"),
        ("script_json", "script.json"),
        ("digest", "digest.md"),
    ):
        src = artifacts.get(key) or ""
        if src and os.path.isfile(src):
            dst = os.path.join(export_dir, filename)
            try:
                shutil.copy2(src, dst)
                paths[key] = dst
            except Exception:
                pass

    output_mp4 = artifacts.get("output_mp4") or ""
    if output_mp4 and os.path.isfile(output_mp4):
        dst = os.path.join(export_dir, os.path.basename(output_mp4))
        try:
            shutil.copy2(output_mp4, dst)
            paths["output_mp4"] = dst
        except Exception:
            paths["output_mp4"] = output_mp4

    # 根目录也落一份 packaging / compliance 便于 meta 引用
    write_json_artifact(task_id, "packaging.json", {
        "titles": payload.get("titles") or [],
        "cover_text": payload.get("cover_text") or "",
        "description": payload.get("description") or "",
        "tags": payload.get("tags") or [],
        "caption": payload.get("caption") or "",
        "credit_line": payload.get("credit_line") or "",
    })
    write_json_artifact(task_id, "compliance.json", payload.get("compliance") or {})
    write_text_artifact(task_id, "narration_copy.txt", payload.get("narration_copy") or "")

    return paths


def fallback_titles_from_copy(direction: str, narration_copy: str) -> Dict[str, Any]:
    """LLM 包装未接通时的降级标题。"""
    text = (narration_copy or "").strip().replace("\n", " ")
    snippet = text[:24] if direction == "inbound" else text[:48]
    if direction == "inbound":
        titles = [
            snippet or "跨境解说成片",
            f"一分钟看懂｜{snippet}" if snippet else "一分钟看懂这条视频",
            f"热门搬运解说｜{snippet}" if snippet else "热门搬运解说",
        ]
        return {
            "titles": titles,
            "cover_text": (snippet[:8] if snippet else "跨境解说"),
            "description": text[:120],
            "tags": ["跨境解说", "本地化", "AI剪辑"],
            "caption": "",
        }
    titles = [
        snippet or "Localized explainer",
        f"Watch this: {snippet}" if snippet else "Watch this localized cut",
        f"Quick take: {snippet}" if snippet else "Quick localized take",
    ]
    return {
        "titles": titles,
        "cover_text": (snippet[:28] if snippet else "Quick take"),
        "description": text[:200],
        "tags": ["localization", "voiceover", "shorts"],
        "caption": text[:150],
    }
