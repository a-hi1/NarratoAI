#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""跨境本地化骨架单测（不依赖真实 LLM / ASR）。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

from app.services.cross_border import asr as asr_mod
from app.services.cross_border import compliance, glossary, packaging, state_machine, style_packs, task_store
from app.services.prompts import PromptManager


class StylePackTests(unittest.TestCase):
    def test_six_packs(self):
        packs = style_packs.list_style_packs()
        self.assertEqual(len(packs), 6)
        inbound = style_packs.list_style_packs("inbound")
        outbound = style_packs.list_style_packs("outbound")
        self.assertEqual(len(inbound), 3)
        self.assertEqual(len(outbound), 3)

    def test_resolve_default_and_mismatch(self):
        p = style_packs.resolve_style_pack("inbound")
        self.assertEqual(p["id"], "in_hook_narration")
        # outbound pack requested under inbound direction -> fallback
        p2 = style_packs.resolve_style_pack("inbound", "out_clean_explain")
        self.assertEqual(p2["direction"], "inbound")


class GlossaryTests(unittest.TestCase):
    def test_parse_and_format(self):
        items = glossary.parse_glossary_text(
            "MrBeast = MrBeast\n老干妈 => Lao Gan Ma | lock\nFoo|Bar|false\n"
        )
        self.assertEqual(len(items), 3)
        self.assertTrue(items[0]["lock"])
        self.assertFalse(items[2]["lock"])
        block = glossary.format_glossary_for_prompt(items)
        self.assertIn("MrBeast", block)
        self.assertIn("Lao Gan Ma", block)

    def test_apply_locked_terms(self):
        items = [{"src": "老干妈", "dst": "Lao Gan Ma", "lock": True}]
        text = glossary.apply_locked_terms("推荐老干妈拌饭", items)
        self.assertIn("Lao Gan Ma", text)


class StateMachineTests(unittest.TestCase):
    def test_happy_path_edges(self):
        state_machine.assert_transition("draft", "queued")
        state_machine.assert_transition("queued", "asr_running")
        state_machine.assert_transition("asr_running", "asr_done")
        state_machine.assert_transition("copy_done", "match_running")
        state_machine.assert_transition("packaging_done", "completed")

    def test_illegal_transition(self):
        with self.assertRaises(state_machine.InvalidTransitionError):
            state_machine.assert_transition("draft", "completed")

    def test_progress_and_next(self):
        self.assertEqual(state_machine.progress_of("copy_done"), 60)
        self.assertEqual(
            state_machine.next_running_after("copy_done", mode="narration"),
            "match_running",
        )
        self.assertEqual(
            state_machine.next_running_after("packaging_done", mode="narration"),
            "completed",
        )
        self.assertEqual(
            state_machine.next_running_after("translate_done", mode="subtitle"),
            "burn_running",
        )
        self.assertEqual(
            state_machine.next_running_after("burn_done", mode="subtitle"),
            "completed",
        )
        self.assertEqual(state_machine.steps_for_mode("subtitle"), ("asr", "translate", "burn"))
        self.assertIn("burn", state_machine.ALL_PIPELINE_STEPS)
        self.assertEqual(
            state_machine.steps_for_mode("dubbing"),
            ("asr", "translate", "separate", "dub_tts", "mix", "burn"),
        )
        self.assertEqual(
            state_machine.next_running_after("translate_done", mode="dubbing"),
            "separate_running",
        )
        self.assertEqual(
            state_machine.next_running_after("mix_done", mode="dubbing"),
            "burn_running",
        )
        self.assertEqual(
            state_machine.next_running_after("burn_done", mode="dubbing"),
            "completed",
        )
        state_machine.assert_transition("translate_done", "separate_running")
        state_machine.assert_transition("separate_done", "dub_tts_running")
        state_machine.assert_transition("dub_tts_done", "mix_running")
        state_machine.assert_transition("mix_done", "burn_running")
        state_machine.assert_transition("completed", "dub_tts_running")
        self.assertIn("separate", state_machine.ALL_PIPELINE_STEPS)
        self.assertIn("dub_tts", state_machine.ALL_PIPELINE_STEPS)
        self.assertIn("mix", state_machine.ALL_PIPELINE_STEPS)

    def test_failed_retry(self):
        state_machine.assert_transition("failed", "digest_running")
        # 失败后常先回 queued，再从任意步继续
        state_machine.assert_transition("failed", "queued")
        state_machine.assert_transition("queued", "copy_running")
        state_machine.assert_transition("queued", "match_running")


class ComplianceTests(unittest.TestCase):
    def test_ratio_and_level(self):
        items = [
            {
                "_id": 1,
                "timestamp": "00:00:00,000-00:00:10,000",
                "OST": 0,
                "narration": "hello",
            },
            {
                "_id": 2,
                "timestamp": "00:00:10,000-00:00:20,000",
                "OST": 1,
                "narration": "播放原片2",
            },
        ]
        ratio = compliance.estimate_original_audio_ratio(items)
        self.assertEqual(ratio, 50.0)
        result = compliance.score_transform_level(
            narration_copy="这是一段足够长的本地化解说文案" * 5,
            items=items,
            target_original_ratio=30,
            source_credit=False,
        )
        self.assertIn(result["level"], {"low", "medium", "high"})
        self.assertTrue(result["warnings"])


