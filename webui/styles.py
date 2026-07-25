#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
NarratoAI 整站 UI 设计系统（扁平、浅色、专业工具风）。

目标：美观、信息层级清晰、交互门槛低。
不依赖外网字体；用系统中文字体栈保证国内可读。
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, List, Optional, Sequence, Tuple


# 语义色 token（与 .streamlit/config.toml 对齐）
COLORS = {
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_soft": "rgba(37, 99, 235, 0.10)",
    "accent": "#E11D48",
    "accent_soft": "rgba(225, 29, 72, 0.08)",
    "bg": "#F4F6FA",
    "surface": "#FFFFFF",
    "surface_2": "#F8FAFC",
    "text": "#0F172A",
    "text_secondary": "#475569",
    "text_muted": "#64748B",
    "border": "#E2E8F0",
    "border_strong": "#CBD5E1",
    "success": "#059669",
    "success_soft": "rgba(5, 150, 105, 0.10)",
    "warning": "#D97706",
    "warning_soft": "rgba(217, 119, 6, 0.12)",
    "danger": "#DC2626",
    "danger_soft": "rgba(220, 38, 38, 0.10)",
    "info": "#0284C7",
    "info_soft": "rgba(2, 132, 199, 0.10)",
}


APP_CSS = f"""
<style>
:root {{
  --na-primary: {COLORS["primary"]};
  --na-primary-hover: {COLORS["primary_hover"]};
  --na-primary-soft: {COLORS["primary_soft"]};
  --na-accent: {COLORS["accent"]};
  --na-accent-soft: {COLORS["accent_soft"]};
  --na-bg: {COLORS["bg"]};
  --na-surface: {COLORS["surface"]};
  --na-surface-2: {COLORS["surface_2"]};
  --na-text: {COLORS["text"]};
  --na-text-2: {COLORS["text_secondary"]};
  --na-muted: {COLORS["text_muted"]};
  --na-border: {COLORS["border"]};
  --na-border-strong: {COLORS["border_strong"]};
  --na-success: {COLORS["success"]};
  --na-success-soft: {COLORS["success_soft"]};
  --na-warning: {COLORS["warning"]};
  --na-warning-soft: {COLORS["warning_soft"]};
  --na-danger: {COLORS["danger"]};
  --na-danger-soft: {COLORS["danger_soft"]};
  --na-info: {COLORS["info"]};
  --na-info-soft: {COLORS["info_soft"]};
  --na-radius: 12px;
  --na-radius-sm: 8px;
  --na-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 16px rgba(15, 23, 42, 0.04);
  --na-font: "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans SC",
             "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif;
}}

html, body, [class*="css"] {{
  font-family: var(--na-font) !important;
}}

/* 主区域：更松、更干净 */
.stApp {{
  background: var(--na-bg);
}}
.main .block-container {{
  padding-top: 1.1rem !important;
  padding-bottom: 2.8rem !important;
  padding-left: 1.6rem !important;
  padding-right: 1.6rem !important;
  max-width: 1400px;
}}

/* 顶栏 / hero */
.narrato-hero {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem 1.25rem;
  margin: 0 0 1rem 0;
  padding: 1rem 1.2rem;
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: var(--na-surface);
  box-shadow: var(--na-shadow);
}}
.narrato-hero-brand {{
  display: flex;
  align-items: center;
  gap: 0.85rem;
  min-width: 0;
}}
.narrato-hero-mark {{
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #fff;
  font-weight: 800;
  font-size: 0.95rem;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--na-primary) 0%, #4F46E5 100%);
}}
.narrato-hero-logo {{
  width: 42px;
  height: 42px;
  border-radius: 10px;
  flex: 0 0 auto;
  display: block;
  object-fit: contain;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}}
.narrato-hero-title {{
  font-size: 1.35rem;
  font-weight: 750;
  color: var(--na-text);
  line-height: 1.25;
  margin: 0;
  letter-spacing: -0.01em;
}}
.narrato-hero-title span {{
  color: var(--na-primary);
}}
.narrato-hero-sub {{
  margin: 0.2rem 0 0 0;
  color: var(--na-muted);
  font-size: 0.9rem;
  line-height: 1.45;
}}
.narrato-hero-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}}
.narrato-chip {{
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.22rem 0.6rem;
  border-radius: 999px;
  border: 1px solid var(--na-border);
  background: var(--na-surface-2);
  color: var(--na-text-2);
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1.3;
  white-space: nowrap;
}}
.narrato-chip.primary {{
  border-color: rgba(37, 99, 235, 0.25);
  background: var(--na-primary-soft);
  color: var(--na-primary);
}}

/* 工作流引导 */
.narrato-guide {{
  margin: 0 0 0.95rem 0;
  padding: 0.75rem 0.95rem;
  border: 1px solid var(--na-border);
  border-left: 4px solid var(--na-primary);
  border-radius: 0 var(--na-radius-sm) var(--na-radius-sm) 0;
  background: var(--na-surface);
  color: var(--na-text-2);
  font-size: 0.92rem;
  line-height: 1.55;
}}
.narrato-guide strong {{
  color: var(--na-text);
  font-weight: 700;
}}

/* 分栏标题 */
.narrato-col-title {{
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--na-text);
  margin: 0 0 0.55rem 0;
  padding: 0.45rem 0.65rem;
  border-radius: var(--na-radius-sm);
  background: var(--na-surface);
  border: 1px solid var(--na-border);
}}

/* 底部操作区 */
.narrato-action-bar {{
  margin-top: 1.1rem;
  padding: 1rem 1.05rem 0.55rem;
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: var(--na-surface);
  box-shadow: var(--na-shadow);
}}
.narrato-action-title {{
  font-size: 1.02rem;
  font-weight: 750;
  color: var(--na-text);
  margin: 0 0 0.15rem 0;
}}
.narrato-action-hint {{
  color: var(--na-muted);
  font-size: 0.88rem;
  margin: 0 0 0.7rem 0;
  line-height: 1.5;
}}

/* 卡片 / 区块 */
.narrato-card {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: var(--na-surface);
  padding: 0.9rem 1rem;
  margin: 0 0 0.85rem 0;
  box-shadow: var(--na-shadow);
}}
.narrato-card-title {{
  font-size: 0.98rem;
  font-weight: 750;
  color: var(--na-text);
  margin: 0 0 0.25rem 0;
}}
.narrato-card-desc {{
  color: var(--na-muted);
  font-size: 0.86rem;
  line-height: 1.5;
  margin: 0 0 0.55rem 0;
}}
.narrato-steps {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.15rem 0 0.35rem 0;
}}
.narrato-step {{
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.28rem 0.65rem;
  border-radius: 999px;
  border: 1px solid var(--na-border);
  background: var(--na-surface-2);
  color: var(--na-muted);
  font-size: 0.8rem;
  font-weight: 600;
  line-height: 1.3;
}}
.narrato-step .n {{
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.72rem;
  background: var(--na-border);
  color: var(--na-text-2);
}}
.narrato-step.done {{
  border-color: rgba(5, 150, 105, 0.28);
  background: var(--na-success-soft);
  color: var(--na-success);
}}
.narrato-step.done .n {{
  background: var(--na-success);
  color: #fff;
}}
.narrato-step.run {{
  border-color: rgba(37, 99, 235, 0.3);
  background: var(--na-primary-soft);
  color: var(--na-primary);
}}
.narrato-step.run .n {{
  background: var(--na-primary);
  color: #fff;
}}
.narrato-step.fail {{
  border-color: rgba(220, 38, 38, 0.3);
  background: var(--na-danger-soft);
  color: var(--na-danger);
}}
.narrato-step.fail .n {{
  background: var(--na-danger);
  color: #fff;
}}
.narrato-step.gate {{
  border-color: rgba(217, 119, 6, 0.35);
  background: var(--na-warning-soft);
  color: var(--na-warning);
}}
.narrato-step.gate .n {{
  background: var(--na-warning);
  color: #fff;
}}

/* 状态条 */
.narrato-status {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: var(--na-surface);
  padding: 0.8rem 0.95rem;
  margin: 0 0 0.85rem 0;
}}
.narrato-status-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.75rem;
  align-items: center;
  margin-bottom: 0.35rem;
}}
.narrato-badge {{
  display: inline-flex;
  align-items: center;
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  line-height: 1.35;
  border: 1px solid transparent;
}}
.narrato-badge.ok {{
  background: var(--na-success-soft);
  color: var(--na-success);
  border-color: rgba(5, 150, 105, 0.22);
}}
.narrato-badge.run {{
  background: var(--na-primary-soft);
  color: var(--na-primary);
  border-color: rgba(37, 99, 235, 0.22);
}}
.narrato-badge.fail {{
  background: var(--na-danger-soft);
  color: var(--na-danger);
  border-color: rgba(220, 38, 38, 0.22);
}}
.narrato-badge.wait {{
  background: var(--na-warning-soft);
  color: var(--na-warning);
  border-color: rgba(217, 119, 6, 0.22);
}}
.narrato-badge.idle {{
  background: var(--na-surface-2);
  color: var(--na-text-2);
  border-color: var(--na-border);
}}
.narrato-status-msg {{
  color: var(--na-text-2);
  font-size: 0.9rem;
  line-height: 1.55;
  margin: 0.25rem 0 0 0;
  white-space: pre-wrap;
}}

/* 空状态 */
.narrato-empty {{
  border: 1px dashed var(--na-border-strong);
  border-radius: var(--na-radius);
  background: var(--na-surface);
  padding: 1.4rem 1.1rem;
  text-align: center;
  color: var(--na-muted);
}}
.narrato-empty-title {{
  color: var(--na-text);
  font-weight: 700;
  font-size: 1rem;
  margin: 0 0 0.35rem 0;
}}
.narrato-empty-desc {{
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.55;
}}

/* 简易指标卡 */
.narrato-metrics {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.55rem;
  margin: 0 0 0.85rem 0;
}}
.narrato-metric {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius-sm);
  background: var(--na-surface);
  padding: 0.55rem 0.7rem;
}}
.narrato-metric .k {{
  color: var(--na-muted);
  font-size: 0.75rem;
  font-weight: 600;
  margin: 0 0 0.15rem 0;
}}
.narrato-metric .v {{
  color: var(--na-text);
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0;
  line-height: 1.3;
  word-break: break-word;
}}

/* Tab 更醒目、更像分段导航 */
button[data-baseweb="tab"] {{
  font-weight: 650 !important;
  font-size: 0.95rem !important;
}}
div[data-baseweb="tab-list"] {{
  gap: 0.25rem;
  border-bottom: 1px solid var(--na-border) !important;
  margin-bottom: 0.85rem;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
  color: var(--na-primary) !important;
}}

/* 主按钮可读性 */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {{
  background: var(--na-primary) !important;
  border-color: var(--na-primary) !important;
  font-weight: 650 !important;
}}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover {{
  background: var(--na-primary-hover) !important;
  border-color: var(--na-primary-hover) !important;
}}
.stButton > button {{
  border-radius: 10px !important;
  min-height: 2.5rem;
}}

/* 输入控件圆角统一 */
.stTextInput input, .stTextArea textarea, .stSelectbox [data-baseweb="select"] > div {{
  border-radius: 10px !important;
}}

/* Expander 更像卡片 */
div[data-testid="stExpander"] {{
  border: 1px solid var(--na-border) !important;
  border-radius: var(--na-radius) !important;
  background: var(--na-surface) !important;
  margin-bottom: 0.55rem;
}}
div[data-testid="stExpander"] details summary p {{
  font-weight: 650 !important;
}}

/* 进度条 */
div[data-testid="stProgress"] > div > div {{
  background: var(--na-primary) !important;
}}

/* 侧栏 */
section[data-testid="stSidebar"] {{
  background: var(--na-surface);
  border-right: 1px solid var(--na-border);
}}

/* 生成状态行 */
.narrato-gen-step {{
  font-size: 0.98rem;
  line-height: 1.7;
  margin: 0.18rem 0;
}}
.narrato-gen-step.current {{ color: var(--na-text); font-weight: 700; }}
.narrato-gen-step.done {{ color: var(--na-muted); font-weight: 500; }}
.narrato-gen-step.todo {{ color: #94A3B8; font-weight: 500; }}

/* 降低 markdown 默认间距抖动 */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
  letter-spacing: -0.01em;
}}

/* 字幕节点实时面板 */
.na-cue-panel {{
  background: var(--na-surface);
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  padding: 0.75rem 0.9rem 0.6rem;
  box-shadow: var(--na-shadow);
  margin: 0.35rem 0 0.6rem;
}}
.na-cue-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
  color: var(--na-text);
  font-size: 0.95rem;
}}
.na-cue-sub {{
  color: var(--na-muted);
  font-size: 0.82rem;
  margin-bottom: 0.5rem;
  line-height: 1.45;
}}
.na-cue-list {{
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding-right: 0.15rem;
}}
.na-cue {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius-sm);
  background: var(--na-surface-2);
  padding: 0.45rem 0.55rem;
}}
.na-cue.ready {{
  border-color: rgba(5, 150, 105, 0.28);
  background: var(--na-success-soft);
}}
.na-cue.pending {{
  border-color: rgba(217, 119, 6, 0.28);
  background: var(--na-warning-soft);
}}
.na-cue.idle {{
  color: var(--na-muted);
}}
.na-cue-meta {{
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.75rem;
  color: var(--na-muted);
  margin-bottom: 0.18rem;
}}
.na-cue-id {{
  font-weight: 700;
  color: var(--na-text-2);
  min-width: 2.2rem;
}}
.na-cue-time {{
  font-variant-numeric: tabular-nums;
  flex: 1;
}}
.na-cue-mark {{
  font-weight: 700;
  color: var(--na-success);
}}
.na-cue.pending .na-cue-mark {{
  color: var(--na-warning);
}}
.na-cue-text {{
  color: var(--na-text);
  font-size: 0.9rem;
  line-height: 1.45;
  word-break: break-word;
}}
.na-cue-foot {{
  margin-top: 0.4rem;
  color: var(--na-muted);
  font-size: 0.78rem;
}}

/* 可点击元素 */
button, [role="button"], a {{
  cursor: pointer;
}}

@media (prefers-reduced-motion: reduce) {{
  * {{
    transition: none !important;
    animation: none !important;
  }}
}}
</style>
"""


