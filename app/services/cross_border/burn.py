#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
字幕硬烧（VideoLingo 风格）：原片 + 目标字幕 → 带字幕成片。

复用 generate_video.merge_materials 的 ffmpeg 字幕滤镜。
默认「电影字幕」：小字、贴底、细描边，尽量不挡画面主体。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple


_TIME_LINE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)

# 预设：用户可在 UI 选。key 稳定，写入 meta.inputs.subtitle_style
# 默认 cinema = 电影字幕（小、贴底、不抢画面）
STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "cinema": {
        "label": "电影字幕（推荐）",
        "subtitle_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width_scale": 0.55,
        "shadow": 0,
        "border_style": 1,
        "back_colour": None,
        "size_scale": 1.0,
    },
    "clean": {
        "label": "干净白字",
        "subtitle_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width_scale": 0.75,
        "shadow": 0,
        "border_style": 1,
        "back_colour": None,
        "size_scale": 1.08,
    },
    "netflix": {
        "label": "网感细描边",
        "subtitle_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width_scale": 0.65,
        "shadow": 0,
        "border_style": 1,
        "back_colour": None,
        "size_scale": 1.05,
    },
    "soft": {
        "label": "柔和阴影",
        "subtitle_color": "#FFFFFF",
        "stroke_color": "#1A1A1A",
        "stroke_width_scale": 0.5,
        "shadow": 1,
        "border_style": 1,
        "back_colour": None,
        "size_scale": 1.05,
    },
    "boxed": {
        "label": "半透明底框",
        "subtitle_color": "#FFFFFF",
        "stroke_color": "#000000",
        "stroke_width_scale": 0.25,
        "shadow": 0,
        "border_style": 3,
        "back_colour": "&H80000000",
        "size_scale": 1.0,
    },
    "yellow": {
        "label": "经典黄字",
        "subtitle_color": "#FFE566",
        "stroke_color": "#000000",
        "stroke_width_scale": 0.8,
        "shadow": 0,
        "border_style": 1,
        "back_colour": None,
        "size_scale": 1.05,
    },
}

# 字号档位：相对 auto 的倍率（auto 已是电影级小字）
SIZE_PRESETS: Dict[str, float] = {
    "auto": 1.0,
    "small": 0.88,
    "medium": 1.12,
    "large": 1.28,
}

# 位置：ASS Alignment + MarginV 占画面高比例
# bottom 默认紧贴底边安全区，字小 + 边距小 = 不抢画面
POSITION_PRESETS: Dict[str, Dict[str, Any]] = {
    "bottom": {"align": 2, "margin_v_ratio": 0.024, "y_percent": None},
    "bottom_high": {"align": 2, "margin_v_ratio": 0.07, "y_percent": None},
    "center": {"align": 5, "margin_v_ratio": 0.0, "y_percent": 50.0},
    "top": {"align": 8, "margin_v_ratio": 0.035, "y_percent": None},
}

# 原片硬字幕遮罩条：手动勾选，不依赖识别
MASK_SIDE_PRESETS: Dict[str, str] = {
    "bottom": "底部遮罩条",
    "top": "顶部遮罩条",
}
MASK_COLOR_PRESETS: Dict[str, str] = {
    "black": "纯黑",
    "translucent": "半透明黑",
}
# 高度占画面高 %；默认盖住常见底部硬字幕
DEFAULT_MASK_HEIGHT_PERCENT = 14.0
MASK_HEIGHT_MIN = 6.0
MASK_HEIGHT_MAX = 28.0


def style_choices_for_ui() -> List[Tuple[str, str]]:
    """[(key, label), ...]"""
    return [(k, v["label"]) for k, v in STYLE_PRESETS.items()]


def mask_side_choices_for_ui() -> List[Tuple[str, str]]:
    return list(MASK_SIDE_PRESETS.items())


def mask_color_choices_for_ui() -> List[Tuple[str, str]]:
    return list(MASK_COLOR_PRESETS.items())


def _clamp_mask_height(value: Any) -> float:
    try:
        h = float(value)
    except (TypeError, ValueError):
        h = DEFAULT_MASK_HEIGHT_PERCENT
    return max(MASK_HEIGHT_MIN, min(MASK_HEIGHT_MAX, h))