class TaskStoreTests(unittest.TestCase):
    def test_create_transition_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "demo.mp4"),
                    glossary="MrBeast = MrBeast",
                    asr_backend="local",
                    video_title="开箱评测",
                    task_name="",
                )
                self.assertTrue(meta["task_id"].startswith("cb_"))
                self.assertEqual(meta["status"], "draft")
                self.assertEqual(meta["source_lang"], "en")
                self.assertEqual(meta["target_lang"], "zh")
                self.assertEqual(meta["inputs"]["asr_backend"], "local")
                self.assertIn("display_name", meta)
                self.assertIn("引入", meta["display_name"])
                self.assertIn("开箱评测", meta["display_name"])
                meta = task_store.transition(meta, "queued")
                self.assertEqual(meta["status"], "queued")
                path = task_store.write_text_artifact(meta["task_id"], "digest.md", "# ok\n")
                self.assertTrue(os.path.isfile(path))
                rows = task_store.list_tasks()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["display_name"], meta["display_name"])

    def test_display_name_custom_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="outbound",
                    video_path="",
                    task_name="我的出海片 A",
                )
                self.assertEqual(meta["display_name"], "我的出海片 A")
                task_store.refresh_display_name(
                    meta,
                    video_path=os.path.join(tmp, "产品演示.mp4"),
                    video_title="产品演示",
                    task_name="",
                )
                # 自定义名仍在 inputs.task_name 时优先；清空后走自动
                meta["inputs"]["task_name"] = ""
                task_store.refresh_display_name(
                    meta,
                    video_path=os.path.join(tmp, "产品演示.mp4"),
                    video_title="产品演示",
                )
                self.assertIn("出海", meta["display_name"])
                self.assertIn("产品演示", meta["display_name"])
                task_store.save_meta(meta)
                loaded = task_store.load_meta(meta["task_id"])
                self.assertEqual(loaded["display_name"], meta["display_name"])

    def test_save_meta_retry_on_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "a.mp4"),
                    video_title="锁文件测试",
                )
                calls = {"n": 0}
                real_replace = os.replace

                def flaky_replace(src, dst):
                    calls["n"] += 1
                    if calls["n"] < 3:
                        raise PermissionError(5, "拒绝访问")
                    return real_replace(src, dst)

                with mock.patch.object(os, "replace", side_effect=flaky_replace):
                    meta = task_store.transition(meta, "queued")
                self.assertEqual(meta["status"], "queued")
                self.assertGreaterEqual(calls["n"], 3)

    def test_failed_keeps_step_for_retry(self):
        """failed 后 error.step / meta.step 仍指向失败前步骤，供 UI 重试。"""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "a.mp4"),
                    video_title="失败步保留",
                )
                meta = task_store.transition(meta, "queued")
                meta = task_store.transition(meta, "asr_running")
                meta = task_store.transition(meta, "asr_done")
                meta = task_store.transition(meta, "translate_running")
                self.assertEqual(meta["step"], "translate")
                meta = task_store.transition(meta, "failed", error="boom")
                self.assertEqual(meta["status"], "failed")
                self.assertEqual(meta["step"], "translate")
                self.assertEqual((meta.get("error") or {}).get("step"), "translate")
                self.assertIn("boom", (meta.get("error") or {}).get("message") or "")


class PackagingTests(unittest.TestCase):
    def test_fallback_and_export(self):
        fb = packaging.fallback_titles_from_copy("inbound", "为了卖书他直接炸了舞台")
        self.assertEqual(len(fb["titles"]), 3)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="outbound",
                    video_path=os.path.join(tmp, "x.mp4"),
                )
                payload = packaging.build_packaging_payload(
                    direction="outbound",
                    narration_copy="A clean product demo voiceover.",
                    titles=fb["titles"],
                    source_credit=True,
                    credit_hint="BrandX",
                    script_items=[],
                )
                paths = packaging.write_export_bundle(meta["task_id"], payload, meta)
                self.assertTrue(os.path.isfile(paths["narration_copy"]))
                self.assertTrue(os.path.isfile(paths["compliance"]))


class PromptRegistrationTests(unittest.TestCase):
    def test_cross_border_prompts_registered(self):
        # import triggers initialize_prompts
        import app.services.prompts  # noqa: F401

        self.assertTrue(
            PromptManager.exists("cross_border_narration", "source_digest")
        )
        self.assertTrue(
            PromptManager.exists("cross_border_narration", "narration_copy")
        )
        self.assertTrue(
            PromptManager.exists("cross_border_narration", "script_matching")
        )
        self.assertTrue(
            PromptManager.exists("cross_border_narration", "title_packaging")
        )

        rendered = PromptManager.get_prompt(
            "cross_border_narration",
            "source_digest",
            parameters={
                "direction": "inbound",
                "source_lang": "en",
                "target_lang": "zh",
                "content_type": "tech_review",
                "platform": "douyin",
                "glossary": "(empty)",
                "subtitle_content": "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            },
        )
        self.assertIn("Core Claims", rendered)
        self.assertIn("Hello", rendered)


class AsrRoutingTests(unittest.TestCase):
    def test_backend_chain_language_bias(self):
        # auto 默认优先内置 whisper（若可用），本地服务仅可达时插入
        with mock.patch.object(asr_mod, "_whisper_available", return_value=True), mock.patch.object(
            asr_mod, "_url_reachable", return_value=False
        ), mock.patch.object(asr_mod, "_bailian_ready", return_value=False):
            zh_chain = asr_mod.backend_chain("auto", "zh")
            en_chain = asr_mod.backend_chain("auto", "en")
            self.assertEqual(zh_chain[0], "whisper")
            self.assertEqual(en_chain[0], "whisper")

        with mock.patch.object(asr_mod, "_whisper_available", return_value=True), mock.patch.object(
            asr_mod, "_url_reachable", return_value=True
        ), mock.patch.object(asr_mod, "_bailian_ready", return_value=False):
            zh_chain = asr_mod.backend_chain("auto", "zh")
            # whisper 仍优先，local 在后
            self.assertEqual(zh_chain[0], "whisper")
            self.assertIn("local", zh_chain)

        self.assertEqual(asr_mod.backend_chain("bailian", "en")[0], "bailian")
        self.assertEqual(asr_mod.backend_chain("manual", "en"), [])

    def test_run_asr_success_and_placeholder(self):
        sample = "1\n00:00:00,000 --> 00:00:01,000\nHello\n"

        def fake_local(video, srt, lang):
            with open(srt, "w", encoding="utf-8") as f:
                f.write(sample)
            return srt

        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "a.mp4")
            with open(video, "wb") as f:
                f.write(b"\x00")
            out = os.path.join(tmp, "source.srt")
            with mock.patch.dict(
                asr_mod._BACKEND_RUNNERS,
                {
                    "local": fake_local,
                    "firered": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
                    "bailian": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
                    "whisper": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
                },
            ):
                path, backend, logs = asr_mod.run_asr(
                    video_path=video,
                    subtitle_file=out,
                    source_lang="zh",
                    preferred_backend="local",
                )
            self.assertEqual(backend, "local")
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(asr_mod.is_placeholder_srt(path))
            self.assertTrue(any("success" in x for x in logs))

            # all fail -> placeholder
            out2 = os.path.join(tmp, "source2.srt")
            with mock.patch.dict(
                asr_mod._BACKEND_RUNNERS,
                {
                    "local": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
                    "firered": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
                    "bailian": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
                    "whisper": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
                },
            ):
                path2, backend2, logs2 = asr_mod.run_asr(
                    video_path=video,
                    subtitle_file=out2,
                    source_lang="en",
                    preferred_backend="auto",
                )
            self.assertEqual(backend2, "placeholder")
            self.assertTrue(asr_mod.is_placeholder_srt(path2))
            self.assertTrue(any("failed" in x.lower() for x in logs2))

    def test_write_segments_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "a.srt")
            path = asr_mod._write_segments_srt(
                out,
                [
                    {"start": 0.0, "end": 1.2, "text": " Hello "},
                    {"start": 1.2, "end": 2.0, "text": "World"},
                ],
            )
            text = open(path, encoding="utf-8").read()
            self.assertIn("Hello", text)
            self.assertIn("World", text)
            self.assertIn("-->", text)


