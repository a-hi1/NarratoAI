#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化 pipeline 骨架。

W1 目标：
- 任务目录 + 状态机可跑通
- LLM 步骤（digest/copy/match/package）可在已有 LLM 配置下执行
- ASR/translate/TTS/render 可插拔；缺依赖时写入占位产物并允许人工补齐后继续
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

from . import packaging as packaging_mod
from .glossary import format_glossary_for_prompt, normalize_glossary
from .state_machine import (
    InvalidTransitionError,
    PIPELINE_STEPS,
    next_running_after,
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


def _set_failed(meta: Dict[str, Any], message: str) -> Dict[str, Any]:
    append_log(meta, message, level="ERROR")
    try:
        return transition(meta, "failed", error=message)
    except InvalidTransitionError:
        meta["status"] = "failed"
        meta["error"] = {"step": meta.get("step"), "message": message}
        return save_meta(meta)


def _ensure_llm_providers():
    try:
        from app.services.llm import register_all_providers

        register_all_providers()
    except Exception as exc:
        logger.warning(f"register_all_providers skipped: {exc}")


def _generate_text(prompt: str, system_prompt: Optional[str] = None) -> str:
    _ensure_llm_providers()
    from app.services.llm.migration_adapter import _run_async_safely
    from app.services.llm.unified_service import UnifiedLLMService

    return _run_async_safely(
        UnifiedLLMService.generate_text,
        prompt=prompt,
        system_prompt=system_prompt,
    )


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

    # 若用户已放置字幕则跳过识别
    if os.path.isfile(source_srt) and os.path.getsize(source_srt) > 0:
        append_log(meta, f"reuse existing source.srt: {source_srt}")
        meta["artifacts"]["source_srt"] = source_srt
        save_meta(meta)
        return transition(meta, "asr_done")

    # 尝试从同名 srt 复制
    if video_path:
        sibling = os.path.splitext(video_path)[0] + ".srt"
        if os.path.isfile(sibling):
            shutil.copy2(sibling, source_srt)
            meta["artifacts"]["source_srt"] = source_srt
            append_log(meta, f"copied sibling subtitle: {sibling}")
            save_meta(meta)
            return transition(meta, "asr_done")

    # 尝试 Whisper（可选）
    try:
        import whisper  # type: ignore

        append_log(meta, "running local whisper ASR")
        model_name = os.environ.get("CROSS_BORDER_WHISPER_MODEL", "small")
        model = whisper.load_model(model_name)
        language = (meta.get("source_lang") or None)
        if language:
            language = language[:2]
        result = model.transcribe(video_path, language=language)
        lines = []
        for i, seg in enumerate(result.get("segments") or [], start=1):
            start = _sec_to_srt(seg.get("start") or 0)
            end = _sec_to_srt(seg.get("end") or 0)
            text = (seg.get("text") or "").strip()
            lines.extend([str(i), f"{start} --> {end}", text, ""])
        write_text_artifact(task_id, "source.srt", "\n".join(lines).strip() + "\n")
        meta["artifacts"]["source_srt"] = source_srt
        save_meta(meta)
        return transition(meta, "asr_done")
    except Exception as exc:
        append_log(meta, f"ASR auto path unavailable: {exc}", level="WARNING")

    # 占位：允许用户稍后上传 source.srt
    placeholder = (
        "1\n00:00:00,000 --> 00:00:02,000\n"
        "[ASR placeholder — replace source.srt with real subtitles]\n"
    )
    write_text_artifact(task_id, "source.srt", placeholder)
    meta["artifacts"]["source_srt"] = source_srt
    append_log(
        meta,
        "ASR placeholder written. Put real source.srt then retry translate/digest.",
        level="WARNING",
    )
    save_meta(meta)
    return transition(meta, "asr_done")


def _sec_to_srt(sec: float) -> str:
    ms = int(round(float(sec) * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def step_translate(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "translate_running")
    task_id = meta["task_id"]
    source_srt = meta["artifacts"].get("source_srt") or artifact_path(task_id, "source.srt")
    target_srt = artifact_path(task_id, "target.srt")

    if not os.path.isfile(source_srt):
        return _set_failed(meta, "source.srt missing before translate")

    # 已有目标字幕则复用
    if os.path.isfile(target_srt) and os.path.getsize(target_srt) > 10:
        meta["artifacts"]["target_srt"] = target_srt
        append_log(meta, "reuse existing target.srt")
        save_meta(meta)
        return transition(meta, "translate_done")

    target_lang = meta.get("target_lang") or "zh"
    glossary_block = format_glossary_for_prompt((meta.get("inputs") or {}).get("glossary"))

    lang_label = {
        "zh": "中文",
        "en": "English",
        "ja": "日本語",
        "ko": "한국어",
    }.get((target_lang or "zh")[:2].lower(), target_lang or "中文")

    try:
        from app.services.subtitle_translator import translate_subtitle_file

        out = translate_subtitle_file(
            source_srt,
            target_srt,
            target_language=lang_label,
        )
        # translate_subtitle_file may write a different path if output empty
        if out and os.path.isfile(out):
            if os.path.abspath(out) != os.path.abspath(target_srt):
                shutil.copy2(out, target_srt)
            meta["artifacts"]["target_srt"] = target_srt
            append_log(meta, "translated via subtitle_translator")
            # glossary note retained in logs for later prompt injection
            if glossary_block:
                append_log(meta, "glossary will be enforced mainly in digest/copy prompts")
            save_meta(meta)
            return transition(meta, "translate_done")
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
            write_text_artifact(task_id, "target.srt", translated.strip() + "\n")
            meta["artifacts"]["target_srt"] = target_srt
            append_log(meta, "translated via LLM fallback")
            save_meta(meta)
            return transition(meta, "translate_done")
        except Exception as exc2:
            shutil.copy2(source_srt, target_srt)
            meta["artifacts"]["target_srt"] = target_srt
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
    prompt = _render_prompt("script_matching", params)
    try:
        raw = _generate_text(prompt, system_prompt=_system_prompt("script_matching"))
        data = _extract_json(raw)
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            raise ValueError("script items empty")
        # 补默认字段
        video_name = _video_basename(meta)
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            item.setdefault("_id", i)
            item.setdefault("video_id", 1)
            item.setdefault("video_name", video_name)
            item.setdefault("OST", 0)
    except Exception as exc:
        return _set_failed(meta, f"script_matching failed: {exc}")

    path = write_json_artifact(task_id, "script.json", {"items": items})
    meta["artifacts"]["script_json"] = path
    save_meta(meta)
    return transition(meta, "match_done")


def step_tts(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "tts_running")
    task_id = meta["task_id"]
    tts_dir = artifact_path(task_id, "tts")
    os.makedirs(tts_dir, exist_ok=True)
    meta["artifacts"]["tts_dir"] = tts_dir

    script_path = meta["artifacts"].get("script_json") or artifact_path(task_id, "script.json")
    items = []
    if os.path.isfile(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data.get("items") if isinstance(data, dict) else data

    voice = (meta.get("inputs") or {}).get("voice_name") or ""
    generated = 0
    try:
        # 尝试 edge-tts 批量（可选）
        import asyncio
        import edge_tts  # type: ignore

        async def _one(text: str, out_path: str, voice_name: str):
            communicate = edge_tts.Communicate(text, voice_name)
            await communicate.save(out_path)

        async def _all():
            nonlocal generated
            for item in items:
                if not isinstance(item, dict) or int(item.get("OST", 0) or 0) == 1:
                    continue
                text = str(item.get("narration") or "").strip()
                if not text or text.startswith("播放原片"):
                    continue
                out = os.path.join(tts_dir, f"{int(item.get('_id') or 0):04d}.mp3")
                v = voice or (
                    "zh-CN-XiaoyiNeural"
                    if (meta.get("target_lang") or "zh").startswith("zh")
                    else "en-US-JennyNeural"
                )
                await _one(text, out, v)
                generated += 1

        if items:
            asyncio.run(_all())
            append_log(meta, f"edge-tts generated {generated} clips")
        else:
            append_log(meta, "no script items for tts", level="WARNING")
    except Exception as exc:
        # 占位
        note = os.path.join(tts_dir, "README.txt")
        with open(note, "w", encoding="utf-8") as f:
            f.write(
                "TTS not generated in this environment.\n"
                f"reason: {exc}\n"
                "Pipeline continues; wire app.services.voice later for production.\n"
            )
        append_log(meta, f"tts placeholder: {exc}", level="WARNING")

    save_meta(meta)
    return transition(meta, "tts_done")


def step_render(meta: Dict[str, Any]) -> Dict[str, Any]:
    meta = transition(meta, "render_running")
    task_id = meta["task_id"]
    # MVP：不强制接完整合成；写占位说明，保留 video 路径引用
    output = artifact_path(task_id, "output.mp4")
    video_path = (meta.get("inputs") or {}).get("video_path") or ""
    if video_path and os.path.isfile(video_path):
        # 不复制大文件，只记源路径；若需要可后续接 generate_video
        meta["artifacts"]["output_mp4"] = video_path
        append_log(
            meta,
            "render skeleton: using source video path as output reference; "
            "hook app.services.generate_video for real cut later",
            level="WARNING",
        )
    else:
        write_text_artifact(
            task_id,
            "output_pending.txt",
            "Render not run: missing source video or renderer not wired.\n",
        )
        meta["artifacts"]["output_mp4"] = ""
        append_log(meta, "render skipped: no video", level="WARNING")
    # 不伪造 mp4 二进制
    if not meta["artifacts"].get("output_mp4"):
        meta["artifacts"]["output_mp4"] = output if os.path.isfile(output) else ""
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
    try:
        params = _prompt_params(
            meta,
            source_digest=digest,
            narration_copy=narration_copy,
        )
        prompt = _render_prompt("title_packaging", params)
        raw = _generate_text(prompt, system_prompt=_system_prompt("title_packaging"))
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
        append_log(meta, "title packaging via LLM")
    except Exception as exc:
        append_log(meta, f"title packaging fallback: {exc}", level="WARNING")
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


STEP_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "asr": step_asr,
    "translate": step_translate,
    "digest": step_digest,
    "copy": step_copy,
    "match": step_match,
    "tts": step_tts,
    "render": step_render,
    "packaging": step_packaging,
}


def run_from(meta: Dict[str, Any], start_step: str = "asr", stop_after: Optional[str] = None) -> Dict[str, Any]:
    """
    同步执行从 start_step 到 stop_after（含）的步骤。
    默认跑完整链路；copy_done 不会自动停，调用方若要人工卡点请 stop_after='copy'。
    """
    if start_step not in PIPELINE_STEPS:
        raise ValueError(f"unknown step: {start_step}")

    # 入队
    if meta.get("status") in {None, "draft", "failed", "cancelled"}:
        try:
            meta = transition(meta, "queued")
        except InvalidTransitionError:
            meta["status"] = "queued"
            save_meta(meta)

    started = False
    for step in PIPELINE_STEPS:
        if not started:
            if step != start_step:
                continue
            started = True
        # 动态取 handler，便于测试 mock 模块级函数
        handler = globals().get(f"step_{step}") or STEP_HANDLERS.get(step)
        if handler is None:
            return _set_failed(meta, f"missing handler for step: {step}")
        try:
            meta = handler(meta)
        except Exception as exc:
            logger.exception(f"cross_border step {step} crashed")
            return _set_failed(meta, f"{step} crashed: {exc}\n{traceback.format_exc()[-500:]}")

        if meta.get("status") == "failed":
            return meta
        if stop_after and step == stop_after:
            return meta
        # 人工卡点：默认完整跑；若环境变量要求在 copy 暂停
        if step == "copy" and os.environ.get("CROSS_BORDER_STOP_AT_COPY", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            return meta
    return meta


def run_task(task_id: str, start_step: str = "asr", stop_after: Optional[str] = None) -> Dict[str, Any]:
    meta = load_meta(task_id)
    return run_from(meta, start_step=start_step, stop_after=stop_after)


def start_task_background(
    task_id: str,
    start_step: str = "asr",
    stop_after: Optional[str] = "copy",
) -> bool:
    """
    后台线程跑 pipeline。默认停在 copy（人工审文案）。
    返回 False 表示已有线程在跑。
    """
    with _lock:
        t = _running_threads.get(task_id)
        if t and t.is_alive():
            return False

        def _target():
            try:
                run_task(task_id, start_step=start_step, stop_after=stop_after)
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
    """文案审核后从 match 跑到结束。"""
    return start_task_background(task_id, start_step="match", stop_after=None)
