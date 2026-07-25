#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
目标语字幕 → 逐句 TTS，并按时间轴铺成一条配音音轨。

质感要点：
- 语种-音色强制对齐（resolve_voice_for_lang）
- 按字幕槽 atempo 伸缩（支持级联，范围约 0.25–4.0）
- 过短句尾部补静音，避免句间空洞感不一致
- 句首/句尾短淡入淡出，降低拼接咔哒声
- 分批 amix，支持更长片（默认 200 句）
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .voices import default_voice_for_lang, normalize_lang, resolve_voice_for_lang

_TIME_LINE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)

# 单批 amix 输入上限（ffmpeg 滤镜图复杂度）
_BATCH_SIZE = 40
_MAX_SEGMENTS = 200


def _ffmpeg() -> str:
    try:
        from app.config import config

        path = str(getattr(config, "ffmpeg_path", "") or "").strip()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    ff = _ffmpeg()
    probe = os.path.join(os.path.dirname(ff), "ffprobe.exe" if os.name == "nt" else "ffprobe")
    if os.path.isfile(probe):
        return probe
    return shutil.which("ffprobe") or "ffprobe"


def srt_ts_to_seconds(ts: str) -> float:
    ts = (ts or "").strip().replace(",", ".")
    h, m, rest = ts.split(":")
    s = float(rest)
    return int(h) * 3600 + int(m) * 60 + s