def build_mask_region_options(
    *,
    side: str = "bottom",
    height_percent: float = DEFAULT_MASK_HEIGHT_PERCENT,
    color: str = "black",
) -> Dict[str, Any]:
    """
    把跨境简化 UI 映射成 generate_video 的 subtitle_mask_* 区域参数。

    - side: bottom|top
    - height_percent: 遮罩条高度占画面高
    - color: black|translucent → solid 条的不透明度
    """
    side = (side or "bottom").strip().lower()
    if side not in MASK_SIDE_PRESETS:
        side = "bottom"
    color = (color or "black").strip().lower()
    if color not in MASK_COLOR_PRESETS:
        color = "black"
    height = _clamp_mask_height(height_percent)
    # 全宽条，略留左右气口避免裁切感
    x_percent = 0.0
    width_percent = 100.0
    y_percent = max(0.0, 100.0 - height) if side == "bottom" else 0.0
    opacity = 100 if color == "black" else 72
    # solid 条不需要高斯模糊；blur_radius=0 走 drawbox 纯色路径
    common = {
        "x_percent": x_percent,
        "y_percent": y_percent,
        "width_percent": width_percent,
        "height_percent": height,
        "blur_radius": 0,
        "opacity_percent": opacity,
    }
    out: Dict[str, Any] = {
        "subtitle_mask_enabled": True,
        "subtitle_mask_mode": "solid",
        "subtitle_mask_side": side,
        "subtitle_mask_color": color,
        "subtitle_mask_height_percent": height,
    }
    for orientation in ("landscape", "portrait"):
        for field, val in common.items():
            out[f"subtitle_mask_{orientation}_{field}"] = val
    return out


def apply_mask_to_burn_options(
    opts: Dict[str, Any],
    inputs: Dict[str, Any],
) -> Dict[str, Any]:
    """
    根据 inputs 中的遮罩开关，写入 merge_materials 可用的 mask 字段，
    并在「字幕叠在遮罩上」时微调位置/边距。
    """
    enabled = bool(inputs.get("subtitle_mask_enabled"))
    if not enabled:
        opts["subtitle_mask_enabled"] = False
        opts["subtitle_mask_mode"] = "off"
        return opts

    side = str(inputs.get("subtitle_mask_side") or "bottom").strip().lower()
    if side not in MASK_SIDE_PRESETS:
        side = "bottom"
    color = str(inputs.get("subtitle_mask_color") or "black").strip().lower()
    if color not in MASK_COLOR_PRESETS:
        color = "black"
    height = _clamp_mask_height(
        inputs.get("subtitle_mask_height_percent") or DEFAULT_MASK_HEIGHT_PERCENT
    )
    on_mask = inputs.get("subtitle_on_mask")
    if on_mask is None:
        on_mask = True
    on_mask = bool(on_mask)

    region = build_mask_region_options(
        side=side, height_percent=height, color=color
    )
    opts.update(region)
    opts["subtitle_on_mask"] = on_mask

    h = int((opts.get("_adaptive") or {}).get("video_height") or 0) or int(
        opts.get("video_height") or 0
    )
    if h <= 0:
        h = 1080
    mask_px = max(20, int(round(h * height / 100.0)))

    # 字幕叠在遮罩条上：把文字锚到条内中下部/中上部
    # 不叠：把文字挪到遮罩外侧，避免写在条上又被盖住观感
    if on_mask:
        if side == "bottom":
            opts["subtitle_position"] = "bottom"
            opts["ass_alignment"] = 2
            # 条高一半左右，字落在条中央偏下
            opts["ass_margin_v"] = max(12, int(round(mask_px * 0.32)))
            opts["custom_position"] = 100.0 - (opts["ass_margin_v"] / h * 100.0)
        else:
            opts["subtitle_position"] = "top"
            opts["ass_alignment"] = 8
            opts["ass_margin_v"] = max(12, int(round(mask_px * 0.28)))
            opts["custom_position"] = opts["ass_margin_v"] / h * 100.0
    else:
        if side == "bottom":
            # 抬高到遮罩上方
            opts["subtitle_position"] = "bottom"
            opts["ass_alignment"] = 2
            opts["ass_margin_v"] = max(
                int(opts.get("ass_margin_v") or 20),
                mask_px + max(10, int(round(h * 0.012))),
            )
            opts["custom_position"] = 100.0 - (opts["ass_margin_v"] / h * 100.0)
        else:
            opts["subtitle_position"] = "bottom"
            opts["ass_alignment"] = 2
            # 顶遮罩时默认仍贴底写译文
            opts["ass_margin_v"] = max(int(opts.get("ass_margin_v") or 16), int(round(h * 0.024)))
            opts["custom_position"] = 100.0 - (opts["ass_margin_v"] / h * 100.0)

    return opts


