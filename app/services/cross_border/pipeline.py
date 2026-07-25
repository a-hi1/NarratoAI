#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化 pipeline 骨架。

W1 目标：
- 任务目录 + 状态机可跑通
- LLM 步骤（digest/copy/match/package）可在已有 LLM 配置下执行
- ASR/translate/TTS/render 可插拔；缺依赖时写入占位产物并允许人工补齐后继续

W2 目标：
- ASR 路由对接项目 FunASR（local/firered/bailian）+ whisper 回退
- translate 注入 glossary；锁定术语后处理
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import traceback
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from app.services.prompts import PromptManager
from app.services.subtitle_text import read_subtitle_text

from . import asr as asr_mod
from . import burn as burn_mod
from . import packaging as packaging_mod
from .glossary import (
    apply_locked_terms,
    format_glossary_for_prompt,
    normalize_glossary,
)
from .state_machine import (
    InvalidTransitionError,
    steps_for_mode,
)
from .style_packs import resolve_style_pack
from .task_store import (
    append_log,
    artifact_path,
    load_meta,
    read_text_artifact,
    save_meta,
    transition,
    write_json_artifact,
    write_text_artifact,
)


PROMPT_CATEGORY = "cross_border_narration"

_lock = threading.Lock()
_running_threads: Dict[str, threading.Thread] = {}


def _set_failed(
    meta: Dict[str, Any],
    message: str,
    step: Optional[str] = None,
) -> Dict[str, Any]:
    # 优先保留调用方指定步 / 当前 step / status 推导步，避免 error.step 为 null
    failed_step = step or meta.get("step")
    if not failed_step:
        status = str(meta.get("status") or "")
        if status.endswith("_running") or status.endswith("_done"):
            failed_step = status.rsplit("_", 1)[0]
    if failed_step:
        meta["step"] = failed_step
    append_log(meta, message, level="ERROR")
    try:
        return transition(meta, "failed", error=message)
    except InvalidTransitionError:
        meta["status"] = "failed"
        meta["error"] = {"step": meta.get("step") or failed_step, "message": message}
        return save_meta(meta)


def _ensure_llm_providers():
    try:
        # 正确路径是 providers 子包；app.services.llm 本身不导出该函数
        from app.services.llm.providers import register_all_providers

        register_all_providers()
    except Exception as exc:
        logger.warning(f"register_all_providers skipped: {exc}")


def _is_transient_llm_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    needles = (
        "connection error",
        "connection reset",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "429",
        "rate limit",
        "502",
        "503",
        "504",
        "server error",
        "remote protocol",
        "ssl",
    )
    return any(n in text for n in needles)


