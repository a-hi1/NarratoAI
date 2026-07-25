#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境任务 ASR 路由。

无字幕文件时，从视频自动识别生成 source.srt：

优先级（可被 meta.inputs.asr_backend / 环境变量覆盖）：
1. 已有 source.srt / 同名旁挂字幕（pipeline 层处理）
2. 内置 faster-whisper（默认可靠路径，无需外部服务）
3. 项目 FunASR 后端：local | firered | bailian（读 config.fun_asr，仅服务可达时）
4. openai-whisper（若已安装）
5. 占位字幕（允许人工补齐后继续）
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


SUPPORTED_BACKENDS = (
    "auto",
    "whisper",
    "local",
    "firered",
    "bailian",
    "manual",
)

# 模块级缓存，避免重复加载模型
_FASTER_WHISPER_MODEL = None
_FASTER_WHISPER_KEY: Optional[Tuple[str, str]] = None


def resolve_asr_backend(meta: Optional[Dict[str, Any]] = None) -> str:
    """解析 ASR 后端：任务覆盖 > 环境变量 > config.fun_asr.backend > auto。"""
    inputs = (meta or {}).get("inputs") or {}
    explicit = str(inputs.get("asr_backend") or "").strip().lower()
    if explicit in SUPPORTED_BACKENDS:
        return explicit
    # 兼容旧值 whisper / faster_whisper
    if explicit in {"faster_whisper", "faster-whisper"}:
        return "whisper"

    env_backend = str(os.environ.get("CROSS_BORDER_ASR_BACKEND") or "").strip().lower()
    if env_backend in SUPPORTED_BACKENDS:
        return env_backend
    if env_backend in {"faster_whisper", "faster-whisper"}:
        return "whisper"

    try:
        from app.config import config

        cfg_backend = str((config.fun_asr or {}).get("backend") or "").strip().lower()
        # 配置里的 local/firered 仅表示偏好，auto 链仍会按可达性排序
        if cfg_backend in {"local", "firered", "bailian", "whisper"}:
            return cfg_backend
    except Exception as exc:
        logger.debug(f"resolve_asr_backend config skip: {exc}")

    return "auto"


def _url_reachable(url: str, timeout: float = 0.6) -> bool:
    if not url:
        return False
    try:
        import requests

        # 任意响应都算服务在线；连接失败才跳过
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        try:
            import requests

            # 有的 ASR 只开了 /health 或根路径 404，用 HEAD/GET 都试
            requests.head(url, timeout=timeout)
            return True
        except Exception:
            return False


def _local_funasr_url() -> str:
    try:
        from app.config import config
        from app.services import fun_asr_subtitle

        return str(
            (config.fun_asr or {}).get("api_url") or fun_asr_subtitle.LOCAL_FUN_ASR_API_URL
        ).strip()
    except Exception:
        return "http://127.0.0.1:7860"


def _firered_url() -> str:
    try:
        from app.config import config
        from app.services import fun_asr_subtitle

        return str(
            (config.fun_asr or {}).get("firered_api_url")
            or fun_asr_subtitle.LOCAL_FIRERED_ASR_API_URL
        ).strip()
    except Exception:
        return "http://127.0.0.1:7867"


def _bailian_ready() -> bool:
    try:
        from app.config import config

        return bool(str((config.fun_asr or {}).get("api_key") or "").strip())
    except Exception:
        return False


def _whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        try:
            import whisper  # noqa: F401

            return True
        except Exception:
            return False


def backend_chain(preferred: str, source_lang: str = "") -> List[str]:
    """
    生成尝试顺序。

    auto 默认优先内置 whisper（faster-whisper），这样「只丢视频」即可出字幕；
    本地 FunASR / FireRed 仅在服务可达时插入；bailian 需 api_key。
    """
    preferred = (preferred or "auto").strip().lower()
    if preferred == "manual":
        return []
    if preferred in {"local", "firered", "bailian", "whisper"}:
        rest = [b for b in ("whisper", "local", "firered", "bailian") if b != preferred]
        return [preferred] + rest

    # auto
    chain: List[str] = []
    # 1) 内置 whisper 最稳，放最前（用户要的「直接给视频」）
    if _whisper_available():
        chain.append("whisper")

    lang = (source_lang or "").strip().lower()[:2]
    local_ok = _url_reachable(_local_funasr_url())
    fire_ok = _url_reachable(_firered_url())
    if lang == "zh":
        if local_ok:
            chain.append("local")
        if fire_ok:
            chain.append("firered")
    else:
        if fire_ok:
            chain.append("firered")
        if local_ok:
            chain.append("local")

    if _bailian_ready():
        chain.append("bailian")

    # 去重保序
    seen = set()
    ordered: List[str] = []
    for b in chain:
        if b not in seen:
            seen.add(b)
            ordered.append(b)

    # 若 whisper 不可用且本地全挂，仍列出 local/firered 让错误信息完整
    if not ordered:
        ordered = ["whisper", "local", "firered", "bailian"]
    return ordered


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