def _parse_srt_blocks(text: str) -> List[Tuple[str, str, str]]:
    """返回 [(start, end, body), ...]"""
    if not text or not text.strip():
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    out: List[Tuple[str, str, str]] = []
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
        start, end = m.group(1).replace(".", ","), m.group(2).replace(".", ",")
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        out.append((start, end, body))
    return out


def build_bilingual_srt(
    source_srt_text: str,
    target_srt_text: str,
    *,
    order: str = "target_first",
) -> str:
    """
    合并双语字幕：同一时间轴上下两行。
    order: target_first | source_first
    按索引对齐；若不一致以 target 为准。
    """
    src_blocks = _parse_srt_blocks(source_srt_text)
    tgt_blocks = _parse_srt_blocks(target_srt_text)
    if not tgt_blocks and not src_blocks:
        return ""
    n = max(len(src_blocks), len(tgt_blocks))
    out_parts: List[str] = []
    seq = 1
    for i in range(n):
        if i < len(tgt_blocks):
            start, end, tgt_body = tgt_blocks[i]
        else:
            start, end, tgt_body = src_blocks[i][0], src_blocks[i][1], ""
        src_body = src_blocks[i][2] if i < len(src_blocks) else ""
        if order == "source_first":
            body = "\n".join([x for x in (src_body, tgt_body) if x])
        else:
            body = "\n".join([x for x in (tgt_body, src_body) if x])
        if not body:
            continue
        out_parts.append(f"{seq}\n{start} --> {end}\n{body}\n")
        seq += 1
    return "\n".join(out_parts).strip() + ("\n" if out_parts else "")


def _probe_wh(video_path: str) -> Tuple[int, int]:
    try:
        from app.services.generate_video import _probe_video

        meta = _probe_video(video_path)
        return int(meta.get("width") or 0), int(meta.get("height") or 0)
    except Exception:
        return 0, 0


def _resolve_font_file(name_or_path: str) -> str:
    """返回 ffmpeg 可用的字体文件路径（优先绝对路径）。"""
    raw = (name_or_path or "").strip() or "simhei.ttf"
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    try:
        from app.services.generate_video import _resolve_font_path

        found = _resolve_font_path(raw)
        if found and os.path.isfile(found):
            return found
    except Exception:
        pass
    try:
        from app.utils import utils

        candidate = os.path.join(utils.font_dir(), os.path.basename(raw))
        if os.path.isfile(candidate):
            return candidate
        base = os.path.basename(raw).lower()
        for fn in os.listdir(utils.font_dir()):
            if fn.lower() == base or fn.lower() == "simhei.ttf":
                return os.path.join(utils.font_dir(), fn)
    except Exception:
        pass
    return raw


