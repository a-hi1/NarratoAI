#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化解说提示词模块（en↔zh 双向）
"""

from .source_digest import SourceDigestPrompt
from .narration_copy import NarrationCopyPrompt
from .script_matching import ScriptMatchingPrompt
from .title_packaging import TitlePackagingPrompt
from ..manager import PromptManager


def register_prompts():
    """注册跨境本地化相关提示词"""
    PromptManager.register_prompt(SourceDigestPrompt(), is_default=True)
    PromptManager.register_prompt(NarrationCopyPrompt(), is_default=True)
    PromptManager.register_prompt(ScriptMatchingPrompt(), is_default=True)
    PromptManager.register_prompt(TitlePackagingPrompt(), is_default=True)


__all__ = [
    "SourceDigestPrompt",
    "NarrationCopyPrompt",
    "ScriptMatchingPrompt",
    "TitlePackagingPrompt",
    "register_prompts",
]
