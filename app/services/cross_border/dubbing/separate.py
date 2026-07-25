#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
人声 / 伴奏分离。

后端优先级：
1. demucs（若已安装 torch+demucs）→ 真分离
2. ffmpeg 立体声中置削弱（center cancel）→ 对部分立体声有效
3. duck：保留原音轨并按 gain 压低 → 永远可用的保底

产物落在 task 目录：
- audio/source.wav
- audio/vocals.wav（可能是占位/近似）
- audio/no_vocals.wav（伴奏或压低后的底噪）
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from loguru import logger


class SeparateError(RuntimeError):
    pass


def _ffmpeg() -> str:
    try:
        from app.config import config

        path = str(getattr(config, "ffmpeg_path", "") or "").strip()
        if path and os.path.isfile(path):
            return path
        app_cfg = getattr(config, "app", None) or {}
        path = str(app_cfg.get("ffmpeg_path") or "").strip()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"


def demucs_available() -> bool:
    try:
        import demucs  # noqa: F401
        import torch  # noqa: F401

        return True
    except Exception:
        return False


def extract_wav(video_path: str, wav_path: str, *, sample_rate: int = 44100) -> str:
    if not video_path or not os.path.isfile(video_path):
        raise SeparateError(f"video missing: {video_path}")
    os.makedirs(os.path.dirname(wav_path) or ".", exist_ok=True)
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "2",
        "-ar",
        str(int(sample_rate)),
        "-c:a",
        "pcm_s16le",
        wav_path,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if r.returncode != 0 or not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 1000:
        raise SeparateError(f"extract wav failed: {(r.stderr or r.stdout or '')[-500:]}")
    return wav_path


def _run_demucs(source_wav: str, out_dir: str) -> Dict[str, str]:
    """调用 demucs CLI/API；返回 vocals / no_vocals 路径。"""
    # 使用 demucs 命令行更稳（避免版本 API 差）
    work = os.path.join(out_dir, "_demucs_work")
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    cmd = [
        os.environ.get("PYTHON", "") or shutil.which("python") or "python",
        "-m",
        "demucs",
        "-n",
        "htdemucs",
        "--two-stems",
        "vocals",
        "-o",
        work,
        source_wav,
    ]
    # 优先用当前解释器
    import sys

    cmd[0] = sys.executable
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=7200,
    )
    if r.returncode != 0:
        raise SeparateError(f"demucs failed: {(r.stderr or r.stdout or '')[-800:]}")

    # demucs 输出 work/htdemucs/<track>/{vocals,no_vocals}.wav
    vocals = ""
    no_vocals = ""
    for root, _dirs, files in os.walk(work):
        for fn in files:
            low = fn.lower()
            path = os.path.join(root, fn)
            if low == "vocals.wav":
                vocals = path
            elif low in {"no_vocals.wav", "instrumental.wav"}:
                no_vocals = path
    if not vocals or not no_vocals:
        raise SeparateError("demucs finished but stems not found")
    dest_v = os.path.join(out_dir, "vocals.wav")
    dest_i = os.path.join(out_dir, "no_vocals.wav")
    shutil.copy2(vocals, dest_v)
    shutil.copy2(no_vocals, dest_i)
    shutil.rmtree(work, ignore_errors=True)
    return {"vocals": dest_v, "no_vocals": dest_i, "backend": "demucs"}


def _center_cancel(source_wav: str, no_vocals_path: str) -> str:
    """立体声中置削弱：L-R 差作为伴奏近似（对人声居中的混音有效）。"""
    # 输出仍为立体声：把 mono 差信号复制到双声道
    filt = (
        "pan=stereo|c0=0.5*c0-0.5*c1|c1=0.5*c0-0.5*c1,"
        "volume=1.6"
    )
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        source_wav,
        "-af",
        filt,
        "-c:a",
        "pcm_s16le",
        no_vocals_path,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if r.returncode != 0 or not os.path.isfile(no_vocals_path):
        raise SeparateError(f"center cancel failed: {(r.stderr or '')[-400:]}")
    return no_vocals_path


def _duck_copy(source_wav: str, no_vocals_path: str, gain: float) -> str:
    gain = max(0.0, min(1.0, float(gain)))
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        source_wav,
        "-af",
        f"volume={gain:.4f}",
        "-c:a",
        "pcm_s16le",
        no_vocals_path,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if r.returncode != 0 or not os.path.isfile(no_vocals_path):
        raise SeparateError(f"duck copy failed: {(r.stderr or '')[-400:]}")
    return no_vocals_path


def _silent_vocals_placeholder(source_wav: str, vocals_path: str) -> str:
    """无真分离时写等长静音人声轨，便于后续接口统一。"""
    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        source_wav,
        "-af",
        "volume=0",
        "-c:a",
        "pcm_s16le",
        vocals_path,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    if r.returncode != 0 or not os.path.isfile(vocals_path):
        # 最后兜底：直接 copy 源
        shutil.copy2(source_wav, vocals_path)
    return vocals_path


def separate_audio(
    video_path: str,
    audio_dir: str,
    *,
    backend: str = "auto",
    duck_gain: float = 0.18,
) -> Dict[str, Any]:
    """
    从视频分离人声/伴奏。

    backend:
      - auto: demucs → center_cancel → duck
      - demucs / center_cancel / duck: 强制
    duck_gain: duck 模式下原声保留比例（0~1）
    """
    os.makedirs(audio_dir, exist_ok=True)
    source_wav = os.path.join(audio_dir, "source.wav")
    vocals_path = os.path.join(audio_dir, "vocals.wav")
    no_vocals_path = os.path.join(audio_dir, "no_vocals.wav")

    extract_wav(video_path, source_wav)
    backend = (backend or "auto").strip().lower()
    used = backend
    note = ""

    def _try_demucs() -> bool:
        if not demucs_available():
            return False
        try:
            _run_demucs(source_wav, audio_dir)
            return True
        except Exception as exc:
            logger.warning(f"demucs separate failed: {exc}")
            return False

    ok = False
    if backend in {"auto", "demucs"}:
        if _try_demucs():
            used = "demucs"
            ok = True
            note = "true vocal/instrumental stems via demucs"
        elif backend == "demucs":
            raise SeparateError(
                "demucs 不可用。请安装: pip install demucs torch  或改用 auto/duck"
            )

    if not ok and backend in {"auto", "center_cancel", "center"}:
        try:
            _center_cancel(source_wav, no_vocals_path)
            _silent_vocals_placeholder(source_wav, vocals_path)
            used = "center_cancel"
            ok = True
            note = "stereo mid cancel approximation (not true stem separation)"
        except Exception as exc:
            logger.warning(f"center_cancel failed: {exc}")
            if backend in {"center_cancel", "center"}:
                raise

    if not ok:
        _duck_copy(source_wav, no_vocals_path, duck_gain)
        _silent_vocals_placeholder(source_wav, vocals_path)
        used = "duck"
        note = f"original audio ducked to gain={duck_gain:.2f} (install demucs for real separation)"

    return {
        "source_wav": source_wav,
        "vocals_wav": vocals_path,
        "no_vocals_wav": no_vocals_path,
        "backend": used,
        "demucs_available": demucs_available(),
        "note": note,
    }