def inject_global_css() -> None:
    """注入整站 CSS（在 set_page_config 之后调用一次）。"""
    import streamlit as st

    st.markdown(APP_CSS, unsafe_allow_html=True)
    # Streamlit 1.x 在 tabs/复杂树 + rerun 时，浏览器偶发
    # NotFoundError: removeChild（React DOM 差分竞态）。
    # 不影响后台任务，但会弹红框；这里在父页面 patch 掉并隐藏该报错。
    inject_removechild_guard()


def inject_removechild_guard() -> None:
    """
    吞掉 Streamlit 前端 removeChild NotFoundError，避免红框吓人。
    用 components.html 在 iframe 里改写 parent 的 Node.prototype。
    每个 session 只注入一次，避免重复挂 observer。
    """
    import streamlit as st

    if st.session_state.get("_na_removechild_guard"):
        return
    st.session_state["_na_removechild_guard"] = True
    try:
        import streamlit.components.v1 as components
    except Exception:
        return

    # height=0 几乎不占位；script 跑在 iframe，通过 window.parent 改主页面
    components.html(
        """
<script>
(function () {
  try {
    var w = window.parent;
    if (!w || w.__naRemoveChildPatched) return;
    w.__naRemoveChildPatched = true;

    var NodeProto = w.Node.prototype;
    var origRemove = NodeProto.removeChild;
    NodeProto.removeChild = function (child) {
      if (child && child.parentNode !== this) {
        return child;
      }
      try {
        return origRemove.call(this, child);
      } catch (e) {
        if (
          e &&
          (e.name === "NotFoundError" ||
            String(e.message || "").indexOf("removeChild") >= 0)
        ) {
          return child;
        }
        throw e;
      }
    };

    function isRemoveChildNoise(text) {
      if (!text) return false;
      return (
        text.indexOf("removeChild") >= 0 ||
        (text.indexOf("NotFoundError") >= 0 &&
          text.indexOf("Node") >= 0)
      );
    }

    function hideNoiseOverlays() {
      try {
        var doc = w.document;
        var candidates = doc.querySelectorAll(
          '[data-testid="stException"], .stException, ' +
            '[data-testid="stAlert"], [class*="stException"], ' +
            'div[role="alert"]'
        );
        for (var i = 0; i < candidates.length; i++) {
          var n = candidates[i];
          var t = n.innerText || n.textContent || "";
          if (isRemoveChildNoise(t)) {
            n.style.setProperty("display", "none", "important");
            n.setAttribute("data-na-hidden-removechild", "1");
          }
        }
      } catch (_) {}
    }

    try {
      var obs = new w.MutationObserver(function () {
        hideNoiseOverlays();
      });
      if (w.document && w.document.body) {
        obs.observe(w.document.body, { childList: true, subtree: true });
      }
      hideNoiseOverlays();
      // 首屏延迟再扫一次，覆盖晚到的 error boundary
      w.setTimeout(hideNoiseOverlays, 300);
      w.setTimeout(hideNoiseOverlays, 1200);
    } catch (_) {}
  } catch (e) {
    /* ignore */
  }
})();
</script>
        """,
        height=0,
    )


