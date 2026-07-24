#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化解说面板（en↔zh 双向 MVP 入口）

与影视/短剧 script_settings 并列，不塞进短剧分支。
长任务走后台线程 + 文件状态轮询，避免 Streamlit 同步阻塞崩页。
"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, Optional

import streamlit as st

from app.services.cross_border import pipeline as cb_pipeline
from app.services.cross_border import task_store
from app.services.cross_border.state_machine import HUMAN_GATES
from app.services.cross_border.style_packs import (
    DEFAULT_BY_DIRECTION,
    style_choices_for_ui,
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


def _status_badge(meta: Dict[str, Any]) -> str:
    status = meta.get("status") or "draft"
    progress = meta.get("progress")
    err = meta.get("error") or {}
    line = f"**状态:** `{status}`"
    if progress is not None and progress >= 0:
        line += f" · **进度:** {progress}%"
    if status == "failed" and err:
        line += f"\n\n⚠️ {err.get('message') or err}"
    gate = HUMAN_GATES.get(status)
    if gate:
        line += f"\n\n🧭 {gate}"
    if cb_pipeline.is_running(meta.get("task_id") or ""):
        line += "\n\n🔄 后台任务运行中…"
    return line


def _render_create_form(tr):
    st.subheader(_tr(tr, "Cross-border Localization", "跨境本地化 · 新建任务"))
    st.caption(
        "上传视频 → 选择 引入(In) / 出海(Out) → 后台生成。"
        " MVP 语对锁定 en↔zh。生成默认在「解说文案」处暂停供你审核。"
    )

    direction_label = st.radio(
        "方向",
        options=["引入 Inbound（en→zh）", "出海 Outbound（zh→en）"],
        horizontal=True,
        key="cb_direction_label",
    )
    direction = "inbound" if direction_label.startswith("引入") else "outbound"

    uploaded = st.file_uploader(
        "上传视频",
        type=["mp4", "mov", "mkv", "webm"],
        key="cb_video_uploader",
    )
    uploaded_srt = st.file_uploader(
        "可选：上传已有源语言字幕 (.srt)",
        type=["srt"],
        key="cb_srt_uploader",
    )

    style_map = style_choices_for_ui(direction)
    default_pack = DEFAULT_BY_DIRECTION[direction]
    default_label = next(
        (label for label, pid in style_map.items() if pid == default_pack),
        next(iter(style_map)),
    )
    style_label = st.selectbox(
        "风格包",
        options=list(style_map.keys()),
        index=list(style_map.keys()).index(default_label),
        key=f"cb_style_{direction}",
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
        original_audio_ratio = st.slider(
            "原片占比目标 %",
            min_value=0,
            max_value=90,
            value=30 if direction == "inbound" else 20,
            step=5,
            key="cb_ost_ratio",
        )
    with col3:
        source_credit = st.checkbox("来源声明", value=True, key="cb_source_credit")

    glossary_text = st.text_area(
        "术语表（可选，出海建议填写）",
        height=100,
        placeholder="MrBeast = MrBeast\n老干妈 => Lao Gan Ma | lock",
        key="cb_glossary",
        help="每行一条：Source = Target 或 Source|Target|true",
    )
    credit_hint = st.text_input("来源/品牌提示", key="cb_credit_hint", placeholder="频道名或作品名")
    asr_backend = "auto"
    voice_name = "zh-CN-XiaoyiNeural" if direction == "inbound" else "en-US-JennyNeural"
    tts_engine = ""

    with st.expander("高级", expanded=False):
        if direction == "inbound":
            source_lang, target_lang = "en", "zh"
        else:
            source_lang, target_lang = "zh", "en"
        c1, c2 = st.columns(2)
        with c1:
            source_lang = st.text_input("源语言", value=source_lang, key="cb_source_lang")
        with c2:
            target_lang = st.text_input("目标语言", value=target_lang, key="cb_target_lang")
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
            key="cb_asr_backend",
            help="优先用项目 fun_asr 配置；全部失败则写占位字幕，可人工补齐后重试。",
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
        platform = st.text_input(
            "目标平台",
            value="douyin" if direction == "inbound" else "tiktok",
            key="cb_platform",
        )
        narration_word_count = st.number_input(
            "目标文案字数/词数",
            min_value=50,
            max_value=5000,
            value=320 if direction == "inbound" else 150,
            step=10,
            key="cb_word_count",
        )
        stop_at_copy = st.checkbox(
            "生成到解说文案后暂停（推荐）",
            value=True,
            key="cb_stop_at_copy",
        )
        default_voice = (
            "zh-CN-XiaoyiNeural" if direction == "inbound" else "en-US-JennyNeural"
        )
        voice_name = st.text_input(
            "TTS 音色",
            value=default_voice,
            key="cb_voice_name",
            help="默认 Edge 神经音色；也可填项目配置的其他引擎音色名。",
        )
        tts_engine = st.selectbox(
            "TTS 引擎",
            options=["", "edge_tts", "azure_speech", "doubaotts", "tencent_tts", "qwen3_tts"],
            format_func=lambda x: x or "跟随全局配置",
            key="cb_tts_engine",
        )

    if st.button("开始生成", type="primary", use_container_width=True, key="cb_start"):
        if not uploaded:
            st.error("请先上传视频")
            return

        # 落盘视频
        task_probe = task_store.new_task_id()
        # create_task 会再生成 id；这里先用 create 后的目录
        meta = task_store.create_task(
            direction=direction,
            video_path="",  # 先占位，写入后回填
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
            tts_engine=tts_engine,
        )
        task_id = meta["task_id"]
        tdir = task_store.task_dir(task_id)
        video_name = task_store.safe_basename(uploaded.name)
        video_path = os.path.join(tdir, video_name)
        with open(video_path, "wb") as f:
            f.write(uploaded.getbuffer())
        meta["inputs"]["video_path"] = video_path

        if uploaded_srt is not None:
            srt_path = os.path.join(tdir, "source.srt")
            with open(srt_path, "wb") as f:
                f.write(uploaded_srt.getbuffer())
            meta["artifacts"]["source_srt"] = srt_path

        task_store.save_meta(meta)
        st.session_state["cb_task_id"] = task_id

        stop_after = "copy" if stop_at_copy else None
        ok = cb_pipeline.start_task_background(
            task_id, start_step="asr", stop_after=stop_after
        )
        if ok:
            st.success(f"任务已创建并后台启动：{task_id}")
        else:
            st.warning(f"任务已创建，但后台线程未能启动（可能已在跑）：{task_id}")
        st.rerun()


def _render_task_detail(tr, meta: Dict[str, Any]):
    st.subheader(f"任务详情 · {meta.get('task_id')}")
    st.markdown(_status_badge(meta))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("刷新状态", key="cb_refresh"):
            st.rerun()
    with c2:
        if st.button(
            "继续匹配成片",
            key="cb_continue",
            disabled=(meta.get("status") != "copy_done")
            or cb_pipeline.is_running(meta["task_id"]),
        ):
            cb_pipeline.continue_after_copy(meta["task_id"])
            st.rerun()
    with c3:
        if st.button(
            "从失败步重试",
            key="cb_retry",
            disabled=meta.get("status") != "failed",
        ):
            step = (meta.get("error") or {}).get("step") or meta.get("step") or "asr"
            if step not in cb_pipeline.STEP_HANDLERS:
                step = "asr"
            cb_pipeline.start_task_background(meta["task_id"], start_step=step, stop_after="copy")
            st.rerun()
    with c4:
        if st.button("清除当前选择", key="cb_clear"):
            st.session_state.pop("cb_task_id", None)
            st.rerun()

    inputs = meta.get("inputs") or {}
    artifacts = meta.get("artifacts") or {}
    st.write(
        {
            "direction": meta.get("direction"),
            "langs": f"{meta.get('source_lang')} → {meta.get('target_lang')}",
            "style_pack": meta.get("style_pack"),
            "asr_backend": artifacts.get("asr_backend") or inputs.get("asr_backend") or "auto",
            "video": inputs.get("video_path"),
            "export_dir": artifacts.get("export_dir"),
        }
    )

    # 字幕预览 + 人工补齐
    with st.expander("字幕预览 / 补齐", expanded=True):
        src = artifacts.get("source_srt") or ""
        tgt = artifacts.get("target_srt") or ""
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**源字幕 (source.srt)**")
            st.text(task_store.read_text_artifact(src)[:4000] or "(空)")
            upload_src = st.file_uploader(
                "替换源字幕",
                type=["srt"],
                key=f"cb_replace_src_{meta['task_id']}",
            )
            if upload_src is not None and st.button("保存源字幕", key="cb_save_src_srt"):
                path = task_store.write_text_artifact(
                    meta["task_id"],
                    "source.srt",
                    upload_src.getvalue().decode("utf-8", errors="ignore"),
                )
                meta["artifacts"]["source_srt"] = path
                meta["artifacts"]["asr_backend"] = "uploaded"
                # 源字幕变更后清掉旧目标字幕，避免错配
                old_tgt = meta["artifacts"].get("target_srt") or ""
                if old_tgt and os.path.isfile(old_tgt):
                    try:
                        os.remove(old_tgt)
                    except OSError:
                        pass
                meta["artifacts"]["target_srt"] = ""
                task_store.append_log(meta, "source.srt replaced by user")
                task_store.save_meta(meta)
                st.success("源字幕已更新，可点「从失败步重试」或重新启动 asr/translate")
                st.rerun()
        with col_b:
            st.markdown("**目标字幕 (target.srt)**")
            st.text(task_store.read_text_artifact(tgt)[:4000] or "(空)")
            upload_tgt = st.file_uploader(
                "替换目标字幕",
                type=["srt"],
                key=f"cb_replace_tgt_{meta['task_id']}",
            )
            if upload_tgt is not None and st.button("保存目标字幕", key="cb_save_tgt_srt"):
                path = task_store.write_text_artifact(
                    meta["task_id"],
                    "target.srt",
                    upload_tgt.getvalue().decode("utf-8", errors="ignore"),
                )
                meta["artifacts"]["target_srt"] = path
                task_store.append_log(meta, "target.srt replaced by user")
                task_store.save_meta(meta)
                st.success("目标字幕已更新")
                st.rerun()

        if st.button(
            "仅重跑 ASR→翻译",
            key="cb_rerun_subtitle",
            disabled=cb_pipeline.is_running(meta.get("task_id") or ""),
        ):
            # 清掉可能的占位/旧目标，强制重走字幕层
            for name in ("source.srt", "target.srt"):
                p = task_store.artifact_path(meta["task_id"], name)
                if os.path.isfile(p) and name == "target.srt":
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            # 若源是占位则删掉以触发重新 ASR
            from app.services.cross_border import asr as asr_mod

            src_path = task_store.artifact_path(meta["task_id"], "source.srt")
            if asr_mod.is_placeholder_srt(src_path):
                try:
                    os.remove(src_path)
                except OSError:
                    pass
                meta["artifacts"]["source_srt"] = ""
            meta["artifacts"]["target_srt"] = ""
            task_store.save_meta(meta)
            cb_pipeline.start_task_background(
                meta["task_id"], start_step="asr", stop_after="copy"
            )
            st.rerun()

    # 摘要
    digest_path = artifacts.get("digest") or ""
    digest_text = task_store.read_text_artifact(digest_path)
    if digest_text:
        with st.expander("源内容摘要 digest", expanded=False):
            st.markdown(digest_text)

    # 解说文案编辑
    copy_path = artifacts.get("narration_copy") or task_store.artifact_path(
        meta["task_id"], "narration_copy.txt"
    )
    copy_text = task_store.read_text_artifact(copy_path)
    st.markdown("#### 解说文案（审核点）")
    edited = st.text_area(
        "narration_copy",
        value=copy_text,
        height=240,
        key=f"cb_copy_editor_{meta['task_id']}_{meta.get('status')}",
        label_visibility="collapsed",
    )
    if st.button("保存文案修改", key="cb_save_copy"):
        path = task_store.write_text_artifact(
            meta["task_id"], "narration_copy.txt", edited.strip() + "\n"
        )
        meta["artifacts"]["narration_copy"] = path
        task_store.append_log(meta, "narration_copy updated by user")
        # 若已在 copy 之后，保存不改状态；若还在 running 则不动
        if meta.get("status") in {"copy_done", "match_done", "failed", "completed"}:
            pass
        task_store.save_meta(meta)
        st.success("已保存")
        st.rerun()

    # 脚本表格
    script_path = artifacts.get("script_json") or ""
    if script_path and os.path.isfile(script_path):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items") if isinstance(data, dict) else data
            if items:
                st.markdown("#### 脚本片段")
                st.dataframe(items, use_container_width=True)
        except Exception as exc:
            st.warning(f"脚本读取失败: {exc}")

    # 包装 / 合规
    compliance_path = artifacts.get("compliance") or ""
    packaging_path = artifacts.get("titles") or ""
    cols = st.columns(2)
    with cols[0]:
        if packaging_path and os.path.isfile(packaging_path):
            st.markdown("#### 标题包装")
            try:
                st.json(json.load(open(packaging_path, encoding="utf-8")))
            except Exception:
                st.text(task_store.read_text_artifact(packaging_path)[:2000])
    with cols[1]:
        if compliance_path and os.path.isfile(compliance_path):
            st.markdown("#### 改造度/合规粗检")
            try:
                st.json(json.load(open(compliance_path, encoding="utf-8")))
            except Exception:
                st.text(task_store.read_text_artifact(compliance_path)[:2000])

    # 日志
    logs = meta.get("logs") or []
    if logs:
        with st.expander("任务日志", expanded=False):
            for row in logs[-80:]:
                st.text(f"{row.get('ts')} [{row.get('level')}] {row.get('message')}")

    export_dir = artifacts.get("export_dir") or ""
    if export_dir and os.path.isdir(export_dir):
        st.caption(f"导出目录: {export_dir}")
    out_mp4 = artifacts.get("output_mp4") or ""
    if out_mp4 and os.path.isfile(out_mp4):
        st.markdown("#### 成片")
        st.caption(out_mp4)
        try:
            st.video(out_mp4)
        except Exception:
            st.info("成片已生成，当前环境无法内嵌预览，请打开路径查看。")
        if st.button("打开导出目录", key="cb_open_export"):
            try:
                os.startfile(export_dir or os.path.dirname(out_mp4))  # type: ignore[attr-defined]
            except Exception as exc:
                st.warning(f"无法打开目录: {exc}")


def _render_task_list(tr):
    st.subheader("任务列表")
    rows = task_store.list_tasks(limit=30)
    if not rows:
        st.info("暂无跨境任务")
        return
    st.dataframe(rows, use_container_width=True)
    options = [r["task_id"] for r in rows]
    selected = st.selectbox("打开任务", options=options, key="cb_list_select")
    if st.button("加载选中任务", key="cb_load_selected"):
        st.session_state["cb_task_id"] = selected
        st.rerun()


def render_cross_border_panel(tr=None):
    """供 webui.py 调用的主入口。"""
    st.divider()
    st.markdown("### 🌍 跨境本地化解说（MVP）")

    tab_new, tab_detail, tab_list = st.tabs(["新建任务", "任务详情", "任务列表"])
    with tab_new:
        _render_create_form(tr)
    with tab_detail:
        meta = _load_selected_meta()
        if not meta:
            st.info("尚未选择任务。请先在「新建任务」开始，或从「任务列表」加载。")
        else:
            _render_task_detail(tr, meta)
    with tab_list:
        _render_task_list(tr)

    # 后台运行时轻量自动刷新
    meta = _load_selected_meta()
    if meta and cb_pipeline.is_running(meta.get("task_id") or ""):
        try:
            from streamlit_autorefresh import st_autorefresh  # type: ignore

            st_autorefresh(interval=3000, key="cb_auto_refresh")
        except Exception:
            st.caption("后台运行中：请点击「刷新状态」查看进度。")
