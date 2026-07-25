#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
跨境任务：从公开视频链接下载源片。

设计目标：
- 仅服务 cross_border 取片，不改主站 material / YoutubeService 行为
- 优先 H.264 + AAC 的 mp4，便于 Windows 播放与后续烧字幕
- 可选代理 / Cookie；缺 yt-dlp 时给出明确安装提示
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

# 默认上限 1080p，避免 4K 拖垮本地流水线
DEFAULT_MAX_HEIGHT = 1080
ALLOWED_MAX_HEIGHTS = (720, 1080, 1440, 2160)

_URL_RE = re.compile(r"^https?://", re.I)


class UrlDownloadError(RuntimeError):
    """下载失败（含依赖缺失、站点限制、网络等）。"""


def is_http_url(value: str) -> bool:
    text = (value or "").strip()
    if not text or not _URL_RE.match(text):
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    return bool(parsed.netloc)


def sanitize_title(title: str, fallback: str = "downloaded_video") -> str:
    text = (title or "").strip() or fallback
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    if len(text) > 48:
        text = text[:46] + "…"
    return text


def yt_dlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except Exception:
        return False


def _resolve_proxy() -> str:
    """读取 config.proxy；未启用则返回空字符串。"""
    try:
        from app.config import config

        proxy_cfg = getattr(config, "proxy", None) or {}
        if not isinstance(proxy_cfg, dict):
            return ""
        if not proxy_cfg.get("enabled"):
            return ""
        for key in ("https", "http", "all"):
            val = str(proxy_cfg.get(key) or "").strip()
            if val:
                return val
    except Exception as exc:
        logger.debug(f"resolve proxy skipped: {exc}")
    return ""


def _ffmpeg_exe() -> str:
    try:
        from app.config import config

        path = str(getattr(config, "ffmpeg_path", "") or "").strip()
        if path and os.path.isfile(path):
            return path
        app_cfg = getattr(config, "app", None) or {}
        path = str(app_cfg.get("ffmpeg_path") or "").strip()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


def _ffprobe_exe() -> str:
    ffmpeg = _ffmpeg_exe()
    if ffmpeg and ffmpeg != "ffmpeg":
        base = os.path.dirname(ffmpeg)
        cand = os.path.join(base, "ffprobe.exe" if os.name == "nt" else "ffprobe")
        if os.path.isfile(cand):
            return cand
    found = shutil.which("ffprobe")
    return found or "ffprobe"


