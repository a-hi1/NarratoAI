#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化面板

默认模式（仿 VideoLingo）：上传视频 → ASR → 翻译 → 硬烧字幕 → 成片
可选模式：多语配音（人声分离 + TTS + 混音 + 烧字幕）
可选模式：解说文案工厂（digest/copy/match/TTS/render）

注意：避免嵌套 st.tabs、避免把 status 写进 widget key——
Streamlit 1.x 在 DOM 差分时会触发 removeChild NotFoundError。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from app.services.cross_border import pipeline as cb_pipeline
from app.services.cross_border import task_store
from app.services.cross_border.state_machine import HUMAN_GATES, steps_for_mode
from app.services.cross_border.style_packs import (
    DEFAULT_BY_DIRECTION,
    style_choices_for_ui,
)
from webui import styles as ui_styles

_SRT_TIME = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def _tr(tr, key: str, default: Optional[str] = None) -> str:
    if tr is None:
        return default or key
    try:
        value = tr(key)
    except Exception:
        return default or key
    if not value or value == key:
        return default or key
    return value


def _load_selected_meta() -> Optional[Dict[str, Any]]:
    task_id = st.session_state.get("cb_task_id") or ""
    if not task_id:
        return None
    try:
        return task_store.load_meta(task_id)
    except FileNotFoundError:
        return None


_STEP_LABELS = {
    "asr": "语音识别",
    "translate": "字幕翻译",
    "burn": "烧录字幕",
    "separate": "人声分离",
    "dub_tts": "配音合成",
    "mix": "音轨混音",
    "digest": "内容摘要",
    "copy": "解说文案",
    "match": "脚本匹配",
    "tts": "解说配音",
    "render": "成片渲染",
    "packaging": "标题包装",
}

_STATUS_CN = {
    "draft": "草稿",
    "queued": "排队中",
    "asr_running": "识别中",
    "asr_done": "识别完成",
    "translate_running": "翻译中",
    "translate_done": "翻译完成",
    "burn_running": "烧字幕中",
    "burn_done": "烧字幕完成",
    "separate_running": "人声分离中",
    "separate_done": "人声分离完成",
    "dub_tts_running": "配音合成中",
    "dub_tts_done": "配音合成完成",
    "mix_running": "混音中",
    "mix_done": "混音完成",
    "digest_running": "摘要中",
    "digest_done": "摘要完成",
    "copy_running": "文案生成中",
    "copy_done": "待审核文案",
    "match_running": "匹配中",
    "match_done": "匹配完成",
    "tts_running": "配音中",
    "tts_done": "配音完成",
    "render_running": "渲染中",
    "render_done": "渲染完成",
    "packaging_running": "包装中",
    "packaging_done": "包装完成",
    "completed": "已完成",
    "failed": "失败",
}

_DIRECTION_CN = {
    "inbound": "引入 Inbound（en→zh）",
    "outbound": "出海 Outbound（zh→en）",
}

_MODE_CN = {
    "subtitle": "字幕本地化",
    "dubbing": "多语配音",
    "narration": "解说文案工厂",
}

_SUBNAV_OPTIONS = ("① 新建任务", "② 任务详情", "③ 任务列表")


def _task_mode(meta: Dict[str, Any]) -> str:
    mode = meta.get("mode") or (meta.get("inputs") or {}).get("mode") or "subtitle"
    mode = str(mode).strip().lower()
    return mode if mode in {"subtitle", "narration", "dubbing"} else "subtitle"


def _step_key_from_status(status: str) -> str:
    s = (status or "").strip()
    if s in {"completed", "packaging_done", "burn_done"}:
        if s == "burn_done":
            return "burn"
        return "packaging" if s == "packaging_done" else ""
    if s == "failed":
        return ""
    if s.endswith("_running") or s.endswith("_done"):
        return s.rsplit("_", 1)[0]
    return ""


def _render_pipeline_progress(meta: Dict[str, Any]) -> None:
    status = meta.get("status") or "draft"
    mode = _task_mode(meta)
    order = list(steps_for_mode(mode))
    current = _step_key_from_status(status)
    failed_step = ""
    if status == "failed":
        failed_step = (meta.get("error") or {}).get("step") or meta.get("step") or ""

    done_keys = set()
    if status == "completed":
        done_keys = set(order)
    elif status.endswith("_done") and current in order:
        idx = order.index(current)
        done_keys = set(order[: idx + 1])
    elif status.endswith("_running") and current in order:
        idx = order.index(current)
        done_keys = set(order[:idx])
    elif failed_step in order:
        idx = order.index(failed_step)
        done_keys = set(order[:idx])

    gate_key = "copy" if status == "copy_done" else ""
    running = status.endswith("_running") or cb_pipeline.is_running(meta.get("task_id") or "")
    steps = [(key, _STEP_LABELS.get(key, key)) for key in order]
    st.markdown(
        ui_styles.pipeline_steps_html(
            steps,
            current=current if (running or status.endswith("_done")) else current,
            done=done_keys,
            failed=failed_step,
            gate=gate_key,
            running=running,
        ),
        unsafe_allow_html=True,
    )


def _task_label(meta: Dict[str, Any]) -> str:
    name = (meta.get("display_name") or "").strip()
    if not name:
        name = task_store.ensure_display_name(meta)
    return name