def parse_srt_cues(text: str) -> List[Dict[str, Any]]:
    if not text or not text.strip():
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    cues: List[Dict[str, Any]] = []
    idx = 0
    for block in blocks:
        lines = [ln.rstrip() for ln in block.strip().splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        if re.match(r"^\d+$", lines[0]) and len(lines) >= 3:
            time_line = lines[1]
            body_lines = lines[2:]
        else:
            time_line = lines[0]
            body_lines = lines[1:]
        m = _TIME_LINE.search(time_line)
        if not m:
            continue
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        idx += 1
        start = srt_ts_to_seconds(m.group(1))
        end = srt_ts_to_seconds(m.group(2))
        if end <= start:
            end = start + 0.5
        cues.append(
            {
                "id": idx,
                "start": start,
                "end": end,
                "text": body.replace("\n", " ").strip(),
            }
        )
    return cues


def _tts_one(
    text: str,
    out_path: str,
    *,
    voice_name: str,
    voice_rate: float = 1.0,
    voice_pitch: float = 1.0,
    tts_engine: str = "edge_tts",
) -> bool:
    try:
        from app.services import voice as voice_svc

        maker = voice_svc.tts(
            text=text,
            voice_name=voice_name,
            voice_rate=voice_rate,
            voice_pitch=voice_pitch,
            voice_file=out_path,
            tts_engine=tts_engine,
        )
        return bool(maker is not None and os.path.isfile(out_path) and os.path.getsize(out_path) > 100)
    except Exception as exc:
        logger.warning(f"voice.tts failed, try edge: {exc}")
    try:
        import asyncio
        import edge_tts  # type: ignore

        async def _run():
            communicate = edge_tts.Communicate(text, voice_name)
            await communicate.save(out_path)

        asyncio.run(_run())
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 100
    except Exception as exc:
        logger.error(f"edge tts failed: {exc}")
        return False


def _audio_duration(path: str) -> float:
    cmd = [
        _ffprobe(),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
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
            return max(0.05, float((r.stdout or "0").strip() or 0))
    except Exception:
        pass
    return 1.0


def synthesize_cues_to_dir(
    cues: List[Dict[str, Any]],
    tts_dir: str,
    *,
    voice_name: str,
    voice_rate: float = 1.0,
    voice_pitch: float = 1.0,
    tts_engine: str = "edge_tts",
) -> List[Dict[str, Any]]:
    os.makedirs(tts_dir, exist_ok=True)
    results: List[Dict[str, Any]] = []
    for cue in cues:
        cid = int(cue["id"])
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        out = os.path.join(tts_dir, f"{cid:04d}.mp3")
        ok = _tts_one(
            text,
            out,
            voice_name=voice_name,
            voice_rate=voice_rate,
            voice_pitch=voice_pitch,
            tts_engine=tts_engine,
        )
        if not ok:
            logger.warning(f"skip cue {cid}: tts failed")
            continue
        dur = _audio_duration(out)
        results.append(
            {
                "id": cid,
                "start": float(cue["start"]),
                "end": float(cue["end"]),
                "text": text,
                "audio_file": out,
                "duration": dur,
                "slot": max(0.1, float(cue["end"]) - float(cue["start"])),
            }
        )
    return results


def _atempo_chain(tempo: float) -> str:
    """
    ffmpeg atempo 单次仅 0.5–2.0；级联覆盖约 0.25–4.0。
    tempo = 原时长/目标槽 → >1 加快压缩，<1 放慢拉长。
    """
    t = float(tempo)
    if t <= 0:
        t = 1.0
    t = max(0.25, min(4.0, t))
    parts: List[str] = []
    # 先拆到 [0.5, 2.0]
    while t > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        t /= 2.0
    while t < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        t /= 0.5
    if abs(t - 1.0) > 0.015:
        parts.append(f"atempo={t:.4f}")
    return ",".join(parts)


def _fit_segment_file(
    src: str,
    dst: str,
    *,
    slot: float,
    duration: float,
) -> Tuple[str, float, float]:
    """
    把一句 TTS 拟合到字幕槽：
    - 明显更长 → atempo 压缩到约 95% 槽长
    - 明显更短 → 尾部 pad 静音到槽长（保持语速自然，不硬拉慢）
    - 接近 → 仅加淡入淡出
    返回 (path, out_duration, tempo_used)
    """
    slot = max(0.12, float(slot))
    duration = max(0.05, float(duration))
    fade = min(0.04, slot * 0.08, duration * 0.15)
    filters: List[str] = []
    tempo_used = 1.0

    # 略留 5% 余量，避免贴死下一句
    target = slot * 0.95
    if duration > slot * 1.08:
        tempo_used = min(4.0, max(0.25, duration / max(target, 0.12)))
        chain = _atempo_chain(tempo_used)
        if chain:
            filters.append(chain)
        out_dur = duration / tempo_used
    elif duration < slot * 0.72:
        # 不拉慢（会发飘）；尾部补静音到接近槽长
        pad = max(0.0, target - duration)
        filters.append(f"apad=pad_dur={pad:.3f}")
        out_dur = duration + pad
        tempo_used = 1.0
    else:
        out_dur = duration

    # 轻高通去 rumble + 淡入淡出
    filters.append("highpass=f=80")
    if fade > 0.008:
        filters.append(f"afade=t=in:st=0:d={fade:.3f}")
        # 淡出起点
        fo_start = max(0.0, out_dur - fade)
        filters.append(f"afade=t=out:st={fo_start:.3f}:d={fade:.3f}")
    filters.append("aformat=sample_rates=44100:channel_layouts=stereo")

    cmd = [
        _ffmpeg(),
        "-y",
        "-i",
        src,
        "-af",
        ",".join(filters),
        "-c:a",
        "pcm_s16le",
        dst,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if r.returncode != 0 or not os.path.isfile(dst):
        # 失败则原样返回
        logger.warning(f"fit segment failed, use raw: {(r.stderr or '')[-200:]}")
        return src, duration, 1.0
    real = _audio_duration(dst)
    return dst, real, tempo_used


def _mix_batch(
    segments: List[Dict[str, Any]],
    output_wav: str,
    *,
    total_duration: float,
) -> str:
    inputs: List[str] = []
    filters: List[str] = []
    labels: List[str] = []
    for i, seg in enumerate(segments):
        path = seg["audio_file"]
        inputs.extend(["-i", path])
        delay_ms = max(0, int(round(float(seg["start"]) * 1000)))
        # 已在 fit 阶段处理 tempo；这里只做延时
        chain = (
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}[a{i}]"
        )
        filters.append(chain)
        labels.append(f"[a{i}]")

    n = len(labels)
    mix = (
        f"{''.join(labels)}amix=inputs={n}:duration=longest:dropout_transition=0:normalize=0,"
        f"atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS[aout]"
    )
    filters.append(mix)
    cmd = [
        _ffmpeg(),
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[aout]",
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
        raise RuntimeError(f"build timeline batch failed: {(r.stderr or '')[-800:]}")
    return output_wav


def _merge_wavs(paths: List[str], output_wav: str, *, total_duration: float) -> str:
    if len(paths) == 1:
        shutil.copy2(paths[0], output_wav)
        return output_wav
    inputs: List[str] = []
    labels: List[str] = []
    filters: List[str] = []
    for i, p in enumerate(paths):
        inputs.extend(["-i", p])
        filters.append(
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[b{i}]"
        )
        labels.append(f"[b{i}]")
    mix = (
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
        f"atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS[aout]"
    )
    filters.append(mix)
    cmd = [
        _ffmpeg(),
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[aout]",
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
        raise RuntimeError(f"merge timeline batches failed: {(r.stderr or '')[-800:]}")
    return output_wav


def build_timeline_audio(
    segments: List[Dict[str, Any]],
    output_wav: str,
    *,
    total_duration: float,
    work_dir: str = "",
) -> str:
    """
    按 start 时间把各句 TTS 铺到一条音轨。
    先逐句 fit 到字幕槽，再分批 amix，最后合并。
    """
    os.makedirs(os.path.dirname(output_wav) or ".", exist_ok=True)
    total_duration = max(1.0, float(total_duration or 1.0))
    if not segments:
        cmd = [
            _ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            f"{total_duration:.3f}",
            "-c:a",
            "pcm_s16le",
            output_wav,
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        return output_wav

    if len(segments) > _MAX_SEGMENTS:
        logger.warning(
            f"dub tts segments truncated {_MAX_SEGMENTS}/{len(segments)} for stability"
        )
        segments = segments[:_MAX_SEGMENTS]

    fit_dir = work_dir or os.path.join(os.path.dirname(output_wav) or ".", "tts_fit")
    os.makedirs(fit_dir, exist_ok=True)
    fitted: List[Dict[str, Any]] = []
    for seg in segments:
        src = seg["audio_file"]
        dst = os.path.join(fit_dir, f"fit_{int(seg['id']):04d}.wav")
        path, out_dur, tempo = _fit_segment_file(
            src,
            dst,
            slot=float(seg.get("slot") or 1.0),
            duration=float(seg.get("duration") or 1.0),
        )
        fitted.append(
            {
                **seg,
                "audio_file": path,
                "duration": out_dur,
                "tempo": tempo,
            }
        )

    if len(fitted) <= _BATCH_SIZE:
        return _mix_batch(fitted, output_wav, total_duration=total_duration)

    batch_paths: List[str] = []
    for bi in range(0, len(fitted), _BATCH_SIZE):
        chunk = fitted[bi : bi + _BATCH_SIZE]
        bp = os.path.join(fit_dir, f"batch_{bi // _BATCH_SIZE:02d}.wav")
        _mix_batch(chunk, bp, total_duration=total_duration)
        batch_paths.append(bp)
    return _merge_wavs(batch_paths, output_wav, total_duration=total_duration)


def synthesize_from_srt(
    srt_text: str,
    work_dir: str,
    *,
    target_lang: str,
    voice_name: str = "",
    voice_rate: float = 1.0,
    voice_pitch: float = 1.0,
    tts_engine: str = "edge_tts",
    total_duration: float = 0.0,
    voice_gender: str = "female",
    force_voice_lang_match: bool = True,
) -> Dict[str, Any]:
    cues = parse_srt_cues(srt_text)
    if not cues:
        raise ValueError("empty target srt cues for dubbing TTS")
    lang = normalize_lang(target_lang)
    voice, corrected = resolve_voice_for_lang(
        lang,
        voice_name,
        gender=voice_gender,
        force_match=force_voice_lang_match,
    )
    if corrected and (voice_name or "").strip():
        logger.warning(
            f"voice '{voice_name}' mismatch target_lang={lang}, using '{voice}'"
        )
    tts_dir = os.path.join(work_dir, "tts_lines")
    segments = synthesize_cues_to_dir(
        cues,
        tts_dir,
        voice_name=voice,
        voice_rate=voice_rate,
        voice_pitch=voice_pitch,
        tts_engine=tts_engine or "edge_tts",
    )
    if not segments:
        raise RuntimeError("all dubbing TTS lines failed")
    if total_duration <= 0:
        total_duration = max(s["end"] for s in segments) + 0.5
    timeline = os.path.join(work_dir, "dub_voice.wav")
    fit_dir = os.path.join(work_dir, "tts_fit")
    build_timeline_audio(
        segments,
        timeline,
        total_duration=total_duration,
        work_dir=fit_dir,
    )
    return {
        "voice_name": voice,
        "voice_corrected": corrected,
        "target_lang": lang,
        "segments": segments,
        "segment_count": len(segments),
        "cue_count": len(cues),
        "timeline_wav": timeline,
        "tts_dir": tts_dir,
        "total_duration": total_duration,
    }