def _probe_video_codec(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    cmd = [
        _ffprobe_exe(),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip().lower()
    except Exception as exc:
        logger.debug(f"ffprobe codec failed: {exc}")
    return ""


def _transcode_to_h264_aac(src: str, dst: str) -> None:
    """将任意可解码片源转成 H.264 + AAC mp4（兼容播放与烧字幕）。"""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    tmp = dst + ".tmp.mp4"
    if os.path.isfile(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-i",
        src,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        tmp,
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) < 1024:
        tail = (r.stderr or r.stdout or "")[-800:]
        raise UrlDownloadError(f"转码 H.264 失败：{tail}")
    if os.path.isfile(dst):
        try:
            os.remove(dst)
        except OSError:
            pass
    os.replace(tmp, dst)


def _format_selector(max_height: int) -> str:
    """优先 H.264/mp4，限制高度，带多级回退。"""
    h = int(max_height or DEFAULT_MAX_HEIGHT)
    if h not in ALLOWED_MAX_HEIGHTS:
        h = DEFAULT_MAX_HEIGHT
    # 顺序：mp4+avc → 任意 avc → 任意 mp4 → 任意 ≤h → 全局 best
    return (
        f"bestvideo[height<={h}][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={h}][vcodec^=avc]+bestaudio/"
        f"best[height<={h}][ext=mp4]/"
        f"bestvideo[height<={h}]+bestaudio/"
        f"best[height<={h}]/"
        f"best"
    )


def _friendly_yt_error(exc: BaseException) -> str:
    msg = str(exc or "").strip() or exc.__class__.__name__
    low = msg.lower()
    if "sign in" in low or "login required" in low or "cookies" in low:
        return (
            "站点要求登录或校验 Cookie。可在高级选项填入 cookies.txt 路径后重试。"
            f"\n技术详情：{msg}"
        )
    if "proxy" in low or "timed out" in low or "timeout" in low or "network" in low:
        return (
            "网络/代理失败。国内访问 YouTube 请在「基础与系统」开启代理后重试。"
            f"\n技术详情：{msg}"
        )
    if "private video" in low or "unavailable" in low or "blocked" in low:
        return f"视频不可用或地区限制。\n技术详情：{msg}"
    if "unsupported url" in low or "no suitable extractor" in low:
        return f"不支持的链接。请确认是公开可访问的视频页 URL。\n技术详情：{msg}"
    return msg


def download_url_to_file(
    url: str,
    output_mp4: str,
    *,
    max_height: int = DEFAULT_MAX_HEIGHT,
    cookiefile: str = "",
    prefer_h264: bool = True,
    progress_hook=None,
) -> Dict[str, Any]:
    """
    下载到指定 mp4 路径。

    Returns:
        {path, title, webpage_url, extractor, filesize, transcoded}
    """
    url = (url or "").strip()
    if not is_http_url(url):
        raise UrlDownloadError("请输入有效的 http(s) 视频链接。")

    if not yt_dlp_available():
        raise UrlDownloadError(
            "未安装 yt-dlp。请执行：.venv/Scripts/python -m pip install yt-dlp"
        )

    import yt_dlp

    output_mp4 = os.path.abspath(output_mp4)
    out_dir = os.path.dirname(output_mp4) or "."
    os.makedirs(out_dir, exist_ok=True)

    work_dir = os.path.join(out_dir, "_url_dl")
    if os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    outtmpl = os.path.join(work_dir, "media.%(ext)s")
    proxy = _resolve_proxy()
    ydl_opts: Dict[str, Any] = {
        "format": _format_selector(max_height),
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
        # Windows 路径安全
        "restrictfilenames": True,
        "windowsfilenames": True,
    }
    if proxy:
        ydl_opts["proxy"] = proxy
    cookie = (cookiefile or "").strip()
    if cookie:
        if not os.path.isfile(cookie):
            raise UrlDownloadError(f"Cookie 文件不存在：{cookie}")
        ydl_opts["cookiefile"] = cookie
    if progress_hook:
        ydl_opts["progress_hooks"] = [progress_hook]

    # 尽量用系统/配置 ffmpeg
    ffmpeg = _ffmpeg_exe()
    if ffmpeg and ffmpeg != "ffmpeg" and os.path.isfile(ffmpeg):
        ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg)

    info: Dict[str, Any] = {}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
    except UrlDownloadError:
        raise
    except Exception as exc:
        logger.exception("yt-dlp download failed")
        raise UrlDownloadError(_friendly_yt_error(exc)) from exc

    # 定位下载产物
    downloaded = ""
    requested = info.get("requested_downloads") or []
    if requested and isinstance(requested, list):
        fp = (requested[0] or {}).get("filepath") or ""
        if fp and os.path.isfile(fp):
            downloaded = fp
    if not downloaded:
        # 扫 work_dir
        for name in os.listdir(work_dir):
            path = os.path.join(work_dir, name)
            if os.path.isfile(path) and not name.endswith(".part"):
                downloaded = path
                break
    if not downloaded or not os.path.isfile(downloaded):
        raise UrlDownloadError("下载完成但未找到视频文件，请换链接或检查网络后重试。")

    title = sanitize_title(str(info.get("title") or "downloaded_video"))
    webpage_url = str(info.get("webpage_url") or url)
    extractor = str(info.get("extractor") or info.get("extractor_key") or "")
    transcoded = False

    # 统一落到 output_mp4
    if os.path.isfile(output_mp4):
        try:
            os.remove(output_mp4)
        except OSError:
            pass

    ext = os.path.splitext(downloaded)[1].lower()
    codec = _probe_video_codec(downloaded)
    h264_like = codec in {"h264", "avc", "avc1"}
    # 已是 mp4+h264 直接用；codec 探测失败但扩展名为 mp4 也直接用，避免多余转码
    need_transcode = bool(prefer_h264) and not (
        ext in {".mp4", ".m4v"} and (h264_like or not codec)
    )

    try:
        if need_transcode:
            logger.info(f"transcode to h264: {downloaded} codec={codec or 'unknown'}")
            _transcode_to_h264_aac(downloaded, output_mp4)
            transcoded = True
        else:
            shutil.copy2(downloaded, output_mp4)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not os.path.isfile(output_mp4) or os.path.getsize(output_mp4) < 1024:
        raise UrlDownloadError("下载后文件无效，请重试或改用本地上传。")

    size = os.path.getsize(output_mp4)
    logger.info(
        f"url download ok: {output_mp4} size={size} title={title} "
        f"extractor={extractor} transcoded={transcoded}"
    )
    return {
        "path": output_mp4,
        "title": title,
        "webpage_url": webpage_url,
        "extractor": extractor,
        "filesize": size,
        "transcoded": transcoded,
        "source_url": url,
    }


def download_url_to_task_dir(
    url: str,
    task_dir: str,
    *,
    max_height: int = DEFAULT_MAX_HEIGHT,
    cookiefile: str = "",
    prefer_h264: bool = True,
) -> Dict[str, Any]:
    """下载到任务目录下的 source.mp4（ASCII 名，避免 ffmpeg 路径坑）。"""
    task_dir = os.path.abspath(task_dir)
    os.makedirs(task_dir, exist_ok=True)
    output_mp4 = os.path.join(task_dir, "source.mp4")
    return download_url_to_file(
        url,
        output_mp4,
        max_height=max_height,
        cookiefile=cookiefile,
        prefer_h264=prefer_h264,
    )
