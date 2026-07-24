#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境任务 ASR 路由。

优先级（可被 meta.inputs.asr_backend / 环境变量覆盖）：
1. 已有 source.srt / 同名旁挂字幕
2. 项目 FunASR 后端：local | firered | bailian（读 config.fun_asr）
3. 可选本地 whisper（需已安装 openai-whisper）
4. 占位字幕（允许人工补齐后继续）
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


SUPPORTED_BACKENDS = ("auto", "local", "firered", "bailian", "whisper", "manual")


def resolve_asr_backend(meta: Optional[Dict[str, Any]] = None) -> str:
    """解析 ASR 后端：任务覆盖 > 环境变量 > config.fun_asr.backend > auto。"""
    inputs = (meta or {}).get("inputs") or {}
    explicit = str(inputs.get("asr_backend") or "").strip().lower()
    if explicit in SUPPORTED_BACKENDS:
        return explicit

    env_backend = str(os.environ.get("CROSS_BORDER_ASR_BACKEND") or "").strip().lower()
    if env_backend in SUPPORTED_BACKENDS:
        return env_backend

    try:
        from app.config import config

        cfg_backend = str((config.fun_asr or {}).get("backend") or "").strip().lower()
        if cfg_backend in {"local", "firered", "bailian"}:
            return cfg_backend
    except Exception as exc:
        logger.debug(f"resolve_asr_backend config skip: {exc}")

    return "auto"


def backend_chain(preferred: str, source_lang: str = "") -> List[str]:
    """
    生成尝试顺序。

    auto 时按源语言倾向：
    - zh: local → firered → bailian → whisper
    - en/other: firered → local → bailian → whisper
    """
    preferred = (preferred or "auto").strip().lower()
    if preferred == "manual":
        return []
    if preferred in {"local", "firered", "bailian", "whisper"}:
        # 主后端失败时仍回退其余路径
        rest = [b for b in ("local", "firered", "bailian", "whisper") if b != preferred]
        return [preferred] + rest

    lang = (source_lang or "").strip().lower()[:2]
    if lang == "zh":
        return ["local", "firered", "bailian", "whisper"]
    return ["firered", "local", "bailian", "whisper"]


def _copy_if_needed(src: str, dst: str) -> str:
    if not src:
        raise FileNotFoundError("empty asr output path")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"asr output missing: {src}")
    if os.path.abspath(src) != os.path.abspath(dst):
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


def _try_local_fun_asr(video_path: str, subtitle_file: str) -> str:
    from app.config import config
    from app.services import fun_asr_subtitle

    api_url = str(
        (config.fun_asr or {}).get("api_url") or fun_asr_subtitle.LOCAL_FUN_ASR_API_URL
    ).strip()
    if not api_url:
        raise ValueError("fun_asr.api_url empty")
    hotword = str((config.fun_asr or {}).get("hotword") or "").strip()
    enable_spk = bool((config.fun_asr or {}).get("enable_spk", False))
    out = fun_asr_subtitle.create_with_local_fun_asr(
        local_file=video_path,
        subtitle_file=subtitle_file,
        api_url=api_url,
        hotword=hotword,
        enable_spk=enable_spk,
    )
    return _copy_if_needed(out or "", subtitle_file)


def _try_firered(video_path: str, subtitle_file: str) -> str:
    from app.config import config
    from app.services import fun_asr_subtitle

    api_url = str(
        (config.fun_asr or {}).get("firered_api_url")
        or fun_asr_subtitle.LOCAL_FIRERED_ASR_API_URL
    ).strip()
    if not api_url:
        raise ValueError("fun_asr.firered_api_url empty")
    out = fun_asr_subtitle.create_with_local_firered_asr(
        local_file=video_path,
        subtitle_file=subtitle_file,
        api_url=api_url,
    )
    return _copy_if_needed(out or "", subtitle_file)


