#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化风格包（In 3 + Out 3）。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


StylePack = Dict[str, Any]

_STYLE_PACKS: Dict[str, StylePack] = {
    "in_hook_narration": {
        "id": "in_hook_narration",
        "direction": "inbound",
        "label_zh": "钩子解说",
        "label_en": "Hook Narration",
        "default_original_audio_ratio": 30,
        "default_word_count_per_min": 320,
        "default_content_type": "tech_review",
        "default_platform": "douyin",
        "tts_voice_hint": {"zh": "zh-CN-YunxiNeural", "en": None},
        "prompt_addendum": (
            "开篇3秒内给出冲突或利益点；信息密度高；"
            "第2段前交代清楚主题对象；保留1-2处原片高能给OST。"
        ),
        "packaging": {
            "subtitle_mode": "target_only",
            "title_style": "curiosity_gap",
            "credit": True,
        },
    },
    "in_roast_fast": {
        "id": "in_roast_fast",
        "direction": "inbound",
        "label_zh": "吐槽快评",
        "label_en": "Roast Fast",
        "default_original_audio_ratio": 42,
        "default_word_count_per_min": 280,
        "default_content_type": "skit_meme",
        "default_platform": "douyin",
        "tts_voice_hint": {"zh": "zh-CN-XiaoyiNeural", "en": None},
        "prompt_addendum": (
            "允许犀利吐槽，不允许侮辱与造谣；包袱服务画面；"
            "句子更短更密；多留原片反应镜头给OST。"
        ),
        "packaging": {
            "subtitle_mode": "target_only",
            "title_style": "reaction",
            "credit": True,
        },
    },
    "in_calm_explain": {
        "id": "in_calm_explain",
        "direction": "inbound",
        "label_zh": "冷静科普",
        "label_en": "Calm Explain",
        "default_original_audio_ratio": 20,
        "default_word_count_per_min": 300,
        "default_content_type": "knowledge",
        "default_platform": "bilibili",
        "tts_voice_hint": {"zh": "zh-CN-YunyangNeural", "en": None},
        "prompt_addendum": (
            "结论-论据-边界；少感叹号；少情绪词；"
            "把关键概念讲清楚，不堆形容词。"
        ),
        "packaging": {
            "subtitle_mode": "target_only",
            "title_style": "informative",
            "credit": True,
        },
    },
    "out_clean_explain": {
        "id": "out_clean_explain",
        "direction": "outbound",
        "label_zh": "清晰说明",
        "label_en": "Clean Explain",
        "default_original_audio_ratio": 20,
        "default_word_count_per_min": 150,
        "default_content_type": "product_demo",
        "default_platform": "youtube_shorts",
        "tts_voice_hint": {"zh": None, "en": "en-US-JennyNeural"},
        "prompt_addendum": (
            "Clear, friendly, competent English. Short sentences. "
            "One information point every 8–12 seconds. No slogan stacking."
        ),
        "packaging": {
            "subtitle_mode": "target_only",
            "title_style": "clean",
            "credit": True,
        },
    },
    "out_native_creator": {
        "id": "out_native_creator",
        "direction": "outbound",
        "label_zh": "原生创作者",
        "label_en": "Native Creator",
        "default_original_audio_ratio": 32,
        "default_word_count_per_min": 160,
        "default_content_type": "skit_meme",
        "default_platform": "tiktok",
        "tts_voice_hint": {"zh": None, "en": "en-US-AriaNeural"},
        "prompt_addendum": (
            "Conversational, slightly playful. Question hooks OK. Soft CTA OK. "
            "Ban Chinglish openers like 'Let us take a look together'."
        ),
        "packaging": {
            "subtitle_mode": "target_only",
            "title_style": "native_hook",
            "credit": True,
        },
    },
    "out_brand_demo": {
        "id": "out_brand_demo",
        "direction": "outbound",
        "label_zh": "品牌演示",
        "label_en": "Brand Demo",
        "default_original_audio_ratio": 38,
        "default_word_count_per_min": 140,
        "default_content_type": "product_demo",
        "default_platform": "tiktok",
        "tts_voice_hint": {"zh": None, "en": "en-US-GuyNeural"},
        "prompt_addendum": (
            "Confident, benefit-led. Glossary product names locked. "
            "No exaggerated medical/income claims. Keep hand/product shots."
        ),
        "packaging": {
            "subtitle_mode": "target_only",
            "title_style": "benefit",
            "credit": True,
        },
    },
}


DEFAULT_BY_DIRECTION = {
    "inbound": "in_hook_narration",
    "outbound": "out_clean_explain",
}


def list_style_packs(direction: Optional[str] = None) -> List[StylePack]:
    packs = []
    for pack in _STYLE_PACKS.values():
        if direction and pack["direction"] != direction:
            continue
        packs.append(deepcopy(pack))
    return packs


def get_style_pack(pack_id: str) -> StylePack:
    if pack_id not in _STYLE_PACKS:
        raise KeyError(f"unknown style pack: {pack_id}")
    return deepcopy(_STYLE_PACKS[pack_id])


def resolve_style_pack(
    direction: str,
    pack_id: Optional[str] = None,
) -> StylePack:
    direction = (direction or "inbound").lower()
    if not pack_id:
        pack_id = DEFAULT_BY_DIRECTION.get(direction, "in_hook_narration")
    pack = get_style_pack(pack_id)
    if pack["direction"] != direction:
        # 方向与风格包不一致时回退默认
        pack = get_style_pack(DEFAULT_BY_DIRECTION[direction])
    return pack


def style_choices_for_ui(direction: str) -> Dict[str, str]:
    """Streamlit selectbox: label -> id"""
    result = {}
    for pack in list_style_packs(direction):
        label = pack["label_zh"] if direction == "inbound" else pack["label_en"]
        result[f"{label} ({pack['id']})"] = pack["id"]
    return result
