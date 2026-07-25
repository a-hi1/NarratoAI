#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""多语默认 Edge TTS 音色与语种白名单。"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# UI / 任务可选语种（ISO 639-1 前两位）
SUPPORTED_LANGS: Tuple[str, ...] = (
    "zh",
    "en",
    "ja",
    "ko",
    "es",
    "fr",
    "de",
    "pt",
    "it",
    "ru",
    "vi",
    "th",
    "id",
    "ar",
    "hi",
)

LANG_LABELS: Dict[str, str] = {
    "zh": "中文 Chinese",
    "en": "英语 English",
    "ja": "日语 Japanese",
    "ko": "韩语 Korean",
    "es": "西班牙语 Spanish",
    "fr": "法语 French",
    "de": "德语 German",
    "pt": "葡萄牙语 Portuguese",
    "it": "意大利语 Italian",
    "ru": "俄语 Russian",
    "vi": "越南语 Vietnamese",
    "th": "泰语 Thai",
    "id": "印尼语 Indonesian",
    "ar": "阿拉伯语 Arabic",
    "hi": "印地语 Hindi",
}

# 每语默认 Edge 音色（女声优先，可被 inputs.voice_name 覆盖）
DEFAULT_EDGE_VOICES: Dict[str, str] = {
    "zh": "zh-CN-XiaoyiNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "it": "it-IT-ElsaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "th": "th-TH-PremwadeeNeural",
    "id": "id-ID-GadisNeural",
    "ar": "ar-SA-ZariyahNeural",
    "hi": "hi-IN-SwaraNeural",
}

# 备用男声（可选）
ALT_EDGE_VOICES: Dict[str, str] = {
    "zh": "zh-CN-YunxiNeural",
    "en": "en-US-GuyNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural",
    "it": "it-IT-DiegoNeural",
    "ru": "ru-RU-DmitryNeural",
    "vi": "vi-VN-NamMinhNeural",
    "th": "th-TH-NiwatNeural",
    "id": "id-ID-ArdiNeural",
    "ar": "ar-SA-HamedNeural",
    "hi": "hi-IN-MadhurNeural",
}

# Edge 音色前缀 → 语种（用于校验「音色是否对应目标语」）
_VOICE_LANG_PREFIX: Tuple[Tuple[str, str], ...] = (
    ("zh-cn", "zh"),
    ("zh-tw", "zh"),
    ("zh-hk", "zh"),
    ("en-us", "en"),
    ("en-gb", "en"),
    ("en-au", "en"),
    ("ja-jp", "ja"),
    ("ko-kr", "ko"),
    ("es-es", "es"),
    ("es-mx", "es"),
    ("fr-fr", "fr"),
    ("de-de", "de"),
    ("pt-br", "pt"),
    ("pt-pt", "pt"),
    ("it-it", "it"),
    ("ru-ru", "ru"),
    ("vi-vn", "vi"),
    ("th-th", "th"),
    ("id-id", "id"),
    ("ar-sa", "ar"),
    ("ar-eg", "ar"),
    ("hi-in", "hi"),
)


def normalize_lang(code: str, fallback: str = "en") -> str:
    raw = (code or "").strip().lower().replace("_", "-")
    if not raw:
        return fallback
    # zh-cn → zh
    two = raw.split("-", 1)[0][:2]
    if two in SUPPORTED_LANGS:
        return two
    return fallback if fallback in SUPPORTED_LANGS else "en"


def lang_choices_for_ui() -> List[Tuple[str, str]]:
    return [(code, LANG_LABELS.get(code, code)) for code in SUPPORTED_LANGS]


def default_voice_for_lang(lang: str, *, gender: str = "female") -> str:
    lang = normalize_lang(lang)
    if (gender or "female").lower().startswith("m"):
        return ALT_EDGE_VOICES.get(lang) or DEFAULT_EDGE_VOICES.get(lang) or "en-US-JennyNeural"
    return DEFAULT_EDGE_VOICES.get(lang) or "en-US-JennyNeural"


def voice_lang(voice_name: str) -> Optional[str]:
    """从 Edge 音色名推断语种；无法识别返回 None。"""
    raw = (voice_name or "").strip().lower().replace("_", "-")
    if not raw:
        return None
    for prefix, lang in _VOICE_LANG_PREFIX:
        if raw.startswith(prefix):
            return lang
    # 宽松：取前两段或前两位
    m = re.match(r"^([a-z]{2})(?:-|$)", raw)
    if m and m.group(1) in SUPPORTED_LANGS:
        return m.group(1)
    return None


def resolve_voice_for_lang(
    target_lang: str,
    voice_name: str = "",
    *,
    gender: str = "female",
    force_match: bool = True,
) -> Tuple[str, bool]:
    """
    保证音色与目标语一致。

    返回 (voice, corrected)：
    - 空音色 → 默认
    - force_match 且音色语种 ≠ 目标语 → 换成目标语默认（避免中文片配英文音色等错位）
    """
    lang = normalize_lang(target_lang)
    voice = (voice_name or "").strip()
    if not voice:
        return default_voice_for_lang(lang, gender=gender), True
    if not force_match:
        return voice, False
    vlang = voice_lang(voice)
    if vlang is None:
        # 非标准 Edge 名（可能是 Azure 自定义）→ 信任用户
        return voice, False
    if vlang != lang:
        return default_voice_for_lang(lang, gender=gender), True
    return voice, False
