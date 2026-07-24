#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
任务目录与 meta 读写。
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.utils.utils import storage_dir

from .state_machine import assert_transition, progress_of, step_of
from .style_packs import resolve_style_pack
from .glossary import normalize_glossary


META_NAME = "meta.json"


def tasks_root() -> str:
    path = os.path.join(storage_dir("tasks", create=True), "cross_border")
    os.makedirs(path, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_task_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"cb_{stamp}_{uuid.uuid4().hex[:6]}"


def task_dir(task_id: str) -> str:
    path = os.path.join(tasks_root(), task_id)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "export"), exist_ok=True)
    return path


def meta_path(task_id: str) -> str:
    return os.path.join(task_dir(task_id), META_NAME)


def artifact_path(task_id: str, name: str) -> str:
    return os.path.join(task_dir(task_id), name)


def load_meta(task_id: str) -> Dict[str, Any]:
    path = meta_path(task_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"task meta not found: {task_id}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    task_id = meta["task_id"]
    meta["updated_at"] = _now_iso()
    path = meta_path(task_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return meta


def create_task(
    *,
    direction: str,
    video_path: str,
    source_lang: str = "",
    target_lang: str = "",
    style_pack: str = "",
    duration_mode: str = "keep",
    original_audio_ratio: Optional[float] = None,
    glossary: Optional[Any] = None,
    source_credit: bool = True,
    content_type: str = "",
    platform: str = "",
    credit_hint: str = "",
    narration_word_count: Optional[int] = None,
    voice_name: str = "",
    asr_backend: str = "auto",
    tts_engine: str = "",
    voice_rate: float = 1.0,
    voice_pitch: float = 1.0,
) -> Dict[str, Any]:
    direction = (direction or "inbound").lower()
    if direction not in {"inbound", "outbound"}:
        raise ValueError("direction must be inbound or outbound")

    if direction == "inbound":
        source_lang = source_lang or "en"
        target_lang = target_lang or "zh"
    else:
        source_lang = source_lang or "zh"
        target_lang = target_lang or "en"

    # MVP 锁定 en↔zh
    pair = {source_lang.lower()[:2], target_lang.lower()[:2]}
    if pair != {"en", "zh"}:
        logger.warning(f"MVP prefers en↔zh, got {source_lang}->{target_lang}")

    pack = resolve_style_pack(direction, style_pack or None)
    if original_audio_ratio is None:
        original_audio_ratio = pack["default_original_audio_ratio"]
    if not content_type:
        content_type = pack.get("default_content_type") or "tech_review"
    if not platform:
        platform = pack.get("default_platform") or (
            "douyin" if direction == "inbound" else "tiktok"
        )
    if narration_word_count is None:
        # 默认按 1 分钟估算，后续 pipeline 可按视频时长重算
        narration_word_count = int(pack.get("default_word_count_per_min") or 300)

    if not voice_name:
        hint = pack.get("tts_voice_hint") or {}
        voice_name = hint.get(target_lang[:2]) or hint.get("zh") or hint.get("en") or ""

    task_id = new_task_id()
    task_dir(task_id)
    meta: Dict[str, Any] = {
        "task_id": task_id,
        "direction": direction,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "style_pack": pack["id"],
        "status": "draft",
        "step": None,
        "progress": 0,
        "inputs": {
            "video_path": video_path,
            "glossary": normalize_glossary(glossary),
            "duration_mode": duration_mode,
            "original_audio_ratio": float(original_audio_ratio),
            "source_credit": bool(source_credit),
            "content_type": content_type,
            "platform": platform,
            "credit_hint": credit_hint,
            "narration_word_count": int(narration_word_count),
            "voice_name": voice_name,
            "style_addendum": pack.get("prompt_addendum") or "",
            "asr_backend": (asr_backend or "auto").strip().lower() or "auto",
            "tts_engine": (tts_engine or "").strip(),
            "voice_rate": float(voice_rate or 1.0),
            "voice_pitch": float(voice_pitch or 1.0),
        },
        "artifacts": {
            "source_srt": "",
            "target_srt": "",
            "asr_backend": "",
            "digest": "",
            "narration_copy": "",
            "script_json": "",
            "tts_dir": "",
            "output_mp4": "",
            "titles": "",
            "description": "",
            "compliance": "",
            "export_dir": artifact_path(task_id, "export"),
        },
        "error": None,
        "logs": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    return save_meta(meta)


def append_log(meta: Dict[str, Any], message: str, level: str = "INFO") -> Dict[str, Any]:
    meta.setdefault("logs", []).append(
        {"ts": _now_iso(), "level": level, "message": str(message)}
    )
    # 防止无限膨胀
    if len(meta["logs"]) > 500:
        meta["logs"] = meta["logs"][-500:]
    return meta


def transition(meta: Dict[str, Any], target_status: str, error: Optional[str] = None) -> Dict[str, Any]:
    result = assert_transition(meta.get("status") or "draft", target_status)
    meta["status"] = result.status
    meta["step"] = result.step
    if result.progress >= 0:
        meta["progress"] = result.progress
    if error:
        meta["error"] = {"step": result.step or meta.get("step"), "message": error}
        append_log(meta, error, level="ERROR")
    elif result.status != "failed":
        meta["error"] = None
    append_log(meta, f"status -> {result.status}")
    return save_meta(meta)


def write_text_artifact(task_id: str, filename: str, content: str) -> str:
    path = artifact_path(task_id, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")
    return path


def write_json_artifact(task_id: str, filename: str, data: Any) -> str:
    path = artifact_path(task_id, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def read_text_artifact(path: str) -> str:
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def list_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    root = tasks_root()
    rows: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return rows
    for name in os.listdir(root):
        path = os.path.join(root, name, META_NAME)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            rows.append(
                {
                    "task_id": meta.get("task_id") or name,
                    "direction": meta.get("direction"),
                    "status": meta.get("status"),
                    "progress": meta.get("progress"),
                    "style_pack": meta.get("style_pack"),
                    "created_at": meta.get("created_at"),
                    "updated_at": meta.get("updated_at"),
                    "error": meta.get("error"),
                }
            )
        except Exception as exc:
            logger.warning(f"skip broken task {name}: {exc}")
    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return rows[:limit]


def safe_basename(path: str) -> str:
    base = os.path.basename(path or "") or "video.mp4"
    base = re.sub(r"[^\w.\-()一-鿿]+", "_", base)
    return base