def _resolve_logo_data_uri() -> str:
    """把 resource/public/logo.png 编成 data URI，避免 Streamlit 静态路径问题。"""
    try:
        import base64
        import os

        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "resource", "public", "logo.png"),
            os.path.join(os.getcwd(), "resource", "public", "logo.png"),
        ]
        for path in candidates:
            path = os.path.abspath(path)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return f"data:image/png;base64,{b64}"
    except Exception:
        pass
    return ""


def hero_html(
    *,
    title: str,
    subtitle: str,
    version: str = "",
    chips: Optional[Sequence[str]] = None,
) -> str:
    title_html = escape(title).replace("NarratoAI", "Narrato<span>AI</span>", 1)
    chips = list(chips or [])
    chip_html = "".join(
        f'<span class="narrato-chip{" primary" if i == 0 else ""}">{escape(c)}</span>'
        for i, c in enumerate(chips)
    )
    if version:
        chip_html += f'<span class="narrato-chip">v{escape(str(version))}</span>'
    logo_uri = _resolve_logo_data_uri()
    if logo_uri:
        mark_html = (
            f'<img class="narrato-hero-logo" src="{logo_uri}" '
            f'alt="NarratoAI" width="42" height="42"/>'
        )
    else:
        mark_html = '<div class="narrato-hero-mark">NA</div>'
    return f"""
    <div class="narrato-hero">
      <div class="narrato-hero-brand">
        {mark_html}
        <div>
          <div class="narrato-hero-title">{title_html}</div>
          <p class="narrato-hero-sub">{escape(subtitle)}</p>
        </div>
      </div>
      <div class="narrato-hero-meta">{chip_html}</div>
    </div>
    """


