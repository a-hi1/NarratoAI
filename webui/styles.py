#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
NarratoAI 整站 UI 设计系统 — Studio Premium

定位：影视创作 SaaS / 专业工具台
风格：浅色编辑室、靛蓝主色、细腻层次、克制动效
不依赖外网字体；系统中文字体栈保证国内可读。
"""

from __future__ import annotations

from html import escape
from typing import Any, Iterable, List, Optional, Sequence, Tuple


# 语义色 token（与 .streamlit/config.toml 对齐）
COLORS = {
    "primary": "#4F46E5",          # indigo-600 更高级
    "primary_hover": "#4338CA",
    "primary_soft": "rgba(79, 70, 229, 0.10)",
    "primary_glow": "rgba(79, 70, 229, 0.22)",
    "accent": "#C026D3",           # fuchsia 点缀
    "accent_soft": "rgba(192, 38, 211, 0.08)",
    "bg": "#F3F4F8",
    "bg_mesh_a": "#EEF2FF",
    "bg_mesh_b": "#FDF4FF",
    "surface": "#FFFFFF",
    "surface_2": "#F8F9FC",
    "surface_3": "#F1F3F9",
    "text": "#0B1220",
    "text_secondary": "#3F4B63",
    "text_muted": "#6B728F",
    "border": "#E6E8F0",
    "border_strong": "#CBD0E0",
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
  --na-primary-glow: {COLORS["primary_glow"]};
  --na-accent: {COLORS["accent"]};
  --na-accent-soft: {COLORS["accent_soft"]};
  --na-bg: {COLORS["bg"]};
  --na-bg-mesh-a: {COLORS["bg_mesh_a"]};
  --na-bg-mesh-b: {COLORS["bg_mesh_b"]};
  --na-surface: {COLORS["surface"]};
  --na-surface-2: {COLORS["surface_2"]};
  --na-surface-3: {COLORS["surface_3"]};
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
  --na-radius: 16px;
  --na-radius-sm: 12px;
  --na-radius-xs: 8px;
  --na-shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
  --na-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px rgba(15, 23, 42, 0.05);
  --na-shadow-lg: 0 4px 8px rgba(15, 23, 42, 0.04), 0 16px 40px rgba(15, 23, 42, 0.08);
  --na-font: "Segoe UI", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei",
             "Noto Sans SC", "Hiragino Sans GB", "Helvetica Neue", Arial, sans-serif;
  --na-mono: ui-monospace, "SF Mono", "Cascadia Mono", "Consolas", monospace;
}}

html, body, [class*="css"] {{
  font-family: var(--na-font) !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* 画布：柔和 mesh，避免一片死灰 */
.stApp {{
  background:
    radial-gradient(1200px 520px at 8% -10%, var(--na-bg-mesh-a) 0%, transparent 55%),
    radial-gradient(900px 480px at 92% 0%, var(--na-bg-mesh-b) 0%, transparent 50%),
    radial-gradient(700px 360px at 50% 100%, rgba(79, 70, 229, 0.05) 0%, transparent 55%),
    var(--na-bg) !important;
}}
.main .block-container {{
  padding-top: 1.0rem !important;
  padding-bottom: 3.2rem !important;
  padding-left: 1.6rem !important;
  padding-right: 1.6rem !important;
  max-width: 1480px;
}}

/* 收窄顶部空白，给 App Shell 更多内容区 */
header[data-testid="stHeader"] {{
  background: transparent !important;
}}
div[data-testid="stToolbar"] {{
  right: 0.5rem !important;
}}

/* 隐藏 Streamlit 默认页脚装饰，更干净 */
footer {{ visibility: hidden; height: 0; }}

/* ========== Hero ========== */
.narrato-hero {{
  position: relative;
  overflow: hidden;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem 1.5rem;
  margin: 0 0 1.15rem 0;
  padding: 1.25rem 1.4rem 1.3rem;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(255,255,255,0.96) 0%, rgba(255,255,255,0.88) 48%, rgba(238,242,255,0.92) 100%);
  box-shadow: var(--na-shadow);
  backdrop-filter: blur(10px);
}}
.narrato-hero::before {{
  content: "";
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 3px;
  background: linear-gradient(90deg, var(--na-primary) 0%, var(--na-accent) 55%, #06B6D4 100%);
  opacity: 0.95;
}}
.narrato-hero::after {{
  content: "";
  position: absolute;
  right: -40px;
  top: -60px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(79,70,229,0.12) 0%, transparent 70%);
  pointer-events: none;
}}
.narrato-hero-brand {{
  display: flex;
  align-items: center;
  gap: 0.95rem;
  min-width: 0;
  position: relative;
  z-index: 1;
}}
.narrato-hero-mark {{
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #fff;
  font-weight: 800;
  font-size: 0.95rem;
  letter-spacing: -0.03em;
  background: linear-gradient(145deg, #6366F1 0%, #4F46E5 48%, #A21CAF 100%);
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.28);
}}
.narrato-hero-logo {{
  width: 48px;
  height: 48px;
  border-radius: 14px;
  flex: 0 0 auto;
  display: block;
  object-fit: contain;
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.10);
  background: #fff;
}}
.narrato-hero-kicker {{
  margin: 0 0 0.15rem 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--na-primary);
  opacity: 0.9;
}}
.narrato-hero-title {{
  font-size: 1.48rem;
  font-weight: 780;
  color: var(--na-text);
  line-height: 1.2;
  margin: 0;
  letter-spacing: -0.025em;
}}
.narrato-hero-title span {{
  background: linear-gradient(120deg, var(--na-primary) 0%, var(--na-accent) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}}
.narrato-hero-sub {{
  margin: 0.28rem 0 0 0;
  color: var(--na-muted);
  font-size: 0.92rem;
  line-height: 1.5;
  max-width: 42rem;
}}
.narrato-hero-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  align-items: center;
  position: relative;
  z-index: 1;
}}

/* ========== Chips / badges ========== */
.narrato-chip {{
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.28rem 0.72rem;
  border-radius: 999px;
  border: 1px solid var(--na-border);
  background: rgba(255,255,255,0.78);
  color: var(--na-text-2);
  font-size: 0.78rem;
  font-weight: 650;
  line-height: 1.3;
  white-space: nowrap;
  box-shadow: var(--na-shadow-sm);
}}
.narrato-chip.primary {{
  border-color: rgba(79, 70, 229, 0.22);
  background: linear-gradient(180deg, rgba(79,70,229,0.12), rgba(79,70,229,0.06));
  color: var(--na-primary);
}}

/* ========== Guide / section ========== */
.narrato-guide {{
  position: relative;
  margin: 0 0 0.95rem 0;
  padding: 0.75rem 1rem 0.75rem 1.1rem;
  border: 1px solid var(--na-border);
  border-radius: 14px;
  background: #fff;
  color: var(--na-text-2);
  font-size: 0.88rem;
  line-height: 1.55;
  box-shadow: var(--na-shadow-sm);
}}
.narrato-guide::before {{
  content: "";
  position: absolute;
  left: 0; top: 10px; bottom: 10px;
  width: 3px;
  border-radius: 999px;
  background: linear-gradient(180deg, var(--na-primary), var(--na-accent));
}}
.narrato-guide strong {{
  color: var(--na-text);
  font-weight: 720;
}}

/* 三步引导条：降低上手门槛 */
.na-steps {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: 0 0 1rem 0;
  padding: 0;
  list-style: none;
}}
.na-step {{
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.8rem;
  border-radius: 999px;
  border: 1px solid var(--na-border);
  background: #fff;
  box-shadow: var(--na-shadow-sm);
  color: var(--na-text-2);
  font-size: 0.84rem;
  font-weight: 600;
  line-height: 1.3;
}}
.na-step-arrow {{
  color: #C4C9D8;
  font-size: 0.85rem;
  font-weight: 500;
  padding: 0 0.1rem;
  align-self: center;
}}

.narrato-col-title {{
  font-size: 0.78rem;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--na-muted);
  margin: 0 0 0.65rem 0;
  padding: 0.55rem 0.75rem;
  border-radius: var(--na-radius-sm);
  background: linear-gradient(180deg, #FFFFFF, var(--na-surface-2));
  border: 1px solid var(--na-border);
  display: flex;
  align-items: center;
  gap: 0.45rem;
}}
.narrato-col-title::before {{
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--na-primary);
  box-shadow: 0 0 0 3px var(--na-primary-soft);
  flex: 0 0 auto;
}}

/* 工作区分栏外壳 */
.narrato-workspace-shell {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: rgba(255,255,255,0.55);
  padding: 0.85rem 0.85rem 0.35rem;
  margin-bottom: 0.35rem;
  box-shadow: var(--na-shadow-sm);
}}

/* ========== Action bar ========== */
.narrato-action-bar {{
  margin-top: 1.25rem;
  padding: 1.15rem 1.2rem 0.7rem;
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background:
    linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,249,252,0.95) 100%);
  box-shadow: var(--na-shadow);
  position: relative;
  overflow: hidden;
}}
.narrato-action-bar::before {{
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, var(--na-primary), transparent 70%);
}}
.narrato-action-title {{
  font-size: 1.05rem;
  font-weight: 760;
  color: var(--na-text);
  margin: 0 0 0.2rem 0;
  letter-spacing: -0.015em;
}}
.narrato-action-hint {{
  color: var(--na-muted);
  font-size: 0.88rem;
  margin: 0 0 0.85rem 0;
  line-height: 1.55;
}}

/* ========== Cards ========== */
.narrato-card {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: linear-gradient(180deg, #FFFFFF 0%, #FCFCFD 100%);
  padding: 1.05rem 1.15rem;
  margin: 0 0 1rem 0;
  box-shadow: var(--na-shadow);
  transition: box-shadow 180ms ease, border-color 180ms ease, transform 180ms ease;
}}
.narrato-card:hover {{
  border-color: rgba(79, 70, 229, 0.18);
  box-shadow: var(--na-shadow-lg);
}}
.narrato-card-title {{
  font-size: 1.05rem;
  font-weight: 760;
  color: var(--na-text);
  margin: 0 0 0.3rem 0;
  letter-spacing: -0.015em;
}}
.narrato-card-desc {{
  color: var(--na-muted);
  font-size: 0.88rem;
  line-height: 1.55;
  margin: 0 0 0.7rem 0;
}}

/* ========== Pipeline steps ========== */
.narrato-steps {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: 0.2rem 0 0.2rem 0;
}}
.narrato-step {{
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.34rem 0.72rem 0.34rem 0.4rem;
  border-radius: 999px;
  border: 1px solid var(--na-border);
  background: var(--na-surface-2);
  color: var(--na-muted);
  font-size: 0.8rem;
  font-weight: 650;
  line-height: 1.3;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}}
.narrato-step .n {{
  width: 1.25rem;
  height: 1.25rem;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 750;
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
  border-color: rgba(79, 70, 229, 0.32);
  background: var(--na-primary-soft);
  color: var(--na-primary);
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.08);
}}
.narrato-step.run .n {{
  background: linear-gradient(135deg, #6366F1, #4F46E5);
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

/* ========== Status panel ========== */
.narrato-status {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background: linear-gradient(135deg, #FFFFFF 0%, #F8F9FC 100%);
  padding: 0.95rem 1.05rem;
  margin: 0 0 1rem 0;
  box-shadow: var(--na-shadow-sm);
}}
.narrato-status-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.7rem;
  align-items: center;
  margin-bottom: 0.25rem;
}}
.narrato-badge {{
  display: inline-flex;
  align-items: center;
  padding: 0.22rem 0.62rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 720;
  line-height: 1.35;
  border: 1px solid transparent;
  letter-spacing: 0.01em;
}}
.narrato-badge.ok {{
  background: var(--na-success-soft);
  color: var(--na-success);
  border-color: rgba(5, 150, 105, 0.22);
}}
.narrato-badge.run {{
  background: var(--na-primary-soft);
  color: var(--na-primary);
  border-color: rgba(79, 70, 229, 0.22);
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
  background: var(--na-surface-3);
  color: var(--na-text-2);
  border-color: var(--na-border);
}}
.narrato-status-msg {{
  color: var(--na-text-2);
  font-size: 0.9rem;
  line-height: 1.55;
  margin: 0.3rem 0 0 0;
  white-space: pre-wrap;
}}

/* ========== Empty ========== */
.narrato-empty {{
  border: 1px dashed var(--na-border-strong);
  border-radius: var(--na-radius);
  background:
    radial-gradient(circle at 50% 0%, rgba(79,70,229,0.06), transparent 55%),
    var(--na-surface);
  padding: 2rem 1.25rem;
  text-align: center;
  color: var(--na-muted);
}}
.narrato-empty-title {{
  color: var(--na-text);
  font-weight: 740;
  font-size: 1.05rem;
  margin: 0 0 0.4rem 0;
  letter-spacing: -0.01em;
}}
.narrato-empty-desc {{
  margin: 0;
  font-size: 0.92rem;
  line-height: 1.6;
  max-width: 28rem;
  margin-left: auto;
  margin-right: auto;
}}

/* ========== Metrics ========== */
.narrato-metrics {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: 0.6rem;
  margin: 0 0 1rem 0;
}}
.narrato-metric {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius-sm);
  background: linear-gradient(180deg, #FFFFFF, var(--na-surface-2));
  padding: 0.7rem 0.8rem;
  box-shadow: var(--na-shadow-sm);
}}
.narrato-metric .k {{
  color: var(--na-muted);
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin: 0 0 0.2rem 0;
}}
.narrato-metric .v {{
  color: var(--na-text);
  font-size: 0.98rem;
  font-weight: 740;
  margin: 0;
  line-height: 1.3;
  word-break: break-word;
}}

/* ========== Page section title ========== */
.narrato-section {{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.75rem;
  margin: 0.2rem 0 0.85rem 0;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid var(--na-border);
}}
.narrato-section-title {{
  margin: 0;
  font-size: 1.18rem;
  font-weight: 760;
  color: var(--na-text);
  letter-spacing: -0.02em;
  line-height: 1.25;
}}
.narrato-section-sub {{
  margin: 0.2rem 0 0 0;
  color: var(--na-muted);
  font-size: 0.86rem;
  line-height: 1.45;
}}
.narrato-mono {{
  font-family: var(--na-mono);
  font-size: 0.82em;
  color: var(--na-muted);
  background: var(--na-surface-3);
  padding: 0.1rem 0.4rem;
  border-radius: 6px;
  border: 1px solid var(--na-border);
}}

/* 任务详情头 */
.narrato-detail-head {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  background:
    linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(238,242,255,0.65) 100%);
  padding: 1.1rem 1.2rem 1rem;
  margin: 0 0 1rem 0;
  box-shadow: var(--na-shadow);
}}
.narrato-detail-head h3 {{
  margin: 0 0 0.25rem 0;
  font-size: 1.22rem;
  font-weight: 760;
  letter-spacing: -0.02em;
  color: var(--na-text);
}}
.narrato-detail-head .meta {{
  color: var(--na-muted);
  font-size: 0.86rem;
  margin: 0 0 0.55rem 0;
}}

/* ========== Tabs：分段导航感 ========== */
div[data-baseweb="tab-list"] {{
  gap: 0.35rem !important;
  padding: 0.35rem !important;
  margin-bottom: 1.05rem !important;
  border-bottom: none !important;
  border: 1px solid var(--na-border) !important;
  border-radius: 14px !important;
  background: rgba(255,255,255,0.72) !important;
  box-shadow: var(--na-shadow-sm);
}}
button[data-baseweb="tab"] {{
  font-weight: 680 !important;
  font-size: 0.94rem !important;
  border-radius: 10px !important;
  padding: 0.55rem 1rem !important;
  color: var(--na-text-2) !important;
  transition: background 160ms ease, color 160ms ease, box-shadow 160ms ease !important;
}}
button[data-baseweb="tab"]:hover {{
  background: rgba(79, 70, 229, 0.06) !important;
  color: var(--na-text) !important;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
  color: #fff !important;
  background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%) !important;
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.28) !important;
}}
/* 隐藏默认下划线指示器 */
div[data-baseweb="tab-highlight"],
div[data-baseweb="tab-border"] {{
  display: none !important;
}}

/* 水平 radio 当分段控件（跨境子导航） */
div[role="radiogroup"] {{
  gap: 0.35rem !important;
  padding: 0.3rem !important;
  border: 1px solid var(--na-border) !important;
  border-radius: 14px !important;
  background: rgba(255,255,255,0.75) !important;
  box-shadow: var(--na-shadow-sm);
  margin-bottom: 0.85rem !important;
}}
div[role="radiogroup"] label {{
  border-radius: 10px !important;
  padding: 0.35rem 0.55rem !important;
  transition: background 150ms ease !important;
}}
div[role="radiogroup"] label:hover {{
  background: rgba(79, 70, 229, 0.06) !important;
}}

/* ========== Buttons ========== */
.stButton > button {{
  border-radius: 12px !important;
  min-height: 2.65rem;
  font-weight: 650 !important;
  border: 1px solid var(--na-border) !important;
  transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease !important;
}}
.stButton > button:hover {{
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08) !important;
}}
.stButton > button:active {{
  transform: translateY(0);
}}
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {{
  background: linear-gradient(135deg, #6366F1 0%, #4F46E5 100%) !important;
  border-color: transparent !important;
  color: #fff !important;
  box-shadow: 0 8px 18px rgba(79, 70, 229, 0.28) !important;
}}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover {{
  background: linear-gradient(135deg, #4F46E5 0%, #4338CA 100%) !important;
  border-color: transparent !important;
}}
.stButton > button:focus-visible {{
  outline: 2px solid var(--na-primary) !important;
  outline-offset: 2px !important;
}}

/* 输入控件 */
.stTextInput input,
.stTextArea textarea,
.stNumberInput input,
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {{
  border-radius: 12px !important;
  border-color: var(--na-border) !important;
  background: #fff !important;
  min-height: 2.55rem;
  transition: border-color 150ms ease, box-shadow 150ms ease !important;
}}
.stTextInput input:focus,
.stTextArea textarea:focus {{
  border-color: rgba(79, 70, 229, 0.45) !important;
  box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.12) !important;
}}
/* 标签更清晰 */
.stTextInput label, .stSelectbox label, .stRadio label, .stNumberInput label,
.stTextArea label, .stMultiSelect label, .stSlider label, .stCheckbox label {{
  font-weight: 650 !important;
  color: var(--na-text-2) !important;
  font-size: 0.9rem !important;
}}
.stCaption, [data-testid="stCaptionContainer"] {{
  color: var(--na-muted) !important;
}}

/* Expander 卡片化 */
div[data-testid="stExpander"] {{
  border: 1px solid var(--na-border) !important;
  border-radius: var(--na-radius) !important;
  background: var(--na-surface) !important;
  margin-bottom: 0.65rem !important;
  box-shadow: var(--na-shadow-sm);
  overflow: hidden;
}}
div[data-testid="stExpander"] details summary {{
  padding-top: 0.55rem !important;
  padding-bottom: 0.55rem !important;
}}
div[data-testid="stExpander"] details summary p {{
  font-weight: 700 !important;
  color: var(--na-text) !important;
}}

/* 进度条 */
div[data-testid="stProgress"] > div {{
  background: var(--na-surface-3) !important;
  border-radius: 999px !important;
  height: 0.55rem !important;
  overflow: hidden;
}}
div[data-testid="stProgress"] > div > div {{
  background: linear-gradient(90deg, #6366F1 0%, #4F46E5 50%, #C026D3 100%) !important;
  border-radius: 999px !important;
}}

/* ========== App Shell：侧栏主导航（浅色、无圆点） ========== */
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #FFFFFF 0%, #F7F8FC 100%) !important;
  border-right: 1px solid var(--na-border) !important;
  min-width: 260px !important;
}}
section[data-testid="stSidebar"] > div {{
  background: transparent !important;
}}
section[data-testid="stSidebar"] .block-container {{
  padding-top: 1rem !important;
  padding-bottom: 1.25rem !important;
  padding-left: 0.85rem !important;
  padding-right: 0.85rem !important;
}}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown {{
  color: var(--na-text-2) !important;
}}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] .stCaption {{
  color: var(--na-muted) !important;
  font-size: 0.78rem !important;
}}
/* 侧栏 expander 轻量 */
section[data-testid="stSidebar"] div[data-testid="stExpander"] {{
  background: var(--na-surface-2) !important;
  border: 1px solid var(--na-border) !important;
  box-shadow: none !important;
  border-radius: 12px !important;
}}
section[data-testid="stSidebar"] div[data-testid="stExpander"] details summary p {{
  color: var(--na-text) !important;
  font-weight: 650 !important;
  font-size: 0.86rem !important;
}}
/* 彻底隐藏侧栏内任何 radio 圆点（兜底） */
section[data-testid="stSidebar"] div[role="radiogroup"] {{
  border: none !important;
  background: transparent !important;
  box-shadow: none !important;
  padding: 0 !important;
  gap: 0.35rem !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] label {{
  position: relative !important;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child,
section[data-testid="stSidebar"] [data-baseweb="radio"],
section[data-testid="stSidebar"] input[type="radio"] {{
  display: none !important;
  width: 0 !important;
  height: 0 !important;
  opacity: 0 !important;
  pointer-events: none !important;
}}

/* —— 按钮式导航：像菜单，不像单选 —— */
section[data-testid="stSidebar"] .stButton {{
  margin-bottom: 0.28rem !important;
}}
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"],
section[data-testid="stSidebar"] button[kind] {{
  width: 100% !important;
  justify-content: flex-start !important;
  text-align: left !important;
  min-height: 2.7rem !important;
  padding: 0.55rem 0.85rem !important;
  border-radius: 11px !important;
  border: 1px solid transparent !important;
  background: transparent !important;
  color: #3F4B63 !important;
  font-weight: 620 !important;
  font-size: 0.93rem !important;
  letter-spacing: -0.01em !important;
  box-shadow: none !important;
  transform: none !important;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease !important;
}}
section[data-testid="stSidebar"] .stButton > button p,
section[data-testid="stSidebar"] .stButton > button span,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] p,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] span {{
  color: inherit !important;
}}
section[data-testid="stSidebar"] .stButton > button svg,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"] svg {{
  fill: currentColor !important;
  color: inherit !important;
  opacity: 0.85;
}}
section[data-testid="stSidebar"] .stButton > button:hover,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"]:hover {{
  background: #F3F4F8 !important;
  border-color: transparent !important;
  color: #0B1220 !important;
  transform: none !important;
  box-shadow: none !important;
}}
section[data-testid="stSidebar"] .stButton > button:active,
section[data-testid="stSidebar"] button[data-testid^="stBaseButton"]:active {{
  transform: none !important;
}}
section[data-testid="stSidebar"] .stButton > button:focus,
section[data-testid="stSidebar"] .stButton > button:focus-visible {{
  box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.14) !important;
  outline: none !important;
}}
/*
 * 当前页：用 secondary/tertiary，不用 primary（避免全局紫底白字盖住侧栏样式）
 * 浅灰底 + 深字 + 细左边线，可读、不抢眼
 */
section[data-testid="stSidebar"] .stButton > button[kind="secondary"],
section[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-secondary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"],
section[data-testid="stSidebar"] button[kind="secondary"] {{
  background: #F0F2F8 !important;
  border: 1px solid #E4E7F0 !important;
  color: #0B1220 !important;
  font-weight: 700 !important;
  box-shadow: inset 3px 0 0 0 #6366F1 !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover,
section[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover,
section[data-testid="stSidebar"] button[kind="secondary"]:hover {{
  background: #E8EBF4 !important;
  border-color: #D9DEEA !important;
  color: #0B1220 !important;
  transform: none !important;
  box-shadow: inset 3px 0 0 0 #4F46E5 !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] p,
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] span,
section[data-testid="stSidebar"] button[kind="secondary"] p,
section[data-testid="stSidebar"] button[kind="secondary"] span {{
  color: #0B1220 !important;
}}
/* 未选中：tertiary 幽灵按钮 */
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"],
section[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-tertiary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"],
section[data-testid="stSidebar"] button[kind="tertiary"] {{
  background: transparent !important;
  border: 1px solid transparent !important;
  color: #3F4B63 !important;
  font-weight: 600 !important;
  box-shadow: none !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"]:hover,
section[data-testid="stSidebar"] button[kind="tertiary"]:hover {{
  background: #F3F4F8 !important;
  color: #0B1220 !important;
  box-shadow: none !important;
}}
/* 兜底：侧栏永远不要出现实心紫底白字 primary */
section[data-testid="stSidebar"] .stButton > button[kind="primary"],
section[data-testid="stSidebar"] .stButton > button[data-testid="baseButton-primary"],
section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"],
section[data-testid="stSidebar"] button[kind="primary"] {{
  background: #F0F2F8 !important;
  border: 1px solid #E4E7F0 !important;
  color: #0B1220 !important;
  font-weight: 700 !important;
  box-shadow: inset 3px 0 0 0 #6366F1 !important;
}}
section[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
section[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
section[data-testid="stSidebar"] button[kind="primary"] p,
section[data-testid="stSidebar"] button[kind="primary"] span {{
  color: #0B1220 !important;
}}
section[data-testid="stSidebar"] hr {{
  border-top: 1px solid var(--na-border) !important;
  margin: 0.75rem 0 !important;
}}

/* 侧栏品牌 */
.na-side-brand {{
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.2rem 0.15rem 0.95rem;
  margin-bottom: 0.55rem;
  border-bottom: 1px solid var(--na-border);
}}
.na-side-mark {{
  width: 38px;
  height: 38px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 0.82rem;
  letter-spacing: -0.03em;
  color: #fff;
  background: linear-gradient(145deg, #6366F1 0%, #4F46E5 55%, #7C3AED 100%);
  box-shadow: 0 6px 14px rgba(79, 70, 229, 0.28);
  flex: 0 0 auto;
}}
.na-side-logo {{
  width: 38px;
  height: 38px;
  border-radius: 11px;
  object-fit: contain;
  background: #fff;
  border: 1px solid var(--na-border);
  flex: 0 0 auto;
}}
.na-side-name {{
  font-size: 1.02rem;
  font-weight: 780;
  letter-spacing: -0.025em;
  color: var(--na-text) !important;
  line-height: 1.15;
  margin: 0;
}}
.na-side-tag {{
  margin: 0.18rem 0 0 0;
  font-size: 0.74rem;
  color: var(--na-muted) !important;
  letter-spacing: 0.02em;
  font-weight: 550;
}}
.na-side-section {{
  margin: 0.35rem 0 0.45rem 0.2rem;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--na-muted) !important;
}}
.na-side-foot {{
  margin-top: 0.85rem;
  padding: 0.7rem 0.75rem;
  border-radius: 12px;
  background: var(--na-surface-2);
  border: 1px solid var(--na-border);
  font-size: 0.78rem;
  color: var(--na-muted) !important;
  line-height: 1.5;
}}
.na-side-foot strong {{
  color: var(--na-text) !important;
  font-weight: 700;
}}

/* 导航项自定义文案（按钮内 HTML 不可用，用上方说明） */
.na-nav-hint {{
  margin: -0.15rem 0 0.55rem 0.2rem;
  font-size: 0.74rem;
  color: var(--na-muted);
  line-height: 1.4;
}}

/* ========== 页面壳：页头 / 工作区 / 操作坞 ========== */
.na-page-actions {{
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}}

/* 工作区分区模块 */
.na-zone {{
  border: 1px solid var(--na-border);
  border-radius: 18px;
  background: linear-gradient(180deg, #FFFFFF 0%, #FBFBFD 100%);
  box-shadow: var(--na-shadow);
  padding: 1rem 1.05rem 0.85rem;
  margin: 0 0 0.95rem 0;
  min-height: 100%;
}}
.na-zone-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin: 0 0 0.75rem 0;
  padding-bottom: 0.65rem;
  border-bottom: 1px solid var(--na-border);
}}
.na-zone-title {{
  margin: 0;
  font-size: 0.98rem;
  font-weight: 760;
  letter-spacing: -0.015em;
  color: var(--na-text);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}}
.na-zone-index {{
  width: 1.45rem;
  height: 1.45rem;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 780;
  color: #fff;
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  box-shadow: 0 4px 10px rgba(79,70,229,0.25);
  flex: 0 0 auto;
}}
.na-zone-hint {{
  margin: 0;
  color: var(--na-muted);
  font-size: 0.8rem;
  font-weight: 600;
}}
.na-zone.primary {{
  border-color: rgba(79, 70, 229, 0.18);
  box-shadow: 0 1px 2px rgba(15,23,42,0.04), 0 12px 28px rgba(79,70,229,0.07);
}}
.na-zone.muted {{
  background: linear-gradient(180deg, #FFFFFF 0%, var(--na-surface-2) 100%);
}}

/* 底部操作坞（大应用 CTA 区） */
.na-dock {{
  position: relative;
  margin-top: 0.5rem;
  padding: 1.05rem 1.2rem 0.95rem;
  border-radius: 18px;
  border: 1px solid rgba(79, 70, 229, 0.16);
  background:
    linear-gradient(135deg, rgba(238,242,255,0.95) 0%, rgba(255,255,255,0.98) 42%, rgba(253,244,255,0.9) 100%);
  box-shadow: var(--na-shadow-lg);
  overflow: hidden;
}}
.na-dock::before {{
  content: "";
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 3px;
  background: linear-gradient(90deg, #6366F1, #C026D3 55%, #06B6D4);
}}
.na-dock-row {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem 1rem;
  margin-bottom: 0.55rem;
}}
.na-dock-title {{
  margin: 0;
  font-size: 1.05rem;
  font-weight: 760;
  letter-spacing: -0.015em;
  color: var(--na-text);
}}
.na-dock-hint {{
  margin: 0.2rem 0 0 0;
  color: var(--na-muted);
  font-size: 0.86rem;
  line-height: 1.5;
}}

/* 主区 container border 统一为 zone 风格（减少「表单堆叠」感） */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  border: 1px solid var(--na-border) !important;
  border-radius: 16px !important;
  background: linear-gradient(180deg, #FFFFFF 0%, #FCFCFD 100%) !important;
  box-shadow: var(--na-shadow-sm) !important;
  padding: 0.15rem 0.15rem !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
  border-color: rgba(79, 70, 229, 0.16) !important;
}}

/* 顶部紧凑工具条 */
.na-topbar {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem 1rem;
  margin: 0 0 0.65rem 0;
  padding: 0.4rem 0.15rem;
  border: none;
  background: transparent;
  box-shadow: none;
}}
.na-topbar-left {{
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}}
.na-topbar-title {{
  font-size: 0.86rem;
  font-weight: 720;
  color: var(--na-text);
  letter-spacing: -0.01em;
  white-space: nowrap;
}}
.na-topbar-sep {{
  width: 1px;
  height: 0.9rem;
  background: var(--na-border-strong);
  opacity: 0.65;
}}
.na-topbar-path {{
  color: var(--na-muted);
  font-size: 0.82rem;
  font-weight: 550;
}}

/* 页面标题区更轻 */
.na-page {{
  margin: 0 0 0.55rem 0;
}}
.na-page-head {{
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem 1rem;
  margin: 0 0 0.7rem 0;
  padding: 0 0 0.75rem;
  border-bottom: 1px solid var(--na-border);
}}
.na-page-kicker {{
  margin: 0 0 0.2rem 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: none;
  color: var(--na-muted);
}}
.na-page-title {{
  margin: 0;
  font-size: 1.4rem;
  font-weight: 760;
  letter-spacing: -0.03em;
  color: var(--na-text);
  line-height: 1.2;
}}
.na-page-desc {{
  margin: 0.3rem 0 0 0;
  color: var(--na-muted);
  font-size: 0.9rem;
  line-height: 1.5;
  max-width: 40rem;
}}

/* ========== 主区 segmented 分段控件（跨境子页 / 模式） ========== */
div[data-testid="stSegmentedControl"] {{
  margin: 0 0 0.85rem 0 !important;
}}
div[data-testid="stSegmentedControl"] > div {{
  background: #F3F4F8 !important;
  border: 1px solid var(--na-border) !important;
  border-radius: 12px !important;
  padding: 0.22rem !important;
  gap: 0.18rem !important;
  box-shadow: none !important;
}}
div[data-testid="stSegmentedControl"] button,
div[data-testid="stSegmentedControl"] label,
div[data-testid="stSegmentedControl"] [role="option"],
div[data-testid="stSegmentedControl"] [data-baseweb="button"] {{
  border-radius: 9px !important;
  border: 1px solid transparent !important;
  background: transparent !important;
  color: #3F4B63 !important;
  font-weight: 620 !important;
  font-size: 0.9rem !important;
  min-height: 2.2rem !important;
  padding: 0.35rem 0.85rem !important;
  box-shadow: none !important;
  transition: background 120ms ease, color 120ms ease, box-shadow 120ms ease !important;
}}
div[data-testid="stSegmentedControl"] button:hover,
div[data-testid="stSegmentedControl"] [role="option"]:hover {{
  background: rgba(255,255,255,0.7) !important;
  color: #0B1220 !important;
}}
/* 选中：白底深字 + 轻阴影（无实心紫、无圆点） */
div[data-testid="stSegmentedControl"] button[aria-checked="true"],
div[data-testid="stSegmentedControl"] button[aria-pressed="true"],
div[data-testid="stSegmentedControl"] [aria-selected="true"],
div[data-testid="stSegmentedControl"] [data-selected="true"],
div[data-testid="stSegmentedControl"] button[kind="primary"],
div[data-testid="stSegmentedControl"] button[data-testid="stBaseButton-segmentedControlActive"] {{
  background: #FFFFFF !important;
  color: #0B1220 !important;
  font-weight: 720 !important;
  border: 1px solid #E4E7F0 !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08) !important;
}}
div[data-testid="stSegmentedControl"] button[aria-checked="true"] p,
div[data-testid="stSegmentedControl"] button[aria-checked="true"] span,
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] p,
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] span,
div[data-testid="stSegmentedControl"] [aria-selected="true"] p,
div[data-testid="stSegmentedControl"] [aria-selected="true"] span {{
  color: #0B1220 !important;
  font-weight: 720 !important;
}}

/* 兜底：主区残留 radio 也做成胶囊（隐藏圆点） */
.main div[role="radiogroup"] {{
  display: inline-flex !important;
  flex-wrap: wrap !important;
  gap: 0.28rem !important;
  padding: 0.28rem !important;
  border: 1px solid var(--na-border) !important;
  border-radius: 14px !important;
  background: #F3F4F8 !important;
  box-shadow: none !important;
  margin: 0 0 1rem 0 !important;
}}
.main div[role="radiogroup"] label {{
  border-radius: 10px !important;
  padding: 0.48rem 0.9rem !important;
  margin: 0 !important;
  background: transparent !important;
  border: 1px solid transparent !important;
  font-weight: 650 !important;
}}
.main div[role="radiogroup"] label > div:first-child,
.main div[role="radiogroup"] [data-baseweb="radio"],
.main div[role="radiogroup"] input[type="radio"] {{
  display: none !important;
  width: 0 !important;
  height: 0 !important;
  opacity: 0 !important;
  pointer-events: none !important;
}}
.main div[role="radiogroup"] label:hover {{
  background: rgba(255,255,255,0.75) !important;
}}
.main div[role="radiogroup"] label:has(input:checked) {{
  background: #FFFFFF !important;
  border-color: #E4E7F0 !important;
  color: #0B1220 !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}}
.main div[role="radiogroup"] label:has(input:checked) p,
.main div[role="radiogroup"] label:has(input:checked) span {{
  color: #0B1220 !important;
  font-weight: 720 !important;
}}

/* 表格 */
div[data-testid="stDataFrame"] {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius-sm);
  overflow: hidden;
  box-shadow: var(--na-shadow-sm);
}}

/* 分隔线更轻 */
hr {{
  border: none !important;
  border-top: 1px solid var(--na-border) !important;
  margin: 1rem 0 !important;
}}

/* 生成状态行 */
.narrato-gen-step {{
  font-size: 0.98rem;
  line-height: 1.7;
  margin: 0.18rem 0;
}}
.narrato-gen-step.current {{ color: var(--na-text); font-weight: 720; }}
.narrato-gen-step.done {{ color: var(--na-muted); font-weight: 500; }}
.narrato-gen-step.todo {{ color: #94A3B8; font-weight: 500; }}

/* markdown 标题 */
.stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
  letter-spacing: -0.02em;
  color: var(--na-text) !important;
}}
.stMarkdown h3 {{
  font-weight: 740 !important;
}}
.stMarkdown h5, .stMarkdown h4 {{
  color: var(--na-text-2) !important;
  font-weight: 720 !important;
}}

/* 字幕节点实时面板 */
.na-cue-panel {{
  background: linear-gradient(180deg, #FFFFFF, #FCFCFD);
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius);
  padding: 0.85rem 0.95rem 0.7rem;
  box-shadow: var(--na-shadow);
  margin: 0.35rem 0 0.7rem;
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
  margin-bottom: 0.55rem;
  line-height: 1.45;
}}
.na-cue-list {{
  max-height: 340px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding-right: 0.2rem;
}}
.na-cue-list::-webkit-scrollbar {{ width: 6px; }}
.na-cue-list::-webkit-scrollbar-thumb {{
  background: #CBD0E0;
  border-radius: 999px;
}}
.na-cue {{
  border: 1px solid var(--na-border);
  border-radius: var(--na-radius-xs);
  background: var(--na-surface-2);
  padding: 0.5rem 0.6rem;
  transition: border-color 150ms ease, background 150ms ease;
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
  font-weight: 740;
  color: var(--na-text-2);
  min-width: 2.2rem;
  font-family: var(--na-mono);
}}
.na-cue-time {{
  font-variant-numeric: tabular-nums;
  flex: 1;
  font-family: var(--na-mono);
  font-size: 0.72rem;
}}
.na-cue-mark {{
  font-weight: 740;
  color: var(--na-success);
}}
.na-cue.pending .na-cue-mark {{
  color: var(--na-warning);
}}
.na-cue-text {{
  color: var(--na-text);
  font-size: 0.9rem;
  line-height: 1.5;
  word-break: break-word;
}}
.na-cue-foot {{
  margin-top: 0.45rem;
  color: var(--na-muted);
  font-size: 0.78rem;
}}

/* alert 更圆润 */
div[data-testid="stAlert"] {{
  border-radius: var(--na-radius-sm) !important;
}}

/* 文件上传区 */
[data-testid="stFileUploader"] {{
  border-radius: var(--na-radius) !important;
}}
[data-testid="stFileUploader"] section {{
  border-radius: var(--na-radius-sm) !important;
  border: 1px dashed var(--na-border-strong) !important;
  background: var(--na-surface-2) !important;
}}

/* 可点击元素 */
button, [role="button"], a {{
  cursor: pointer;
}}

@media (max-width: 900px) {{
  .main .block-container {{
    padding-left: 1rem !important;
    padding-right: 1rem !important;
  }}
  .narrato-hero {{
    padding: 1rem 1.05rem;
  }}
  .narrato-hero-title {{
    font-size: 1.22rem;
  }}
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


_LOGO_DATA_URI_CACHE: Optional[str] = None
_LOGO_DATA_URI_TRIED = False


def _resolve_logo_data_uri() -> str:
    """把 resource/public/logo.png 编成 data URI（进程内缓存，避免每次 rerun 读盘编码）。"""
    global _LOGO_DATA_URI_CACHE, _LOGO_DATA_URI_TRIED
    if _LOGO_DATA_URI_TRIED:
        return _LOGO_DATA_URI_CACHE or ""
    _LOGO_DATA_URI_TRIED = True
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
                _LOGO_DATA_URI_CACHE = f"data:image/png;base64,{b64}"
                return _LOGO_DATA_URI_CACHE
    except Exception:
        pass
    _LOGO_DATA_URI_CACHE = ""
    return ""


def side_brand_html(
    *,
    name: str = "NarratoAI",
    tag: str = "Creative Studio",
) -> str:
    logo_uri = _resolve_logo_data_uri()
    if logo_uri:
        mark = (
            f'<img class="na-side-logo" src="{logo_uri}" alt="NarratoAI" '
            f'width="40" height="40"/>'
        )
    else:
        mark = '<div class="na-side-mark">NA</div>'
    return f"""
    <div class="na-side-brand">
      {mark}
      <div>
        <div class="na-side-name">{escape(name)}</div>
        <p class="na-side-tag">{escape(tag)}</p>
      </div>
    </div>
    """


def side_section_html(text: str) -> str:
    return f'<div class="na-side-section">{escape(text)}</div>'


def side_foot_html(html: str) -> str:
    return f'<div class="na-side-foot">{html}</div>'


def steps_html(steps: Sequence[str]) -> str:
    """横向步骤条：纯文字 + 箭头，无数字标号。"""
    parts: List[str] = ['<div class="na-steps">']
    for i, label in enumerate(steps):
        if i > 0:
            parts.append('<span class="na-step-arrow">→</span>')
        parts.append(f'<span class="na-step">{escape(str(label))}</span>')
    parts.append("</div>")
    return "".join(parts)


def topbar_html(*, path: str, chips: Optional[Sequence[str]] = None) -> str:
    chips = list(chips or [])
    chip_html = "".join(
        f'<span class="narrato-chip{" primary" if i == 0 else ""}">{escape(c)}</span>'
        for i, c in enumerate(chips)
    )
    return f"""
    <div class="na-topbar">
      <div class="na-topbar-left">
        <span class="na-topbar-title">Narrato<span style="color:var(--na-primary)">AI</span></span>
        <span class="na-topbar-sep"></span>
        <span class="na-topbar-path">{escape(path)}</span>
      </div>
      <div class="narrato-hero-meta">{chip_html}</div>
    </div>
    """


def page_head_html(
    *,
    title: str,
    description: str = "",
    kicker: str = "",
    trailing_html: str = "",
) -> str:
    kicker_h = (
        f'<div class="na-page-kicker">{escape(kicker)}</div>' if kicker else ""
    )
    desc_h = (
        f'<p class="na-page-desc">{escape(description)}</p>' if description else ""
    )
    trail = f'<div class="na-page-actions">{trailing_html}</div>' if trailing_html else ""
    return f"""
    <div class="na-page">
      <div class="na-page-head">
        <div>
          {kicker_h}
          <h1 class="na-page-title">{escape(title)}</h1>
          {desc_h}
        </div>
        {trail}
      </div>
    </div>
    """


def zone_head_html(
    title: str,
    *,
    index: str = "",
    hint: str = "",
    primary: bool = False,
) -> str:
    idx = (
        f'<span class="na-zone-index">{escape(str(index))}</span>' if index else ""
    )
    hint_h = f'<p class="na-zone-hint">{escape(hint)}</p>' if hint else ""
    # 仅头部；外层用 st.container 承载控件，避免 HTML 包不住 Streamlit widget
    return f"""
    <div class="na-zone-head">
      <div class="na-zone-title">{idx}{escape(title)}</div>
      {hint_h}
    </div>
    """


def dock_html(*, title: str, hint: str = "") -> str:
    hint_h = f'<p class="na-dock-hint">{escape(hint)}</p>' if hint else ""
    return f"""
    <div class="na-dock">
      <div class="na-dock-row">
        <div>
          <div class="na-dock-title">{escape(title)}</div>
          {hint_h}
        </div>
      </div>
    </div>
    """


def hero_html(
    *,
    title: str,
    subtitle: str,
    version: str = "",
    chips: Optional[Sequence[str]] = None,
    kicker: str = "CREATIVE STUDIO",
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
            f'alt="NarratoAI" width="48" height="48"/>'
        )
    else:
        mark_html = '<div class="narrato-hero-mark">NA</div>'
    kicker_html = (
        f'<div class="narrato-hero-kicker">{escape(kicker)}</div>' if kicker else ""
    )
    return f"""
    <div class="narrato-hero">
      <div class="narrato-hero-brand">
        {mark_html}
        <div>
          {kicker_html}
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


def section_html(title: str, subtitle: str = "", trailing_html: str = "") -> str:
    sub = f'<p class="narrato-section-sub">{escape(subtitle)}</p>' if subtitle else ""
    trail = f'<div>{trailing_html}</div>' if trailing_html else ""
    return f"""
    <div class="narrato-section">
      <div>
        <div class="narrato-section-title">{escape(title)}</div>
        {sub}
      </div>
      {trail}
    </div>
    """


def detail_head_html(
    *,
    title: str,
    meta_line: str = "",
    badge_html: str = "",
) -> str:
    meta = f'<p class="meta">{meta_line}</p>' if meta_line else ""
    return f"""
    <div class="narrato-detail-head">
      <h3>{escape(title)}</h3>
      {meta}
      {badge_html}
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
    if s == "completed":
        return "ok"
    if s == "failed":
        return "fail"
    if s.endswith("_running") or s in {"queued"}:
        return "run"
    if s in {"copy_done", "translate_done"}:
        return "wait"
    if s.endswith("_done"):
        return "ok"
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
            prog = f'<span class="narrato-chip primary">{int(progress)}%</span>'
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
