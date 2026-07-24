#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化 · 源内容摘要（事实层）
替代影视/短剧的「剧情分析」，服务 en↔zh 双向搬运解说。
"""

from ..base import ParameterizedPrompt, PromptMetadata, ModelType, OutputFormat


class SourceDigestPrompt(ParameterizedPrompt):
    """跨境源内容摘要提示词"""

    def __init__(self):
        metadata = PromptMetadata(
            name="source_digest",
            category="cross_border_narration",
            version="v1.0",
            description="把源视频字幕整理成可解说的事实与节拍包，不写口播文案",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.TEXT,
            tags=["跨境", "本地化", "摘要", "en-zh", "inbound", "outbound"],
            parameters=[
                "direction",
                "source_lang",
                "target_lang",
                "content_type",
                "platform",
                "glossary",
                "subtitle_content",
            ],
        )
        super().__init__(
            metadata,
            required_parameters=["direction", "subtitle_content"],
        )
        self._system_prompt = (
            "You produce a structured source digest for cross-border video localization. "
            "Do NOT write voiceover copy. Stick to facts grounded in the subtitles. "
            "Follow the fixed Markdown headings exactly."
        )

    def get_template(self) -> str:
        return """# Cross-border Source Digest

## Task
Turn the source video subtitles into a reusable fact & beat pack for localization narration.
This is NOT plot analysis for drama. This is NOT voiceover copy.

## Direction
- direction: ${direction}   # inbound = foreign→target domestic (often en→zh); outbound = domestic→foreign (often zh→en)
- source_lang: ${source_lang}
- target_lang: ${target_lang}
- content_type: ${content_type}
- platform: ${platform}

## Glossary (MUST respect lock=true entities)
${glossary}

## Hard rules
1. No greeting, no role-play chatter, no invented facts.
2. Subtitles are the only hard truth. Mark uncertain items explicitly.
3. Keep proper nouns consistent; prefer glossary Target when lock=true.
4. High-energy moments must include timestamps when available.
5. Output ONLY the Markdown sections below, in this order.

## Direction-specific focus
### If direction=inbound
- Flag background a domestic target audience may lack.
- Flag compress-friendly beats for short-form re-narration.
- Optional local humor only if natural; never force memes.

### If direction=outbound
- Flag Chinese-context items foreign audiences will miss.
- Flag slang/internet words that must be meaning-translated, not literal.
- Flag risky absolute claims (medical, income, guaranteed results).
- Align entity names with glossary.

## Output format (fixed)

## Meta
- Title / topic: [...]
- Content type: [${content_type}]
- Source language: [${source_lang}]
- Likely audience of source: [...]
- Time span of subtitles: [start --> end | unknown]

## Core Claims / Facts
- [2-8 factual bullets only from subtitles]

## People & Entities
| Name (canonical) | Role | Notes |
|---|---|---|
| ... | ... | ... |

## Timeline Beats
| Timestamp | Beat | Function |
|---|---|---|
| HH:MM:SS,mmm --> HH:MM:SS,mmm | what happens | setup / payoff / demo / reaction / CTA / other |

## High-energy Moments（必须留原片的点）
1. [timestamp] — [why keep original audio/picture]

## Culture Notes（一端观众可能不懂的点）
- [...]

## Risks（敏感/夸大/版权注意）
- [...]

## Do Not Invent（字幕没有的别编）
- [list things model must not invent; or "none"]

# Source subtitles
${subtitle_content}
"""