class TranslateGlossaryPromptTests(unittest.TestCase):
    def test_prompt_contains_glossary(self):
        from app.services.subtitle_corrector import parse_srt_blocks
        from app.services.subtitle_translator import _build_translation_prompt

        blocks = parse_srt_blocks(
            "1\n00:00:00,000 --> 00:00:01,000\nTry Lao Gan Ma\n"
        )
        prompt = _build_translation_prompt(
            blocks,
            "English",
            glossary_block="| 老干妈 | Lao Gan Ma | true |",
        )
        self.assertIn("Lao Gan Ma", prompt)
        self.assertIn("术语表", prompt)


class PipelineSkeletonTests(unittest.TestCase):
    def test_run_with_mocked_llm_and_srt(self):
        from app.services.cross_border import pipeline as cb_pipeline

        sample_srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nHello world this is a test\n\n"
            "2\n00:00:03,000 --> 00:00:06,000\nWe launch a crazy book stunt\n"
        )
        digest_md = "## Meta\n- topic: test\n## High-energy Moments（必须留原片的点）\n1. 00:00:03 — stunt\n"
        copy_txt = "他为了卖书，直接把舞台炸了。这本书到底有多狂？"
        match_json = json.dumps(
            {
                "items": [
                    {
                        "_id": 1,
                        "video_id": 1,
                        "video_name": "demo.mp4",
                        "timestamp": "00:00:00,000-00:00:03,000",
                        "picture": "host talks",
                        "narration": "他为了卖书，直接把舞台炸了。",
                        "OST": 0,
                    },
                    {
                        "_id": 2,
                        "video_id": 1,
                        "video_name": "demo.mp4",
                        "timestamp": "00:00:03,000-00:00:06,000",
                        "picture": "explosion",
                        "narration": "播放原片2",
                        "OST": 1,
                    },
                ]
            },
            ensure_ascii=False,
        )
        title_json = json.dumps(
            {
                "titles": ["炸了", "卖书", "狂"],
                "cover_text": "炸了",
                "description": "desc",
                "tags": ["t"],
                "caption": "",
                "credit_line": "原片来源：demo",
            },
            ensure_ascii=False,
        )

        def fake_generate(prompt: str, system_prompt: str = None):
            p = prompt or ""
            if "Cross-border Source Digest" in p or "Source Digest" in p:
                return digest_md
            if "Localized Narration Copy" in p or "voiceover body" in p.lower():
                return copy_txt
            if "Script Matching" in p or "strict JSON only" in p:
                return match_json
            if "Title Packaging" in p or "title packaging" in p.lower():
                return title_json
            if "Translate the following SRT" in p:
                return sample_srt.replace("Hello", "你好").replace("We launch", "我们搞了")
            return "ok"

        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "demo.mp4")
            with open(video_path, "wb") as f:
                f.write(b"\x00\x00")
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=video_path,
                    style_pack="in_hook_narration",
                    glossary="Hello = 哈喽",
                    mode="narration",
                )
                srt_path = task_store.artifact_path(meta["task_id"], "source.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(sample_srt)
                meta["artifacts"]["source_srt"] = srt_path
                task_store.save_meta(meta)

                with mock.patch.object(cb_pipeline, "_generate_text", side_effect=fake_generate), mock.patch.object(
                    cb_pipeline, "step_translate", side_effect=lambda m: _fake_translate(m, sample_srt)
                ), mock.patch.object(
                    cb_pipeline, "step_tts", side_effect=lambda m: _fake_pass(m, "tts")
                ), mock.patch.object(
                    cb_pipeline, "step_render", side_effect=lambda m: _fake_pass(m, "render")
                ):
                    result = cb_pipeline.run_from(
                        task_store.load_meta(meta["task_id"]),
                        start_step="asr",
                        stop_after=None,
                    )

                self.assertEqual(
                    result["status"],
                    "completed",
                    msg=f"error={result.get('error')} logs={result.get('logs')[-5:]}",
                )
                self.assertTrue(
                    os.path.isfile(task_store.artifact_path(meta["task_id"], "digest.md"))
                )
                self.assertTrue(
                    os.path.isfile(task_store.artifact_path(meta["task_id"], "script.json"))
                )
                self.assertTrue(
                    os.path.isdir(task_store.artifact_path(meta["task_id"], "export"))
                )

    def test_step_asr_uses_router(self):
        from app.services.cross_border import pipeline as cb_pipeline

        sample = "1\n00:00:00,000 --> 00:00:01,000\nHello router\n"
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "v.mp4")
            with open(video, "wb") as f:
                f.write(b"00")
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=video,
                    asr_backend="local",
                )
                meta = task_store.transition(meta, "queued")

                def fake_run_asr(**kwargs):
                    path = kwargs["subtitle_file"]
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(sample)
                    return path, "local", ["trying ASR backend=local", "ASR success via local"]

                with mock.patch.object(asr_mod, "run_asr", side_effect=fake_run_asr):
                    result = cb_pipeline.step_asr(meta)

                self.assertEqual(result["status"], "asr_done")
                self.assertEqual(result["artifacts"]["asr_backend"], "local")
                self.assertIn(
                    "Hello router",
                    task_store.read_text_artifact(result["artifacts"]["source_srt"]),
                )

    def test_step_translate_rejects_placeholder(self):
        from app.services.cross_border import pipeline as cb_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "x.mp4"),
                )
                asr_mod.write_placeholder_srt(
                    task_store.artifact_path(meta["task_id"], "source.srt")
                )
                meta["artifacts"]["source_srt"] = task_store.artifact_path(
                    meta["task_id"], "source.srt"
                )
                meta = task_store.transition(meta, "queued")
                meta = task_store.transition(meta, "asr_running")
                meta = task_store.transition(meta, "asr_done")
                result = cb_pipeline.step_translate(meta)
                self.assertEqual(result["status"], "failed")
                self.assertIn("placeholder", (result.get("error") or {}).get("message", "").lower())

    def test_step_tts_uses_voice_service(self):
        from app.services.cross_border import pipeline as cb_pipeline

        items = [
            {
                "_id": 1,
                "timestamp": "00:00:00,000-00:00:03,000",
                "narration": "这是解说",
                "OST": 0,
            },
            {
                "_id": 2,
                "timestamp": "00:00:03,000-00:00:06,000",
                "narration": "播放原片2",
                "OST": 1,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "v.mp4"),
                    voice_name="zh-CN-XiaoyiNeural",
                    tts_engine="edge_tts",
                )
                task_store.write_json_artifact(
                    meta["task_id"], "script.json", {"items": items}
                )
                meta["artifacts"]["script_json"] = task_store.artifact_path(
                    meta["task_id"], "script.json"
                )
                # advance to match_done
                for st in (
                    "queued",
                    "asr_running",
                    "asr_done",
                    "translate_running",
                    "translate_done",
                    "digest_running",
                    "digest_done",
                    "copy_running",
                    "copy_done",
                    "match_running",
                    "match_done",
                ):
                    meta = task_store.transition(meta, st)

                def fake_voice_tts(**kwargs):
                    path = kwargs["voice_file"]
                    with open(path, "wb") as f:
                        f.write(b"ID3fake")
                    return object()

                with mock.patch(
                    "app.services.voice.tts", side_effect=fake_voice_tts
                ):
                    result = cb_pipeline.step_tts(meta)

                self.assertEqual(result["status"], "tts_done")
                clips = [
                    n
                    for n in os.listdir(result["artifacts"]["tts_dir"])
                    if n.endswith(".mp3")
                ]
                self.assertEqual(len(clips), 1)
                self.assertTrue(
                    os.path.isfile(
                        task_store.artifact_path(meta["task_id"], "tts_manifest.json")
                    )
                )

    def test_normalize_script_items_ost(self):
        from app.services.cross_border.pipeline import _normalize_script_items

        items = _normalize_script_items(
            [
                {"narration": "播放原片x", "OST": 0},
                {"narration": "", "OST": 1},
                {"narration": "正常解说", "OST": 0},
            ],
            "demo.mp4",
        )
        self.assertEqual(items[0]["OST"], 1)
        self.assertTrue(items[1]["narration"].startswith("播放原片"))
        self.assertEqual(items[2]["OST"], 0)
        self.assertEqual(items[2]["narration"], "正常解说")

    def test_fallback_script_items_and_forced_match(self):
        from app.services.cross_border import pipeline as cb_pipeline

        srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nHello book promo\n\n"
            "2\n00:00:03,000 --> 00:00:06,000\nDon't press that button yet\n\n"
            "3\n00:00:06,000 --> 00:00:09,000\nWe will blow up something\n"
        )
        copy = "他为了卖书直接炸了舞台。\n先别按那个按钮。\n整本书都是高能。"
        items = cb_pipeline._fallback_script_items(
            copy, srt, "demo.mp4", target_original_ratio=30
        )
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(any(int(i.get("OST", 0) or 0) == 1 for i in items))
        self.assertTrue(all(i.get("timestamp") for i in items))

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "demo.mp4"),
                )
                task_store.write_text_artifact(meta["task_id"], "source.srt", srt)
                task_store.write_text_artifact(meta["task_id"], "digest.md", "# d\n")
                task_store.write_text_artifact(meta["task_id"], "narration_copy.txt", copy)
                meta["artifacts"]["source_srt"] = task_store.artifact_path(
                    meta["task_id"], "source.srt"
                )
                meta["artifacts"]["digest"] = task_store.artifact_path(
                    meta["task_id"], "digest.md"
                )
                meta["artifacts"]["narration_copy"] = task_store.artifact_path(
                    meta["task_id"], "narration_copy.txt"
                )
                for st in (
                    "queued",
                    "asr_running",
                    "asr_done",
                    "translate_running",
                    "translate_done",
                    "digest_running",
                    "digest_done",
                    "copy_running",
                    "copy_done",
                ):
                    meta = task_store.transition(meta, st)
                # 默认即启发式；无需 LLM
                result = cb_pipeline.step_match(meta)
                self.assertEqual(result["status"], "match_done")
                script_path = result["artifacts"]["script_json"]
                with open(script_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.assertIn(data.get("match_via"), {"heuristic", "heuristic_fallback"})
                self.assertTrue(data.get("items"))


class RenderHelperTests(unittest.TestCase):
    def test_build_tts_results_from_manifest(self):
        from app.services.cross_border import render as render_mod

        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "0001.mp3")
            with open(audio, "wb") as f:
                f.write(b"ID3" + b"\x00" * 20000)
            manifest = os.path.join(tmp, "tts_manifest.json")
            with open(manifest, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "clips": [
                            {
                                "_id": 1,
                                "audio_file": audio,
                                "timestamp": "00:00:00,000-00:00:03,000",
                            }
                        ]
                    },
                    f,
                )
            items = [
                {
                    "_id": 1,
                    "OST": 0,
                    "narration": "hello",
                    "timestamp": "00:00:00,000-00:00:03,000",
                },
                {
                    "_id": 2,
                    "OST": 1,
                    "narration": "播放原片2",
                    "timestamp": "00:00:03,000-00:00:06,000",
                },
            ]
            results = render_mod.build_tts_results_from_manifest(
                items=items, tts_dir=tmp, manifest_path=manifest
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["_id"], 1)
            self.assertGreater(results[0]["duration"], 0)

    def test_step_render_fallback_on_missing_video(self):
        from app.services.cross_border import pipeline as cb_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=os.path.join(tmp, "missing.mp4"),
                )
                task_store.write_json_artifact(
                    meta["task_id"],
                    "script.json",
                    {
                        "items": [
                            {
                                "_id": 1,
                                "OST": 0,
                                "narration": "hi",
                                "timestamp": "00:00:00,000-00:00:02,000",
                            }
                        ]
                    },
                )
                meta["artifacts"]["script_json"] = task_store.artifact_path(
                    meta["task_id"], "script.json"
                )
                for st in (
                    "queued",
                    "asr_running",
                    "asr_done",
                    "translate_running",
                    "translate_done",
                    "digest_running",
                    "digest_done",
                    "copy_running",
                    "copy_done",
                    "match_running",
                    "match_done",
                    "tts_running",
                    "tts_done",
                ):
                    meta = task_store.transition(meta, st)
                result = cb_pipeline.step_render(meta)
                # 失败回退仍标记 render_done，保证流水线可到 packaging
                self.assertEqual(result["status"], "render_done")
                self.assertTrue(
                    any("fallback" in (x.get("message") or "").lower() for x in result.get("logs") or [])
                )


