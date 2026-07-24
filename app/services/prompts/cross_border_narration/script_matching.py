#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境本地化 · 文案↔时间轴匹配（剪辑层）
输出字段兼容现有 TTS / 合成链路。
"""

from ..base import ParameterizedPrompt, PromptMetadata, ModelType, OutputFormat


class ScriptMatchingPrompt(ParameterizedPrompt):
    """跨境解说文案画面匹配提示词"""

    def __init__(self):
        metadata = PromptMetadata(
            name="script_matching",
            category="cross_border_narration",
            version="v1.0",
            description="将审核后的跨境解说文案匹配到字幕时间戳，生成标准剪辑 JSON",
            model_type=ModelType.TEXT,
            output_format=OutputFormat.JSON,
            tags=["跨境", "匹配", "剪辑脚本", "OST", "inbound", "outbound"],
            parameters=[
                "direction",
                "source_lang",
                "target_lang",
                "style_pack",
                "content_type",
                "source_digest",
                "subtitle_content",
                "narration_copy",
                "original_sound_ratio",
                "style_addendum",
            ],
        )
        super().__init__(
            metadata,
            required_parameters=["direction", "subtitle_content", "narration_copy"],
        )
        self._system_prompt = (
            "You are an editor matching localized voiceover lines to source video timestamps. "
            "Output strict JSON only. Preserve creator-approved narration meaning."
        )

    def get_template(self) -> str:
        return """# Cross-border Script Matching

## Goal
Match the reviewed voiceover copy to source subtitle timestamps and produce a final editable clip script JSON.

## Inputs
- direction: ${direction}
- source_lang: ${source_lang}
- target_lang: ${target_lang}
- style_pack: ${style_pack}
- content_type: ${content_type}
- original_sound_ratio target: ${original_sound_ratio}%

## Style notes
${style_addendum}

## Source digest
<digest>
${source_digest}
</digest>

## Reviewed narration copy
<narration_copy>
${narration_copy}
</narration_copy>

## Source subtitles (with video headers / local timestamps)
<subtitles>
${subtitle_content}
</subtitles>

## Matching rules (shared)
1. Split narration by sentence enders first; only split on commas when two real ideas exist.
2. You may merge adjacent sentences into one OST=0 bridge, but do not change core meaning.
3. Skip credits, ads, sponsor reads, pure watermarks, unrelated promos.
4. timestamp must use each video's local time, format "HH:MM:SS,mmm-HH:MM:SS,mmm".
5. Same video_id ranges must not overlap.
6. First item should usually be OST=0 hook unless ratio strategy forces otherwise (still prefer OST=0 first).
7. OST=1 total duration share should approach ${original_sound_ratio}% by time, not by count.
8. Estimate spoken duration roughly: CJK chars/5 seconds; English words/2.5 seconds. Prefer ±0.5s when possible.
9. picture describes visible action/scene, not abstract feelings only.
10. OST=0 narration = voiceover text; OST=1 narration = "播放原片" + _id (or equivalent keep-original marker).

## Direction strategies
### inbound
- Explosions / screams / punchlines / big reactions → prefer OST=1.
- Pure explanation lines → OST=0.
- Hook sentence should land near open 0–3s when possible.

### outbound
- Product close-ups / hand demos stay on picture; VO can be OST=0 over them.
- Strong emotional original audio → OST=1.
- Leave slightly longer picture for English VO so words are not cut off.
- When brand/product appears on screen, speak glossary-locked name in VO.

## Ratio guidance
- 0%: no OST=1.
- 10–30%: only critical original peaks.
- 40–60%: VO bridges + key original moments.
- 70–90%: original-led; VO as hooks/bridges only.

## Fields
- _id: continuous from 1
- video_id: integer from subtitle headers (default 1)
- video_name: basename from headers when present
- timestamp, picture, narration, OST (0 or 1)

## Output
Strict JSON only:

{
  "items": [
    {
      "_id": 1,
      "video_id": 1,
      "video_name": "video.mp4",
      "timestamp": "00:00:00,000-00:00:03,200",
      "picture": "...",
      "narration": "...",
      "OST": 0
    }
  ]
}
"""
