#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化 · 目标语解说文案（表达层）
"""

from ..base import ParameterizedPrompt, PromptMetadata, ModelType, OutputFormat


class NarrationCopyPrompt(ParameterizedPrompt):
    """跨境本地化解说文案提示词"""

    def __init__(self):
        metadata = PromptMetadata(
            name="narration_copy",
            category="cross_border_narration",
            version="v1.0",
            description="基于源内容摘要生成目标语本地化解说正文，不绑定时间戳",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.TEXT,
            tags=["跨境", "本地化", "解说文案", "inbound", "outbound"],
            parameters=[
                "direction",
                "source_lang",
                "target_lang",
                "style_pack",
                "content_type",
                "platform",
                "duration_mode",
                "source_digest",
                "subtitle_content",
                "glossary",
                "narration_word_count",
                "style_addendum",
            ],
        )
        super().__init__(
            metadata,
            required_parameters=["direction", "source_digest", "subtitle_content"],
        )
        self._system_prompt = (
            "You write localized voiceover body for cross-border short video. "
            "Not literal translation. Not drama spoiler narration. "
            "Output only the voiceover body in the target language."
        )

    def get_template(self) -> str:
        return """# Cross-border Localized Narration Copy

## Goal
Write voiceover body that a creator can lightly edit and ship on ${platform}.
Do localization, not machine translation, and not film/TV drama recap style.

## Direction & languages
- direction: ${direction}
- source_lang: ${source_lang}
- target_lang: ${target_lang}
- style_pack: ${style_pack}
- content_type: ${content_type}
- duration_mode: ${duration_mode}
- target word/char count: ${narration_word_count}

## Style pack addendum (must obey)
${style_addendum}

## Source digest
<digest>
${source_digest}
</digest>

## Subtitles (source; may include target if provided)
<subtitles>
${subtitle_content}
</subtitles>

## Glossary
${glossary}

## Shared hard rules
1. Output ONLY the voiceover body in ${target_lang}. No JSON, timestamps, titles, markdown headings, or explanations.
2. Do not invent facts absent from digest/subtitles.
3. Glossary lock=true terms must appear exactly as Target.
4. Respect ${narration_word_count} with about ±10% tolerance (CJK by non-space chars; others by words).
5. Short spoken sentences. One idea per sentence when possible.
6. Separate beats with blank lines if helpful; never write timestamps.

## If direction=inbound (usually target_lang=zh)
- Open with conflict / benefit / contrast within the first 1–2 sentences.
- Prefer short Chinese oral lines suitable for Douyin/Bilibili narration.
- Avoid short-drama clichés like「她不知道的是」and baseless melodrama.
- Proper names: keep or use glossary; optional short identity apposition once.
- Do not turn tech/product/skit videos into soap-opera plots.

## If direction=outbound (usually target_lang=en)
- Native hook. Forbidden openers: "Hello everyone, today I will introduce..."
- Conversational English for TikTok/YouTube Shorts. No Chinglish, no four-character slogan dumps, no bureaucratic tone.
- Meaning-translate Chinese internet slang; never literal idiom dumps.
- Soft CTA only if style/content needs it; brand demo may be more benefit-led.
- Keep glossary product/brand names exact.

## Content-type emphasis
- tech_review: verdict first; humanize specs.
- product_demo: problem → solution → proof.
- skit_meme: punchline pacing; denser reactions.
- knowledge: one clear takeaway; no sermon.
- story_recap: spoiler-safe hook + clean beats.
- news_explain: 5W, neutral tone.

Now write the voiceover body only.
"""