def adaptive_style(
    *,
    video_width: int = 0,
    video_height: int = 0,
    font_size_override: Optional[int] = None,
    bilingual: bool = False,
    size_preset: str = "auto",
    style_key: str = "cinema",
    position_key: str = "bottom",
) -> Dict[str, Any]:
    """
    按分辨率算字号 / 描边 / 底部边距。

    默认电影字幕（偏小、贴底、舒服）：
    - 1080p 横屏约 22px（≈2% 屏高）
    - 竖屏 608 约 16px
    不挡主体，需要时才看得到。
    """
    w = max(0, int(video_width or 0))
    h = max(0, int(video_height or 0))
    if w <= 0 or h <= 0:
        w, h = 1920, 1080
    short = min(w, h)
    is_portrait = h >= w * 1.05

    # 兼容旧 clean 当默认时仍可用；未知 key 回落 cinema
    if style_key not in STYLE_PRESETS:
        style_key = "cinema"
    preset = STYLE_PRESETS.get(style_key) or STYLE_PRESETS["cinema"]
    size_scale = float(SIZE_PRESETS.get(size_preset) or 1.0) * float(
        preset.get("size_scale") or 1.0
    )

    if font_size_override and int(font_size_override) > 0:
        font_size = int(font_size_override)
    else:
        if is_portrait:
            # 竖屏：短边 / 38 → 608≈16，1080≈28 → 夹到 14–26
            base = short / 38.0
            font_size = int(round(base * size_scale))
            font_size = max(14, min(26, font_size))
        else:
            # 横屏：高度 / 48 → 720≈15，1080≈22.5，1440≈30，2160≈45→夹 32
            base = h / 48.0
            font_size = int(round(base * size_scale))
            font_size = max(14, min(32, font_size))
        if bilingual:
            # 双语两行更占高，再略缩
            font_size = max(13, int(round(font_size * 0.88)))

    # 极细描边：小字配细边，避免发糊发胖
    stroke_base = max(0.5, min(1.4, font_size / 28.0))
    stroke_width = round(stroke_base * float(preset.get("stroke_width_scale") or 1.0), 1)
    stroke_width = max(0.5, min(1.6, stroke_width))

    pos = POSITION_PRESETS.get(position_key) or POSITION_PRESETS["bottom"]
    # 贴底：默认约 2.4% 屏高；双语略加大避免两行贴边被裁
    margin_ratio = float(pos["margin_v_ratio"] or 0.024)
    margin_v = max(10, int(round(h * margin_ratio)))
    if bilingual and position_key in {"bottom", "bottom_high"}:
        margin_v = max(margin_v, int(round(h * 0.036)))

    # 左右边距：按宽度约 4.5%，给自动换行留气口，避免顶满左右
    margin_lr = max(24, min(80, int(round(w * 0.045))))

    # 兼容旧 custom_position 语义（0–100 从上到下）
    if pos.get("y_percent") is not None:
        y_percent = float(pos["y_percent"])
        subtitle_position = "center" if position_key == "center" else "custom"
    elif position_key == "top":
        y_percent = 5.0
        subtitle_position = "top"
    else:
        # bottom / bottom_high：ASS bottom + MarginV，不靠 y_percent 估位
        y_percent = 100.0 - (margin_v / max(1, h) * 100.0)
        subtitle_position = "bottom"

    return {
        "subtitle_font_size": font_size,
        "stroke_width": stroke_width,
        "stroke_color": preset.get("stroke_color") or "#000000",
        "subtitle_color": preset.get("subtitle_color") or "#FFFFFF",
        "subtitle_position": subtitle_position,
        "custom_position": y_percent,
        "margin_v": margin_v,
        "margin_lr": margin_lr,
        "ass_alignment": int(pos.get("align") or 2),
        "ass_border_style": int(preset.get("border_style") or 1),
        "ass_shadow": int(preset.get("shadow") or 0),
        "ass_back_colour": preset.get("back_colour"),
        # 主站 orientation 回退用：更贴底
        "subtitle_position_portrait_y_percent": 93.0,
        "subtitle_position_landscape_y_percent": 95.0,
        "is_portrait": is_portrait,
        "video_width": w,
        "video_height": h,
        "style_key": style_key,
        "size_preset": size_preset,
        "position_key": position_key,
    }


