#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境「多语配音」实验模块（mode=dubbing）。

路径：ASR → 翻译 → 人声分离 → 目标语 TTS → 伴奏+配音混音 → 烧字幕。

与 subtitle / narration 解耦：分离与混音逻辑集中在本包，pipeline 只调 step_*。
无人声分离模型时自动降级（压低原声 / 立体声中置削弱），不阻断流水线。
"""

from . import mix, separate, synthesize, voices

__all__ = ["separate", "synthesize", "mix", "voices"]