def _try_bailian(video_path: str, subtitle_file: str) -> str:
    from app.config import config
    from app.services import fun_asr_subtitle

    api_key = str((config.fun_asr or {}).get("api_key") or "").strip()
    if not api_key:
        raise ValueError("fun_asr.api_key empty for bailian backend")
    out = fun_asr_subtitle.create_with_fun_asr(
        local_file=video_path,
        subtitle_file=subtitle_file,
        api_key=api_key,
    )
    return _copy_if_needed(out or "", subtitle_file)


def _try_whisper(video_path: str, subtitle_file: str, source_lang: str = "") -> str:
    import whisper  # type: ignore

    model_name = os.environ.get("CROSS_BORDER_WHISPER_MODEL", "small")
    model = whisper.load_model(model_name)
    language = (source_lang or "").strip()[:2] or None
    result = model.transcribe(video_path, language=language)

    def _sec_to_srt(sec: float) -> str:
        ms = int(round(float(sec) * 1000))
        h, rem = divmod(ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, milli = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    lines: List[str] = []
    for i, seg in enumerate(result.get("segments") or [], start=1):
        start = _sec_to_srt(seg.get("start") or 0)
        end = _sec_to_srt(seg.get("end") or 0)
        text = (seg.get("text") or "").strip()
        lines.extend([str(i), f"{start} --> {end}", text, ""])
    content = "\n".join(lines).strip() + "\n"
    if not content.strip():
        raise RuntimeError("whisper returned empty transcript")
    parent = os.path.dirname(subtitle_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(content)
    return subtitle_file


_BACKEND_RUNNERS = {
    "local": lambda video, srt, lang: _try_local_fun_asr(video, srt),
    "firered": lambda video, srt, lang: _try_firered(video, srt),
    "bailian": lambda video, srt, lang: _try_bailian(video, srt),
    "whisper": lambda video, srt, lang: _try_whisper(video, srt, lang),
}


def write_placeholder_srt(subtitle_file: str) -> str:
    content = (
        "1\n00:00:00,000 --> 00:00:02,000\n"
        "[ASR placeholder — replace source.srt with real subtitles]\n"
    )
    parent = os.path.dirname(subtitle_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(content)
    return subtitle_file


def is_placeholder_srt(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read(500)
        return "ASR placeholder" in text
    except Exception:
        return False


def run_asr(
    *,
    video_path: str,
    subtitle_file: str,
    source_lang: str = "",
    preferred_backend: str = "auto",
) -> Tuple[str, str, List[str]]:
    """
    执行 ASR。

    Returns:
        (output_srt_path, used_backend, attempt_logs)
        used_backend 可能为 placeholder
    """
    logs: List[str] = []
    if not video_path or not os.path.isfile(video_path):
        write_placeholder_srt(subtitle_file)
        logs.append("video missing; wrote placeholder srt")
        return subtitle_file, "placeholder", logs

    chain = backend_chain(preferred_backend, source_lang)
    if not chain:
        write_placeholder_srt(subtitle_file)
        logs.append("manual backend selected; wrote placeholder for human upload")
        return subtitle_file, "placeholder", logs

    last_error = ""
    for backend in chain:
        runner = _BACKEND_RUNNERS.get(backend)
        if not runner:
            continue
        try:
            logs.append(f"trying ASR backend={backend}")
            out = runner(video_path, subtitle_file, source_lang)
            if out and os.path.isfile(out) and os.path.getsize(out) > 0:
                if is_placeholder_srt(out):
                    raise RuntimeError("backend returned placeholder content")
                logs.append(f"ASR success via {backend}: {out}")
                return out, backend, logs
            raise RuntimeError(f"{backend} returned empty srt")
        except Exception as exc:
            last_error = f"{backend}: {exc}"
            logs.append(f"ASR backend failed: {last_error}")
            logger.warning(f"cross_border ASR {last_error}")

    write_placeholder_srt(subtitle_file)
    logs.append(f"all ASR backends failed; placeholder written. last={last_error}")
    return subtitle_file, "placeholder", logs