def _sec_to_srt(sec: float) -> str:
    ms = int(round(max(0.0, float(sec)) * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def _write_segments_srt(subtitle_file: str, segments) -> str:
    lines: List[str] = []
    idx = 0
    for seg in segments:
        if isinstance(seg, dict):
            start = float(seg.get("start") or 0)
            end = float(seg.get("end") or 0)
            text = (seg.get("text") or "").strip()
        else:
            start = float(getattr(seg, "start", 0) or 0)
            end = float(getattr(seg, "end", 0) or 0)
            text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        if end <= start:
            end = start + 0.5
        idx += 1
        lines.extend([str(idx), f"{_sec_to_srt(start)} --> {_sec_to_srt(end)}", text, ""])
    content = "\n".join(lines).strip() + "\n"
    if idx == 0 or not content.strip():
        raise RuntimeError("ASR returned empty transcript")
    parent = os.path.dirname(subtitle_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(content)
    return subtitle_file


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


def _default_whisper_device() -> str:
    env = (os.environ.get("CROSS_BORDER_WHISPER_DEVICE") or "").strip().lower()
    if env in {"cpu", "cuda", "auto"}:
        if env != "auto":
            return env
    # auto / 未设置：有 ctranslate2 CUDA 就用
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _default_whisper_model() -> str:
    """
    默认 base：大视频 CPU 上 small 太慢。
    可用 CROSS_BORDER_WHISPER_MODEL=tiny|base|small|medium 覆盖。
    """
    return (
        os.environ.get("CROSS_BORDER_WHISPER_MODEL")
        or os.environ.get("CROSS_BORDER_FASTER_WHISPER_MODEL")
        or "base"
    ).strip() or "base"


def _get_ffmpeg_bin() -> str:
    try:
        from app.services.generate_video import _get_ffmpeg_binary

        return _get_ffmpeg_binary()
    except Exception:
        return "ffmpeg"


def _extract_audio_for_asr(video_path: str, wav_path: str) -> str:
    """
    抽 16k 单声道 wav 给 whisper。大视频直接喂 mp4 会慢很多（解码整段视频流）。
    """
    import subprocess

    os.makedirs(os.path.dirname(wav_path) or ".", exist_ok=True)
    ffmpeg = _get_ffmpeg_bin()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-hide_banner",
        "-loglevel",
        "error",
        wav_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 100:
        err = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"extract audio failed: {err or 'empty wav'}")
    return wav_path


def _get_faster_whisper_model(model_name: str, device: str):
    global _FASTER_WHISPER_MODEL, _FASTER_WHISPER_KEY
    key = (model_name, device)
    if _FASTER_WHISPER_MODEL is not None and _FASTER_WHISPER_KEY == key:
        return _FASTER_WHISPER_MODEL
    from faster_whisper import WhisperModel

    # CPU 默认 int8；有 CUDA 时 float16
    if device == "cuda":
        compute_type = os.environ.get("CROSS_BORDER_WHISPER_COMPUTE", "float16")
    else:
        compute_type = os.environ.get("CROSS_BORDER_WHISPER_COMPUTE", "int8")
    logger.info(
        f"loading faster-whisper model={model_name} device={device} compute={compute_type}"
    )
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    _FASTER_WHISPER_MODEL = model
    _FASTER_WHISPER_KEY = key
    return model


def _try_faster_whisper(video_path: str, subtitle_file: str, source_lang: str = "") -> str:
    """
    内置 faster-whisper。
    大文件策略：先 ffmpeg 抽 16k mono 音频再识别，避免整段视频解码。
    默认模型 base + beam_size=1，优先速度。
    """
    model_name = _default_whisper_model()
    device = _default_whisper_device()
    model = _get_faster_whisper_model(model_name, device)

    language = (source_lang or "").strip()[:2] or None
    if language in {"", "auto", "none"}:
        language = None

    # 抽音频到任务目录旁（与 srt 同目录）
    wav_path = os.path.splitext(subtitle_file)[0] + ".asr.wav"
    audio_input = video_path
    try:
        logger.info(f"ASR extract audio → {wav_path}")
        audio_input = _extract_audio_for_asr(video_path, wav_path)
        logger.info(
            f"ASR audio ready size={os.path.getsize(audio_input)} bytes"
        )
    except Exception as exc:
        logger.warning(f"extract audio failed, fallback to video: {exc}")
        audio_input = video_path

    beam = int(os.environ.get("CROSS_BORDER_WHISPER_BEAM", "1") or "1")
    beam = max(1, min(5, beam))
    # 大文件用 vad 跳过静音；best_of 与 beam 对齐
    segments_iter, info = model.transcribe(
        audio_input,
        language=language,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
        beam_size=beam,
        best_of=beam,
        word_timestamps=False,
        condition_on_previous_text=False,
    )
    segs = list(segments_iter)
    detected = getattr(info, "language", None)
    logger.info(
        f"faster-whisper done: lang={detected} segments={len(segs)} "
        f"model={model_name} device={device} beam={beam}"
    )
    # 清临时 wav，省磁盘
    if audio_input == wav_path and os.path.isfile(wav_path):
        try:
            os.remove(wav_path)
        except OSError:
            pass
    return _write_segments_srt(subtitle_file, segs)


def _try_openai_whisper(video_path: str, subtitle_file: str, source_lang: str = "") -> str:
    import whisper  # type: ignore

    model_name = _default_whisper_model()
    model = whisper.load_model(model_name)
    language = (source_lang or "").strip()[:2] or None
    if language in {"", "auto", "none"}:
        language = None
    result = model.transcribe(video_path, language=language)
    return _write_segments_srt(subtitle_file, result.get("segments") or [])


def _try_whisper(video_path: str, subtitle_file: str, source_lang: str = "") -> str:
    """优先 faster-whisper（已内置安装），回退 openai-whisper。"""
    errors: List[str] = []
    try:
        return _try_faster_whisper(video_path, subtitle_file, source_lang)
    except Exception as exc:
        errors.append(f"faster-whisper: {exc}")
        logger.warning(f"faster-whisper failed: {exc}")
    try:
        return _try_openai_whisper(video_path, subtitle_file, source_lang)
    except Exception as exc:
        errors.append(f"openai-whisper: {exc}")
        raise RuntimeError("; ".join(errors)) from exc


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
    logs.append(f"ASR chain: {' → '.join(chain) if chain else '(manual)'}")
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