class BurnSubtitleModeTests(unittest.TestCase):
    def test_build_bilingual_srt(self):
        from app.services.cross_border import burn as burn_mod

        src = (
            "1\n00:00:00,000 --> 00:00:02,000\nHello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nWorld\n"
        )
        tgt = (
            "1\n00:00:00,000 --> 00:00:02,000\n你好\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n世界\n"
        )
        merged = burn_mod.build_bilingual_srt(src, tgt, order="target_first")
        self.assertIn("你好", merged)
        self.assertIn("Hello", merged)
        # 目标在前
        hello_pos = merged.index("Hello")
        nihao_pos = merged.index("你好")
        self.assertLess(nihao_pos, hello_pos)

    def test_adaptive_style_portrait(self):
        from app.services.cross_border import burn as burn_mod

        # 竖屏 608x1080：short/46 × cinema0.9 ≈ 12，夹在 12–22
        style = burn_mod.adaptive_style(video_width=608, video_height=1080)
        self.assertTrue(style["is_portrait"])
        self.assertGreaterEqual(style["subtitle_font_size"], 12)
        self.assertLessEqual(style["subtitle_font_size"], 18)
        self.assertAlmostEqual(style["subtitle_font_size"], 12, delta=3)

        # 横屏 1920x1080：h/56 × cinema0.9 ≈ 17，电影更小贴底
        land = burn_mod.adaptive_style(video_width=1920, video_height=1080)
        self.assertFalse(land["is_portrait"])
        self.assertGreaterEqual(land["subtitle_font_size"], 14)
        self.assertLessEqual(land["subtitle_font_size"], 22)
        self.assertAlmostEqual(land["subtitle_font_size"], 17, delta=3)

        style_bi = burn_mod.adaptive_style(
            video_width=608, video_height=1080, bilingual=True
        )
        self.assertLessEqual(
            style_bi["subtitle_font_size"], style["subtitle_font_size"]
        )

        # 默认 cinema；贴底 margin 小、左右有气口
        self.assertEqual(land["style_key"], "cinema")
        self.assertGreaterEqual(land["margin_v"], 8)
        self.assertLessEqual(land["margin_v"], 36)
        self.assertGreaterEqual(land["margin_lr"], 28)
        self.assertLessEqual(land["stroke_width"], 1.0)

        opts = burn_mod.resolve_burn_options(
            {
                "subtitle_font": "simhei.ttf",
                "subtitle_font_size": 0,
                "subtitle_style": "cinema",
                "subtitle_position_key": "bottom",
            },
            video_path="",
        )
        self.assertIn("subtitle_font_size", opts)
        self.assertGreater(opts["subtitle_font_size"], 0)
        self.assertLessEqual(opts["subtitle_font_size"], 22)
        self.assertEqual(opts["subtitle_position"], "bottom")
        self.assertIn("ass_margin_v", opts)
        self.assertGreater(opts["ass_margin_v"], 0)
        self.assertIn("ass_margin_lr", opts)
        # 旧默认 48/64 且未手动设定 → 走自适应
        opts_legacy = burn_mod.resolve_burn_options(
            {"subtitle_font_size": 48, "subtitle_font_size_user_set": False},
            video_path="",
        )
        self.assertNotEqual(opts_legacy["subtitle_font_size"], 48)
        self.assertLessEqual(opts_legacy["subtitle_font_size"], 28)

    def test_mask_bar_options(self):
        from app.services.cross_border import burn as burn_mod

        region = burn_mod.build_mask_region_options(
            side="bottom", height_percent=16, color="black"
        )
        self.assertTrue(region["subtitle_mask_enabled"])
        self.assertEqual(region["subtitle_mask_mode"], "solid")
        self.assertEqual(region["subtitle_mask_side"], "bottom")
        self.assertEqual(region["subtitle_mask_landscape_height_percent"], 16)
        self.assertAlmostEqual(region["subtitle_mask_landscape_y_percent"], 84.0)
        self.assertEqual(region["subtitle_mask_landscape_blur_radius"], 0)
        self.assertEqual(region["subtitle_mask_landscape_opacity_percent"], 100)

        top = burn_mod.build_mask_region_options(
            side="top", height_percent=12, color="translucent"
        )
        self.assertEqual(top["subtitle_mask_side"], "top")
        self.assertEqual(top["subtitle_mask_landscape_y_percent"], 0.0)
        self.assertEqual(top["subtitle_mask_landscape_height_percent"], 12)
        self.assertEqual(top["subtitle_mask_landscape_opacity_percent"], 72)

        # 关闭遮罩
        opts_off = burn_mod.resolve_burn_options(
            {"subtitle_mask_enabled": False, "subtitle_style": "cinema"},
            video_path="",
        )
        self.assertFalse(opts_off["subtitle_mask_enabled"])

        # 底部遮罩 + 字幕叠在条上 → 贴底 margin 落在条内
        opts_on = burn_mod.resolve_burn_options(
            {
                "subtitle_mask_enabled": True,
                "subtitle_mask_side": "bottom",
                "subtitle_mask_color": "black",
                "subtitle_mask_height_percent": 14,
                "subtitle_on_mask": True,
                "subtitle_position_key": "bottom",
            },
            video_path="",
        )
        self.assertTrue(opts_on["subtitle_mask_enabled"])
        self.assertEqual(opts_on["subtitle_mask_mode"], "solid")
        self.assertEqual(opts_on["subtitle_mask_side"], "bottom")
        self.assertTrue(opts_on.get("subtitle_on_mask"))
        self.assertEqual(opts_on["subtitle_position"], "bottom")
        self.assertGreater(opts_on["ass_margin_v"], 0)
        self.assertEqual(opts_on["subtitle_mask_landscape_height_percent"], 14.0)

        # 不叠在条上：margin 应抬高到遮罩外
        opts_off_text = burn_mod.resolve_burn_options(
            {
                "subtitle_mask_enabled": True,
                "subtitle_mask_side": "bottom",
                "subtitle_mask_height_percent": 14,
                "subtitle_on_mask": False,
            },
            video_path="",
        )
        self.assertGreater(
            opts_off_text["ass_margin_v"], opts_on["ass_margin_v"]
        )

        # 顶部遮罩 + 叠在条上
        opts_top = burn_mod.resolve_burn_options(
            {
                "subtitle_mask_enabled": True,
                "subtitle_mask_side": "top",
                "subtitle_mask_height_percent": 12,
                "subtitle_on_mask": True,
            },
            video_path="",
        )
        self.assertEqual(opts_top["subtitle_position"], "top")
        self.assertEqual(opts_top["ass_alignment"], 8)

        # 高度夹紧
        self.assertEqual(
            burn_mod._clamp_mask_height(3), burn_mod.MASK_HEIGHT_MIN
        )
        self.assertEqual(
            burn_mod._clamp_mask_height(99), burn_mod.MASK_HEIGHT_MAX
        )

    def test_subtitle_mode_pipeline_to_burn(self):
        from app.services.cross_border import pipeline as cb_pipeline

        sample_srt = (
            "1\n00:00:00,000 --> 00:00:03,000\nHello world\n\n"
            "2\n00:00:03,000 --> 00:00:06,000\nSecond line\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "demo.mp4")
            with open(video_path, "wb") as f:
                f.write(b"\x00\x00")
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="inbound",
                    video_path=video_path,
                    mode="subtitle",
                    bilingual=True,
                )
                self.assertEqual(meta.get("mode"), "subtitle")
                srt_path = task_store.artifact_path(meta["task_id"], "source.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(sample_srt)
                meta["artifacts"]["source_srt"] = srt_path
                task_store.save_meta(meta)

                def fake_burn(m):
                    m = task_store.transition(m, "burn_running")
                    out = os.path.join(
                        task_store.artifact_path(m["task_id"], "export"), "output.mp4"
                    )
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with open(out, "wb") as f:
                        f.write(b"\x00" * 2048)
                    m["artifacts"]["output_mp4"] = out
                    m["artifacts"]["burn_srt"] = task_store.artifact_path(
                        m["task_id"], "burn.srt"
                    )
                    task_store.write_text_artifact(
                        m["task_id"], "burn.srt", "1\n00:00:00,000 --> 00:00:01,000\n你好\n"
                    )
                    task_store.save_meta(m)
                    m = task_store.transition(m, "burn_done")
                    return task_store.transition(m, "completed")

                with mock.patch.object(
                    cb_pipeline, "step_translate", side_effect=lambda m: _fake_translate(m, sample_srt)
                ), mock.patch.object(cb_pipeline, "step_burn", side_effect=fake_burn):
                    result = cb_pipeline.run_from(
                        task_store.load_meta(meta["task_id"]),
                        start_step="asr",
                        stop_after=None,
                    )

                self.assertEqual(
                    result["status"],
                    "completed",
                    msg=f"error={result.get('error')} logs={result.get('logs')[-5:]}",
                )
                self.assertTrue(
                    os.path.isfile(result["artifacts"].get("output_mp4") or "")
                )
                # 字幕模式不应生成 digest/script
                self.assertFalse(
                    os.path.isfile(task_store.artifact_path(meta["task_id"], "digest.md"))
                )


def _fake_translate(meta, sample_srt):
    from app.services.cross_border.task_store import (
        save_meta,
        transition,
        write_text_artifact,
    )

    meta = transition(meta, "translate_running")
    path = write_text_artifact(meta["task_id"], "target.srt", sample_srt)
    meta["artifacts"]["target_srt"] = path
    save_meta(meta)
    return transition(meta, "translate_done")


def _fake_pass(meta, step):
    from app.services.cross_border.task_store import artifact_path, save_meta, transition

    meta = transition(meta, f"{step}_running")
    if step == "tts":
        tts_dir = artifact_path(meta["task_id"], "tts")
        os.makedirs(tts_dir, exist_ok=True)
        meta["artifacts"]["tts_dir"] = tts_dir
    if step == "render":
        meta["artifacts"]["output_mp4"] = meta["inputs"].get("video_path") or ""
    save_meta(meta)
    return transition(meta, f"{step}_done")



class UrlDownloadHelperTests(unittest.TestCase):
    def test_is_http_url_and_title(self):
        from app.services.cross_border import url_download as ud

        self.assertTrue(ud.is_http_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
        self.assertTrue(ud.is_http_url("http://example.com/a.mp4"))
        self.assertFalse(ud.is_http_url(""))
        self.assertFalse(ud.is_http_url("ftp://x"))
        self.assertFalse(ud.is_http_url("not a url"))
        self.assertEqual(ud.sanitize_title("Hello:World/Test"), "Hello World Test")
        self.assertEqual(ud.sanitize_title(""), "downloaded_video")

    def test_format_selector_contains_height(self):
        from app.services.cross_border import url_download as ud

        sel = ud._format_selector(720)
        self.assertIn("height<=720", sel)
        self.assertIn("mp4", sel)

    def test_download_invalid_url_and_missing_ytdlp(self):
        from app.services.cross_border import url_download as ud

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "source.mp4")
            with self.assertRaises(ud.UrlDownloadError):
                ud.download_url_to_file("not-a-url", out)
            with mock.patch.object(ud, "yt_dlp_available", return_value=False):
                with self.assertRaises(ud.UrlDownloadError) as ctx:
                    ud.download_url_to_file("https://example.com/v", out)
                self.assertIn("yt-dlp", str(ctx.exception).lower())

    def test_download_success_with_mocked_ytdlp(self):
        import sys
        import types
        from app.services.cross_border import url_download as ud

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "source.mp4")
            # download_url_to_file creates work_dir under out's parent
            work_dir = os.path.join(tmp, "_url_dl")

            class FakeYDL:
                def __init__(self, opts):
                    self.opts = opts

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def extract_info(self, url, download=True):
                    os.makedirs(work_dir, exist_ok=True)
                    media = os.path.join(work_dir, "media.mp4")
                    with open(media, "wb") as f:
                        f.write(b"\x00" * 4096)
                    return {
                        "title": "Demo: Title/OK",
                        "webpage_url": url,
                        "extractor": "fake",
                        "requested_downloads": [{"filepath": media}],
                    }

            fake_mod = types.SimpleNamespace(YoutubeDL=FakeYDL)
            with mock.patch.dict(sys.modules, {"yt_dlp": fake_mod}), mock.patch.object(
                ud, "yt_dlp_available", return_value=True
            ), mock.patch.object(ud, "_probe_video_codec", return_value="h264"):
                result = ud.download_url_to_file(
                    "https://example.com/watch?v=1",
                    out,
                    prefer_h264=True,
                )
            self.assertTrue(os.path.isfile(result["path"]))
            self.assertEqual(result["title"], "Demo Title OK")
            self.assertFalse(result["transcoded"])
            self.assertEqual(result["extractor"], "fake")


