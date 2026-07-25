#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化服务（en↔zh 双向）

默认模式 subtitle：仿 VideoLingo，ASR → 翻译 → 硬烧字幕。
可选模式 narration：解说文案工厂（digest/copy/match/TTS/render）。
"""

from . import asr
from . import burn
from . import compliance
from . import glossary
from . import packaging
from . import pipeline
from . import render
from . import state_machine
from . import style_packs
from . import task_store

__all__ = [
    "asr",
    "burn",
    "compliance",
    "glossary",
    "packaging",
    "pipeline",
    "render",
    "state_machine",
    "style_packs",
    "task_store",
]
