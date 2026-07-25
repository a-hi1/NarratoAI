#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
伴奏 + 配音混音，并回贴到视频（可无字幕；字幕由 burn 步骤处理）。

质感：
- 人声轨：轻高通 + 压缩，更贴片
- 伴奏：在人声出现时 sidechain 压低（可关）
- 整轨 loudnorm 到播客/短视频常用响度
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from loguru import logger


def _ffmpeg() -> str:
    try:
        from app.config import config

        path = str(getattr(config, "ffmpeg_path", "") or "").strip()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"


def mix_instrumental_and_voice(
    *,
    instrumental_wav: str,
    voice_wav: str,
    output_wav: str,
    instrumental_volume: float = 0.55,
    voice_volume: float = 1.8,
    sidechain_duck: bool = True,
    duck_threshold: float = 0.02,
    duck_ratio: float = 8.0,
) -> str:
    """
    混音原则：配音必须可听清。
    - 默认配音 > 伴奏（voice 1.8 / instr 0.55）
    - sidechain 必须 asplit 分叉：同一 label 不能同时喂 sidechain 与 amix
    - 人声压缩 + makeup，避免 TTS 被 BGM 盖掉
    """
    if not os.path.isfile(instrumental_wav):
        raise FileNotFoundError(instrumental_wav)
    if not os.path.isfile(voice_wav):
        raise FileNotFoundError(voice_wav)
    os.makedirs(os.path.dirname(output_wav) or ".", exist_ok=True)
    # 允许更高配音增益；伴奏别超过 1.2
    iv = max(0.0, min(1.5, float(instrumental_volume)))
    vv = max(0.0, min(3.0, float(voice_volume)))
    # 人声：抬音量 + 去 rumble + 压缩 + makeup（TTS 往往比 BGM 弱）
    voice_fx = (
        f"volume={vv:.3f},highpass=f=90,lowpass=f=11000,"
        f"acompressor=threshold=-22dB:ratio=3:attack=5:release=100:makeup=5,"
        f"aformat=sample_rates=44100:channel_layouts=stereo"
    )
    # loudnorm 双扫描对 17min+ 片很慢；默认用 dynaudnorm 近似响度，可设
    # CROSS_BORDER_MIX_LOUDNORM=1 强制 classic loudnorm
    use_loudnorm = (os.environ.get("CROSS_BORDER_MIX_LOUDNORM") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    # dynaudnorm 一次扫描即可，长片明显快；参数偏保守避免泵感
    loud_tail = (
        "loudnorm=I=-16:TP=-1.5:LRA=11"
        if use_loudnorm
        else "dynaudnorm=f=150:g=15:p=0.9:m=10:r=0.5"
    )
    if sidechain_duck:
        # 关键：asplit 把人声拆成 sidechain 探测轨 + 最终叠入轨，避免 [vc] 双消费
        thr = max(0.001, min(0.5, float(duck_threshold)))
        ratio = max(1.5, min(20.0, float(duck_ratio)))
        filt = (
            f"[1:a]{voice_fx},asplit=2[vc][vcsc];"
            f"[0:a]volume={iv:.3f},aformat=sample_rates=44100:channel_layouts=stereo[bg0];"
            f"[bg0][vcsc]sidechaincompress=threshold={thr}:ratio={ratio}:"
            f"attack=12:release=220:makeup=1:mix=1[bg];"
            f"[bg][vc]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"{loud_tail}[aout]"
        )
    else:
        filt = (
            f"[0:a]volume={iv:.3f},aformat=sample_rates=44100:channel_layouts=stereo[bg];"
            f"[1:a]{voice_fx}[vc];"
            f"[bg][vc]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"{loud_tail}[aout]"
        )
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        instrumental_wav,
        "-i",
        voice_wav,
        "-filter_complex",
        filt,
        "-map",
        "[aout]",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        output_wav,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
    )
    if r.returncode != 0 or not os.path.isfile(output_wav):
        logger.warning(
            f"mix advanced failed, retry plain: {(r.stderr or '')[-400:]}"
        )
        # 保底：硬叠，配音仍用抬高后的 vv
        filt2 = (
            f"[0:a]volume={iv:.3f},aformat=sample_rates=44100:channel_layouts=stereo[bg];"
            f"[1:a]volume={vv:.3f},aformat=sample_rates=44100:channel_layouts=stereo[vc];"
            f"[bg][vc]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
        )
        cmd = [
            _ffmpeg(),
            "-y",
            "-i",
            instrumental_wav,
            "-i",
            voice_wav,
            "-filter_complex",
            filt2,
            "-map",
            "[aout]",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            output_wav,
        ]
        r2 = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
        if r2.returncode != 0 or not os.path.isfile(output_wav):
            raise RuntimeError(f"audio mix failed: {(r2.stderr or r.stderr or '')[-800:]}")
    return output_wav


def mux_video_with_audio(
    *,
    video_path: str,
    audio_path: str,
    output_mp4: str,
    video_encoder: str = "libx264",
) -> str:
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(audio_path)
    os.makedirs(os.path.dirname(output_mp4) or ".", exist_ok=True)
    # 优先 copy 视频流；失败再软编
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        output_mp4,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    if r.returncode == 0 and os.path.isfile(output_mp4) and os.path.getsize(output_mp4) > 1000:
        return output_mp4

    logger.warning("mux copy video failed, re-encode with libx264")
    enc = (video_encoder or "libx264").strip() or "libx264"
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        video_path,
        "-i",
        audio_path,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        enc,
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        output_mp4,
    ]
    r2 = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    if r2.returncode != 0 or not os.path.isfile(output_mp4):
        raise RuntimeError(f"mux video failed: {(r2.stderr or r.stderr or '')[-800:]}")
    return output_mp4


def probe_duration_seconds(media_path: str) -> float:
    ff = _ffmpeg()
    probe = os.path.join(os.path.dirname(ff), "ffprobe.exe" if os.name == "nt" else "ffprobe")
    if not os.path.isfile(probe):
        probe = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        probe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if r.returncode == 0:
            return max(0.1, float((r.stdout or "0").strip() or 0))
    except Exception:
        pass
    return 0.0
