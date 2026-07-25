"""LLM-powered SRT subtitle translation."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import ceil
from typing import Any, Callable

from loguru import logger

from app.config import config
from app.config.defaults import resolve_text_model_name
from app.services.llm.migration_adapter import _run_async_safely
from app.services.llm.unified_service import UnifiedLLMService
from app.services.subtitle_corrector import (
    _ensure_llm_providers_registered,
    _extract_json_text,
    parse_srt_blocks,
)
from app.services.subtitle_text import read_subtitle_text
from app.utils import utils


class SubtitleTranslationError(RuntimeError):
    """Raised when subtitle translation cannot produce a valid SRT."""


DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_WORKERS = 3
DEFAULT_MAX_REPAIR_ATTEMPTS = 3

TranslationProgressCallback = Callable[[int, int, str], None]


def _get_positive_int(value, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _resolve_batch_size(batch_size: int | None = None) -> int:
    if batch_size is None:
        batch_size = config.app.get("subtitle_translate_batch_size", DEFAULT_BATCH_SIZE)
    return _get_positive_int(batch_size, DEFAULT_BATCH_SIZE, minimum=1, maximum=200)


def _resolve_max_workers(max_workers: int | None = None) -> int:
    if max_workers is None:
        max_workers = config.app.get("subtitle_translate_max_workers", DEFAULT_MAX_WORKERS)
    return _get_positive_int(max_workers, DEFAULT_MAX_WORKERS, minimum=1, maximum=8)


def _split_blocks(blocks, batch_size: int):
    return [blocks[index:index + batch_size] for index in range(0, len(blocks), batch_size)]


def _build_translation_prompt(
    blocks,
    target_language: str,
    glossary_block: str = "",
) -> str:
    payload = {str(block.order): block.text for block in blocks}
    glossary_section = ""
    if glossary_block and glossary_block.strip():
        glossary_section = f"""
术语表（必须遵守，lock=true 的目标写法不可改写）：
{glossary_block.strip()}
"""
    return f"""
请将以下 SRT 字幕文本翻译为{target_language}。

翻译要求：
1. 结合全部字幕内容理解语境，输出自然、准确、适合字幕阅读的{target_language}。
2. 只翻译字幕文本，不要修改时间轴、序号、条目数量或条目顺序。
3. 保留必要的说话人标记、专有名词、品牌名、代码、数字和换行；除非目标语言中有约定译名。
4. 不要添加解释、注释、剧情信息或 Markdown。
5. 空字幕文本保持为空字符串。
6. 若提供术语表，对 lock=true 的词条必须使用表中 Target 写法，不得自由音译。
{glossary_section}
只输出严格 JSON 对象，不要输出 Markdown 或解释文字。必须保留所有输入 key，格式必须为：
{{"1":"翻译后的字幕文本","2":"翻译后的字幕文本"}}

待翻译字幕条目：
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def _parse_translations(raw_output: str, expected_ids: set[int]) -> dict[int, str]:
    json_text = _extract_json_text(raw_output)
    try:
        data: Any = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise SubtitleTranslationError("LLM 未返回有效 JSON 字幕翻译结果") from exc

    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [{"id": key, "text": value} for key, value in data.items()]
    else:
        raise SubtitleTranslationError("LLM 字幕翻译结果格式无效")

    if not isinstance(items, list):
        raise SubtitleTranslationError("LLM 字幕翻译结果缺少 items 列表")

    translations: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id in expected_ids:
            translations[item_id] = str(item.get("text") or "").strip()

    missing_ids = sorted(expected_ids - set(translations.keys()))
    if missing_ids:
        raise SubtitleTranslationError(f"LLM 字幕翻译结果缺少字幕条目: {missing_ids[:10]}")
    return translations


def _build_repair_prompt(
    *,
    blocks,
    target_language: str,
    previous_output: str,
    error_message: str,
    glossary_block: str = "",
) -> str:
    payload = {str(block.order): block.text for block in blocks}
    glossary_section = ""
    if glossary_block and glossary_block.strip():
        glossary_section = f"\n术语表：\n{glossary_block.strip()}\n"
    return f"""
你上一轮返回的字幕翻译 JSON 无法通过校验，请修复后重新输出。

目标语言：{target_language}
{glossary_section}
校验错误：
{error_message}

原始字幕条目：
{json.dumps(payload, ensure_ascii=False, indent=2)}

上一轮输出：
{previous_output}

请只输出严格 JSON 对象，必须包含并且只包含原始字幕条目的所有 key。
""".strip()