def _friendly_error(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        return "未知错误"
    low = text.lower()
    if "winerror 5" in low or "拒绝访问" in text or "permissionerror" in low:
        return (
            "保存任务状态时文件被占用（常见于 Windows 杀软/索引/并发读写）。"
            "已自动加重试，请点「从失败步重试」。"
            f"\n\n技术详情：{text}"
        )
    if "placeholder" in low or "占位" in text:
        return f"{text}\n\n提示：可上传源字幕后点「仅重跑 ASR→翻译」。"
    if (
        "connection error" in low
        or "api_call_error" in low
        or "timed out" in low
        or "timeout" in low
        or "rate limit" in low
        or "提供商未注册" in text
    ):
        return (
            "大模型/翻译调用失败（网络抖动 / 超时）。"
            "请检查 config.toml 中的 LLM 配置后点「从失败步重试」。"
            f"\n\n技术详情：{text}"
        )
    if "illegal transition" in low:
        return (
            "状态机迁移异常。请再点「从失败步重试」。"
            f"\n\n技术详情：{text}"
        )
    return text


def _status_badge(meta: Dict[str, Any]) -> str:
    """返回状态面板 HTML（含模式 / 状态徽章与提示）。"""
    status = meta.get("status") or "draft"
    progress = meta.get("progress")
    err = meta.get("error") or {}
    status_cn = _STATUS_CN.get(status, status)
    step = (err.get("step") if isinstance(err, dict) else None) or meta.get("step") or ""
    step_cn = _STEP_LABELS.get(step, step)
    mode = _task_mode(meta)

    extras: List[str] = []
    if status == "failed" and step_cn:
        extras.append(f"失败步骤：{step_cn}")
    if status == "failed" and err:
        msg = err.get("message") if isinstance(err, dict) else err
        extras.append(_friendly_error(msg))
    gate = HUMAN_GATES.get(status)
    if gate:
        extras.append(str(gate))
    if status == "copy_done":
        extras.append("请审核下方解说文案，确认后点击「继续匹配成片」。")
    if status == "translate_done" and mode == "subtitle":
        extras.append("可改字幕后点「继续烧字幕」，或等待自动完成。")
    if status == "translate_done" and mode == "dubbing":
        extras.append("可改字幕后点「继续配音」，或等待自动完成。")
    if status == "separate_done" and mode == "dubbing":
        extras.append(
            f"分离后端：{(meta.get('artifacts') or {}).get('separate_backend') or '-'}。"
            " 可继续配音 TTS。"
        )
    tp = meta.get("translate_progress") or {}
    if status == "translate_running" and tp:
        done = tp.get("completed")
        total = tp.get("total")
        msg = str(tp.get("message") or "").strip()
        if total:
            extras.append(f"翻译节点 {done}/{total}" + (f" · {msg}" if msg else ""))
        elif msg:
            extras.append(msg)
    if cb_pipeline.is_running(meta.get("task_id") or ""):
        extras.append("后台任务运行中…字幕节点会局部自动刷新；状态条请点「刷新状态」。")

    return ui_styles.status_panel_html(
        mode_label=_MODE_CN.get(mode, mode),
        status_label=status_cn,
        status_key=status,
        progress=progress,
        extra_lines=extras,
    )


def _safe_rerun() -> None:
    """
    统一 rerun 入口。不在这里 sleep/轮询。
    真正的 removeChild 防护在 styles.inject_removechild_guard。
    """
    st.rerun()


def _parse_srt_cues_for_ui(text: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    """轻量解析 SRT → UI 节点；不依赖 dubbing 模块。"""
    if not text or not str(text).strip():
        return []
    blocks = re.split(r"\n\s*\n", str(text).strip())
    cues: List[Dict[str, Any]] = []
    idx = 0
    for block in blocks:
        lines = [ln.rstrip() for ln in block.strip().splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        if re.match(r"^\d+$", lines[0]) and len(lines) >= 3:
            time_line = lines[1]
            body_lines = lines[2:]
            try:
                idx = int(lines[0])
            except ValueError:
                idx += 1
        else:
            time_line = lines[0]
            body_lines = lines[1:]
            idx += 1
        m = _SRT_TIME.search(time_line)
        if not m:
            continue
        body = "\n".join(body_lines).strip()
        pending = body.startswith("…") or body.startswith("...")
        if pending:
            # 去掉预览用的省略号前缀
            body = re.sub(r"^[…\.]+\s*", "", body)
        cues.append(
            {
                "id": idx,
                "start": m.group(1).replace(".", ","),
                "end": m.group(2).replace(".", ","),
                "text": body,
                "pending": pending,
            }
        )
        if len(cues) >= max(1, int(limit or 200)):
            break
    return cues


def _srt_path_for_task(meta: Dict[str, Any], which: str) -> str:
    task_id = meta.get("task_id") or ""
    arts = meta.get("artifacts") or {}
    key = "source_srt" if which == "source" else "target_srt"
    path = arts.get(key) or ""
    if path and os.path.isfile(path):
        return path
    name = "source.srt" if which == "source" else "target.srt"
    if task_id:
        p = task_store.artifact_path(task_id, name)
        if os.path.isfile(p):
            return p
    return path or ""


def _render_live_subtitle_nodes(meta: Dict[str, Any], *, running: bool) -> None:
    """
    实时字幕节点：读取磁盘上的 source/target.srt（翻译中会增量写 target）。
    运行中用 st.fragment(run_every=2s) 局部刷新，避免整页 auto-rerun。
    """
    status = meta.get("status") or ""
    mode = _task_mode(meta)
    if mode not in {"subtitle", "dubbing"}:
        return

    show_live = running or status in {
        "asr_running",
        "asr_done",
        "translate_running",
        "translate_done",
        "burn_running",
        "burn_done",
        "completed",
        "separate_running",
        "separate_done",
        "dub_tts_running",
        "dub_tts_done",
        "mix_running",
        "mix_done",
        "failed",
    }
    if not show_live:
        return

    task_id = meta.get("task_id") or ""
    tp = meta.get("translate_progress") or {}
    want_auto = bool(
        running
        and status
        in {
            "asr_running",
            "translate_running",
            "burn_running",
            "separate_running",
            "dub_tts_running",
            "mix_running",
        }
    )

    def _draw() -> None:
        # fragment 内重新读盘，才能看到后台增量写入
        try:
            live_meta = task_store.load_meta(task_id) if task_id else meta
        except Exception:
            live_meta = meta
        live_status = live_meta.get("status") or status
        live_tp = live_meta.get("translate_progress") or tp
        src_path = _srt_path_for_task(live_meta, "source")
        tgt_path = _srt_path_for_task(live_meta, "target")
        src_text = task_store.read_text_artifact(src_path) if src_path else ""
        tgt_text = task_store.read_text_artifact(tgt_path) if tgt_path else ""
        src_cues = _parse_srt_cues_for_ui(src_text, limit=80)
        tgt_cues = _parse_srt_cues_for_ui(tgt_text, limit=80)

        # 翻译进度条（有则显示）
        if live_status == "translate_running" or live_tp:
            done = int(live_tp.get("completed") or 0)
            total = int(live_tp.get("total") or 0)
            msg = str(live_tp.get("message") or "")
            if total > 0:
                st.caption(f"翻译进度 **{done}/{total}** · {msg}")
                st.progress(min(1.0, max(0.0, done / float(total))))
            elif msg:
                st.caption(msg)

        if live_status == "asr_running" and not src_cues:
            st.info("正在识别台词… 识别完成后会先出现源字幕节点，再开始翻译。")
        elif live_status == "translate_running" and not tgt_cues and src_cues:
            st.info("正在翻译… 批次完成后节点会逐条从「…」变为已译。")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                ui_styles.subtitle_cues_html(
                    src_cues,
                    max_items=24,
                    title="源字幕节点",
                    subtitle=f"{os.path.basename(src_path) if src_path else 'source.srt'}"
                    + (f" · {len(src_cues)} 条" if src_cues else " · 等待识别"),
                ),
                unsafe_allow_html=True,
            )
        with c2:
            pending_n = sum(1 for c in tgt_cues if c.get("pending"))
            ready_n = len(tgt_cues) - pending_n
            sub = (
                f"已译 {ready_n}"
                + (f" · 待译/预览 {pending_n}" if pending_n else "")
                + (f" · {live_status}" if live_status else "")
            )
            st.markdown(
                ui_styles.subtitle_cues_html(
                    tgt_cues,
                    max_items=24,
                    title="目标字幕节点（实时）",
                    subtitle=sub or "等待翻译写入 target.srt",
                ),
                unsafe_allow_html=True,
            )

    st.markdown("##### 字幕节点")
    if want_auto and hasattr(st, "fragment"):
        # 局部刷新：长任务 3s 足够，比 2s 更省 CPU；只重绘本块
        @st.fragment(run_every=3)
        def _live_fragment() -> None:
            _draw()

        _live_fragment()
        st.caption("运行中每 3 秒自动刷新字幕节点（局部刷新，几乎不拖慢后台生成）。")
    else:
        _draw()


def _maybe_auto_refresh(task_id: str) -> None:
    """
    不自动 st.rerun() 整页。

    Streamlit 1.x 在外层 tabs + 复杂详情树下，周期性整页 rerun
    极易触发浏览器 removeChild NotFoundError。
    进度请点「刷新状态」；字幕节点在详情内用 st.fragment 局部刷新。
    前端已注入 removeChild 防护，偶发红框也会被隐藏。
    """
    if not task_id or not cb_pipeline.is_running(task_id):
        return
    st.info(
        "后台仍在运行。字幕节点区会局部自动刷新；"
        "状态条/进度请点上方「刷新状态」（已关闭整页自动刷新，避免页面崩溃）。"
    )


def _render_create_form(tr):
    st.markdown(
        ui_styles.card_html(
            _tr(tr, "Cross-border Localization", "新建本地化任务"),
            "本地上传或粘贴公开视频链接 → 自动识别台词 → 翻译 → 烧字幕成片。有现成字幕可一并上传，跳过识别。",
            body_html=ui_styles.pipeline_steps_html(
                [
                    ("upload", "取片"),
                    ("asr", "识别台词"),
                    ("translate", "翻译"),
                    ("burn", "烧字幕"),
                ],
                current="upload",
                running=False,
            ),
        ),
        unsafe_allow_html=True,
    )

    # 第一步：选路径（默认推荐）
    mode_label = st.radio(
        "① 选择模式",
        options=[
            "字幕本地化（推荐）",
            "多语配音（实验）",
            "解说文案工厂（高级）",
        ],
        horizontal=True,
        key="cb_mode_label",
        help=(
            "字幕本地化 = 识别 + 翻译 + 烧字幕（保留原声）；"
            "多语配音 = 分离人声 + 目标语 TTS + 混音 + 烧字幕；"
            "解说文案工厂 = 重写解说 + TTS + 剪辑。"
        ),
    )
    if mode_label.startswith("字幕"):
        mode = "subtitle"
    elif mode_label.startswith("多语"):
        mode = "dubbing"
    else:
        mode = "narration"

    direction_label = st.radio(
        "② 选择方向",
        options=["引入 Inbound（en→zh）", "出海 Outbound（zh→en）"],
        horizontal=True,
        key="cb_direction_label",
        help="引入：外网英文片 → 中文字幕；出海：国内中文片 → 英文字幕。",
    )
    direction = "inbound" if direction_label.startswith("引入") else "outbound"

    # Streamlit 带 key 的输入框会锁定 session_state；切换方向时必须同步语对/默认音色等
    if st.session_state.get("cb_direction_synced") != direction:
        if direction == "inbound":
            st.session_state["cb_source_lang"] = "en"
            st.session_state["cb_target_lang"] = "zh"
            st.session_state["cb_voice_name"] = "zh-CN-XiaoyiNeural"
            st.session_state["cb_platform"] = "douyin"
            st.session_state["cb_word_count"] = 320
            st.session_state["cb_ost_ratio"] = 30
        else:
            st.session_state["cb_source_lang"] = "zh"
            st.session_state["cb_target_lang"] = "en"
            st.session_state["cb_voice_name"] = "en-US-JennyNeural"
            st.session_state["cb_platform"] = "tiktok"
            st.session_state["cb_word_count"] = 150
            st.session_state["cb_ost_ratio"] = 20
        st.session_state["cb_direction_synced"] = direction

    st.markdown("**③ 准备素材**")
    source_mode = st.radio(
        "素材来源",
        options=["本地上传", "链接下载"],
        horizontal=True,
        key="cb_source_mode",
        help="本地上传：本机视频文件。链接下载：粘贴 YouTube 等公开链接，用 yt-dlp 取片（需网络/代理）。",
    )

    uploaded = None
    source_url = ""
    download_max_height = 1080
    download_cookiefile = ""
    if source_mode == "本地上传":
        uploaded = st.file_uploader(
            "上传视频（必填）",
            type=["mp4", "mov", "mkv", "webm"],
            key="cb_video_uploader",
            help="支持 mp4 / mov / mkv / webm。大文件会流式写入，请耐心等待。",
        )
    else:
        from app.services.cross_border import url_download as url_dl

        if not url_dl.yt_dlp_available():
            st.warning(
                "未检测到 yt-dlp。请先安装：`.venv/Scripts/python -m pip install yt-dlp`，"
                "或改回「本地上传」。"
            )
        source_url = st.text_input(
            "视频链接",
            key="cb_source_url",
            placeholder="https://www.youtube.com/watch?v=... 或其它 yt-dlp 支持的公开链接",
            help="仅用于你有权处理的公开内容。国内访问 YouTube 请先在设置里开代理。",
        )
        with st.expander("下载选项（一般不用改）", expanded=False):
            height_label = st.selectbox(
                "最高清晰度",
                options=["1080p（推荐）", "720p", "1440p", "2160p"],
                index=0,
                key="cb_dl_height",
            )
            height_map = {
                "1080p（推荐）": 1080,
                "720p": 720,
                "1440p": 1440,
                "2160p": 2160,
            }
            download_max_height = height_map.get(height_label, 1080)
            download_cookiefile = st.text_input(
                "Cookie 文件路径（可选）",
                key="cb_dl_cookie",
                placeholder="例如 C:\\Users\\...\\cookies.txt",
                help="部分站点需登录时，可导出 Netscape 格式 cookies.txt。",
            )
            st.caption(
                "下载后会尽量转成 H.264 + AAC 的 mp4，便于播放和烧字幕。"
                "长视频可能需要几分钟，请耐心等待。"
            )

    with st.expander("可选：已有字幕文件（.srt）", expanded=False):
        st.caption("不传则自动从视频识别。传了就直接用，跳过 ASR。")
        uploaded_srt = st.file_uploader(
            "源语言字幕",
            type=["srt"],
            key="cb_srt_uploader",
            label_visibility="collapsed",
        )

    glossary_text = ""
    task_name = st.text_input(
        "任务显示名称（可选）",
        key="cb_task_name",
        placeholder="例如：引入 · 产品开箱 · 字幕本地化",
    )

    bilingual = False
    subtitle_font_size = 0  # 0 = 按视频分辨率自适应
    subtitle_style = "cinema"
    subtitle_size_preset = "auto"
    subtitle_position_key = "bottom"
    subtitle_font_size_user_set = False
    subtitle_mask_enabled = False
    subtitle_mask_side = "bottom"
    subtitle_mask_color = "black"
    subtitle_mask_height_percent = 14.0
    subtitle_on_mask = True
    asr_backend = "auto"
    # dubbing defaults（配音必须压过伴奏，否则听感像「只有背景音」）
    separate_backend = "auto"
    duck_gain = 0.18
    instrumental_volume = 0.55
    dub_voice_volume = 1.8
    voice_gender = "female"
    burn_after_mix = True
    sidechain_duck = True
    # 音色/引擎：配音在 expander 里填；解说在高级里填；这里只做初值
    voice_name = "zh-CN-XiaoyiNeural" if direction == "inbound" else "en-US-JennyNeural"
    tts_engine = "edge_tts" if mode == "dubbing" else ""
    voice_rate = 1.0
    voice_pitch = 1.0

    if mode in {"subtitle", "dubbing"}:
        from app.services.cross_border import burn as burn_mod

        # 渐进披露：默认收起样式，降低门槛；需要时再展开
        style_title = (
            "④ 字幕样式（可选，默认电影字幕）"
            if mode == "subtitle"
            else "④ 配音与字幕样式"
        )
        with st.expander(style_title, expanded=(mode == "dubbing")):
            if mode == "dubbing":
                from app.services.cross_border.dubbing import separate as sep_mod
                from app.services.cross_border.dubbing import voices as voices_mod

                demucs_ok = sep_mod.demucs_available()
                if demucs_ok:
                    st.success(
                        "已检测到 demucs + torch，默认做人声/伴奏真分离（CPU 会慢一些）。"
                    )
                else:
                    st.warning(
                        "未安装 demucs/torch：将降级为中置削弱/压低原声。"
                        " 真分离：`.venv/Scripts/python -m pip install torch demucs`"
                    )

                # —— 配音音色控制（新建即可换，不必等任务详情）——
                st.markdown("##### 配音音色（可换）")
                eng_choices = voices_mod.engine_choices_for_ui()
                eng_ids = [e for e, _ in eng_choices]
                eng_labels = {e: lab for e, lab in eng_choices}
                if "cb_tts_engine_dub" not in st.session_state:
                    st.session_state["cb_tts_engine_dub"] = "edge_tts"
                tts_engine = st.selectbox(
                    "TTS 引擎",
                    options=eng_ids,
                    format_func=lambda k: eng_labels.get(k, k or "跟随全局"),
                    key="cb_tts_engine_dub",
                    help="Edge 免费但偏机械；豆包/Qwen 更自然；IndexTTS 可克隆参考音（需本地服务）。",
                )
                gcol_a, gcol_b = st.columns(2)
                with gcol_a:
                    gender_label = st.selectbox(
                        "音色性别",
                        options=["女声", "男声"],
                        index=0,
                        key="cb_voice_gender",
                    )
                    voice_gender = "male" if gender_label.startswith("男") else "female"
                with gcol_b:
                    # 目标语：跟方向默认，可在高级改；这里用于筛预设
                    tgt_for_voice = (
                        st.session_state.get("cb_target_lang")
                        or ("zh" if direction == "inbound" else "en")
                    )
                    tgt_for_voice = voices_mod.normalize_lang(str(tgt_for_voice))
                    st.caption(f"当前按目标语 **{tgt_for_voice}** 筛选预设（高级可改语种）")

                presets = voices_mod.presets_for_engine(
                    tts_engine or "edge_tts",
                    tgt_for_voice,
                    gender=voice_gender,
                )
                preset_ids = [p[0] for p in presets]
                preset_lab = {p[0]: p[1] for p in presets}
                # 性别/引擎/语种变化时，若当前音色不在列表则切到第一项
                cur_voice = (st.session_state.get("cb_voice_name") or "").strip()
                sync_key = f"{tts_engine}|{tgt_for_voice}|{voice_gender}"
                if st.session_state.get("cb_voice_sync_key") != sync_key:
                    st.session_state["cb_voice_sync_key"] = sync_key
                    if preset_ids and (not cur_voice or cur_voice not in preset_ids):
                        # 空 id 的占位（克隆引擎）不强制写入
                        first = next((x for x in preset_ids if x), "")
                        if first:
                            st.session_state["cb_voice_name"] = first
                            cur_voice = first
                    st.session_state["cb_dub_voice_lang"] = tgt_for_voice

                if preset_ids and any(preset_ids):
                    # 选项直接用 voice id，避免语种/性别切换后 index 错位
                    if st.session_state.get("cb_voice_preset") not in preset_ids:
                        preferred = cur_voice if cur_voice in preset_ids else next(
                            (x for x in preset_ids if x), preset_ids[0]
                        )
                        st.session_state["cb_voice_preset"] = preferred
                    picked_id = st.selectbox(
                        "音色预设",
                        options=preset_ids,
                        format_func=lambda vid: preset_lab.get(vid, vid or "（自定义）"),
                        key="cb_voice_preset",
                        help="选预设会写入下方音色 ID；也可直接改 ID。",
                    )
                    if picked_id and st.session_state.get("cb_voice_name") != picked_id:
                        st.session_state["cb_voice_name"] = picked_id

                if "cb_voice_name" not in st.session_state:
                    st.session_state["cb_voice_name"] = voices_mod.default_voice_for_lang(
                        tgt_for_voice, gender=voice_gender
                    )
                voice_name = st.text_input(
                    "音色 ID / 名称（可改）",
                    key="cb_voice_name",
                    help=(
                        "Edge：如 zh-CN-XiaoxiaoNeural；"
                        "豆包：如 BV700_V2_streaming；"
                        "克隆引擎：填参考音色 ID 或本地 wav 路径（视引擎约定）。"
                    ),
                )
                r1, r2 = st.columns(2)
                with r1:
                    if "cb_voice_rate" not in st.session_state:
                        st.session_state["cb_voice_rate"] = 1.0
                    voice_rate = st.slider(
                        "语速",
                        min_value=0.7,
                        max_value=1.4,
                        step=0.05,
                        key="cb_voice_rate",
                        help="1.0 正常；偏快可塞进更短字幕槽。",
                    )
                with r2:
                    if "cb_voice_pitch" not in st.session_state:
                        st.session_state["cb_voice_pitch"] = 1.0
                    voice_pitch = st.slider(
                        "音调（Edge/Azure 有效）",
                        min_value=0.8,
                        max_value=1.2,
                        step=0.05,
                        key="cb_voice_pitch",
                    )
                st.info(
                    "上传自定义音色 / 原片声线克隆：后续可做（参考音 wav + IndexTTS）。"
                    " 当前请用上方引擎预设或手动填音色 ID。"
                )

                st.markdown("##### 分离与混音")
                sep_labels = {
                    "auto": "自动（优先 demucs 真分离，CPU 长片较慢）",
                    "demucs": "强制 demucs 真分离（CPU 长片可能 30–90 分钟）",
                    "center_cancel": "立体声中置削弱（近似·快）",
                    "duck": "压低原声（保底·最快）",
                }
                separate_backend = st.selectbox(
                    "人声分离方式",
                    options=list(sep_labels.keys()),
                    format_func=lambda k: sep_labels[k],
                    index=0 if demucs_ok else 0,
                    key="cb_separate_backend",
                    help=(
                        "长视频（>10 分钟）若要快：选「中置削弱」或「压低原声」。"
                        " demucs 真分离质量最好，但 CPU 无 GPU 时 17 分钟片可能要半小时以上。"
                        " 人声分离与配音 TTS 已默认并行。"
                    ),
                )
                c_d1, c_d2 = st.columns(2)
                with c_d1:
                    duck_gain = st.slider(
                        "压低原声增益（仅 duck）",
                        min_value=0.0,
                        max_value=0.6,
                        value=0.18,
                        step=0.02,
                        key="cb_duck_gain",
                        help="仅 duck 后端使用；0=静音原声。",
                    )
                    instrumental_volume = st.slider(
                        "伴奏音量",
                        min_value=0.1,
                        max_value=1.2,
                        value=0.55,
                        step=0.05,
                        key="cb_instr_vol",
                        help="建议 0.4–0.7；太高会盖住配音。",
                    )
                with c_d2:
                    dub_voice_volume = st.slider(
                        "配音音量",
                        min_value=0.8,
                        max_value=2.5,
                        value=1.8,
                        step=0.05,
                        key="cb_dub_vol",
                        help="默认 1.8，确保中文/目标语配音听得清。",
                    )
                    sidechain_duck = st.checkbox(
                        "人声出现时自动压低伴奏（sidechain）",
                        value=True,
                        key="cb_sidechain_duck",
                        help="配音开口时伴奏略压，更像正式混音；关闭则两轨硬叠。",
                    )
                burn_after_mix = st.checkbox(
                    "混音后烧目标字幕",
                    value=True,
                    key="cb_burn_after_mix",
                    help="关闭则只导出配音视频（无硬字幕）。",
                )
                st.caption(
                    "链路：识别 → 翻译 →（人声分离 ∥ 目标语 TTS 并行）→ 伴奏混音 → 烧字幕。"
                    " 长片瓶颈多半在 demucs；要快请改「中置削弱/压低原声」。音色须对应目标语。"
                )

            bilingual = st.checkbox(
                "双语字幕（目标语在上 / 源语在下）",
                value=False,
                key="cb_bilingual",
            )
            style_choices = burn_mod.style_choices_for_ui()
            style_labels = [f"{lab}" for _, lab in style_choices]
            style_keys = [k for k, _ in style_choices]
            style_idx = st.selectbox(
                "字幕样式",
                options=list(range(len(style_labels))),
                format_func=lambda i: style_labels[i],
                index=0,
                key="cb_subtitle_style",
            )
            subtitle_style = style_keys[int(style_idx)]

            pos_labels = {
                "bottom": "底部（推荐）",
                "bottom_high": "底部偏上（躲开原字幕）",
                "center": "画面中央",
                "top": "顶部",
            }
            pos_key = st.selectbox(
                "字幕位置",
                options=list(pos_labels.keys()),
                format_func=lambda k: pos_labels[k],
                index=0,
                key="cb_subtitle_pos",
            )
            subtitle_position_key = pos_key

            size_labels = {
                "auto": "自动（按分辨率）",
                "small": "偏小",
                "medium": "标准",
                "large": "偏大",
                "manual": "手动数值",
            }
            size_key = st.selectbox(
                "字号",
                options=list(size_labels.keys()),
                format_func=lambda k: size_labels[k],
                index=0,
                key="cb_font_mode",
            )
            if size_key == "manual":
                subtitle_font_size = st.slider(
                    "字号数值（电影字幕 1080p 约 16–18）",
                    min_value=12,
                    max_value=48,
                    value=17,
                    step=1,
                    key="cb_font_size",
                )
                subtitle_font_size_user_set = True
                subtitle_size_preset = "auto"
            else:
                subtitle_font_size = 0
                subtitle_font_size_user_set = False
                subtitle_size_preset = size_key if size_key != "medium" else "auto"
                if size_key == "medium":
                    subtitle_size_preset = "medium"

            st.markdown("##### 原片硬字幕遮罩（可选）")
            subtitle_mask_enabled = st.checkbox(
                "用遮罩条盖住原片硬字幕，再烧译文",
                value=False,
                key="cb_mask_enabled",
                help="原片底部/顶部已烧死字幕时勾选。不会擦除画面，只是盖住再叠新字幕。",
            )
            if subtitle_mask_enabled:
                m1, m2 = st.columns(2)
                with m1:
                    side_labels = dict(burn_mod.mask_side_choices_for_ui())
                    subtitle_mask_side = st.selectbox(
                        "遮罩位置",
                        options=list(side_labels.keys()),
                        format_func=lambda k: side_labels[k],
                        index=0,
                        key="cb_mask_side",
                    )
                with m2:
                    color_labels = dict(burn_mod.mask_color_choices_for_ui())
                    subtitle_mask_color = st.selectbox(
                        "遮罩颜色",
                        options=list(color_labels.keys()),
                        format_func=lambda k: color_labels[k],
                        index=0,
                        key="cb_mask_color",
                    )
                subtitle_mask_height_percent = st.slider(
                    "遮罩高度（占画面高 %）",
                    min_value=int(burn_mod.MASK_HEIGHT_MIN),
                    max_value=int(burn_mod.MASK_HEIGHT_MAX),
                    value=int(burn_mod.DEFAULT_MASK_HEIGHT_PERCENT),
                    step=1,
                    key="cb_mask_height",
                )
                subtitle_on_mask = st.checkbox(
                    "新字幕叠在遮罩条上",
                    value=True,
                    key="cb_on_mask",
                    help="开启：译文写在遮罩条内。关闭：译文挪到遮罩外侧。",
                )
                st.caption(
                    "建议：原字幕贴底 → 底部遮罩 + 叠在条上；"
                    "原字幕偏高且不想挡画面 → 可改「字幕位置」为顶部，或关掉「叠在条上」。"
                )

            st.caption(
                "默认电影字幕：更小字、贴底、细描边，方便看画面。"
                "1080p 横屏约 17px，竖屏约 12px。成片后仍可在详情页改样式重烧。"
            )

        with st.expander("术语表与识别（一般不用改）", expanded=False):
            glossary_text = st.text_area(
                "术语表（可选）",
                height=80,
                placeholder="MrBeast = MrBeast\n老干妈 => Lao Gan Ma | lock",
                key="cb_glossary",
            )
            asr_backend_label = st.selectbox(
                "语音识别",
                options=[
                    "auto（内置 whisper，推荐）",
                    "whisper 内置 faster-whisper",
                    "local FunASR（需本地服务）",
                    "firered（需本地服务）",
                    "bailian 阿里百炼",
                    "manual 仅用上传字幕",
                ],
                index=0,
                key="cb_asr_backend",
            )
            asr_backend_map = {
                "auto（内置 whisper，推荐）": "auto",
                "whisper 内置 faster-whisper": "whisper",
                "local FunASR（需本地服务）": "local",
                "firered（需本地服务）": "firered",
                "bailian 阿里百炼": "bailian",
                "manual 仅用上传字幕": "manual",
            }
            asr_backend = asr_backend_map.get(asr_backend_label, "auto")
    else:
        glossary_text = st.text_area(
            "术语表（可选）",
            height=80,
            placeholder="MrBeast = MrBeast\n老干妈 => Lao Gan Ma | lock",
            key="cb_glossary",
        )
        asr_backend = "auto"

    # 解说工厂专属（不要覆盖配音 expander 已写入的 voice_name / tts_engine）
    style_pack = DEFAULT_BY_DIRECTION[direction]
    duration_mode = "keep"
    original_audio_ratio = 30 if direction == "inbound" else 20
    source_credit = True
    credit_hint = ""
    content_type = "tech_review"
    platform = "douyin" if direction == "inbound" else "tiktok"
    narration_word_count = 320 if direction == "inbound" else 150
    stop_at_copy = True
    if direction == "inbound":
        source_lang, target_lang = "en", "zh"
    else:
        source_lang, target_lang = "zh", "en"
    # 非配音模式才给默认音色；配音已在「④ 配音与字幕样式」里选好
    if mode != "dubbing":
        voice_name = "zh-CN-XiaoyiNeural" if direction == "inbound" else "en-US-JennyNeural"
        if mode != "narration":
            tts_engine = tts_engine or ""

    if mode == "narration":
        style_map = style_choices_for_ui(direction)
        default_pack = DEFAULT_BY_DIRECTION[direction]
        style_labels = list(style_map.keys())
        default_label = next(
            (label for label, pid in style_map.items() if pid == default_pack),
            style_labels[0],
        )
        try:
            default_index = style_labels.index(default_label)
        except ValueError:
            default_index = 0
        style_label = st.selectbox(
            "风格包",
            options=style_labels,
            index=default_index,
            key="cb_style_pack",
        )
        style_pack = style_map[style_label]

        col1, col2, col3 = st.columns(3)
        with col1:
            duration_mode = st.selectbox(
                "时长策略",
                options=["keep", "compress_90s", "compress_60s"],
                index=0,
                key="cb_duration_mode",
            )
        with col2:
            if "cb_ost_ratio" not in st.session_state:
                st.session_state["cb_ost_ratio"] = 30 if direction == "inbound" else 20
            original_audio_ratio = st.slider(
                "原片占比目标 %",
                min_value=0,
                max_value=90,
                step=5,
                key="cb_ost_ratio",
            )
        with col3:
            source_credit = st.checkbox("来源声明", value=True, key="cb_source_credit")
        credit_hint = st.text_input("来源/品牌提示", key="cb_credit_hint", placeholder="频道名或作品名")
        stop_at_copy = st.checkbox(
            "生成到解说文案后暂停（推荐）",
            value=True,
            key="cb_stop_at_copy",
        )

    with st.expander("高级", expanded=False):
        # 语对随方向自动切换（见上方 cb_direction_synced）；此处只读 session / 允许手改
        expected_pair = "en → zh" if direction == "inbound" else "zh → en"
        st.caption(
            f"当前方向：**{_DIRECTION_CN.get(direction, direction)}**，默认语对 **{expected_pair}**。"
            " 切换「引入/出海」会自动改源/目标语言；仍可在下面手改。"
        )
        c1, c2 = st.columns(2)
        with c1:
            # 不用 value= 抢 key：由 session_state 驱动，避免方向切换后仍显示旧值
            if "cb_source_lang" not in st.session_state:
                st.session_state["cb_source_lang"] = source_lang
            source_lang = st.text_input("源语言", key="cb_source_lang")
        with c2:
            if "cb_target_lang" not in st.session_state:
                st.session_state["cb_target_lang"] = target_lang
            target_lang = st.text_input("目标语言", key="cb_target_lang")
        if mode == "dubbing":
            from app.services.cross_border.dubbing import voices as voices_mod

            lang_choices = voices_mod.lang_choices_for_ui()
            lang_codes = [c for c, _ in lang_choices]
            # 目标语快捷选择（音色控件已在上方 expander，这里只改语种）
            cur_tgt = (st.session_state.get("cb_target_lang") or target_lang or "en")[:2]
            try:
                tgt_idx = lang_codes.index(cur_tgt)
            except ValueError:
                tgt_idx = lang_codes.index("en") if "en" in lang_codes else 0
            pick = st.selectbox(
                "目标语种（快捷）",
                options=list(range(len(lang_codes))),
                format_func=lambda i: lang_choices[i][1],
                index=tgt_idx,
                key="cb_target_lang_pick",
                help="选择后会写入目标语言；上方「配音音色」预设会按新语种刷新。",
            )
            picked_lang = lang_codes[int(pick)]
            if st.session_state.get("cb_target_lang") != picked_lang:
                st.session_state["cb_target_lang"] = picked_lang
                target_lang = picked_lang
                # 语种变了 → 下次渲染按新语重筛音色预设
                st.session_state.pop("cb_voice_sync_key", None)
            # 从 session 回读 expander 已选的音色/引擎（避免被默认值覆盖）
            voice_name = (st.session_state.get("cb_voice_name") or voice_name or "").strip()
            tts_engine = st.session_state.get("cb_tts_engine_dub", tts_engine)
            voice_rate = float(st.session_state.get("cb_voice_rate") or voice_rate or 1.0)
            voice_pitch = float(st.session_state.get("cb_voice_pitch") or voice_pitch or 1.0)
            st.caption(
                f"当前配音：引擎 `{tts_engine or 'edge_tts'}` · 音色 `{voice_name or '-'}` · "
                f"语速 {voice_rate:.2f}。可在上方「④ 配音与字幕样式」更换。"
            )
        if mode == "narration":
            asr_backend_label = st.selectbox(
                "ASR 后端",
                options=[
                    "auto（按语言 + 配置自动）",
                    "local FunASR-Pack",
                    "firered 本地 ASR",
                    "bailian 阿里百炼",
                    "whisper 本地",
                    "manual 仅用上传字幕",
                ],
                index=0,
                key="cb_asr_backend_narr",
            )
            asr_backend_map = {
                "auto（按语言 + 配置自动）": "auto",
                "local FunASR-Pack": "local",
                "firered 本地 ASR": "firered",
                "bailian 阿里百炼": "bailian",
                "whisper 本地": "whisper",
                "manual 仅用上传字幕": "manual",
            }
            asr_backend = asr_backend_map.get(asr_backend_label, "auto")
            content_type = st.selectbox(
                "内容类型",
                options=[
                    "tech_review",
                    "product_demo",
                    "skit_meme",
                    "knowledge",
                    "story_recap",
                    "news_explain",
                ],
                key="cb_content_type",
            )
            if "cb_platform" not in st.session_state:
                st.session_state["cb_platform"] = platform
            platform = st.text_input("目标平台", key="cb_platform")
            if "cb_word_count" not in st.session_state:
                st.session_state["cb_word_count"] = int(narration_word_count)
            narration_word_count = st.number_input(
                "目标文案字数/词数",
                min_value=50,
                max_value=5000,
                step=10,
                key="cb_word_count",
            )
            if "cb_voice_name" not in st.session_state:
                st.session_state["cb_voice_name"] = (
                    "zh-CN-XiaoyiNeural" if direction == "inbound" else "en-US-JennyNeural"
                )
            voice_name = st.text_input("TTS 音色", key="cb_voice_name")
            tts_engine = st.selectbox(
                "TTS 引擎",
                options=["", "edge_tts", "azure_speech", "doubaotts", "tencent_tts", "qwen3_tts"],
                format_func=lambda x: x or "跟随全局配置",
                key="cb_tts_engine",
            )

    if mode == "subtitle":
        start_label = "开始字幕本地化"
    elif mode == "dubbing":
        start_label = "开始多语配音"
    else:
        start_label = "开始解说文案生成"
    if st.button(start_label, type="primary", use_container_width=True, key="cb_start"):
        use_url = source_mode == "链接下载"
        if use_url:
            from app.services.cross_border import url_download as url_dl

            if not (source_url or "").strip():
                st.error("请粘贴视频链接，或改回「本地上传」")
                return
            if not url_dl.is_http_url(source_url):
                st.error("链接格式无效，请使用 http(s) 开头的公开视频地址")
                return
            if not url_dl.yt_dlp_available():
                st.error("未安装 yt-dlp，无法链接下载。请 pip install yt-dlp 或改用本地上传。")
                return
            video_title = "链接视频"
        else:
            if not uploaded:
                st.error("请先上传视频，或切换到「链接下载」")
                return
            video_title = task_store.video_stem(uploaded.name)

        # 配音模式：若未手填音色，按目标语+性别给默认
        if mode == "dubbing" and not (voice_name or "").strip():
            from app.services.cross_border.dubbing import voices as voices_mod

            voice_name = voices_mod.default_voice_for_lang(
                target_lang or "en", gender=voice_gender
            )

        meta = task_store.create_task(
            direction=direction,
            video_path="",
            source_lang=source_lang,
            target_lang=target_lang,
            style_pack=style_pack,
            duration_mode=duration_mode,
            original_audio_ratio=float(original_audio_ratio),
            glossary=glossary_text,
            source_credit=source_credit,
            content_type=content_type,
            platform=platform,
            credit_hint=credit_hint,
            narration_word_count=int(narration_word_count),
            asr_backend=asr_backend,
            voice_name=voice_name,
            tts_engine=tts_engine or ("edge_tts" if mode == "dubbing" else ""),
            voice_rate=float(voice_rate if mode == "dubbing" else 1.0),
            voice_pitch=float(voice_pitch if mode == "dubbing" else 1.0),
            task_name=(task_name or "").strip(),
            video_title=video_title,
            mode=mode,
            bilingual=bilingual,
            subtitle_font="simhei.ttf",
            subtitle_font_size=int(subtitle_font_size or 0),
            subtitle_position=subtitle_position_key,
            subtitle_color="#FFFFFF",
            subtitle_style=subtitle_style,
            subtitle_size_preset=subtitle_size_preset,
            subtitle_position_key=subtitle_position_key,
            subtitle_font_size_user_set=bool(subtitle_font_size_user_set),
            subtitle_mask_enabled=bool(subtitle_mask_enabled),
            subtitle_mask_side=subtitle_mask_side,
            subtitle_mask_color=subtitle_mask_color,
            subtitle_mask_height_percent=float(subtitle_mask_height_percent or 14.0),
            subtitle_on_mask=bool(subtitle_on_mask),
            separate_backend=separate_backend,
            duck_gain=float(duck_gain),
            instrumental_volume=float(instrumental_volume),
            dub_voice_volume=float(dub_voice_volume),
            voice_gender=voice_gender,
            burn_after_mix=bool(burn_after_mix),
            sidechain_duck=bool(sidechain_duck),
        )
        # 手动字号时关掉自适应
        if subtitle_font_size_user_set and int(subtitle_font_size or 0) > 0:
            meta["inputs"]["subtitle_auto_style"] = False
            meta["inputs"]["subtitle_font_size_user_set"] = True
        else:
            meta["inputs"]["subtitle_auto_style"] = True
            meta["inputs"]["subtitle_font_size_user_set"] = False
        task_id = meta["task_id"]
        tdir = task_store.task_dir(task_id)

        try:
            if use_url:
                from app.services.cross_border import url_download as url_dl

                with st.spinner("正在下载视频（可能需要几分钟）…"):
                    dl = url_dl.download_url_to_task_dir(
                        source_url.strip(),
                        tdir,
                        max_height=int(download_max_height or 1080),
                        cookiefile=(download_cookiefile or "").strip(),
                        prefer_h264=True,
                    )
                video_path = dl["path"]
                video_title = dl.get("title") or video_title
                meta["inputs"]["source_url"] = dl.get("source_url") or source_url.strip()
                meta["inputs"]["source_webpage_url"] = dl.get("webpage_url") or ""
                meta["inputs"]["source_extractor"] = dl.get("extractor") or ""
                meta["inputs"]["source_transcoded"] = bool(dl.get("transcoded"))
                meta["inputs"]["video_source"] = "url"
                task_store.append_log(
                    meta,
                    f"downloaded from url extractor={dl.get('extractor')} "
                    f"transcoded={dl.get('transcoded')} size={dl.get('filesize')}",
                )
            else:
                # 固定 ASCII 文件名，避免中文路径让 ffprobe/ffmpeg 滤镜踩坑；
                # 显示名仍用原始上传文件名。
                ext = os.path.splitext(uploaded.name or "")[1].lower() or ".mp4"
                if ext not in {".mp4", ".mov", ".mkv", ".webm"}:
                    ext = ".mp4"
                video_path = os.path.join(tdir, f"source{ext}")
                # 大文件流式落盘，避免 getbuffer() 整文件进内存
                with open(video_path, "wb") as f:
                    uploaded.seek(0)
                    while True:
                        chunk = uploaded.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                meta["inputs"]["video_source"] = "upload"
        except Exception as exc:
            # 下载/落盘失败：删掉空任务，避免列表堆垃圾
            err_text = str(exc)
            try:
                import shutil

                shutil.rmtree(tdir, ignore_errors=True)
            except Exception:
                pass
            st.error(f"准备源视频失败：{err_text}")
            return

        task_store.refresh_display_name(
            meta,
            video_path=video_path,
            video_title=video_title,
            task_name=(task_name or "").strip(),
        )
        meta["inputs"]["video_path"] = video_path

        if uploaded_srt is not None:
            srt_path = os.path.join(tdir, "source.srt")
            with open(srt_path, "wb") as f:
                uploaded_srt.seek(0)
                f.write(uploaded_srt.read())
            meta["artifacts"]["source_srt"] = srt_path

        task_store.save_meta(meta)
        st.session_state["cb_task_id"] = task_id
        st.session_state["cb_pending_subnav"] = "② 任务详情"

        if mode in {"subtitle", "dubbing"}:
            # 字幕 / 配音：跑完全程
            ok = cb_pipeline.start_task_background(
                task_id, start_step="asr", stop_after=None
            )
        else:
            stop_after = "copy" if stop_at_copy else None
            ok = cb_pipeline.start_task_background(
                task_id, start_step="asr", stop_after=stop_after
            )
        label = meta.get("display_name") or task_id
        if ok:
            st.success(f"任务已创建并后台启动：{label}")
        else:
            st.warning(f"任务已创建，但后台线程未能启动（可能已在跑）：{label}")
        _safe_rerun()


def _script_table_rows(items: List[Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        rows.append(
            {
                "ID": it.get("_id"),
                "时间轴": it.get("timestamp") or "",
                "OST": it.get("OST"),
                "画面": str(it.get("picture") or "")[:80],
                "解说": str(it.get("narration") or "")[:120],
            }
        )
    return rows


def _render_task_detail(tr, meta: Dict[str, Any]):
    task_id = meta.get("task_id") or ""
    label = _task_label(meta)
    mode = _task_mode(meta)
    st.markdown(f"### {label}")
    st.caption(f"内部编号 `{task_id}` · {_MODE_CN.get(mode, mode)}")
    st.markdown(_status_badge(meta), unsafe_allow_html=True)
    st.markdown(f"**{_tr(tr, 'Pipeline Progress', '流水线进度')}**")
    _render_pipeline_progress(meta)

    running = cb_pipeline.is_running(task_id)
    status = meta.get("status") or ""
    try:
        progress_val = int(meta.get("progress") or 0)
    except (TypeError, ValueError):
        progress_val = 0
    # 进度条始终渲染，避免 running/完成时 DOM 节点增减触发 removeChild
    st.progress(min(max(progress_val, 0), 100) / 100.0)

    # 按钮树固定 4 列 + 固定 key，避免 mode 切换时 DOM 结构跳变
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("刷新状态", key="cb_refresh", use_container_width=True):
            _safe_rerun()
    with c2:
        # 三种模式都画同一个 primary 按钮槽，只改 label/disabled/动作
        if mode == "subtitle":
            primary_label = "继续烧字幕"
            primary_disabled = (
                status not in {"translate_done", "burn_done", "completed"}
            ) or running
        elif mode == "dubbing":
            primary_label = "继续配音"
            primary_disabled = (
                status
                not in {
                    "translate_done",
                    "separate_done",
                    "dub_tts_done",
                    "mix_done",
                    "burn_done",
                    "completed",
                }
            ) or running
        else:
            primary_label = "继续匹配成片"
            primary_disabled = (status != "copy_done") or running
        if st.button(
            primary_label,
            key="cb_continue_primary",
            type="primary",
            use_container_width=True,
            disabled=primary_disabled,
        ):
            if mode == "subtitle":
                cb_pipeline.continue_after_translate(task_id)
            elif mode == "dubbing":
                if status in {"translate_done"}:
                    cb_pipeline.continue_after_translate(task_id)
                elif status in {"separate_done", "dub_tts_done", "mix_done"}:
                    nxt = {
                        "separate_done": "dub_tts",
                        "dub_tts_done": "mix",
                        "mix_done": "burn",
                    }.get(status, "separate")
                    cb_pipeline.start_task_background(
                        task_id, start_step=nxt, stop_after=None
                    )
                else:
                    cb_pipeline.start_task_background(
                        task_id, start_step="burn", stop_after=None
                    )
            else:
                cb_pipeline.continue_after_copy(task_id)
            _safe_rerun()
    with c3:
        if st.button(
            "从失败步重试",
            key="cb_retry",
            use_container_width=True,
            disabled=status != "failed",
        ):
            step = (meta.get("error") or {}).get("step") or meta.get("step") or "asr"
            if step not in cb_pipeline.STEP_HANDLERS:
                step = "asr"
            if mode in {"subtitle", "dubbing"}:
                stop = None
            else:
                stop = "copy"
            cb_pipeline.start_task_background(task_id, start_step=step, stop_after=stop)
            _safe_rerun()
    with c4:
        if st.button("清除当前选择", key="cb_clear", use_container_width=True):
            st.session_state.pop("cb_task_id", None)
            _safe_rerun()

    with st.expander("重命名任务", expanded=False):
        new_name = st.text_input("显示名称", value=label, key="cb_rename_input")
        if st.button("保存名称", key="cb_save_name"):
            task_store.refresh_display_name(meta, task_name=(new_name or "").strip())
            task_store.save_meta(meta)
            st.success("已更新显示名称")
            _safe_rerun()

    inputs = meta.get("inputs") or {}
    artifacts = meta.get("artifacts") or {}
    direction = meta.get("direction") or ""
    st.markdown(
        ui_styles.metrics_html(
            [
                ("方向", _DIRECTION_CN.get(direction, direction or "-")),
                ("语对", f"{meta.get('source_lang') or '-'} → {meta.get('target_lang') or '-'}"),
                ("模式", _MODE_CN.get(mode, mode)),
                (
                    "ASR",
                    str(artifacts.get("asr_backend") or inputs.get("asr_backend") or "auto"),
                ),
            ]
        ),
        unsafe_allow_html=True,
    )
    video_path = inputs.get("video_path") or ""
    if video_path:
        st.caption(f"源视频：`{video_path}`")
    export_dir = artifacts.get("export_dir") or ""
    if export_dir:
        st.caption(f"导出目录：`{export_dir}`")

    # 实时字幕节点（ASR/翻译过程中可读盘增量 target.srt）
    _render_live_subtitle_nodes(meta, running=running)

    with st.expander(
        "字幕预览 / 补齐", expanded=(mode in {"subtitle", "dubbing"})
    ):
        src = artifacts.get("source_srt") or ""
        tgt = artifacts.get("target_srt") or ""
        # 运行中编辑器可能覆盖正在写入的 target；给出提示
        if running and status in {"translate_running", "asr_running"}:
            st.caption(
                "生成中：上方「字幕节点」会实时刷新；下方编辑器保存会覆盖当前草稿，请待翻译完成后再改。"
            )
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**源字幕 (source.srt)**")
            # 运行中从磁盘重读，避免 artifacts 路径尚未回写
            src_path = _srt_path_for_task(meta, "source") or src
            st.text_area(
                "source_preview",
                value=task_store.read_text_artifact(src_path)[:4000] or "(空)",
                height=180,
                key="cb_src_preview",
                disabled=True,
                label_visibility="collapsed",
            )
            upload_src = st.file_uploader(
                "替换源字幕",
                type=["srt"],
                key="cb_replace_src",
            )
            if upload_src is not None and st.button("保存源字幕", key="cb_save_src_srt"):
                path = task_store.write_text_artifact(
                    task_id,
                    "source.srt",
                    upload_src.getvalue().decode("utf-8", errors="ignore"),
                )
                meta["artifacts"]["source_srt"] = path
                meta["artifacts"]["asr_backend"] = "uploaded"
                old_tgt = meta["artifacts"].get("target_srt") or ""
                if old_tgt and os.path.isfile(old_tgt):
                    try:
                        os.remove(old_tgt)
                    except OSError:
                        pass
                meta["artifacts"]["target_srt"] = ""
                task_store.append_log(meta, "source.srt replaced by user")
                task_store.save_meta(meta)
                st.success("源字幕已更新")
                _safe_rerun()
        with col_b:
            st.markdown("**目标字幕 (target.srt)**")
            # 可编辑目标字幕（字幕模式核心）
            editor_key = f"cb_tgt_editor_{task_id}"
            tgt_path = _srt_path_for_task(meta, "target") or tgt
            # 翻译进行中不要用 session 缓存锁死旧内容：每次从磁盘刷新初值
            if running and status == "translate_running":
                st.session_state[editor_key] = task_store.read_text_artifact(tgt_path)
                st.session_state["cb_tgt_editor_task"] = task_id
            elif st.session_state.get("cb_tgt_editor_task") != task_id:
                st.session_state["cb_tgt_editor_task"] = task_id
                st.session_state[editor_key] = task_store.read_text_artifact(tgt_path)
            edited_tgt = st.text_area(
                "target_editor",
                height=180,
                key=editor_key,
                label_visibility="collapsed",
            )
            b1, b2 = st.columns(2)
            with b1:
                if st.button("保存目标字幕", key="cb_save_tgt_srt"):
                    path = task_store.write_text_artifact(
                        task_id, "target.srt", (edited_tgt or "").strip() + "\n"
                    )
                    meta["artifacts"]["target_srt"] = path
                    task_store.append_log(meta, "target.srt updated by user")
                    task_store.save_meta(meta)
                    st.success("目标字幕已保存")
                    _safe_rerun()
            with b2:
                upload_tgt = st.file_uploader(
                    "上传替换",
                    type=["srt"],
                    key="cb_replace_tgt",
                )
                if upload_tgt is not None and st.button("用上传文件覆盖", key="cb_overwrite_tgt"):
                    path = task_store.write_text_artifact(
                        task_id,
                        "target.srt",
                        upload_tgt.getvalue().decode("utf-8", errors="ignore"),
                    )
                    meta["artifacts"]["target_srt"] = path
                    task_store.append_log(meta, "target.srt replaced by upload")
                    task_store.save_meta(meta)
                    st.success("目标字幕已更新")
                    _safe_rerun()

        if st.button(
            "仅重跑 ASR→翻译",
            key="cb_rerun_subtitle",
            disabled=running,
        ):
            for name in ("target.srt", "burn.srt"):
                p = task_store.artifact_path(task_id, name)
                if os.path.isfile(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            from app.services.cross_border import asr as asr_mod

            src_path = task_store.artifact_path(task_id, "source.srt")
            if asr_mod.is_placeholder_srt(src_path):
                try:
                    os.remove(src_path)
                except OSError:
                    pass
                meta["artifacts"]["source_srt"] = ""
            meta["artifacts"]["target_srt"] = ""
            meta["artifacts"]["burn_srt"] = ""
            task_store.save_meta(meta)
            stop = None if mode in {"subtitle", "dubbing"} else "copy"
            cb_pipeline.start_task_background(task_id, start_step="asr", stop_after=stop)
            _safe_rerun()

    # 配音模式：换音色 / 重分离 / 重混音
    if mode == "dubbing":
        from app.services.cross_border.dubbing import voices as voices_mod

        # expanded 固定，避免状态切换时 expander 节点增减触发 removeChild
        with st.expander("配音控制（换音色 / 重分离 / 重混）", expanded=False):
            arts = meta.get("artifacts") or {}
            st.caption(
                f"分离后端：`{arts.get('separate_backend') or '-'}` · "
                f"配音轨：`{os.path.basename(arts.get('dub_voice_wav') or '') or '-'}` · "
                f"混音片：`{os.path.basename(arts.get('dubbed_mp4') or '') or '-'}`"
            )
            cur_voice = str((meta.get("inputs") or {}).get("voice_name") or "")
            new_voice = st.text_input(
                "TTS 音色",
                value=cur_voice,
                key=f"cb_dub_voice_edit_{task_id}",
            )
            gcol1, gcol2, gcol3 = st.columns(3)
            with gcol1:
                if st.button(
                    "换音色重配音",
                    key=f"cb_rerun_dub_tts_{task_id}",
                    disabled=running,
                    use_container_width=True,
                ):
                    meta["inputs"]["voice_name"] = (new_voice or "").strip() or cur_voice
                    task_store.save_meta(meta)
                    cb_pipeline.rerun_dub_tts(task_id)
                    _safe_rerun()
            with gcol2:
                if st.button(
                    "重做人声分离",
                    key=f"cb_rerun_sep_{task_id}",
                    disabled=running,
                    use_container_width=True,
                ):
                    cb_pipeline.start_task_background(
                        task_id, start_step="separate", stop_after=None
                    )
                    _safe_rerun()
            with gcol3:
                if st.button(
                    "仅重混音+烧字幕",
                    key=f"cb_rerun_mix_{task_id}",
                    disabled=running,
                    use_container_width=True,
                ):
                    cb_pipeline.start_task_background(
                        task_id, start_step="mix", stop_after=None
                    )
                    _safe_rerun()
            st.caption(
                "默认音色参考："
                + " · ".join(
                    f"{k}={voices_mod.DEFAULT_EDGE_VOICES[k]}"
                    for k in ("zh", "en", "ja", "ko")
                )
            )

    # 字幕/配音模式：改样式后只重烧（不必重跑 ASR/翻译）
    if mode in {"subtitle", "dubbing"}:
        from app.services.cross_border import burn as burn_mod

        with st.expander("改样式后重烧字幕", expanded=(status in {"completed", "burn_done", "translate_done"})):
            cur = meta.get("inputs") or {}
            style_choices = burn_mod.style_choices_for_ui()
            style_keys = [k for k, _ in style_choices]
            style_labels = [lab for _, lab in style_choices]
            cur_style = str(cur.get("subtitle_style") or "cinema")
            try:
                style_default = style_keys.index(cur_style)
            except ValueError:
                style_default = 0

            c_style, c_pos, c_size = st.columns(3)
            with c_style:
                style_idx = st.selectbox(
                    "样式",
                    options=list(range(len(style_labels))),
                    format_func=lambda i: style_labels[i],
                    index=style_default,
                    key=f"cb_reburn_style_{task_id}",
                )
                reburn_style = style_keys[int(style_idx)]
            with c_pos:
                pos_labels = {
                    "bottom": "底部",
                    "bottom_high": "底部偏上",
                    "center": "中央",
                    "top": "顶部",
                }
                cur_pos = str(cur.get("subtitle_position_key") or cur.get("subtitle_position") or "bottom")
                if cur_pos not in pos_labels:
                    cur_pos = "bottom"
                reburn_pos = st.selectbox(
                    "位置",
                    options=list(pos_labels.keys()),
                    format_func=lambda k: pos_labels[k],
                    index=list(pos_labels.keys()).index(cur_pos),
                    key=f"cb_reburn_pos_{task_id}",
                )
            with c_size:
                size_labels = {
                    "auto": "自动",
                    "small": "偏小",
                    "medium": "标准",
                    "large": "偏大",
                    "manual": "手动",
                }
                cur_size = str(cur.get("subtitle_size_preset") or "auto")
                if cur.get("subtitle_font_size_user_set"):
                    cur_size = "manual"
                if cur_size not in size_labels:
                    cur_size = "auto"
                reburn_size = st.selectbox(
                    "字号",
                    options=list(size_labels.keys()),
                    format_func=lambda k: size_labels[k],
                    index=list(size_labels.keys()).index(cur_size),
                    key=f"cb_reburn_size_{task_id}",
                )
            reburn_manual = 0
            if reburn_size == "manual":
                reburn_manual = st.slider(
                    "字号数值",
                    min_value=20,
                    max_value=64,
                    value=int(cur.get("subtitle_font_size") or 40),
                    step=2,
                    key=f"cb_reburn_manual_{task_id}",
                )
            reburn_bilingual = st.checkbox(
                "双语字幕",
                value=bool(cur.get("bilingual")),
                key=f"cb_reburn_bilingual_{task_id}",
            )

            st.markdown("##### 原片硬字幕遮罩")
            reburn_mask = st.checkbox(
                "启用遮罩条盖住原字幕",
                value=bool(cur.get("subtitle_mask_enabled")),
                key=f"cb_reburn_mask_{task_id}",
            )
            reburn_mask_side = str(cur.get("subtitle_mask_side") or "bottom")
            reburn_mask_color = str(cur.get("subtitle_mask_color") or "black")
            reburn_mask_h = float(cur.get("subtitle_mask_height_percent") or 14.0)
            reburn_on_mask = bool(cur.get("subtitle_on_mask", True))
            if reburn_mask:
                rm1, rm2 = st.columns(2)
                with rm1:
                    side_labels = dict(burn_mod.mask_side_choices_for_ui())
                    if reburn_mask_side not in side_labels:
                        reburn_mask_side = "bottom"
                    reburn_mask_side = st.selectbox(
                        "遮罩位置",
                        options=list(side_labels.keys()),
                        format_func=lambda k: side_labels[k],
                        index=list(side_labels.keys()).index(reburn_mask_side),
                        key=f"cb_reburn_mask_side_{task_id}",
                    )
                with rm2:
                    color_labels = dict(burn_mod.mask_color_choices_for_ui())
                    if reburn_mask_color not in color_labels:
                        reburn_mask_color = "black"
                    reburn_mask_color = st.selectbox(
                        "遮罩颜色",
                        options=list(color_labels.keys()),
                        format_func=lambda k: color_labels[k],
                        index=list(color_labels.keys()).index(reburn_mask_color),
                        key=f"cb_reburn_mask_color_{task_id}",
                    )
                reburn_mask_h = st.slider(
                    "遮罩高度 %",
                    min_value=int(burn_mod.MASK_HEIGHT_MIN),
                    max_value=int(burn_mod.MASK_HEIGHT_MAX),
                    value=int(max(burn_mod.MASK_HEIGHT_MIN, min(burn_mod.MASK_HEIGHT_MAX, reburn_mask_h))),
                    step=1,
                    key=f"cb_reburn_mask_h_{task_id}",
                )
                reburn_on_mask = st.checkbox(
                    "新字幕叠在遮罩条上",
                    value=reburn_on_mask,
                    key=f"cb_reburn_on_mask_{task_id}",
                )

            # 预览将采用的自适应字号
            try:
                preview = burn_mod.resolve_burn_options(
                    {
                        "subtitle_style": reburn_style,
                        "subtitle_size_preset": reburn_size if reburn_size != "manual" else "auto",
                        "subtitle_position_key": reburn_pos,
                        "subtitle_font_size": reburn_manual if reburn_size == "manual" else 0,
                        "subtitle_font_size_user_set": reburn_size == "manual",
                        "bilingual": reburn_bilingual,
                        "subtitle_mask_enabled": reburn_mask,
                        "subtitle_mask_side": reburn_mask_side,
                        "subtitle_mask_color": reburn_mask_color,
                        "subtitle_mask_height_percent": reburn_mask_h,
                        "subtitle_on_mask": reburn_on_mask,
                    },
                    video_path=str(cur.get("video_path") or ""),
                )
                ad = preview.get("_adaptive") or {}
                mask_tip = ""
                if preview.get("subtitle_mask_enabled"):
                    mask_tip = (
                        f" · 遮罩 {preview.get('subtitle_mask_side')}/"
                        f"{preview.get('subtitle_mask_height_percent')}%"
                        f"/{preview.get('subtitle_mask_color')}"
                    )
                st.caption(
                    f"预览：字号 **{preview.get('subtitle_font_size')}** · "
                    f"描边 {preview.get('stroke_width')} · "
                    f"MarginV {preview.get('ass_margin_v')} · "
                    f"分辨率 {ad.get('video_width')}×{ad.get('video_height')}"
                    f"{mask_tip}"
                )
            except Exception:
                pass

            can_reburn = (
                status in {"translate_done", "burn_done", "completed", "failed"}
                and not running
            )
            if st.button(
                "应用样式并重烧",
                key=f"cb_apply_reburn_{task_id}",
                type="primary",
                disabled=not can_reburn,
                use_container_width=True,
            ):
                meta.setdefault("inputs", {})
                meta["inputs"]["subtitle_style"] = reburn_style
                meta["inputs"]["subtitle_position_key"] = reburn_pos
                meta["inputs"]["subtitle_position"] = reburn_pos
                meta["inputs"]["bilingual"] = bool(reburn_bilingual)
                meta["inputs"]["subtitle_mask_enabled"] = bool(reburn_mask)
                meta["inputs"]["subtitle_mask_side"] = reburn_mask_side
                meta["inputs"]["subtitle_mask_color"] = reburn_mask_color
                meta["inputs"]["subtitle_mask_height_percent"] = float(reburn_mask_h)
                meta["inputs"]["subtitle_on_mask"] = bool(reburn_on_mask)
                if reburn_size == "manual":
                    meta["inputs"]["subtitle_size_preset"] = "auto"
                    meta["inputs"]["subtitle_font_size"] = int(reburn_manual)
                    meta["inputs"]["subtitle_font_size_user_set"] = True
                    meta["inputs"]["subtitle_auto_style"] = False
                else:
                    meta["inputs"]["subtitle_size_preset"] = reburn_size
                    meta["inputs"]["subtitle_font_size"] = 0
                    meta["inputs"]["subtitle_font_size_user_set"] = False
                    meta["inputs"]["subtitle_auto_style"] = True
                task_store.append_log(
                    meta,
                    f"reburn style={reburn_style} pos={reburn_pos} size={reburn_size} "
                    f"bilingual={reburn_bilingual} mask={reburn_mask} "
                    f"side={reburn_mask_side} h={reburn_mask_h}",
                )
                task_store.save_meta(meta)
                cb_pipeline.continue_after_translate(task_id)
                st.success("已应用样式，后台重烧中…")
                _safe_rerun()

    # 解说模式专属区块
    if mode == "narration":
        digest_path = artifacts.get("digest") or ""
        digest_text = task_store.read_text_artifact(digest_path)
        if digest_text:
            with st.expander("源内容摘要 digest", expanded=False):
                st.text(digest_text[:8000])

        copy_path = artifacts.get("narration_copy") or task_store.artifact_path(
            task_id, "narration_copy.txt"
        )
        copy_text = task_store.read_text_artifact(copy_path)
        st.markdown("#### 解说文案（审核点）")
        editor_key = f"cb_copy_editor_{task_id}"
        if st.session_state.get("cb_copy_editor_task") != task_id:
            st.session_state["cb_copy_editor_task"] = task_id
            st.session_state[editor_key] = copy_text
        edited = st.text_area(
            "narration_copy",
            height=240,
            key=editor_key,
            label_visibility="collapsed",
        )
        if st.button("保存文案修改", key="cb_save_copy"):
            path = task_store.write_text_artifact(
                task_id, "narration_copy.txt", (edited or "").strip() + "\n"
            )
            meta["artifacts"]["narration_copy"] = path
            task_store.append_log(meta, "narration_copy updated by user")
            task_store.save_meta(meta)
            st.success("已保存")
            _safe_rerun()

        script_path = artifacts.get("script_json") or ""
        if script_path and os.path.isfile(script_path):
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("items") if isinstance(data, dict) else data
                rows = _script_table_rows(items or [])
                if rows:
                    st.markdown("#### 脚本片段")
                    st.dataframe(rows, use_container_width=True, hide_index=True)
            except Exception as exc:
                st.warning(f"脚本读取失败: {exc}")

        compliance_path = artifacts.get("compliance") or ""
        packaging_path = artifacts.get("titles") or ""
        cols = st.columns(2)
        with cols[0]:
            if packaging_path and os.path.isfile(packaging_path):
                st.markdown("#### 标题包装")
                try:
                    with open(packaging_path, encoding="utf-8") as pf:
                        st.json(json.load(pf))
                except Exception:
                    st.text(task_store.read_text_artifact(packaging_path)[:2000])
        with cols[1]:
            if compliance_path and os.path.isfile(compliance_path):
                st.markdown("#### 改造度/合规粗检")
                try:
                    with open(compliance_path, encoding="utf-8") as cf:
                        st.json(json.load(cf))
                except Exception:
                    st.text(task_store.read_text_artifact(compliance_path)[:2000])

    logs = meta.get("logs") or []
    if logs:
        with st.expander("任务日志", expanded=False):
            lines = [
                f"{row.get('ts')} [{row.get('level')}] {row.get('message')}"
                for row in logs[-80:]
            ]
            st.text("\n".join(lines))

    out_mp4 = artifacts.get("output_mp4") or ""
    if out_mp4 and os.path.isfile(out_mp4):
        st.markdown("#### 成片")
        st.caption(out_mp4)
        try:
            size_mb = os.path.getsize(out_mp4) / (1024 * 1024)
        except OSError:
            size_mb = 0
        # 大文件勿整包读入内存：走路径播放；过大则只给下载/打开
        try:
            if size_mb > 120:
                st.warning(
                    f"成片约 {size_mb:.0f}MB，内嵌预览易卡顿/触发页面错误。"
                    "请点下方打开目录或下载查看。"
                )
                with open(out_mp4, "rb") as vf:
                    st.download_button(
                        "下载成片",
                        data=vf,
                        file_name=os.path.basename(out_mp4),
                        mime="video/mp4",
                        key="cb_dl_output",
                    )
            else:
                # 传路径比 read() 更稳，避免大块 bytes 导致 DOM 抖动
                st.video(out_mp4)
        except Exception:
            st.info("成片已生成，当前环境无法内嵌预览，请打开路径查看。")
        if st.button("打开导出目录", key="cb_open_export"):
            try:
                os.startfile(export_dir or os.path.dirname(out_mp4))  # type: ignore[attr-defined]
            except Exception as exc:
                st.warning(f"无法打开目录: {exc}")

    _maybe_auto_refresh(task_id)


def _render_task_list(tr):
    st.markdown("### 任务列表")
    st.caption("最近 30 条跨境任务。点「加载选中任务」进入详情。")
    rows = task_store.list_tasks(limit=30)
    if not rows:
        st.markdown(
            ui_styles.empty_html(
                "还没有跨境任务",
                "切换到「① 新建任务」，上传视频即可开始字幕本地化。",
            ),
            unsafe_allow_html=True,
        )
        return

    display_rows = []
    option_labels = []
    option_ids = []
    for r in rows:
        status = r.get("status") or ""
        name = r.get("display_name") or r.get("task_id")
        mode = r.get("mode") or "subtitle"
        display_rows.append(
            {
                "任务名称": name,
                "模式": _MODE_CN.get(mode, mode),
                "方向": _DIRECTION_CN.get(r.get("direction"), r.get("direction")),
                "状态": _STATUS_CN.get(status, status),
                "进度": f"{r.get('progress') or 0}%",
                "更新时间": r.get("updated_at") or r.get("created_at"),
            }
        )
        option_ids.append(r["task_id"])
        option_labels.append(
            f"{name}  ·  {_MODE_CN.get(mode, mode)}  ·  {_STATUS_CN.get(status, status)}"
        )
    st.dataframe(display_rows, use_container_width=True, hide_index=True)

    if "cb_list_select" not in st.session_state and option_labels:
        st.session_state["cb_list_select"] = option_labels[0]
    if st.session_state.get("cb_list_select") not in option_labels:
        st.session_state["cb_list_select"] = option_labels[0]

    selected_label = st.selectbox("打开任务", options=option_labels, key="cb_list_select")
    selected = (
        option_ids[option_labels.index(selected_label)]
        if selected_label in option_labels
        else option_ids[0]
    )
    if st.button("加载选中任务", key="cb_load_selected", type="primary", use_container_width=True):
        st.session_state["cb_task_id"] = selected
        st.session_state["cb_pending_subnav"] = "② 任务详情"
        _safe_rerun()


def render_cross_border_panel(tr=None):
    """供 webui.py 调用的主入口（独立工作流 Tab）。"""
    try:
        _render_cross_border_panel_inner(tr)
    except Exception as exc:
        # 服务端异常时给出可恢复提示，避免整页白屏
        st.error(f"跨境面板渲染异常：{exc}")
        st.caption("可点浏览器刷新，或切到「任务列表」再进详情。")
        if st.button("重置跨境子导航", key="cb_reset_subnav"):
            for k in (
                "cb_subnav",
                "cb_pending_subnav",
                "cb_prefer_detail_once",
                "cb_last_auto_refresh_ts",
            ):
                st.session_state.pop(k, None)
            _safe_rerun()


def _render_cross_border_panel_inner(tr=None):
    st.caption(
        "默认路径：翻译 + 烧字幕（对齐 VideoLingo）。"
        " 也可切到解说文案工厂。语对锁定 en↔zh。"
    )

    meta = _load_selected_meta()
    if meta:
        s = meta.get("status") or "draft"
        st.markdown(
            ui_styles.status_panel_html(
                mode_label=_MODE_CN.get(_task_mode(meta), _task_mode(meta)),
                status_label=_STATUS_CN.get(s, s),
                status_key=s,
                progress=meta.get("progress"),
                extra_lines=[
                    f"当前任务：{_task_label(meta)}",
                    _DIRECTION_CN.get(meta.get("direction"), meta.get("direction") or ""),
                ],
            ),
            unsafe_allow_html=True,
        )

    # pending 必须在 radio 实例化之前写入，否则 StreamlitAPIException
    pending = st.session_state.pop("cb_pending_subnav", None)
    if pending in _SUBNAV_OPTIONS:
        st.session_state["cb_subnav"] = pending
    elif "cb_subnav" not in st.session_state:
        st.session_state["cb_subnav"] = "① 新建任务"
    if meta and st.session_state.get("cb_prefer_detail_once"):
        st.session_state["cb_subnav"] = "② 任务详情"
        st.session_state["cb_prefer_detail_once"] = False
    # 非法值回落，防止 options 变更后 key 残留导致 DOM 异常
    if st.session_state.get("cb_subnav") not in _SUBNAV_OPTIONS:
        st.session_state["cb_subnav"] = "① 新建任务"

    subnav = st.radio(
        "跨境子页面",
        options=list(_SUBNAV_OPTIONS),
        horizontal=True,
        key="cb_subnav",
        label_visibility="collapsed",
        help="① 新建 · ② 查看进度与成片 · ③ 历史任务",
    )

    if subnav == "① 新建任务":
        _render_create_form(tr)
    elif subnav == "② 任务详情":
        meta = _load_selected_meta()
        if not meta:
            st.info("尚未选择任务。请先在「① 新建任务」开始，或从「③ 任务列表」加载。")
        else:
            _render_task_detail(tr, meta)
    else:
        _render_task_list(tr)