def guide_html(text: str) -> str:
    return f'<div class="narrato-guide">{text}</div>'


def col_title_html(text: str) -> str:
    return f'<div class="narrato-col-title">{escape(text)}</div>'


def action_bar_html(title: str, hint: str) -> str:
    return f"""
    <div class="narrato-action-bar">
      <div class="narrato-action-title">{escape(title)}</div>
      <div class="narrato-action-hint">{escape(hint)}</div>
    </div>
    """


def card_html(title: str, desc: str = "", body_html: str = "") -> str:
    desc_block = f'<p class="narrato-card-desc">{escape(desc)}</p>' if desc else ""
    return f"""
    <div class="narrato-card">
      <div class="narrato-card-title">{escape(title)}</div>
      {desc_block}
      {body_html}
    </div>
    """


def empty_html(title: str, desc: str) -> str:
    return f"""
    <div class="narrato-empty">
      <div class="narrato-empty-title">{escape(title)}</div>
      <p class="narrato-empty-desc">{escape(desc)}</p>
    </div>
    """


def metrics_html(items: Sequence[Tuple[str, str]]) -> str:
    parts = []
    for k, v in items:
        parts.append(
            f'<div class="narrato-metric"><div class="k">{escape(k)}</div>'
            f'<div class="v">{escape(v)}</div></div>'
        )
    return f'<div class="narrato-metrics">{"".join(parts)}</div>'


