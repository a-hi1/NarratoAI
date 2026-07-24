#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化 · 标题/简介/标签包装（分发层）
"""

from ..base import ParameterizedPrompt, PromptMetadata, ModelType, OutputFormat


class TitlePackagingPrompt(ParameterizedPrompt):
    """跨境标题与分发包装提示词"""

    def __init__(self):
        metadata = PromptMetadata(
            name="title_packaging",
            category="cross_border_narration",
            version="v1.0",
            description="基于摘要与解说文案生成目标平台标题、简介、标签与来源声明",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.JSON,
            tags=["跨境", "标题", "包装", "SEO", "inbound", "outbound"],
            parameters=[
                "direction",
                "source_lang",
                "target_lang",
                "style_pack",
                "content_type",
                "platform",
                "source_digest",
                "narration_copy",
                "glossary",
                "source_credit",
                "credit_hint",
            ],
        )
        super().__init__(
            metadata,
            required_parameters=["direction", "source_digest", "narration_copy"],
        )
        self._system_prompt = (
            "You write platform packaging for localized short videos. "
            "Output strict JSON only. No vulgar clickbait or false promises."
        )

    def get_template(self) -> str:
        return """# Cross-border Title Packaging

## Inputs
- direction: ${direction}
- source_lang: ${source_lang}
- target_lang: ${target_lang}
- style_pack: ${style_pack}
- content_type: ${content_type}
- platform: ${platform}
- source_credit enabled: ${source_credit}
- credit_hint: ${credit_hint}

## Digest
${source_digest}

## Narration copy
${narration_copy}

## Glossary
${glossary}

## Rules
### Shared
- titles: 3 options in target language
- no fake giveaways, no illegal claims
- respect glossary locks
- if source_credit is true, fill credit_line; else credit_line may be empty string

### inbound (often Chinese platforms)
- curiosity gap OK; no vulgar spam
- cover_text: 4–8 Chinese characters preferred
- tags suitable for Douyin/Bilibili style discovery
- description short and scannable

### outbound (often EN Shorts/TikTok/YouTube)
- no ALL-CAPS shouting titles
- avoid spammy emoji walls
- include "caption" for short post paste
- description natural with light keywords
- 2–5 hashtags max inside tags or description naturally

## Output JSON only
{
  "titles": ["...", "...", "..."],
  "cover_text": "...",
  "description": "...",
  "tags": ["..."],
  "caption": "...",
  "credit_line": "..."
}
"""