def _translate_chunk(
    *,
    chunk,
    chunk_index: int,
    total_chunks: int,
    target_language: str,
    provider: str,
    api_key: str,
    base_url: str,
    model_name: str,
    temperature: float,
    max_repair_attempts: int,
    glossary_block: str = "",
) -> dict[int, str]:
    start_order = chunk[0].order
    end_order = chunk[-1].order
    expected_ids = {block.order for block in chunk}
    logger.info(
        f"字幕翻译批次 {chunk_index}/{total_chunks} 开始: "
        f"条目 {start_order}-{end_order}, 共 {len(chunk)} 条"
    )

    prompt = _build_translation_prompt(chunk, target_language, glossary_block=glossary_block)
    last_output = ""
    last_error = ""
    for attempt in range(1, max_repair_attempts + 1):
        if attempt > 1:
            logger.warning(
                f"字幕翻译批次 {chunk_index}/{total_chunks} 第 {attempt} 次修复: {last_error}"
            )
            prompt = _build_repair_prompt(
                blocks=chunk,
                target_language=target_language,
                previous_output=last_output,
                error_message=last_error,
                glossary_block=glossary_block,
            )

        raw_output = _run_async_safely(
            UnifiedLLMService.generate_text,
            prompt=prompt,
            system_prompt=(
                f"你是一位专业字幕翻译员，擅长在严格保留 JSON key 一一对应的前提下，"
                f"将字幕准确翻译为{target_language}。"
            ),
            provider=provider,
            temperature=temperature,
            response_format="json",
            api_key=api_key,
            api_base=base_url,
            model=model_name,
            thinking_level="off",
        )
        last_output = str(raw_output or "")
        try:
            translations = _parse_translations(last_output, expected_ids)
        except SubtitleTranslationError as exc:
            last_error = str(exc)
            if attempt >= max_repair_attempts:
                logger.error(
                    f"字幕翻译批次 {chunk_index}/{total_chunks} 失败: "
                    f"条目 {start_order}-{end_order}, {last_error}"
                )
                raise
            continue

        logger.info(
            f"字幕翻译批次 {chunk_index}/{total_chunks} 完成: "
            f"条目 {start_order}-{end_order}"
        )
        return translations

    raise SubtitleTranslationError(
        f"字幕翻译批次 {chunk_index}/{total_chunks} 未生成有效结果: 条目 {start_order}-{end_order}"
    )


def _call_progress_callback(
    progress_callback: TranslationProgressCallback | None,
    completed: int,
    total: int,
    message: str,
) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(completed, total, message)
    except Exception as exc:
        logger.debug(f"字幕翻译进度回调失败: {exc}")


def _render_translated_srt(
    blocks,
    translations: dict[int, str],
    *,
    pending_mode: str = "empty",
) -> str:
    """
    pending_mode:
      - empty: 未译条目正文为空（最终成品用）
      - source: 未译条目暂时显示原文（实时预览用）
      - ellipsis: 未译条目显示「… 原文」
    """
    rendered_blocks = []
    mode = (pending_mode or "empty").strip().lower()
    for block in blocks:
        if block.order in translations:
            translated_text = translations.get(block.order, "") or ""
        elif mode == "source":
            translated_text = block.text or ""
        elif mode in {"ellipsis", "pending", "…"}:
            src = (block.text or "").strip()
            translated_text = f"… {src}" if src else "…"
        else:
            translated_text = ""
        rendered_blocks.append(f"{block.index_line}\n{block.time_line}\n{translated_text}")
    return "\n\n".join(rendered_blocks).rstrip() + "\n"


