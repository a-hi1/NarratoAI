#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境任务成片渲染。

复用项目既有链路：
  clip_video.clip_video_unified
  → update_script.update_script_timestamps
  → audio_merger.merge_audio_files
  → merger_video.combine_clip_videos
  → generate_video.merge_materials
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


def _load_script_items(script_path: str) -> List[Dict[str, Any]]:
    if not script_path or not os.path.isfile(script_path):
        return []
    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _estimate_duration_from_timestamp(timestamp: str) -> float:
    raw = str(timestamp or "")
    if "-" not in raw:
        return 3.0

    def _parse(ts: str) -> float:
        ts = ts.strip().replace(".", ",")
        h, m, rest = ts.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    try:
        start_s, end_s = raw.split("-", 1)
        return max(0.5, _parse(end_s) - _parse(start_s))
    except Exception:
        return 3.0


def _audio_duration(path: str, fallback: float = 3.0) -> float:
    if not path or not os.path.isfile(path):
        return fallback
    try:
        from app.services.voice import get_audio_duration_from_file

        dur = float(get_audio_duration_from_file(path) or 0)
        if dur > 0:
            return dur
    except Exception as exc:
        logger.debug(f"get_audio_duration_from_file failed: {exc}")
    # 文件体积粗估
    try:
        size = os.path.getsize(path)
        return max(0.8, size / 20000.0)
    except Exception:
        return fallback


def build_tts_results_from_manifest(
    *,
    items: List[Dict[str, Any]],
    tts_dir: str,
    manifest_path: str = "",
) -> List[Dict[str, Any]]:
    """从 step_tts 产物构造 clip_video 需要的 tts_results。"""
    by_id: Dict[int, Dict[str, Any]] = {}
    if manifest_path and os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for clip in data.get("clips") or []:
                if not isinstance(clip, dict):
                    continue
                try:
                    cid = int(clip.get("_id") or 0)
                except (TypeError, ValueError):
                    continue
                if cid:
                    by_id[cid] = clip
        except Exception as exc:
            logger.warning(f"read tts_manifest failed: {exc}")

    results: List[Dict[str, Any]] = []
    for item in items:
        try:
            ost = int(item.get("OST", 0) or 0)
        except (TypeError, ValueError):
            ost = 0
        if ost == 1:
            continue
        try:
            item_id = int(item.get("_id") or 0)
        except (TypeError, ValueError):
            continue
        text = str(item.get("narration") or "").strip()
        if not text or text.startswith("播放原片"):
            continue

        audio_file = ""
        if item_id in by_id:
            audio_file = str(by_id[item_id].get("audio_file") or "")
        if not audio_file or not os.path.isfile(audio_file):
            # 约定命名 0001.mp3
            candidate = os.path.join(tts_dir, f"{item_id:04d}.mp3")
            if os.path.isfile(candidate):
                audio_file = candidate
            else:
                # 兼容 wav
                candidate_wav = os.path.join(tts_dir, f"{item_id:04d}.wav")
                if os.path.isfile(candidate_wav):
                    audio_file = candidate_wav
        if not audio_file or not os.path.isfile(audio_file):
            logger.warning(f"tts clip missing for item {item_id}")
            continue

        fallback = _estimate_duration_from_timestamp(str(item.get("timestamp") or ""))
        duration = _audio_duration(audio_file, fallback=fallback)
        results.append(
            {
                "_id": item_id,
                "timestamp": item.get("timestamp"),
                "audio_file": audio_file,
                "subtitle_file": "",
                "duration": duration,
                "text": text,
            }
        )
    return results