class DubbingModuleTests(unittest.TestCase):
    def test_voices_normalize_and_defaults(self):
        from app.services.cross_border.dubbing import voices as voices_mod

        self.assertEqual(voices_mod.normalize_lang("zh-CN"), "zh")
        self.assertEqual(voices_mod.normalize_lang("EN_us"), "en")
        self.assertEqual(voices_mod.normalize_lang("xx", fallback="ja"), "ja")
        self.assertTrue(voices_mod.default_voice_for_lang("ja").startswith("ja-"))
        self.assertIn("Guy", voices_mod.default_voice_for_lang("en", gender="male"))
        codes = [c for c, _ in voices_mod.lang_choices_for_ui()]
        self.assertIn("zh", codes)
        self.assertIn("ko", codes)
        # 音色必须对应目标语：中文目标 + 英文音色 → 纠正
        v, corrected = voices_mod.resolve_voice_for_lang(
            "zh", "en-US-JennyNeural", gender="female"
        )
        self.assertTrue(corrected)
        self.assertTrue(v.startswith("zh-"))
        v2, c2 = voices_mod.resolve_voice_for_lang(
            "en", "en-US-JennyNeural", gender="female"
        )
        self.assertFalse(c2)
        self.assertEqual(v2, "en-US-JennyNeural")
        self.assertEqual(voices_mod.voice_lang("ja-JP-NanamiNeural"), "ja")

    def test_parse_srt_cues(self):
        from app.services.cross_border.dubbing import synthesize as synth_mod

        text = (
            "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n"
            "2\n00:00:02,000 --> 00:00:03,000\nWorld\nline2\n"
        )
        cues = synth_mod.parse_srt_cues(text)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]["text"], "Hello")
        self.assertEqual(cues[1]["text"], "World line2")
        self.assertAlmostEqual(cues[0]["end"], 1.5)
        self.assertEqual(synth_mod.parse_srt_cues(""), [])

    def test_create_task_dubbing_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="outbound",
                    video_path=os.path.join(tmp, "a.mp4"),
                    mode="dubbing",
                    target_lang="ja",
                    separate_backend="duck",
                    duck_gain=0.2,
                    voice_gender="male",
                    burn_after_mix=True,
                )
                self.assertEqual(meta["mode"], "dubbing")
                self.assertEqual(meta["inputs"]["mode"], "dubbing")
                self.assertEqual(meta["inputs"]["separate_backend"], "duck")
                self.assertAlmostEqual(meta["inputs"]["duck_gain"], 0.2)
                self.assertEqual(meta["inputs"]["voice_gender"], "male")
                self.assertTrue(meta["inputs"]["burn_after_mix"])
                self.assertIn("dubbed_mp4", meta["artifacts"])

    def test_dubbing_pipeline_handlers_mocked(self):
        from app.services.cross_border import pipeline as cb_pipeline

        sample_srt = (
            "1\n00:00:00,000 --> 00:00:02,000\n你好世界\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\n第二句\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "demo.mp4")
            with open(video_path, "wb") as f:
                f.write(b"\x00" * 2048)
            with mock.patch.object(task_store, "tasks_root", return_value=tmp):
                meta = task_store.create_task(
                    direction="outbound",
                    video_path=video_path,
                    mode="dubbing",
                    target_lang="en",
                    separate_backend="duck",
                )
                srt_path = task_store.artifact_path(meta["task_id"], "source.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(sample_srt)
                meta["artifacts"]["source_srt"] = srt_path
                task_store.save_meta(meta)

                def fake_separate(m):
                    m = task_store.transition(m, "separate_running")
                    audio_dir = task_store.artifact_path(m["task_id"], "audio")
                    os.makedirs(audio_dir, exist_ok=True)
                    for name in ("source.wav", "vocals.wav", "no_vocals.wav"):
                        p = os.path.join(audio_dir, name)
                        with open(p, "wb") as f:
                            f.write(b"RIFF" + b"\x00" * 100)
                        m["artifacts"][name.replace(".wav", "_wav")] = p
                    m["artifacts"]["separate_backend"] = "duck"
                    task_store.save_meta(m)
                    return task_store.transition(m, "separate_done")

                def fake_dub_tts(m):
                    m = task_store.transition(m, "dub_tts_running")
                    dub_dir = task_store.artifact_path(m["task_id"], "dub")
                    os.makedirs(dub_dir, exist_ok=True)
                    voice = os.path.join(dub_dir, "dub_voice.wav")
                    with open(voice, "wb") as f:
                        f.write(b"RIFF" + b"\x00" * 100)
                    m["artifacts"]["dub_voice_wav"] = voice
                    task_store.save_meta(m)
                    return task_store.transition(m, "dub_tts_done")

                def fake_mix(m):
                    m = task_store.transition(m, "mix_running")
                    dub_dir = task_store.artifact_path(m["task_id"], "dub")
                    os.makedirs(dub_dir, exist_ok=True)
                    mixed = os.path.join(dub_dir, "mixed.wav")
                    dubbed = os.path.join(dub_dir, "dubbed.mp4")
                    with open(mixed, "wb") as f:
                        f.write(b"RIFF" + b"\x00" * 100)
                    with open(dubbed, "wb") as f:
                        f.write(b"\x00" * 2048)
                    m["artifacts"]["mixed_wav"] = mixed
                    m["artifacts"]["dubbed_mp4"] = dubbed
                    task_store.save_meta(m)
                    return task_store.transition(m, "mix_done")

                def fake_burn(m):
                    m = task_store.transition(m, "burn_running")
                    out = os.path.join(
                        task_store.artifact_path(m["task_id"], "export"), "output.mp4"
                    )
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with open(out, "wb") as f:
                        f.write(b"\x00" * 2048)
                    m["artifacts"]["output_mp4"] = out
                    task_store.save_meta(m)
                    m = task_store.transition(m, "burn_done")
                    return task_store.transition(m, "completed")

                # 并行路径会直调 demucs/TTS，单测 mock 逐步 handler 时关闭并行
                with mock.patch.dict(
                    os.environ, {"CROSS_BORDER_DUB_PARALLEL": "0"}, clear=False
                ), mock.patch.object(
                    cb_pipeline,
                    "step_translate",
                    side_effect=lambda m: _fake_translate(m, sample_srt),
                ), mock.patch.object(
                    cb_pipeline, "step_separate", side_effect=fake_separate
                ), mock.patch.object(
                    cb_pipeline, "step_dub_tts", side_effect=fake_dub_tts
                ), mock.patch.object(
                    cb_pipeline, "step_mix", side_effect=fake_mix
                ), mock.patch.object(
                    cb_pipeline, "step_burn", side_effect=fake_burn
                ):
                    result = cb_pipeline.run_from(
                        task_store.load_meta(meta["task_id"]),
                        start_step="asr",
                        stop_after=None,
                    )

                self.assertEqual(
                    result["status"],
                    "completed",
                    msg=f"error={result.get('error')} logs={result.get('logs')[-8:]}",
                )
                self.assertEqual(result.get("mode"), "dubbing")
                self.assertTrue(
                    os.path.isfile(result["artifacts"].get("output_mp4") or "")
                )
                self.assertTrue(
                    os.path.isfile(result["artifacts"].get("dubbed_mp4") or "")
                )


if __name__ == "__main__":
    unittest.main()