def _generate_text(
    prompt: str,
    system_prompt: Optional[str] = None,
    *,
    max_attempts: int = 2,
) -> str:
    """调用统一 LLM；对连接类瞬时错误做有限次短退避（默认 2 次，避免卡死数分钟）。"""
    import time

    _ensure_llm_providers()
    from app.services.llm.migration_adapter import _run_async_safely
    from app.services.llm.unified_service import UnifiedLLMService

    last_exc: Optional[BaseException] = None
    attempts = max(1, int(max_attempts or 1))
    for attempt in range(1, attempts + 1):
        try:
            return _run_async_safely(
                UnifiedLLMService.generate_text,
                prompt=prompt,
                system_prompt=system_prompt,
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_transient_llm_error(exc):
                raise
            # 短退避：1s / 2s，避免旧逻辑 4min×3 把整条流水线拖死
            delay = min(attempt, 3)
            logger.warning(
                f"LLM transient error (attempt {attempt}/{attempts}), "
                f"retry in {delay}s: {exc}"
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model output")
    # fenced
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _video_basename(meta: Dict[str, Any]) -> str:
    return os.path.basename((meta.get("inputs") or {}).get("video_path") or "video.mp4")


def _subtitle_content_from_paths(paths: List[str], video_path: str = "") -> str:
    sections = []
    for index, path in enumerate(paths, start=1):
        if not path or not os.path.exists(path):
            continue
        header = f"# 视频 {index}: {os.path.basename(video_path or path)}"
        sections.append(f"{header}\n{read_subtitle_text(path).text}".strip())
    return "\n\n".join(sections)


def _prompt_params(meta: Dict[str, Any], **extra) -> Dict[str, Any]:
    inputs = meta.get("inputs") or {}
    pack = resolve_style_pack(meta.get("direction") or "inbound", meta.get("style_pack"))
    glossary = format_glossary_for_prompt(inputs.get("glossary"))
    params = {
        "direction": meta.get("direction") or "inbound",
        "source_lang": meta.get("source_lang") or "",
        "target_lang": meta.get("target_lang") or "",
        "style_pack": meta.get("style_pack") or pack["id"],
        "content_type": inputs.get("content_type") or pack.get("default_content_type") or "tech_review",
        "platform": inputs.get("platform") or pack.get("default_platform") or "",
        "duration_mode": inputs.get("duration_mode") or "keep",
        "glossary": glossary,
        "style_addendum": inputs.get("style_addendum") or pack.get("prompt_addendum") or "",
        "original_sound_ratio": int(float(inputs.get("original_audio_ratio") or pack["default_original_audio_ratio"])),
        "narration_word_count": int(inputs.get("narration_word_count") or pack.get("default_word_count_per_min") or 300),
        "source_credit": str(bool(inputs.get("source_credit", True))).lower(),
        "credit_hint": inputs.get("credit_hint") or "",
    }
    params.update(extra)
    return params


def _render_prompt(name: str, params: Dict[str, Any]) -> str:
    return PromptManager.get_prompt(category=PROMPT_CATEGORY, name=name, parameters=params)


def _system_prompt(name: str) -> Optional[str]:
    try:
        obj = PromptManager.get_prompt_object(PROMPT_CATEGORY, name)
        return obj.get_system_prompt()
    except Exception:
        return None


def step_asr(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "asr_running")
    task_id = meta["task_id"]
    inputs = meta["inputs"]
    video_path = inputs.get("video_path") or ""
    source_srt = artifact_path(task_id, "source.srt")

    # 若用户已放置真实字幕则跳过识别（占位字幕会重跑）
    if (
        os.path.isfile(source_srt)
        and os.path.getsize(source_srt) > 0
        and not asr_mod.is_placeholder_srt(source_srt)
    ):
        append_log(meta, f"reuse existing source.srt: {source_srt}")
        meta["artifacts"]["source_srt"] = source_srt
        meta["artifacts"]["asr_backend"] = inputs.get("asr_backend") or "uploaded"
        save_meta(meta)
        return transition(meta, "asr_done")

    # 尝试从同名 srt 复制
    if video_path:
        sibling = os.path.splitext(video_path)[0] + ".srt"
        if os.path.isfile(sibling) and not asr_mod.is_placeholder_srt(sibling):
            shutil.copy2(sibling, source_srt)
            meta["artifacts"]["source_srt"] = source_srt
            meta["artifacts"]["asr_backend"] = "sibling"
            append_log(meta, f"copied sibling subtitle: {sibling}")
            save_meta(meta)
            return transition(meta, "asr_done")

    preferred = asr_mod.resolve_asr_backend(meta)
    append_log(
        meta,
        f"ASR start backend={preferred} video={os.path.basename(video_path or '')} "
        f"size={os.path.getsize(video_path) if video_path and os.path.isfile(video_path) else 0}",
    )
    save_meta(meta)
    out_path, used_backend, attempt_logs = asr_mod.run_asr(
        video_path=video_path,
        subtitle_file=source_srt,
        source_lang=meta.get("source_lang") or "",
        preferred_backend=preferred,
    )
    for line in attempt_logs:
        level = "WARNING" if "failed" in line.lower() or "placeholder" in line.lower() else "INFO"
        append_log(meta, line, level=level)

    meta["artifacts"]["source_srt"] = out_path or source_srt
    meta["artifacts"]["asr_backend"] = used_backend
    if used_backend == "placeholder":
        append_log(
            meta,
            "ASR placeholder written. Upload real source.srt then retry from asr/translate.",
            level="WARNING",
        )
    save_meta(meta)
    return transition(meta, "asr_done")


def step_translate(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "translate_running")
    task_id = meta["task_id"]
    source_srt = meta["artifacts"].get("source_srt") or artifact_path(task_id, "source.srt")
    target_srt = artifact_path(task_id, "target.srt")

    if not os.path.isfile(source_srt):
        return _set_failed(meta, "source.srt missing before translate")

    if asr_mod.is_placeholder_srt(source_srt):
        return _set_failed(
            meta,
            "source.srt is still ASR placeholder; upload real subtitles before translate",
        )

    # 已有目标字幕则复用
    if os.path.isfile(target_srt) and os.path.getsize(target_srt) > 10:
        meta["artifacts"]["target_srt"] = target_srt
        append_log(meta, "reuse existing target.srt")
        save_meta(meta)
        return transition(meta, "translate_done")

    target_lang = meta.get("target_lang") or "zh"
    glossary_items = normalize_glossary((meta.get("inputs") or {}).get("glossary"))
    glossary_block = format_glossary_for_prompt(glossary_items)

    lang_label = {
        "zh": "中文",
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
    }.get((target_lang or "zh")[:2].lower(), target_lang or "中文")

    def _postprocess_and_save(text: str, via: str) -> Dict[str, Any]:
        cleaned = apply_locked_terms(text or "", glossary_items)
        write_text_artifact(task_id, "target.srt", cleaned.strip() + "\n")
        meta["artifacts"]["target_srt"] = target_srt
        # 清理实时进度字段
        meta.pop("translate_progress", None)
        append_log(meta, f"translated via {via}")
        if glossary_items:
            append_log(meta, f"glossary applied ({len(glossary_items)} terms)")
        save_meta(meta)
        return transition(meta, "translate_done")

    # 进度 meta 写盘节流：长片每批都 save 会和 Windows 文件锁打架；约 1.2s 一次足够 UI
    _progress_last_save = [0.0]

    def _on_translate_progress(completed: int, total: int, message: str) -> None:
        """边译边写进度，供详情页实时展示字幕节点（节流写 meta）。"""
        try:
            import time as _time

            total_i = max(0, int(total or 0))
            done_i = max(0, int(completed or 0))
            pct = int(round(100.0 * done_i / total_i)) if total_i else 0
            # translate 在状态机里约 20–40%，用子进度填中间段
            base, span = 22, 18
            meta["progress"] = min(39, base + int(span * pct / 100.0))
            meta["translate_progress"] = {
                "completed": done_i,
                "total": total_i,
                "percent": pct,
                "message": str(message or "")[:240],
            }
            meta["artifacts"]["target_srt"] = target_srt
            now = _time.monotonic()
            is_edge = done_i <= 0 or (total_i and done_i >= total_i)
            # 不全量 append_log；只偶尔记一条
            if total_i and (
                is_edge or done_i % max(1, total_i // 5) == 0
            ):
                append_log(meta, str(message or f"translate {done_i}/{total_i}")[:200])
            # 节流：边缘节点必写；中间最多约 1.2s 一次
            if is_edge or (now - _progress_last_save[0]) >= 1.2:
                save_meta(meta)
                _progress_last_save[0] = now
        except Exception as exc:
            logger.warning(f"translate progress callback failed: {exc}")

    try:
        from app.services.subtitle_translator import translate_subtitle_file

        out = translate_subtitle_file(
            source_srt,
            target_srt,
            target_language=lang_label,
            glossary_block=glossary_block if glossary_items else "",
            progress_callback=_on_translate_progress,
            write_partial=True,
        )
        if out and os.path.isfile(out):
            with open(out, encoding="utf-8") as fp:
                translated_text = fp.read()
            if os.path.abspath(out) != os.path.abspath(target_srt):
                # postprocess writes to target_srt
                pass
            return _postprocess_and_save(translated_text, "subtitle_translator")
        raise RuntimeError("translate_subtitle_file returned empty path")
    except Exception as exc:
        append_log(meta, f"subtitle_translator failed: {exc}", level="WARNING")
        try:
            with open(source_srt, encoding="utf-8") as srt_fp:
                source_srt_text = srt_fp.read()
            prompt = (
                f"Translate the following SRT subtitles into {lang_label}.\n"
                f"Keep index numbers and timestamps unchanged. Only translate dialogue lines.\n"
                f"{glossary_block}\n\n"
                f"SRT:\n{source_srt_text}"
            )
            translated = _generate_text(
                prompt,
                system_prompt="You are a subtitle translator. Output valid SRT only.",
            )
            fence = re.search(r"```(?:srt)?\s*([\s\S]*?)```", translated)
            if fence:
                translated = fence.group(1).strip()
            return _postprocess_and_save(translated, "LLM fallback")
        except Exception as exc2:
            shutil.copy2(source_srt, target_srt)
            meta["artifacts"]["target_srt"] = target_srt
            meta.pop("translate_progress", None)
            append_log(meta, f"translate fallback copy source: {exc2}", level="WARNING")
            save_meta(meta)
            return transition(meta, "translate_done")


def step_digest(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "digest_running")
    task_id = meta["task_id"]
    source_srt = meta["artifacts"].get("source_srt") or artifact_path(task_id, "source.srt")
    target_srt = meta["artifacts"].get("target_srt") or ""
    paths = [source_srt]
    if target_srt and os.path.isfile(target_srt):
        paths.append(target_srt)
    subtitle_content = _subtitle_content_from_paths(paths, meta["inputs"].get("video_path") or "")
    if not subtitle_content.strip():
        return _set_failed(meta, "empty subtitles for digest")

    params = _prompt_params(meta, subtitle_content=subtitle_content)
    prompt = _render_prompt("source_digest", params)
    try:
        digest = _generate_text(prompt, system_prompt=_system_prompt("source_digest"))
    except Exception as exc:
        return _set_failed(meta, f"digest LLM failed: {exc}")

    path = write_text_artifact(task_id, "digest.md", digest.strip() + "\n")
    meta["artifacts"]["digest"] = path
    save_meta(meta)
    return transition(meta, "digest_done")


def step_copy(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "copy_running")
    task_id = meta["task_id"]
    digest = read_text_artifact(meta["artifacts"].get("digest") or artifact_path(task_id, "digest.md"))
    source_srt = meta["artifacts"].get("source_srt") or artifact_path(task_id, "source.srt")
    target_srt = meta["artifacts"].get("target_srt") or ""
    paths = [p for p in [source_srt, target_srt] if p]
    subtitle_content = _subtitle_content_from_paths(paths, meta["inputs"].get("video_path") or "")
    if not digest.strip():
        return _set_failed(meta, "digest missing before copy")

    params = _prompt_params(
        meta,
        source_digest=digest,
        subtitle_content=subtitle_content,
    )
    prompt = _render_prompt("narration_copy", params)
    try:
        copy_text = _generate_text(prompt, system_prompt=_system_prompt("narration_copy"))
    except Exception as exc:
        return _set_failed(meta, f"narration_copy LLM failed: {exc}")

    path = write_text_artifact(task_id, "narration_copy.txt", copy_text.strip() + "\n")
    meta["artifacts"]["narration_copy"] = path
    save_meta(meta)
    return transition(meta, "copy_done")


_SRT_BLOCK_RE = re.compile(
    r"(?m)^\s*(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n"
    r"([\s\S]*?)(?=\n\s*\d+\s*\n\d{2}:\d{2}:\d{2}|\Z)"
)
_NARRATION_SPLIT_RE = re.compile(r"(?<=[。！？!?\n])\s+|\n+")
_OST_HINT_RE = re.compile(
    r"(爆炸|炸|按钮|按下|boom|blow|press|explosion|原片|原声)",
    re.IGNORECASE,
)


def _parse_srt_cues(srt_text: str) -> List[Dict[str, str]]:
    """轻量解析 SRT 为 [{start,end,text}]，供 match 回退使用。"""
    text = (srt_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    cues: List[Dict[str, str]] = []
    for match in _SRT_BLOCK_RE.finditer(text + "\n"):
        start = match.group(2).replace(".", ",")
        end = match.group(3).replace(".", ",")
        body = re.sub(r"\s+", " ", (match.group(4) or "").strip())
        cues.append({"start": start, "end": end, "text": body})
    return cues


def _split_narration_lines(narration_copy: str) -> List[str]:
    raw = (narration_copy or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    parts = [p.strip() for p in _NARRATION_SPLIT_RE.split(raw) if p and p.strip()]
    # 合并过短碎片，避免 TTS 碎成一堆单字
    merged: List[str] = []
    buf = ""
    for part in parts:
        candidate = f"{buf}{part}".strip() if buf else part
        if len(candidate) < 8 and not candidate.endswith(("。", "！", "？", "!", "?")):
            buf = candidate
            continue
        if buf and len(part) < 4:
            merged.append(f"{buf}{part}".strip())
            buf = ""
            continue
        if buf:
            merged.append(buf)
            buf = ""
        merged.append(part)
    if buf:
        if merged:
            merged[-1] = f"{merged[-1]}{buf}".strip()
        else:
            merged.append(buf)
    return [m for m in merged if m]


def _fallback_script_items(
    narration_copy: str,
    srt_text: str,
    video_name: str,
    *,
    target_original_ratio: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    LLM 匹配失败时的启发式脚本：
    - 按句切解说
    - 均分映射到源字幕时间轴
    - 命中爆炸/按钮等高能词的字幕段插入 OST=1
    """
    lines = _split_narration_lines(narration_copy)
    cues = _parse_srt_cues(srt_text)
    if not lines:
        raise ValueError("empty narration for fallback match")
    if not cues:
        # 无字幕时整段用默认时间窗
        items = []
        for i, line in enumerate(lines, start=1):
            items.append(
                {
                    "_id": i,
                    "video_id": 1,
                    "video_name": video_name,
                    "timestamp": "00:00:00,000-00:00:03,000",
                    "picture": "fallback window",
                    "narration": line,
                    "OST": 0,
                }
            )
        return _normalize_script_items(items, video_name)

    # 高能原片候选
    ost_cues = [c for c in cues if _OST_HINT_RE.search(c.get("text") or "")]
    # 控制 OST 占比：最多约 target_ratio 对应的条数（粗）
    max_ost = max(1, int(round(len(cues) * max(0.0, target_original_ratio) / 100.0))) if cues else 0
    ost_cues = ost_cues[:max_ost] if max_ost else []

    items: List[Dict[str, Any]] = []
    n_lines = len(lines)
    n_cues = len(cues)
    for i, line in enumerate(lines):
        # 线性映射到字幕索引
        cue_idx = min(n_cues - 1, int(i * n_cues / max(1, n_lines)))
        cue = cues[cue_idx]
        items.append(
            {
                "_id": len(items) + 1,
                "video_id": 1,
                "video_name": video_name,
                "timestamp": f"{cue['start']}-{cue['end']}",
                "picture": cue.get("text") or "",
                "narration": line,
                "OST": 0,
            }
        )
        # 在对应高能字幕后插入原片
        for ost in ost_cues:
            if ost is cue or (
                ost["start"] == cue["start"] and ost["end"] == cue["end"]
            ):
                items.append(
                    {
                        "_id": len(items) + 1,
                        "video_id": 1,
                        "video_name": video_name,
                        "timestamp": f"{ost['start']}-{ost['end']}",
                        "picture": ost.get("text") or "high-energy original",
                        "narration": f"播放原片{len(items) + 1}",
                        "OST": 1,
                    }
                )
                # 每个 ost cue 只插一次
                ost_cues = [x for x in ost_cues if x is not ost]
                break

    # 若完全没插到 OST，把最后一条高能字幕补上
    if not any(int(x.get("OST", 0) or 0) == 1 for x in items):
        seed = next((c for c in cues if _OST_HINT_RE.search(c.get("text") or "")), None)
        if seed is None and len(cues) >= 2:
            seed = cues[min(len(cues) - 1, max(0, len(cues) // 2))]
        if seed is not None:
            items.append(
                {
                    "_id": len(items) + 1,
                    "video_id": 1,
                    "video_name": video_name,
                    "timestamp": f"{seed['start']}-{seed['end']}",
                    "picture": seed.get("text") or "original",
                    "narration": f"播放原片{len(items) + 1}",
                    "OST": 1,
                }
            )

    return _normalize_script_items(items, video_name)


def _normalize_script_items(items: List[Any], video_name: str) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item.setdefault("_id", i)
        item.setdefault("video_id", 1)
        item.setdefault("video_name", video_name)
        try:
            item["OST"] = int(item.get("OST", 0) or 0)
        except (TypeError, ValueError):
            item["OST"] = 0
        narration = str(item.get("narration") or "").strip()
        # 「播放原片*」约定为原声轨；两边不一致时以文案标记为准
        if narration.startswith("播放原片"):
            item["OST"] = 1
        if item["OST"] == 1 and not narration:
            item["narration"] = f"播放原片{item['_id']}"
        item["narration"] = str(item.get("narration") or "").strip()
        normalized.append(item)
    return normalized


def step_match(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "match_running")
    task_id = meta["task_id"]
    digest = read_text_artifact(meta["artifacts"].get("digest") or artifact_path(task_id, "digest.md"))
    narration_copy = read_text_artifact(
        meta["artifacts"].get("narration_copy") or artifact_path(task_id, "narration_copy.txt")
    )
    source_srt = meta["artifacts"].get("source_srt") or artifact_path(task_id, "source.srt")
    subtitle_content = _subtitle_content_from_paths(
        [source_srt], meta["inputs"].get("video_path") or ""
    )
    if not narration_copy.strip():
        return _set_failed(meta, "narration_copy missing before match")

    params = _prompt_params(
        meta,
        source_digest=digest,
        subtitle_content=subtitle_content,
        narration_copy=narration_copy,
    )
    target_ratio = float((meta.get("inputs") or {}).get("original_audio_ratio") or 30)
    items: List[Dict[str, Any]] = []
    # 默认启发式（秒级）。LLM 匹配慢且易挂，需质量时再开 CROSS_BORDER_MATCH_LLM=1
    prefer_llm = os.environ.get("CROSS_BORDER_MATCH_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }
    force_fallback = os.environ.get("CROSS_BORDER_MATCH_FALLBACK", "").lower() in {
        "1",
        "true",
        "yes",
    }
    match_via = "heuristic"
    llm_error: Optional[str] = None

    def _heuristic_items() -> List[Dict[str, Any]]:
        srt_path = source_srt if os.path.isfile(source_srt) else ""
        srt_text = read_subtitle_text(srt_path).text if srt_path else ""
        if not srt_text.strip():
            srt_text = subtitle_content
        return _fallback_script_items(
            narration_copy,
            srt_text,
            _video_basename(meta),
            target_original_ratio=target_ratio,
        )

    if prefer_llm and not force_fallback:
        prompt = _render_prompt("script_matching", params)
        try:
            raw = _generate_text(
                prompt,
                system_prompt=_system_prompt("script_matching"),
                max_attempts=1,
            )
            data = _extract_json(raw)
            raw_items = data.get("items") if isinstance(data, dict) else data
            if not isinstance(raw_items, list) or not raw_items:
                raise ValueError("script items empty")
            items = _normalize_script_items(raw_items, _video_basename(meta))
            if not items:
                raise ValueError("script items empty after normalize")
            match_via = "llm"
        except Exception as exc:
            llm_error = str(exc)
            append_log(
                meta,
                f"script_matching LLM failed, heuristic fallback: {exc}",
                level="WARNING",
            )

    if not items:
        try:
            items = _heuristic_items()
            match_via = "heuristic_fallback" if llm_error else "heuristic"
        except Exception as exc2:
            detail = f"{llm_error}; fallback: {exc2}" if llm_error else str(exc2)
            return _set_failed(meta, f"script_matching failed: {detail}", step="match")
    if not items:
        return _set_failed(meta, "script_matching produced no items", step="match")
    append_log(meta, f"script matched via {match_via}: {len(items)} items")

    from . import compliance as compliance_mod

    actual_ratio = compliance_mod.estimate_original_audio_ratio(items)
    meta["artifacts"]["ost_ratio"] = actual_ratio
    if actual_ratio >= 0:
        delta = abs(actual_ratio - target_ratio)
        msg = f"OST ratio actual={actual_ratio}% target={target_ratio}%"
        append_log(meta, msg, level="WARNING" if delta > 20 else "INFO")
        if actual_ratio > target_ratio + 25:
            append_log(
                meta,
                "原片占比偏高：建议人工删减 OST=1 段或补解说，以免改造度不足",
                level="WARNING",
            )
        elif actual_ratio < max(0.0, target_ratio - 25):
            append_log(
                meta,
                "原片占比偏低：高能原声可能被切掉，建议核对 High-energy Moments",
                level="WARNING",
            )

    path = write_json_artifact(
        task_id,
        "script.json",
        {
            "items": items,
            "ost_ratio": actual_ratio,
            "target_original_audio_ratio": target_ratio,
            "match_via": match_via,
        },
    )
    meta["artifacts"]["script_json"] = path
    save_meta(meta)
    return transition(meta, "match_done")


def _default_voice_name(meta: Dict[str, Any]) -> str:
    voice = str((meta.get("inputs") or {}).get("voice_name") or "").strip()
    if voice:
        return voice
    if (meta.get("target_lang") or "zh").startswith("zh"):
        return "zh-CN-XiaoyiNeural"
    return "en-US-JennyNeural"


def _default_tts_engine(meta: Dict[str, Any]) -> str:
    engine = str((meta.get("inputs") or {}).get("tts_engine") or "").strip()
    if engine:
        return engine
    try:
        from app.config import config

        return str(config.app.get("tts_engine") or "edge_tts")
    except Exception:
        return "edge_tts"


def _generate_tts_with_voice_service(
    *,
    items: List[Dict[str, Any]],
    tts_dir: str,
    voice_name: str,
    tts_engine: str,
    voice_rate: float,
    voice_pitch: float,
) -> List[Dict[str, Any]]:
    from app.services import voice as voice_svc

    results: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or int(item.get("OST", 0) or 0) == 1:
            continue
        text = str(item.get("narration") or "").strip()
        if not text or text.startswith("播放原片"):
            continue
        item_id = int(item.get("_id") or 0)
        out = os.path.join(tts_dir, f"{item_id:04d}.mp3")
        sub_maker = voice_svc.tts(
            text=text,
            voice_name=voice_name,
            voice_rate=voice_rate,
            voice_pitch=voice_pitch,
            voice_file=out,
            tts_engine=tts_engine,
        )
        if sub_maker is None or not os.path.isfile(out):
            raise RuntimeError(f"voice.tts failed for item {item_id}")
        results.append(
            {
                "_id": item_id,
                "timestamp": item.get("timestamp"),
                "audio_file": out,
                "engine": tts_engine,
                "voice_name": voice_name,
            }
        )
    return results


def _generate_tts_with_edge(
    *,
    items: List[Dict[str, Any]],
    tts_dir: str,
    voice_name: str,
) -> List[Dict[str, Any]]:
    import asyncio
    import edge_tts  # type: ignore

    async def _one(text: str, out_path: str, v: str):
        communicate = edge_tts.Communicate(text, v)
        await communicate.save(out_path)

    async def _all():
        results: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or int(item.get("OST", 0) or 0) == 1:
                continue
            text = str(item.get("narration") or "").strip()
            if not text or text.startswith("播放原片"):
                continue
            item_id = int(item.get("_id") or 0)
            out = os.path.join(tts_dir, f"{item_id:04d}.mp3")
            await _one(text, out, voice_name)
            results.append(
                {
                    "_id": item_id,
                    "timestamp": item.get("timestamp"),
                    "audio_file": out,
                    "engine": "edge_tts",
                    "voice_name": voice_name,
                }
            )
        return results

    return asyncio.run(_all())


def step_tts(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "tts_running")
    task_id = meta["task_id"]
    tts_dir = artifact_path(task_id, "tts")
    os.makedirs(tts_dir, exist_ok=True)
    meta["artifacts"]["tts_dir"] = tts_dir

    script_path = meta["artifacts"].get("script_json") or artifact_path(task_id, "script.json")
    items: List[Dict[str, Any]] = []
    if os.path.isfile(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw_items = data.get("items") if isinstance(data, dict) else data
        items = [x for x in (raw_items or []) if isinstance(x, dict)]

    if not items:
        append_log(meta, "no script items for tts", level="WARNING")
        save_meta(meta)
        return transition(meta, "tts_done")

    voice_name = _default_voice_name(meta)
    tts_engine = _default_tts_engine(meta)
    voice_rate = float((meta.get("inputs") or {}).get("voice_rate") or 1.0)
    voice_pitch = float((meta.get("inputs") or {}).get("voice_pitch") or 1.0)
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    try:
        results = _generate_tts_with_voice_service(
            items=items,
            tts_dir=tts_dir,
            voice_name=voice_name,
            tts_engine=tts_engine,
            voice_rate=voice_rate,
            voice_pitch=voice_pitch,
        )
        append_log(
            meta,
            f"voice service ({tts_engine}) generated {len(results)} clips with {voice_name}",
        )
    except Exception as exc:
        errors.append(f"voice service: {exc}")
        append_log(meta, f"voice.tts failed, fallback edge-tts: {exc}", level="WARNING")
        try:
            # edge 路径强制用 edge 可用音色
            edge_voice = voice_name
            if not edge_voice or not any(x in edge_voice for x in ("Neural", "zh-", "en-")):
                edge_voice = _default_voice_name({**meta, "inputs": {**(meta.get("inputs") or {}), "voice_name": ""}})
            results = _generate_tts_with_edge(
                items=items,
                tts_dir=tts_dir,
                voice_name=edge_voice,
            )
            append_log(meta, f"edge-tts generated {len(results)} clips with {edge_voice}")
        except Exception as exc2:
            errors.append(f"edge-tts: {exc2}")
            note = os.path.join(tts_dir, "README.txt")
            with open(note, "w", encoding="utf-8") as f:
                f.write(
                    "TTS not generated in this environment.\n"
                    f"errors: {errors}\n"
                    "Pipeline continues; check voice engine config / network.\n"
                )
            append_log(meta, f"tts placeholder: {errors}", level="WARNING")

    if results:
        write_json_artifact(task_id, "tts_manifest.json", {"clips": results})
        meta["artifacts"]["tts_manifest"] = artifact_path(task_id, "tts_manifest.json")

    save_meta(meta)
    return transition(meta, "tts_done")


def step_render(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "render_running")
    task_id = meta["task_id"]
    video_path = (meta.get("inputs") or {}).get("video_path") or ""
    output = artifact_path(task_id, "output.mp4")
    work_dir = artifact_path(task_id, "render")
    os.makedirs(work_dir, exist_ok=True)

    script_path = meta["artifacts"].get("script_json") or artifact_path(task_id, "script.json")
    tts_dir = meta["artifacts"].get("tts_dir") or artifact_path(task_id, "tts")
    manifest_path = meta["artifacts"].get("tts_manifest") or artifact_path(
        task_id, "tts_manifest.json"
    )

    try:
        from . import render as render_mod

        items = render_mod._load_script_items(script_path)
        if not items:
            raise ValueError("script.json empty or missing")
        if not video_path or not os.path.isfile(video_path):
            raise FileNotFoundError("source video missing")

        tts_results = render_mod.build_tts_results_from_manifest(
            items=items,
            tts_dir=tts_dir,
            manifest_path=manifest_path,
        )
        # 无 TTS 但仍有 OST=1 片段时，允许纯原片拼接
        has_ost1 = any(int(i.get("OST", 0) or 0) == 1 for i in items)
        if not tts_results and not has_ost1:
            raise RuntimeError("no tts clips and no OST=1 segments; cannot render")

        aspect = "16:9"
        # 竖屏平台默认 9:16
        platform = str((meta.get("inputs") or {}).get("platform") or "").lower()
        if platform in {"douyin", "tiktok", "reels", "shorts"}:
            aspect = "9:16"

        final_path, debug = render_mod.render_final_video(
            task_id=task_id,
            video_path=video_path,
            script_items=items,
            tts_results=tts_results,
            work_dir=work_dir,
            output_mp4=output,
            video_aspect=aspect,
            subtitle_enabled=False,
            voice_volume=1.0,
            original_volume=1.0,
        )
        # 同步一份到 export
        export_dir = meta["artifacts"].get("export_dir") or artifact_path(task_id, "export")
        os.makedirs(export_dir, exist_ok=True)
        export_mp4 = os.path.join(export_dir, "output.mp4")
        try:
            if os.path.abspath(final_path) != os.path.abspath(export_mp4):
                shutil.copy2(final_path, export_mp4)
        except Exception as copy_exc:
            append_log(meta, f"export copy skipped: {copy_exc}", level="WARNING")
            export_mp4 = final_path

        meta["artifacts"]["output_mp4"] = export_mp4 if os.path.isfile(export_mp4) else final_path
        write_json_artifact(task_id, "render_debug.json", debug)
        meta["artifacts"]["render_debug"] = artifact_path(task_id, "render_debug.json")
        append_log(
            meta,
            f"render ok: clips={debug.get('clip_count')} tts={debug.get('tts_count')} "
            f"-> {meta['artifacts']['output_mp4']}",
        )
        save_meta(meta)
        return transition(meta, "render_done")
    except Exception as exc:
        # 骨架回退：不伪造 mp4，保留源路径引用
        append_log(meta, f"render failed, fallback skeleton: {exc}", level="WARNING")
        traceback_msg = traceback.format_exc()
        append_log(meta, traceback_msg[-1500:], level="WARNING")
        write_text_artifact(
            task_id,
            "output_pending.txt",
            f"Render failed or skipped.\nreason: {exc}\n"
            "Check script/tts/ffmpeg. Source video kept as reference.\n",
        )
        if video_path and os.path.isfile(video_path):
            meta["artifacts"]["output_mp4"] = video_path
        else:
            meta["artifacts"]["output_mp4"] = ""
        save_meta(meta)
        return transition(meta, "render_done")


def step_packaging(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "packaging_running")
    task_id = meta["task_id"]
    narration_copy = read_text_artifact(
        meta["artifacts"].get("narration_copy") or artifact_path(task_id, "narration_copy.txt")
    )
    digest = read_text_artifact(meta["artifacts"].get("digest") or artifact_path(task_id, "digest.md"))
    script_items: List[Dict[str, Any]] = []
    script_path = meta["artifacts"].get("script_json") or artifact_path(task_id, "script.json")
    if os.path.isfile(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        script_items = data.get("items") if isinstance(data, dict) else data or []

    inputs = meta.get("inputs") or {}
    pack_payload: Dict[str, Any]
    # 默认本地标题包装（秒级）；需要 LLM 质量时设 CROSS_BORDER_PACKAGING_LLM=1
    prefer_llm_pack = os.environ.get("CROSS_BORDER_PACKAGING_LLM", "").lower() in {
        "1",
        "true",
        "yes",
    }
    pack_via = "fallback"
    try:
        if not prefer_llm_pack:
            raise RuntimeError("local packaging preferred")
        params = _prompt_params(
            meta,
            source_digest=digest,
            narration_copy=narration_copy,
        )
        prompt = _render_prompt("title_packaging", params)
        raw = _generate_text(
            prompt,
            system_prompt=_system_prompt("title_packaging"),
            max_attempts=1,
        )
        data = _extract_json(raw)
        pack_payload = packaging_mod.build_packaging_payload(
            direction=meta.get("direction") or "inbound",
            narration_copy=narration_copy,
            titles=data.get("titles"),
            cover_text=data.get("cover_text") or "",
            description=data.get("description") or "",
            tags=data.get("tags"),
            caption=data.get("caption") or "",
            credit_line=data.get("credit_line") or "",
            credit_hint=inputs.get("credit_hint") or "",
            source_credit=bool(inputs.get("source_credit", True)),
            script_items=script_items,
            original_audio_ratio_target=float(inputs.get("original_audio_ratio") or 30),
        )
        pack_via = "llm"
        append_log(meta, "title packaging via LLM")
    except Exception as exc:
        if prefer_llm_pack:
            append_log(meta, f"title packaging fallback: {exc}", level="WARNING")
        else:
            append_log(meta, "title packaging via local fallback (fast path)")
        fb = packaging_mod.fallback_titles_from_copy(
            meta.get("direction") or "inbound", narration_copy
        )
        pack_payload = packaging_mod.build_packaging_payload(
            direction=meta.get("direction") or "inbound",
            narration_copy=narration_copy,
            titles=fb.get("titles"),
            cover_text=fb.get("cover_text") or "",
            description=fb.get("description") or "",
            tags=fb.get("tags"),
            caption=fb.get("caption") or "",
            credit_hint=inputs.get("credit_hint") or "",
            source_credit=bool(inputs.get("source_credit", True)),
            script_items=script_items,
            original_audio_ratio_target=float(inputs.get("original_audio_ratio") or 30),
        )

    paths = packaging_mod.write_export_bundle(task_id, pack_payload, meta)
    meta["artifacts"]["titles"] = paths.get("packaging") or ""
    meta["artifacts"]["description"] = paths.get("packaging") or ""
    meta["artifacts"]["compliance"] = paths.get("compliance") or ""
    meta["artifacts"]["export_dir"] = artifact_path(task_id, "export")
    save_meta(meta)
    meta = transition(meta, "packaging_done")
    return transition(meta, "completed")


def step_separate(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    配音模式：人声/伴奏分离。
    demucs 可选；不可用时 center_cancel / duck 自动降级。
    """
    from .dubbing import separate as separate_mod

    meta = transition(meta, "separate_running")
    task_id = meta["task_id"]
    inputs = meta.get("inputs") or {}
    artifacts = meta.setdefault("artifacts", {})
    video_path = inputs.get("video_path") or ""
    if not video_path or not os.path.isfile(video_path):
        return _set_failed(meta, "video missing before separate", step="separate")

    audio_dir = artifact_path(task_id, "audio")
    backend = str(inputs.get("separate_backend") or "auto")
    duck_gain = float(inputs.get("duck_gain") if inputs.get("duck_gain") is not None else 0.18)

    try:
        result = separate_mod.separate_audio(
            video_path,
            audio_dir,
            backend=backend,
            duck_gain=duck_gain,
        )
    except Exception as exc:
        logger.exception("separate failed")
        return _set_failed(meta, f"separate failed: {exc}", step="separate")

    artifacts["source_wav"] = result.get("source_wav") or ""
    artifacts["vocals_wav"] = result.get("vocals_wav") or ""
    artifacts["no_vocals_wav"] = result.get("no_vocals_wav") or ""
    artifacts["separate_backend"] = result.get("backend") or backend
    inputs["separate_backend_used"] = result.get("backend") or backend
    write_json_artifact(
        task_id,
        "separate.json",
        {
            "backend": result.get("backend"),
            "demucs_available": result.get("demucs_available"),
            "note": result.get("note"),
            "source_wav": result.get("source_wav"),
            "vocals_wav": result.get("vocals_wav"),
            "no_vocals_wav": result.get("no_vocals_wav"),
        },
    )
    append_log(
        meta,
        f"separate backend={result.get('backend')} note={result.get('note')}",
        level="WARNING" if result.get("backend") != "demucs" else "INFO",
    )
    save_meta(meta)
    return transition(meta, "separate_done")


def step_dub_tts(meta: Dict[str, Any]) -> Dict[str, Any]:
    """配音模式：目标字幕逐句 TTS → 时间轴配音轨。"""
    from .dubbing import mix as mix_mod
    from .dubbing import synthesize as synth_mod
    from .dubbing.voices import normalize_lang, resolve_voice_for_lang

    meta = transition(meta, "dub_tts_running")
    task_id = meta["task_id"]
    inputs = meta.get("inputs") or {}
    artifacts = meta.setdefault("artifacts", {})
    target_srt = artifacts.get("target_srt") or artifact_path(task_id, "target.srt")
    if not os.path.isfile(target_srt) or os.path.getsize(target_srt) < 5:
        return _set_failed(meta, "target.srt missing/empty before dub_tts", step="dub_tts")

    srt_text = read_text_artifact(target_srt)
    work_dir = artifact_path(task_id, "dub")
    video_path = inputs.get("video_path") or ""
    total_dur = 0.0
    if video_path and os.path.isfile(video_path):
        total_dur = mix_mod.probe_duration_seconds(video_path)
    if total_dur <= 0 and artifacts.get("source_wav"):
        total_dur = mix_mod.probe_duration_seconds(artifacts["source_wav"])

    lang = normalize_lang(meta.get("target_lang") or inputs.get("target_lang") or "en")
    gender = str(inputs.get("voice_gender") or "female")
    raw_voice = (inputs.get("voice_name") or "").strip()
    voice_name, voice_corrected = resolve_voice_for_lang(
        lang, raw_voice, gender=gender, force_match=True
    )
    voice_rate = float(inputs.get("voice_rate") or 1.0)
    voice_pitch = float(inputs.get("voice_pitch") or 1.0)
    tts_engine = (inputs.get("tts_engine") or "edge_tts").strip() or "edge_tts"
    workers = synth_mod._tts_worker_count(tts_engine)
    append_log(
        meta,
        f"dub_tts start lang={lang} voice={voice_name} engine={tts_engine} workers={workers}",
    )
    save_meta(meta)

    try:
        result = synth_mod.synthesize_from_srt(
            srt_text,
            work_dir,
            target_lang=lang,
            voice_name=voice_name,
            voice_rate=voice_rate,
            voice_pitch=voice_pitch,
            tts_engine=tts_engine,
            total_duration=total_dur,
            voice_gender=gender,
            force_voice_lang_match=True,
        )
    except Exception as exc:
        logger.exception("dub_tts failed")
        return _set_failed(meta, f"dub_tts failed: {exc}", step="dub_tts")

    artifacts["dub_voice_wav"] = result.get("timeline_wav") or ""
    artifacts["tts_dir"] = result.get("tts_dir") or ""
    artifacts["dub_tts_meta"] = artifact_path(task_id, "dub/tts_meta.json")
    # segments 可能很大，只落关键字段
    write_json_artifact(
        task_id,
        "dub/tts_meta.json",
        {
            "voice_name": result.get("voice_name"),
            "voice_corrected": bool(result.get("voice_corrected") or voice_corrected),
            "target_lang": result.get("target_lang"),
            "segment_count": result.get("segment_count"),
            "cue_count": result.get("cue_count"),
            "timeline_wav": result.get("timeline_wav"),
            "total_duration": result.get("total_duration"),
            "segments": [
                {
                    "id": s.get("id"),
                    "start": s.get("start"),
                    "end": s.get("end"),
                    "duration": s.get("duration"),
                    "slot": s.get("slot"),
                    "text": s.get("text"),
                    "audio_file": s.get("audio_file"),
                }
                for s in (result.get("segments") or [])
            ],
        },
    )
    inputs["voice_name"] = result.get("voice_name") or voice_name
    if result.get("voice_corrected") or voice_corrected:
        append_log(
            meta,
            f"voice auto-matched to target_lang={lang}: {raw_voice or '(empty)'} → {inputs['voice_name']}",
            level="WARNING",
        )
    append_log(
        meta,
        f"dub_tts voice={result.get('voice_name')} lang={result.get('target_lang')} "
        f"segments={result.get('segment_count')}/{result.get('cue_count')}",
    )
    save_meta(meta)
    return transition(meta, "dub_tts_done")


def step_mix(meta: Dict[str, Any]) -> Dict[str, Any]:
    """配音模式：伴奏 + 配音混音，回贴到视频（尚不烧字幕）。"""
    from .dubbing import mix as mix_mod

    meta = transition(meta, "mix_running")
    task_id = meta["task_id"]
    inputs = meta.get("inputs") or {}
    artifacts = meta.setdefault("artifacts", {})
    video_path = inputs.get("video_path") or ""
    no_vocals = artifacts.get("no_vocals_wav") or artifact_path(task_id, "audio/no_vocals.wav")
    dub_voice = artifacts.get("dub_voice_wav") or artifact_path(task_id, "dub/dub_voice.wav")

    if not video_path or not os.path.isfile(video_path):
        return _set_failed(meta, "video missing before mix", step="mix")
    if not os.path.isfile(no_vocals):
        return _set_failed(meta, "no_vocals.wav missing before mix", step="mix")
    if not os.path.isfile(dub_voice):
        return _set_failed(meta, "dub_voice.wav missing before mix", step="mix")

    mixed_wav = artifact_path(task_id, "dub/mixed.wav")
    # 默认配音压过伴奏：旧任务 0.9/1.15 实测会被 BGM 盖住
    iv = float(
        inputs.get("instrumental_volume")
        if inputs.get("instrumental_volume") is not None
        else 0.55
    )
    vv = float(
        inputs.get("dub_voice_volume")
        if inputs.get("dub_voice_volume") is not None
        else 1.8
    )
    # 兼容旧任务：若仍是偏弱默认，自动抬配音、压伴奏
    try:
        if abs(iv - 0.9) < 1e-6 and abs(vv - 1.15) < 1e-6:
            iv, vv = 0.55, 1.8
            append_log(
                meta,
                "auto-boost dub mix levels (legacy 0.9/1.15 → 0.55/1.8)",
                level="WARNING",
            )
    except Exception:
        pass
    # 默认开启 sidechain：人声出现时压低伴奏，更贴片
    sidechain = inputs.get("sidechain_duck")
    if sidechain is None:
        sidechain = True
    try:
        mix_mod.mix_instrumental_and_voice(
            instrumental_wav=no_vocals,
            voice_wav=dub_voice,
            output_wav=mixed_wav,
            instrumental_volume=iv,
            voice_volume=vv,
            sidechain_duck=bool(sidechain),
        )
        dubbed_mp4 = artifact_path(task_id, "dub/dubbed.mp4")
        mix_mod.mux_video_with_audio(
            video_path=video_path,
            audio_path=mixed_wav,
            output_mp4=dubbed_mp4,
        )
    except Exception as exc:
        logger.exception("mix failed")
        return _set_failed(meta, f"mix failed: {exc}", step="mix")

    if not os.path.isfile(dubbed_mp4) or os.path.getsize(dubbed_mp4) < 1000:
        return _set_failed(meta, "mix produced empty dubbed.mp4", step="mix")

    artifacts["mixed_wav"] = mixed_wav
    artifacts["dubbed_mp4"] = dubbed_mp4
    # 若后续不烧字幕，也把 dubbed 当作成片
    if not bool(inputs.get("burn_after_mix", True)):
        export_dir = artifact_path(task_id, "export")
        os.makedirs(export_dir, exist_ok=True)
        output_mp4 = os.path.join(export_dir, "output.mp4")
        try:
            shutil.copy2(dubbed_mp4, output_mp4)
            artifacts["output_mp4"] = output_mp4
            artifacts["export_dir"] = export_dir
        except OSError as exc:
            append_log(meta, f"copy dubbed to export failed: {exc}", level="WARNING")
            artifacts["output_mp4"] = dubbed_mp4

    append_log(meta, f"mixed audio → {dubbed_mp4}")
    save_meta(meta)
    meta = transition(meta, "mix_done")
    if not bool(inputs.get("burn_after_mix", True)):
        return transition(meta, "completed")
    return meta


def step_burn(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    VideoLingo 风格：视频 + 目标字幕 → 硬烧成片。
    字幕模式：原片 + 原声；配音模式：优先用混音后的 dubbed.mp4。
    可选双语：目标在上 / 源在下。
    """
    meta = transition(meta, "burn_running")
    task_id = meta["task_id"]
    inputs = meta.get("inputs") or {}
    artifacts = meta.setdefault("artifacts", {})
    mode = _task_mode(meta)
    # 配音模式烧在已替换音轨的视频上
    video_path = ""
    if mode == "dubbing":
        video_path = artifacts.get("dubbed_mp4") or ""
    if not video_path or not os.path.isfile(video_path):
        video_path = inputs.get("video_path") or ""
    target_srt = artifacts.get("target_srt") or artifact_path(task_id, "target.srt")
    source_srt = artifacts.get("source_srt") or artifact_path(task_id, "source.srt")

    if not video_path or not os.path.isfile(video_path):
        return _set_failed(meta, "video missing before burn", step="burn")
    if not os.path.isfile(target_srt) or os.path.getsize(target_srt) < 5:
        return _set_failed(meta, "target.srt missing/empty before burn", step="burn")

    bilingual = bool(inputs.get("bilingual"))
    burn_srt_path = artifact_path(task_id, "burn.srt")
    if bilingual and os.path.isfile(source_srt):
        src_text = read_text_artifact(source_srt)
        tgt_text = read_text_artifact(target_srt)
        merged = burn_mod.build_bilingual_srt(src_text, tgt_text, order="target_first")
        if not merged.strip():
            # 合并失败则退回单语目标字幕
            merged = tgt_text
            append_log(meta, "bilingual merge empty, fallback to target.srt", level="WARNING")
        write_text_artifact(task_id, "burn.srt", merged)
        append_log(meta, "built bilingual burn.srt (target over source)")
    else:
        # 单语：直接用目标字幕
        tgt_text = read_text_artifact(target_srt)
        write_text_artifact(task_id, "burn.srt", tgt_text if tgt_text.endswith("\n") else tgt_text + "\n")
        append_log(meta, "using target.srt for burn")

    artifacts["burn_srt"] = burn_srt_path
    export_dir = artifact_path(task_id, "export")
    os.makedirs(export_dir, exist_ok=True)
    output_mp4 = os.path.join(export_dir, "output.mp4")

    try:
        burn_mod.burn_subtitles_to_video(
            video_path=video_path,
            subtitle_path=burn_srt_path,
            output_path=output_mp4,
            options=inputs,
        )
    except Exception as exc:
        logger.exception("burn failed")
        return _set_failed(meta, f"burn failed: {exc}", step="burn")

    if not os.path.isfile(output_mp4) or os.path.getsize(output_mp4) < 1000:
        return _set_failed(meta, "burn produced empty output.mp4", step="burn")

    artifacts["output_mp4"] = output_mp4
    artifacts["export_dir"] = export_dir
    # 同步一份字幕到 export 方便下载
    try:
        export_srt = os.path.join(export_dir, "subtitle.srt")
        shutil.copy2(burn_srt_path, export_srt)
        artifacts["export_srt"] = export_srt
    except OSError as exc:
        append_log(meta, f"copy export srt failed: {exc}", level="WARNING")

    append_log(meta, f"burned subtitles → {output_mp4}")
    save_meta(meta)
    meta = transition(meta, "burn_done")
    return transition(meta, "completed")


STEP_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "asr": step_asr,
    "translate": step_translate,
    "digest": step_digest,
    "copy": step_copy,
    "match": step_match,
    "tts": step_tts,
    "render": step_render,
    "packaging": step_packaging,
    "burn": step_burn,
    "separate": step_separate,
    "dub_tts": step_dub_tts,
    "mix": step_mix,
}


def _task_mode(meta: Dict[str, Any]) -> str:
    mode = (meta.get("mode") or (meta.get("inputs") or {}).get("mode") or "subtitle")
    mode = str(mode).strip().lower()
    return mode if mode in {"subtitle", "narration", "dubbing"} else "subtitle"


def run_from(meta: Dict[str, Any], start_step: str = "asr", stop_after: Optional[str] = None) -> Dict[str, Any]:
    """
    同步执行从 start_step 到 stop_after（含）的步骤。
    按 meta.mode 选择步骤链：
      - subtitle（默认）：asr → translate → burn → completed
      - narration：asr → … → packaging → completed
      - dubbing：asr → translate → separate → dub_tts → mix → burn → completed
    解说模式若要在 copy 人工卡点，请 stop_after='copy'。
    """
    mode = _task_mode(meta)
    steps = steps_for_mode(mode)
    if start_step not in steps:
        # 兼容：旧任务或跨模式重试
        if start_step in STEP_HANDLERS:
            steps = list(dict.fromkeys(list(steps) + [start_step]))
        else:
            raise ValueError(f"unknown step for mode={mode}: {start_step}")

    # 入队 / 失败恢复
    if meta.get("status") in {None, "draft", "failed", "cancelled"}:
        try:
            meta = transition(meta, "queued")
        except InvalidTransitionError:
            meta["status"] = "queued"
            meta["error"] = None
            save_meta(meta)

    started = False
    for step in steps:
        if not started:
            if step != start_step:
                continue
            started = True
        handler = globals().get(f"step_{step}") or STEP_HANDLERS.get(step)
        if handler is None:
            return _set_failed(meta, f"missing handler for step: {step}", step=step)
        try:
            meta = handler(meta)
        except Exception as exc:
            logger.exception(f"cross_border step {step} crashed")
            return _set_failed(
                meta,
                f"{step} crashed: {exc}\n{traceback.format_exc()[-500:]}",
                step=step,
            )

        if meta.get("status") == "failed":
            err = meta.get("error") or {}
            if not err.get("step"):
                meta["error"] = {**err, "step": step, "message": err.get("message") or "failed"}
                meta["step"] = step
                save_meta(meta)
            return meta
        if meta.get("status") == "completed":
            return meta
        if stop_after and step == stop_after:
            return meta
        # 解说模式环境变量卡点
        if (
            mode == "narration"
            and step == "copy"
            and os.environ.get("CROSS_BORDER_STOP_AT_COPY", "").lower()
            in {"1", "true", "yes"}
        ):
            return meta
    return meta


def run_task(task_id: str, start_step: str = "asr", stop_after: Optional[str] = None) -> Dict[str, Any]:
    meta = load_meta(task_id)
    return run_from(meta, start_step=start_step, stop_after=stop_after)


_STOP_AFTER_UNSET = object()


def start_task_background(
    task_id: str,
    start_step: str = "asr",
    stop_after: Any = _STOP_AFTER_UNSET,
) -> bool:
    """
    后台线程跑 pipeline。
    - subtitle 模式默认跑完全程（asr→translate→burn）
    - dubbing 模式默认跑完全程（asr→…→mix→burn）
    - narration 模式默认停在 copy（人工审文案）；显式传 stop_after=None 跑完全程
    返回 False 表示已有线程在跑。
    """
    with _lock:
        t = _running_threads.get(task_id)
        if t and t.is_alive():
            return False

        # 未显式指定时：按模式给默认 stop；显式 None 表示不卡点
        resolved_stop: Optional[str]
        if stop_after is _STOP_AFTER_UNSET:
            resolved_stop = None
            try:
                meta0 = load_meta(task_id)
                if _task_mode(meta0) == "narration":
                    resolved_stop = "copy"
            except Exception:
                resolved_stop = None
        else:
            resolved_stop = stop_after  # type: ignore[assignment]

        def _target():
            try:
                run_task(task_id, start_step=start_step, stop_after=resolved_stop)
            except Exception as exc:
                logger.exception(f"background task {task_id} failed: {exc}")
                try:
                    meta = load_meta(task_id)
                    _set_failed(meta, str(exc))
                except Exception:
                    pass
            finally:
                with _lock:
                    _running_threads.pop(task_id, None)

        thread = threading.Thread(target=_target, name=f"cross_border_{task_id}", daemon=True)
        _running_threads[task_id] = thread
        thread.start()
        return True


def is_running(task_id: str) -> bool:
    with _lock:
        t = _running_threads.get(task_id)
        return bool(t and t.is_alive())


def continue_after_copy(task_id: str) -> bool:
    """文案审核后从 match 跑到结束（仅 narration 模式）。"""
    return start_task_background(task_id, start_step="match", stop_after=None)


def continue_after_translate(task_id: str) -> bool:
    """字幕/配音：审核字幕后继续。字幕→burn；配音→separate。"""
    try:
        meta = load_meta(task_id)
        mode = _task_mode(meta)
    except Exception:
        mode = "subtitle"
    if mode == "dubbing":
        return start_task_background(task_id, start_step="separate", stop_after=None)
    return start_task_background(task_id, start_step="burn", stop_after=None)


def continue_after_separate(task_id: str) -> bool:
    """配音模式：从 dub_tts 跑到结束。"""
    return start_task_background(task_id, start_step="dub_tts", stop_after=None)


def rerun_dub_tts(task_id: str) -> bool:
    """配音模式：换音色后从 dub_tts 重跑到结束。"""
    return start_task_background(task_id, start_step="dub_tts", stop_after=None)