def pipeline_steps_html(
    steps: Sequence[Tuple[str, str]],
    *,
    current: str = "",
    done: Optional[Iterable[str]] = None,
    failed: str = "",
    gate: str = "",
    running: bool = False,
) -> str:
    """
    steps: [(key, label), ...]
    state: done / run / fail / gate / idle
    """
    done_set = set(done or [])
    chips = []
    for i, (key, label) in enumerate(steps, start=1):
        cls = ""
        if key in done_set:
            cls = "done"
        elif failed and key == failed:
            cls = "fail"
        elif gate and key == gate:
            cls = "gate"
        elif running and key == current:
            cls = "run"
        elif key == current and not running:
            cls = "run"
        chips.append(
            f'<span class="narrato-step {cls}"><span class="n">{i}</span>{escape(label)}</span>'
        )
    return f'<div class="narrato-steps">{"".join(chips)}</div>'


def status_badge_class(status: str) -> str:
    s = (status or "").lower()
    if s in {"completed", "burn_done", "packaging_done"} or s.endswith("_done") and s not in {
        "copy_done",
        "translate_done",
    }:
        if s in {"copy_done", "translate_done"}:
            return "wait"
        if s.endswith("_done") or s == "completed":
            return "ok" if s == "completed" else "ok"
    if s == "completed":
        return "ok"
    if s == "failed":
        return "fail"
    if s.endswith("_running") or s in {"queued"}:
        return "run"
    if s in {"copy_done", "translate_done"}:
        return "wait"
    return "idle"