def render_final_video(
    *,
    task_id: str,
    video_path: str,
    script_items: List[Dict[str, Any]],
    tts_results: List[Dict[str, Any]],
    work_dir: str,
    output_mp4: str,
    video_aspect: str = "16:9",
    subtitle_enabled: bool = False,
    voice_volume: float = 1.0,
    original_volume: float = 1.0,
) -> Tuple[str, Dict[str, Any]]:
    """
    执行裁剪 + 拼接 + 混音。

    Returns:
        (final_video_path, debug_info)
    """
    if not video_path or not os.path.isfile(video_path):
        raise FileNotFoundError(f"source video missing: {video_path}")
    if not script_items:
        raise ValueError("empty script items")

    from app.models.schema import VideoAspect
    from app.services import audio_merger, clip_video, generate_video, merger_video, update_script

    os.makedirs(work_dir, exist_ok=True)
    clip_dir = os.path.join(work_dir, "clips")
    os.makedirs(clip_dir, exist_ok=True)

    # 1) 统一裁剪
    video_clip_result = clip_video.clip_video_unified(
        video_origin_path=video_path,
        script_list=script_items,
        tts_results=tts_results,
        output_dir=clip_dir,
        task_id=task_id,
    )
    if not video_clip_result:
        raise RuntimeError("clip_video_unified returned empty result")

    tts_clip_result = {r["_id"]: r["audio_file"] for r in tts_results}
    new_script_list = update_script.update_script_timestamps(
        script_items,
        video_clip_result,
        tts_clip_result,
        {},
    )

    # 2) 合并解说轨
    total_duration = sum(float(s.get("duration") or 0) for s in new_script_list)
    if total_duration <= 0:
        total_duration = sum(float(r.get("duration") or 0) for r in tts_results) or 1.0

    # audio_merger 使用 utils.task_dir(task_id)；为隔离跨境任务，写到 work_dir 后拷贝
    # 这里直接在 work_dir 手工合成更可控：优先用项目 merge，失败则跳过混音只拼视频
    merged_audio_path = ""
    try:
        # audio_merger 内部会写到 storage/tasks/{task_id}
        # 用跨境 task_id 可能污染主任务目录，但可接受；再复制到 work_dir
        merged_audio_path = audio_merger.merge_audio_files(
            task_id=task_id,
            total_duration=total_duration,
            list_script=new_script_list,
        ) or ""
        if merged_audio_path and os.path.isfile(merged_audio_path):
            dest = os.path.join(work_dir, "merged_narration.mp3")
            shutil.copy2(merged_audio_path, dest)
            merged_audio_path = dest
    except Exception as exc:
        logger.warning(f"merge_audio_files failed: {exc}")
        merged_audio_path = ""

    # 3) 拼接视频片段
    video_clips: List[str] = []
    video_ost: List[int] = []
    for script in new_script_list:
        vp = script.get("video") or ""
        if vp and os.path.isfile(vp):
            video_clips.append(vp)
            try:
                video_ost.append(int(script.get("OST", 0) or 0))
            except (TypeError, ValueError):
                video_ost.append(0)
    if not video_clips:
        raise RuntimeError("no clipped video segments to merge")

    merger_path = os.path.join(work_dir, "merger.mp4")
    try:
        aspect = VideoAspect(video_aspect)
    except Exception:
        aspect = VideoAspect.landscape

    merger_video.combine_clip_videos(
        output_video_path=merger_path,
        video_paths=video_clips,
        video_ost_list=video_ost,
        video_aspect=aspect,
        threads=4,
    )
    if not os.path.isfile(merger_path):
        raise RuntimeError("combine_clip_videos did not produce merger.mp4")

    # 4) 混入解说轨
    has_ost1 = any(int(s.get("OST", 0) or 0) == 1 for s in new_script_list)
    final_path = output_mp4
    os.makedirs(os.path.dirname(final_path) or ".", exist_ok=True)

    if merged_audio_path and os.path.isfile(merged_audio_path):
        options = {
            "voice_volume": voice_volume,
            "bgm_volume": 0.0,
            "original_audio_volume": original_volume if has_ost1 else 0.0,
            "keep_original_audio": has_ost1,
            "subtitle_enabled": bool(subtitle_enabled),
        }
        generate_video.merge_materials(
            video_path=merger_path,
            audio_path=merged_audio_path,
            output_path=final_path,
            subtitle_path=None,
            bgm_path=None,
            options=options,
        )
    else:
        # 无解说轨时直接用拼接结果
        shutil.copy2(merger_path, final_path)

    if not os.path.isfile(final_path) or os.path.getsize(final_path) < 1000:
        raise RuntimeError(f"final video missing or too small: {final_path}")

    debug = {
        "clip_count": len(video_clips),
        "tts_count": len(tts_results),
        "has_ost1": has_ost1,
        "merged_audio": merged_audio_path,
        "merger_video": merger_path,
        "total_duration": total_duration,
        "script_items": len(new_script_list),
    }
    return final_path, debug