def resolve_burn_options(
    inputs: Optional[Dict[str, Any]] = None,
    *,
    video_path: str = "",
) -> Dict[str, Any]:
    inputs = inputs or {}
    w, h = 0, 0
    if video_path and os.path.isfile(video_path):
        w, h = _probe_wh(video_path)

    style_key = str(
        inputs.get("subtitle_style") or inputs.get("style_key") or "cinema"
    ).strip()
    if style_key not in STYLE_PRESETS:
        style_key = "cinema"

    size_preset = str(inputs.get("subtitle_size_preset") or "auto").strip().lower()
    if size_preset not in SIZE_PRESETS:
        size_preset = "auto"

    position_key = str(
        inputs.get("subtitle_position_key")
        or inputs.get("subtitle_position")
        or "bottom"
    ).strip().lower()
    # 兼容旧值 custom / bottom / top / center
    if position_key in {"custom", "bottom"}:
        position_key = "bottom"
    elif position_key not in POSITION_PRESETS:
        position_key = "bottom"

    raw_size = inputs.get("subtitle_font_size")
    override = None
    try:
        if raw_size is not None and str(raw_size).strip() not in {"", "0", "auto"}:
            override = int(raw_size)
    except (TypeError, ValueError):
        override = None

    # 旧默认 48 且未手动设定 → 走自适应
    if (
        not inputs.get("subtitle_font_size_user_set")
        and override in {48, 64, None}
        and size_preset == "auto"
    ):
        if override in {48, 64}:
            override = None

    bilingual = bool(inputs.get("bilingual"))
    style = adaptive_style(
        video_width=w,
        video_height=h,
        font_size_override=override if inputs.get("subtitle_font_size_user_set") else override,
        bilingual=bilingual,
        size_preset=size_preset if not (override and inputs.get("subtitle_font_size_user_set")) else "auto",
        style_key=style_key,
        position_key=position_key,
    )

    # 手动字号优先
    if inputs.get("subtitle_font_size_user_set") and override and override > 0:
        style["subtitle_font_size"] = int(override)
        style["stroke_width"] = max(1.2, min(2.8, round(override / 22.0, 1)))

    font_raw = (inputs.get("subtitle_font") or "simhei.ttf").strip() or "simhei.ttf"
    font = _resolve_font_file(font_raw)

    # 颜色：用户覆盖 > 预设
    color = (inputs.get("subtitle_color") or style["subtitle_color"]).strip() or "#FFFFFF"
    stroke = (inputs.get("stroke_color") or style["stroke_color"]).strip() or "#000000"
    try:
        stroke_width = float(
            inputs.get("stroke_width")
            if inputs.get("stroke_width") is not None
            else style["stroke_width"]
        )
    except (TypeError, ValueError):
        stroke_width = float(style["stroke_width"])

    opts: Dict[str, Any] = {
        "keep_original_audio": True,
        "original_audio_volume": 1.0,
        "voice_volume": 0.0,
        "bgm_volume": 0.0,
        "subtitle_enabled": True,
        "subtitle_mask_enabled": False,
        "subtitle_font": font,
        "subtitle_font_size": int(style["subtitle_font_size"]),
        "subtitle_color": color,
        "subtitle_position": style["subtitle_position"],
        "custom_position": float(style["custom_position"]),
        "subtitle_position_portrait_y_percent": style["subtitle_position_portrait_y_percent"],
        "subtitle_position_landscape_y_percent": style["subtitle_position_landscape_y_percent"],
        "stroke_color": stroke,
        "stroke_width": stroke_width,
        # 透传给 force_style / margin 计算
        "ass_margin_v": int(style["margin_v"]),
        "ass_margin_lr": int(style.get("margin_lr") or 40),
        "ass_alignment": int(style["ass_alignment"]),
        "ass_border_style": int(style["ass_border_style"]),
        "ass_shadow": int(style["ass_shadow"]),
        "ass_back_colour": style.get("ass_back_colour"),
        "threads": int(inputs.get("threads") or max(4, (os.cpu_count() or 4) // 2)),
        "fps": int(inputs.get("fps") or 30),
        "use_ffmpeg_merge": True,
        "merge_engine": "ffmpeg",
        "video_encoder": (inputs.get("video_encoder") or "libx264"),
        "_adaptive": {
            "video_width": style["video_width"],
            "video_height": style["video_height"],
            "is_portrait": style["is_portrait"],
            "font_size": style["subtitle_font_size"],
            "style_key": style_key,
            "size_preset": size_preset,
            "position_key": position_key,
            "margin_v": style["margin_v"],
            "margin_lr": style.get("margin_lr"),
            "bilingual": bilingual,
        },
    }
    # 原片硬字幕遮罩条（手动，可选）
    opts = apply_mask_to_burn_options(opts, inputs)
    ad = opts.setdefault("_adaptive", {})
    ad["mask_enabled"] = bool(opts.get("subtitle_mask_enabled"))
    ad["mask_side"] = opts.get("subtitle_mask_side") or ""
    ad["mask_color"] = opts.get("subtitle_mask_color") or ""
    ad["mask_height_percent"] = opts.get("subtitle_mask_height_percent")
    ad["subtitle_on_mask"] = bool(opts.get("subtitle_on_mask", True))
    return opts


def burn_subtitles_to_video(
    *,
    video_path: str,
    subtitle_path: str,
    output_path: str,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """
    将字幕硬烧到原片。保留原声音轨，不叠 TTS。
    返回 output_path。
    """
    if not video_path or not os.path.isfile(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    if not subtitle_path or not os.path.isfile(subtitle_path):
        raise FileNotFoundError(f"subtitle not found: {subtitle_path}")
    if os.path.getsize(subtitle_path) < 5:
        raise ValueError(f"subtitle empty: {subtitle_path}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    opts = resolve_burn_options(options, video_path=video_path)

    from loguru import logger

    logger.info(
        "burn style: "
        f"font={opts.get('subtitle_font')} size={opts.get('subtitle_font_size')} "
        f"stroke={opts.get('stroke_width')} pos={opts.get('subtitle_position')} "
        f"margin_v={opts.get('ass_margin_v')} "
        f"mask={opts.get('subtitle_mask_enabled')} "
        f"mask_side={opts.get('subtitle_mask_side')} "
        f"mask_h={opts.get('subtitle_mask_height_percent')} "
        f"adaptive={opts.get('_adaptive')}"
    )

    from app.services.generate_video import merge_materials

    return merge_materials(
        video_path=video_path,
        audio_path="",
        output_path=output_path,
        subtitle_path=subtitle_path,
        bgm_path=None,
        options=opts,
    )