def status_panel_html(
    *,
    mode_label: str,
    status_label: str,
    status_key: str = "",
    progress: Any = None,
    extra_lines: Optional[Sequence[str]] = None,
) -> str:
    badge_cls = status_badge_class(status_key)
    prog = ""
    try:
        if progress is not None and int(progress) >= 0:
            prog = f'<span class="narrato-chip">{int(progress)}%</span>'
    except (TypeError, ValueError):
        pass
    extras = ""
    for line in extra_lines or []:
        if line:
            extras += f'<div class="narrato-status-msg">{escape(line)}</div>'
    return f"""
    <div class="narrato-status">
      <div class="narrato-status-row">
        <span class="narrato-badge idle">{escape(mode_label)}</span>
        <span class="narrato-badge {badge_cls}">{escape(status_label)}</span>
        {prog}
      </div>
      {extras}
    </div>
    """


def subtitle_cues_html(
    cues: Sequence[dict],
    *,
    max_items: int = 40,
    title: str = "字幕节点",
    subtitle: str = "",
    pending_prefix: str = "…",
) -> str:
    """
    渲染字幕 cue 节点列表。
    cue: {id, start, end, text, pending?}
    """
    rows = list(cues or [])
    total = len(rows)
    shown = rows[: max(1, int(max_items or 40))]
    more = total - len(shown)
    items = []
    for cue in shown:
        cid = escape(str(cue.get("id") or ""))
        start = escape(str(cue.get("start") or ""))
        end = escape(str(cue.get("end") or ""))
        text = escape(str(cue.get("text") or "").strip() or "（空）")
        pending = bool(cue.get("pending"))
        cls = "pending" if pending else "ready"
        mark = escape(pending_prefix) if pending else "✓"
        items.append(
            f'<div class="na-cue {cls}">'
            f'<div class="na-cue-meta"><span class="na-cue-id">#{cid}</span>'
            f'<span class="na-cue-time">{start} → {end}</span>'
            f'<span class="na-cue-mark">{mark}</span></div>'
            f'<div class="na-cue-text">{text}</div></div>'
        )
    if not items:
        items.append('<div class="na-cue idle"><div class="na-cue-text">暂无字幕节点</div></div>')
    foot = ""
    if more > 0:
        foot = f'<div class="na-cue-foot">还有 {more} 条未展开</div>'
    sub = f'<div class="na-cue-sub">{escape(subtitle)}</div>' if subtitle else ""
    return (
        f'<div class="na-cue-panel">'
        f'<div class="na-cue-head"><strong>{escape(title)}</strong>'
        f'<span class="narrato-chip">{total} 条</span></div>'
        f"{sub}"
        f'<div class="na-cue-list">{"".join(items)}</div>'
        f"{foot}</div>"
    )
