# NarratoAI 跨境本地化解说 — 项目介绍与开发接手提示词

> 更新时间：2026-07-25  
> 用途：新开 Claude / 开发会话时，把本文整段或「开发提示词」一节贴进去即可快速接手。

---

## 一、项目一句话

**NarratoAI** 是开源的影视/短剧 AI 解说文案 + 自动剪辑工具（Streamlit WebUI）。  
我们在其之上做二开：**跨境视频本地化**，支持 **en↔zh 双向**（配音模式可扩多语），三种模式：

| 模式 | 路径 | 类比 |
|------|------|------|
| **subtitle（默认）** | ASR → 翻译 → 硬烧字幕 | [VideoLingo](https://github.com/Huanshere/VideoLingo) |
| **dubbing（实验）** | ASR → 翻译 → 人声分离 → 目标语 TTS → 混音 → 烧字幕 | 多语配音 / 换声 |
| **narration（高级）** | ASR → 翻译 → digest → 文案 → 匹配 → TTS → 成片 | 解说文案工厂 |

| 方向 | 含义 | 典型场景 |
|------|------|----------|
| **Inbound 引入** | 目标为中文（如 en/ja/ko → zh） | 抖音/B站搬运本地化 |
| **Outbound 出海** | 源为中文或目标非中文（如 zh→en/ja，en→ja） | TikTok/YouTube 出海 |

**字幕本地化已支持多语**（不仅 en↔zh）：UI「② 语对」可选日/韩/西/法/德等；翻译 LLM 使用目标语本名（如 `日本語`）；ASR 按 `source_lang` 提示 whisper。  
默认产品路径：**翻译 + 烧字幕**（保留原声）。解说文案工厂为可选高级模式。

---

## 二、仓库与分支

| 项 | 值 |
|----|-----|
| 本地路径 | `D:\zhuomian\Github\NarratoAI` |
| 上游 origin | `https://github.com/linyqh/NarratoAI.git`（**不要擅自 push**） |
| 用户 fork | `https://github.com/a-hi1/NarratoAI.git`（remote 名：`fork`） |
| 功能分支 | `feat/cross-border-narration-mvp` |
| 基线 commit | `a9e17d0`（upstream main，含 Sonilo SFX） |
| 最新功能提交 | `097e708` W5 成片渲染 |

```bash
# 推送到 fork（正确）
git push fork feat/cross-border-narration-mvp

# 禁止默认推 upstream，除非用户明确要求
# git push origin ...
```

**不要提交：** `config.toml`（含 API Key）、`build.log`、`resource/scripts/测试_*`、`resource/videos/测试.srt`。

---

## 三、8 周路线图与当前进度

| 周 | 目标 | 状态 |
|----|------|------|
| **W1** | 任务目录 + 状态机 + LLM 步骤 + Streamlit 入口 | ✅ `264da51` |
| **W2** | ASR 路由 + 翻译术语表 + 字幕 UI | ✅ `e8543b1` |
| **W3** | 文案层 In/Out + 6 风格包 + copy 审核门 | ✅（合在 W1） |
| **W4** | 脚本匹配 OST + TTS（voice 服务） | ✅ `e8543b1` |
| **W5** | 真成片 render + 包装导出 | ✅ `097e708` |
| **W6** | 稳态：重试/超时/错误步保留/LLM 回退 | 🟡 进行中（失败步保留 + LLM 重试 + match 启发式 + UI 加固 + **默认字幕本地化模式**；压测/超时可视化未做） |
| **W7** | 真片 In+Out 打磨 prompt / 风格 | ⬜ 未做 |
| **W8** | 商业化包装 | ⬜ 未做 |

**已验证：** Inbound 真片 E2E（`测试.mp4` + 上传 SRT）可跑到 `completed`，成片在 `export/output.mp4`。  
match 在 LLM 不稳时可用 `CROSS_BORDER_MATCH_FALLBACK=1` 强制启发式，或自动回退。

**建议下一优先级：**  
1）Outbound 一条完整验证（中文片 → 英文解说）  
2）W6 剩余：任务列表体验 / 超时可视化 / 压测  
3）W7 真片 prompt / 风格打磨

---

## 四、流水线状态机

### 字幕本地化（mode=subtitle，默认，仿 VideoLingo）

```
draft → queued
  → asr_running → asr_done
  → translate_running → translate_done
  → burn_running → burn_done
  → completed
  ↘ failed（可从失败步重试）
```

### 多语配音（mode=dubbing，实验）

```
draft → queued
  → asr_running → asr_done
  → translate_running → translate_done
  → separate_running → separate_done   # demucs / center_cancel / duck
  → dub_tts_running → dub_tts_done     # 目标字幕逐句 TTS → 时间轴
  → mix_running → mix_done             # 伴奏 + 配音 → dubbed.mp4
  → burn_running → burn_done           # 在 dubbed.mp4 上烧目标字幕
  → completed
  ↘ failed（可从失败步重试）
```

### 解说文案工厂（mode=narration）

```
draft → queued
  → asr_running → asr_done
  → translate_running → translate_done
  → digest_running → digest_done
  → copy_running → copy_done          ← 人工门（HUMAN_GATE）
  → match_running → match_done
  → tts_running → tts_done
  → render_running → render_done
  → packaging_running → packaging_done
  → completed
  ↘ failed（可从失败步重试）
```

- 字幕模式：后台默认跑完全程；可改 target.srt 后点「继续烧字幕」。
- 配音模式：后台默认跑完全程；可改字幕后「继续配音」；详情可换音色重配 / 重分离 / 重混。
- 解说模式：默认 `stop_after="copy"`，审核后再点「继续匹配成片」。
- 任务落盘：`storage/tasks/cross_border/{task_id}/meta.json` + 各 artifact。
- 后台：线程 + 文件轮询（避免 Streamlit 同步阻塞 / removeChild）。

---

## 五、关键代码地图

```
app/services/cross_border/
  state_machine.py   # 状态转移、进度、HUMAN_GATES；steps_for_mode(subtitle|dubbing|narration)
  style_packs.py     # 6 套风格包（3 In + 3 Out）
  glossary.py        # 术语解析 / prompt 注入 / 锁定替换
  compliance.py      # OST 占比、改造度粗分
  task_store.py      # create/load/save/list、artifact IO；mode/bilingual/dubbing 字段
  asr.py             # FunASR local/firered/bailian + whisper 回退
  burn.py            # 双语 SRT 合并 + 硬烧（复用 generate_video.merge_materials）
  pipeline.py        # step_* + run_from + 后台线程（含 step_burn / separate / dub_tts / mix）
  render.py          # clip/merge 成片（解说模式）
  packaging.py       # 标题包装 + export bundle
  dubbing/           # 多语配音独立模块
    voices.py        # 多语 Edge 音色 + 语种白名单
    separate.py      # demucs / center_cancel / duck 人声分离
    synthesize.py    # 目标 SRT → 逐句 TTS → 时间轴音轨
    mix.py           # 伴奏+配音混音、mux 回视频
  __init__.py

app/services/prompts/cross_border_narration/
  source_digest.py / narration_copy.py / script_matching.py / title_packaging.py
  → 在 app/services/prompts/__init__.py 的 initialize_prompts() 注册

webui/components/cross_border_panel.py   # 新建 / 详情 / 列表（默认字幕模式；可选链接下载）
webui.py                                 # 主界面下方挂载面板
webui/styles.py                          # 整站 UI 设计系统

app/services/cross_border/url_download.py  # yt-dlp 链接取片 → source.mp4（尽量 H.264）
app/services/test_cross_border_unittest.py  # 单测（mock LLM/ASR/burn/url 下载）
```

### 复用的主站能力（不要重复造轮子）

| 能力 | 入口 |
|------|------|
| LLM | `UnifiedLLMService` + `migration_adapter._run_async_safely` |
| 字幕翻译 | `app.services.subtitle_translator`（已支持 `glossary_block`） |
| ASR | `app.services.fun_asr_subtitle` + `config.fun_asr` |
| TTS | `app.services.voice.tts`（失败回退 edge-tts） |
| 成片 | `clip_video.clip_video_unified` → `audio_merger` → `merger_video.combine_clip_videos` → `generate_video.merge_materials` |
| 脚本字段 | `_id, video_id, video_name, timestamp, picture, narration, OST` |

### 风格包 ID

- In：`in_hook_narration`（默认）、`in_roast_fast`、`in_calm_explain`
- Out：`out_clean_explain`（默认）、`out_native_creator`、`out_brand_demo`

### ASR 后端（字幕从哪来）

**可以不传字幕文件。** 只上传视频时，pipeline 会自动 ASR 生成 `source.srt`：

`auto | whisper | local | firered | bailian | manual`

- **`auto`（默认）**：优先内置 **faster-whisper**（已写入 requirements，首次会下载 `base` 模型）→ 本地 FunASR/FireRed（仅服务可达时）→ 百炼（有 api_key 时）
- **`whisper`**：强制 faster-whisper / openai-whisper
- **`local` / `firered`**：本机 FunASR 服务（默认 7860 / 7867）
- **`manual`**：必须上传 srt，否则写占位

大文件加速（默认已开）：
1. 上传流式写盘（8MB chunk，不 `getbuffer` 整文件进内存）
2. ASR 先 ffmpeg 抽 16k mono wav，再喂 whisper（避免整段视频解码）
3. 默认模型 `base` + `beam_size=1` + VAD 跳静音；有 CUDA 自动用 GPU

环境变量：
- `CROSS_BORDER_WHISPER_MODEL=tiny|base|small|medium`（默认 `base`）
- `CROSS_BORDER_WHISPER_DEVICE=cpu|cuda|auto`
- `CROSS_BORDER_WHISPER_BEAM=1..5`（默认 1）
- `CROSS_BORDER_WHISPER_COMPUTE=int8|float16`

烧录样式（`burn.py`，默认**电影字幕·更小**）：
- 自适应字号：横屏 `h/56`（1080p≈19，cinema×0.9≈17），竖屏 `short/46`（608≈13）；更小、贴底、细描边
- 左右边距约 5% 宽；底部 MarginV 约 1.8% 高
- 默认预设 `cinema`；另有 `clean` / `netflix` / `soft` / `boxed` / `yellow`
- 位置：`bottom` / `bottom_high` / `center` / `top`
- 字号档：`auto` / `small`(0.82) / `medium` / `large` / 手动
- **原片硬字幕遮罩条（手动）**：`subtitle_mask_enabled` + `side`(bottom/top) + `height%` + `color`(black/translucent) + `subtitle_on_mask`；burn 时 ffmpeg `drawbox` 盖住原字幕区再烧译文（不识别、不擦除）
- UI：新建默认电影字幕；详情「改样式后重烧」只重 burn
- 默认编码器 `libx264`
- **实时字幕节点**：翻译时按批次增量写 `target.srt`（未译条目暂显 `… 原文`）；详情页用 `st.fragment(run_every=2s)` 局部刷新源/目标节点卡片，不整页 auto-rerun
  - `meta.translate_progress = {completed,total,percent,message}`
  - 状态条进度在 translate 阶段约 22–40% 随批次推进

### 多语配音（mode=dubbing）要点

链路：`asr → translate → separate → dub_tts → mix → burn`

| 步骤 | 产物 | 说明 |
|------|------|------|
| separate | `audio/{source,vocals,no_vocals}.wav` | `auto`：优先 demucs 真分离 → center_cancel → duck |
| dub_tts | `dub/dub_voice.wav` + `dub/tts_lines/*.mp3` | 读 `target.srt`；句级 atempo 拟合槽位 + 淡入淡出 |
| mix | `dub/mixed.wav` + `dub/dubbed.mp4` | 人声压缩 + sidechain 压伴奏 + loudnorm -16 LUFS |
| burn | `export/output.mp4` | **烧在 dubbed.mp4 上**（已换音轨） |

- **人声分离（真分离已可用）**：venv 已装 `torch 2.13+cpu` + `demucs 4.1`。`auto` 优先 demucs。CPU 较慢；首次会下载 htdemucs 模型。
  - 重装：`pip install torch --index-url https://download.pytorch.org/whl/cpu` 再 `pip install demucs`
- **语种-音色对齐**：`resolve_voice_for_lang` 强制 Edge 音色与目标语一致（错配自动换成该语默认声）
- **配音质感**：句级 atempo 拟合字幕槽 + 淡入淡出 + 尾部 pad；混音 sidechain + 压缩 + loudnorm
- **混音默认音量（重要）**：伴奏 `0.55` / 配音 `1.8`。旧默认 0.9/1.15 会把中文 TTS 盖成「只有背景音」。
  - sidechain 必须用 `asplit` 分叉人声标签，不能同一 `[vc]` 既喂 sidechain 又 amix
  - 旧任务重混时若仍是 0.9/1.15，pipeline 会自动抬到 0.55/1.8
- **速度（长片重点）**：
  - **`separate` ∥ `dub_tts` 并行**（默认开）：wall-clock ≈ max(分离, 配音)。`CROSS_BORDER_DUB_PARALLEL=0` 可关
  - `dub_tts`：Edge/Azure 默认 **3 路**（过高易限流），豆包等云端默认 **4 路**，本地克隆串行。`CROSS_BORDER_TTS_WORKERS=1..16`
  - 句数上限默认 **2000**（旧 200 会截长片）；`CROSS_BORDER_TTS_MAX_SEGMENTS`
  - fit 阶段并行 ffmpeg：`CROSS_BORDER_TTS_FIT_WORKERS`（默认约 cpu/3，≤6）
  - 已生成 `dub/tts_lines/*.mp3`、已 fit 的 wav、已有 `vocals/no_vocals` **可复用**
  - demucs CPU 默认 `-j≈cpu/4`（上限 4）；`CROSS_BORDER_DEMUCS_JOBS` / `CROSS_BORDER_DEMUCS_DEVICE=cpu|cuda` / `CROSS_BORDER_DEMUCS_SEGMENT`
  - 混音默认 `dynaudnorm`（比 loudnorm 快）；要经典响度归一设 `CROSS_BORDER_MIX_LOUDNORM=1`
  - **17 分钟+ 真分离在 CPU 上仍可能 30–90 分钟**：要快可选 `center_cancel` / `duck`（秒～分钟级）
- **多语**：`dubbing/voices.py` 内置 15 语默认 Edge 音色 + 引擎/预设列表（Edge 中英日韩、豆包 BV*）
- **inputs 字段**：`separate_backend` / `duck_gain` / `instrumental_volume` / `dub_voice_volume` / `voice_gender` / `burn_after_mix` / `sidechain_duck` / `tts_engine` / `voice_name` / `voice_rate` / `voice_pitch`
- **UI**：新建「多语配音」展开 **④ 配音与字幕样式**（引擎/性别/预设/音色 ID/语速音调/分离混音）；高级只改目标语种；详情可换音色重配 / 重分离 / 重混
- **自定义音色（规划）**：上传参考 wav + IndexTTS/IndexTTS2 克隆，当前未做上传入口，可选引擎 `indextts` 并手填参考路径
- **限制（已知）**：CPU demucs 仍慢；sidechain 依赖 ffmpeg；TTS 句数默认截断 200；翻译质量仍偏 en↔zh

---

## 六、本地运行

```bash
cd D:/zhuomian/Github/NarratoAI
# 使用项目 venv（系统 Python 可能缺 loguru）
.venv/Scripts/python webui.py
# 或项目既有启动方式

# 单测
.venv/Scripts/python -m unittest app.services.test_cross_border_unittest -v
```

配置：`config.toml`（参考 `config.example.toml` 的 `[fun_asr]`、TTS、文本 LLM）。  
**切勿把真实 Key 提交进 git。**

WebUI（中文优先，工作流 Tab，扁平浅色设计系统）：
- **影视 / 短剧解说** — 脚本 · 配音 · 画面字幕 + 底部「成片与导出」
- **跨境本地化** — 新建（本地上传 / **链接下载**） / 详情（彩色步骤条 + 状态卡） / 任务列表
- **基础与系统** — 语言、模型、代理、系统设置

设计系统：`webui/styles.py` + `.streamlit/config.toml` 浅色主题（primary `#2563EB`）。

链接下载（可选）：`app/services/cross_border/url_download.py` 基于 **yt-dlp**，默认落 `source.mp4` 并尽量转 H.264+AAC；依赖 `requirements.txt` 中的 `yt-dlp`；国内访问 YouTube 需在设置开启代理。本地上传路径不变。

默认界面语言 `zh`；`page_title` 为「NarratoAI 影视解说工坊」。

---

## 七、设计原则（改代码时遵守）

1. **本地化 ≠ 翻译**：digest → 风格化解说文案 → 时间轴匹配 → TTS → 按 OST 剪辑。  
2. **可插拔降级**：ASR/TTS/render 缺依赖时写占位/回退，尽量不把整条流水线打死（占位字幕在 translate 前会 fail 并提示上传）。  
3. **人工门在 copy_done**：默认停在解说文案审核。  
4. **handler 动态查找**：`run_from` 用 `globals().get(f"step_{step}")`，方便单测 mock。  
5. **不污染上游**：只 push `fork`；功能独立模块，少改主站核心。  
6. **脚本 JSON 兼容主站**：字段与短剧/影视解说一致，便于复用 clip/tts。  
7. **OST 约定**：`narration` 以 `播放原片` 开头 → 强制 `OST=1`；成片时 OST=1 保原声，OST=0 用 TTS 时长裁切。

---

## 八、已知坑

- 系统 Python 无依赖 → 必须用 `.venv/Scripts/python`。  
- `origin` 是上游，`fork` 才是用户仓库。  
- `gh` 可能未登录；HTTPS push 若失败让用户 `! gh auth login`。  
- 真实 LLM Key 可能 401（`API_KEY_DISABLED`）或 Connection error；单测必须 mock `_generate_text`。  
- `pipeline._ensure_llm_providers` 必须从 `app.services.llm.providers` 导入（不是 `app.services.llm`）。  
- failed 后 `error.step` 必须保留失败步；`queued` 允许进入任意 `*_running` 以便中途重试。  
- match 提示词长、LLM 易超时 → 自动启发式回退；调试可 `CROSS_BORDER_MATCH_FALLBACK=1`。  
- Streamlit 长任务勿同步阻塞 → 后台线程 + `meta.json` 轮询；**不要**依赖 `streamlit_autorefresh`（未装且易炸 DOM）。  
- **burn WinError 206 / 长片卡 burn_running**：ffmpeg 快路径曾优先 `drawtext`（每条字幕一条滤镜），507 条字幕会把命令行撑爆 → 回退 MoviePy，AV1 长片极慢且易被重启打断。已改为**优先 `subtitles` 滤镜**；drawtext 仅作短字幕回退且 >80 条直接报错。上传视频落盘用 **ASCII 名 `source.ext`**（显示名仍用原文件名），避免中文路径踩 ffprobe。
- **成片打不开/卡住**：imageio 自带 ffmpeg 的 **QSV 硬编**在滤镜链上可能产出坏 NAL（播放器卡死、Invalid NAL unit size）。跨境硬烧默认 **`libx264` 软编**（`inputs.video_encoder` 可覆盖）；编码参数强制 `yuv420p`。  
- render 依赖 ffmpeg；失败时 `step_render` 回退骨架，流水线仍可 packaging。  
- 翻译/API 路径勿把 `config.toml` 打进 commit。

---

## 九、给新对话的「开发提示词」（可直接粘贴）

下面整段复制到新会话即可：

```text
你是 NarratoAI 跨境本地化解说（cross-border narration）功能的开发助手。

## 项目
- 路径：D:\zhuomian\Github\NarratoAI
- 分支：feat/cross-border-narration-mvp
- fork remote：fork → https://github.com/a-hi1/NarratoAI.git
- 上游 origin：https://github.com/linyqh/NarratoAI.git（禁止擅自 push origin）
- 详细接手文档：docs/cross_border_handoff.md

## 产品目标
做 en↔zh 双向「视频本地化工厂」：Inbound(en→zh) / Outbound(zh→en)。
不是纯 MT，而是：ASR → 翻译(术语表) → 源摘要 digest → 风格化解说文案 → 人工审核 → 脚本匹配(OST) → TTS → 成片 → 标题包装导出。

## 代码入口
- 流水线：app/services/cross_border/pipeline.py
- 状态机：state_machine.py
- ASR：asr.py（FunASR local/firered/bailian + whisper）
- 成片：render.py（复用 clip_video / merger_video / generate_video）
- Prompt：app/services/prompts/cross_border_narration/
- UI：webui/components/cross_border_panel.py
- 单测：app/services/test_cross_border_unittest.py（22 tests，用 .venv/Scripts/python 跑）

## 进度
W1–W5 已完成；默认模式已切到 **subtitle（ASR→翻译→硬烧字幕，仿 VideoLingo）**。
解说工厂保留为 mode=narration。W6 部分完成。下一步优先：
1) 字幕模式真片 E2E（上传视频/SRT → completed 带字幕成片）
2) Outbound 字幕/解说验证
3) W6 剩余 / W7 打磨

## 约束
- 匹配现有代码风格；优先复用主站 voice/fun_asr/clip/merge，不重造轮子
- 不提交 config.toml、测试媒体、build.log、API Key
- 只 push fork 分支，除非用户明确要求合上游
- 长任务后台线程 + 文件状态，避免 Streamlit DOM 崩溃
- 改 pipeline 后跑：.venv/Scripts/python -m unittest app.services.test_cross_border_unittest -v

## 任务存储
storage/tasks/cross_border/{task_id}/meta.json
默认在 copy_done 暂停人工审核，再 continue_after_copy。

接手后先读 docs/cross_border_handoff.md 与 pipeline.py 顶部注释，再按用户本轮目标动手；能直接改代码就不要只给方案。
```

---

## 十、给产品/业务向新对话的「介绍提示词」（可选）

```text
NarratoAI 跨境本地化：把海外短视频做成国内平台可播的「本地化解说版」，也可反向出海。
核心差异：不是字幕机翻，而是按平台语气重写解说 + 保留高能原片片段(OST) + 术语锁定 + 人工过文案再成片。
方向：Inbound en→zh（抖音等）、Outbound zh→en（TikTok 等）。
当前工程：Streamlit 面板 + 可落盘任务状态机 + 6 风格包；ASR/TTS/成片已接主站能力，MVP 可跑通到 packaging。
商业化方向：跨境内容工作室 / 代运营工厂，按条或按时长收费；合规上强调改造度与来源声明，非法务结论。
```

---

## 十一、常用命令速查

```bash
cd D:/zhuomian/Github/NarratoAI
git checkout feat/cross-border-narration-mvp
git status
.venv/Scripts/python -m unittest app.services.test_cross_border_unittest -v
git add app/services/cross_border app/services/prompts/cross_border_narration \
  app/services/test_cross_border_unittest.py app/services/subtitle_translator.py \
  webui/components/cross_border_panel.py webui.py webui/components/__init__.py \
  app/services/prompts/__init__.py
# commit 后：
git push fork feat/cross-border-narration-mvp
```
