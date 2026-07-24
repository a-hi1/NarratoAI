# NarratoAI 跨境本地化解说 — 项目介绍与开发接手提示词

> 更新时间：2026-07-24  
> 用途：新开 Claude / 开发会话时，把本文整段或「开发提示词」一节贴进去即可快速接手。

---

## 一、项目一句话

**NarratoAI** 是开源的影视/短剧 AI 解说文案 + 自动剪辑工具（Streamlit WebUI）。  
我们在其之上做二开：**跨境视频本地化工厂**（不是纯机器翻译），支持 **en↔zh 双向**：

| 方向 | 含义 | 典型场景 |
|------|------|----------|
| **Inbound 引入** | 外网英文片 → 中文解说 | 抖音/B站搬运本地化 |
| **Outbound 出海** | 国内中文片 → 英文解说 | TikTok/YouTube 出海 |

产品定位：**带风格包、术语表、原片占比、人工审核门的本地化解说流水线**。

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
| **W6** | 稳态：重试/超时/错误步保留/LLM 回退 | 🟡 进行中（失败步保留 + LLM 重试 + match 启发式回退已落地；压测/列表体验未做） |
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

```
draft → queued
  → asr_running → asr_done
  → translate_running → translate_done
  → digest_running → digest_done
  → copy_running → copy_done          ← 默认人工门（HUMAN_GATE）
  → match_running → match_done
  → tts_running → tts_done
  → render_running → render_done
  → packaging_running → packaging_done
  → completed
  ↘ failed（可从失败步重试）
```

- 默认 `stop_after="copy"`：生成到解说文案后暂停，用户改完再点「继续匹配成片」。
- 任务落盘：`storage/tasks/cross_border/{task_id}/meta.json` + 各 artifact。
- 后台：线程 + 文件轮询（避免 Streamlit 同步阻塞 / removeChild）。

---

## 五、关键代码地图

```
app/services/cross_border/
  state_machine.py   # 状态转移、进度、HUMAN_GATES
  style_packs.py     # 6 套风格包（3 In + 3 Out）
  glossary.py        # 术语解析 / prompt 注入 / 锁定替换
  compliance.py      # OST 占比、改造度粗分
  task_store.py      # create/load/save/list、artifact IO
  asr.py             # FunASR local/firered/bailian + whisper 回退
  pipeline.py        # step_* + run_from + 后台线程
  render.py          # clip/merge 成片
  packaging.py       # 标题包装 + export bundle
  __init__.py

app/services/prompts/cross_border_narration/
  source_digest.py / narration_copy.py / script_matching.py / title_packaging.py
  → 在 app/services/prompts/__init__.py 的 initialize_prompts() 注册

webui/components/cross_border_panel.py   # 新建 / 详情 / 列表
webui.py                                 # 主界面下方挂载面板

app/services/test_cross_border_unittest.py  # 26 个单测（mock LLM/ASR）
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

### ASR 后端

`auto | local | firered | bailian | whisper | manual`  
`auto`：zh 优先 local→firered→bailian→whisper；en 优先 firered→local→bailian→whisper。

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

WebUI（中文优先，工作流 Tab）：
- **🎬 影视 / 短剧解说** — 脚本 · 配音 · 画面字幕 + 底部「成片与导出」
- **🌍 跨境本地化** — 新建 / 详情（步骤条） / 任务列表
- **⚙️ 基础与系统** — 语言、模型、代理、系统设置

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
- Streamlit 长任务勿同步阻塞 → 后台线程 + `meta.json` 轮询（可选 `streamlit_autorefresh`）。  
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
W1–W5 已完成；Inbound 真片 E2E 已跑通 completed。W6 部分完成（失败步保留、LLM 重试、match 启发式回退）。下一步优先：
1) Outbound 真片验证
2) W6 剩余（列表体验/超时可视化）
3) W7 prompt / 风格打磨

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