def translate_srt_content(
    srt_content: str,
    *,
    target_language: str = "中文",
    provider: str = "",
    api_key: str = "",
    base_url: str = "",
    model_name: str = "",
    temperature: float = 0.2,
    batch_size: int | None = None,
    max_workers: int | None = None,
    progress_callback: TranslationProgressCallback | None = None,
    glossary_block: str = "",
    partial_output_file: str = "",
    partial_pending_mode: str = "ellipsis",
) -> str:
    target_language = str(target_language or "").strip() or "中文"
    blocks = parse_srt_blocks(srt_content)
    _ensure_llm_providers_registered()
    resolved_model_name = str(
        model_name or resolve_text_model_name(config.app, provider, prefer_fast=True)
    ).strip()

    resolved_batch_size = _resolve_batch_size(batch_size)
    chunks = _split_blocks(blocks, resolved_batch_size)
    resolved_max_workers = min(_resolve_max_workers(max_workers), len(chunks))
    total_chunks = len(chunks)
    total_blocks = len(blocks)

    logger.info(
        f"开始批量翻译字幕: 共 {total_blocks} 条, {total_chunks} 批, "
        f"每批最多 {resolved_batch_size} 条, 并发 {resolved_max_workers}, "
        f"目标语言: {target_language}, 高效率模型: {resolved_model_name}"
    )

    translations: dict[int, str] = {}
    completed_blocks = 0
    partial_path = (partial_output_file or "").strip()
    # 长字幕实时写盘节流：只在「首批 / 每 N 批 / 完成」写，避免每批重写整份 SRT 拖慢翻译
    # 小任务（≤2 批）仍每批写；大任务按批次数自适应
    if total_chunks <= 2:
        _partial_every = 1
    elif total_chunks <= 10:
        _partial_every = 2
    else:
        _partial_every = max(2, total_chunks // 8)  # 大约写 8 次预览
    _partial_writes = 0

    def _emit_partial(completed: int, message: str, *, force_write: bool = False, chunk_index: int = 0) -> None:
        nonlocal _partial_writes
        should_write = False
        if partial_path:
            if force_write or completed <= 0 or completed >= total_blocks:
                should_write = True
            elif chunk_index > 0 and (
                chunk_index == 1 or chunk_index % _partial_every == 0
            ):
                should_write = True
        if should_write and partial_path:
            try:
                # 实时预览：未完成条目先显示原文/省略号，避免空白节点
                partial = _render_translated_srt(
                    blocks,
                    translations,
                    pending_mode=partial_pending_mode or "ellipsis",
                )
                write_srt_file(partial, partial_path)
                _partial_writes += 1
            except Exception as exc:
                logger.warning(f"partial srt write failed: {exc}")
        _call_progress_callback(progress_callback, completed, total_blocks, message)

    _emit_partial(0, f"开始翻译字幕，共 {total_blocks} 条，{total_chunks} 批", force_write=True)

    if total_chunks == 1:
        translations.update(
            _translate_chunk(
                chunk=chunks[0],
                chunk_index=1,
                total_chunks=total_chunks,
                target_language=target_language,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model_name=resolved_model_name,
                temperature=temperature,
                max_repair_attempts=DEFAULT_MAX_REPAIR_ATTEMPTS,
                glossary_block=glossary_block,
            )
        )
        completed_blocks = total_blocks
        _emit_partial(completed_blocks, "字幕翻译完成", force_write=True)
    else:
        with ThreadPoolExecutor(max_workers=resolved_max_workers) as executor:
            future_to_meta = {}
            for index, chunk in enumerate(chunks, start=1):
                future = executor.submit(
                    _translate_chunk,
                    chunk=chunk,
                    chunk_index=index,
                    total_chunks=total_chunks,
                    target_language=target_language,
                    provider=provider,
                    api_key=api_key,
                    base_url=base_url,
                    model_name=resolved_model_name,
                    temperature=temperature,
                    max_repair_attempts=DEFAULT_MAX_REPAIR_ATTEMPTS,
                    glossary_block=glossary_block,
                )
                future_to_meta[future] = (index, chunk)

            for future in as_completed(future_to_meta):
                chunk_index, chunk = future_to_meta[future]
                chunk_translations = future.result()
                translations.update(chunk_translations)
                completed_blocks += len(chunk)
                message = (
                    f"字幕翻译进度: {completed_blocks}/{total_blocks} 条 "
                    f"({ceil(completed_blocks * 100 / total_blocks)}%), "
                    f"完成批次 {chunk_index}/{total_chunks}"
                )
                logger.info(message)
                _emit_partial(
                    completed_blocks,
                    message,
                    force_write=(completed_blocks >= total_blocks),
                    chunk_index=int(chunk_index),
                )

    missing_ids = sorted({block.order for block in blocks} - set(translations.keys()))
    if missing_ids:
        raise SubtitleTranslationError(f"字幕翻译结果缺少字幕条目: {missing_ids[:10]}")

    translated_srt = _render_translated_srt(blocks, translations, pending_mode="empty")
    if partial_path:
        try:
            write_srt_file(translated_srt, partial_path)
        except Exception as exc:
            logger.warning(f"final partial srt write failed: {exc}")
    if _partial_writes:
        logger.info(
            f"字幕翻译完成，共 {total_blocks} 条；实时预览写盘 {_partial_writes} 次（节流 every≈{_partial_every} 批）"
        )
    else:
        logger.info(f"字幕翻译完成，共 {total_blocks} 条")
    return translated_srt


def write_srt_file(srt_content: str, subtitle_file: str = "") -> str:
    if not subtitle_file:
        subtitle_file = os.path.join(utils.subtitle_dir(), "subtitle_translated.srt")
    parent = os.path.dirname(subtitle_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(srt_content)
    return subtitle_file


def translate_subtitle_file(
    subtitle_file: str,
    output_file: str = "",
    *,
    target_language: str = "中文",
    provider: str = "",
    api_key: str = "",
    base_url: str = "",
    model_name: str = "",
    temperature: float = 0.2,
    batch_size: int | None = None,
    max_workers: int | None = None,
    progress_callback: TranslationProgressCallback | None = None,
    glossary_block: str = "",
    write_partial: bool = True,
) -> str:
    if not subtitle_file or not os.path.isfile(subtitle_file):
        raise SubtitleTranslationError(f"字幕文件不存在: {subtitle_file}")

    decoded = read_subtitle_text(subtitle_file)
    # 默认边译边写到 output_file，供 UI 实时展示字幕节点
    partial_path = (output_file or "").strip() if write_partial else ""
    translated_srt = translate_srt_content(
        decoded.text,
        target_language=target_language,
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        temperature=temperature,
        batch_size=batch_size,
        max_workers=max_workers,
        progress_callback=progress_callback,
        glossary_block=glossary_block,
        partial_output_file=partial_path,
        partial_pending_mode="ellipsis",
    )
    return write_srt_file(translated_srt, output_file)
