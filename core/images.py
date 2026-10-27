# -*- coding: utf-8 -*-
"""Image search (Bing/DDG) + optional generate; temp files cleaned after send."""
from __future__ import annotations

import html
import json
import re
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .cache_paths import tmp_images_dir

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# 想看看栗子 / 发张图 / 搜一下猫 等
SEE_INTENT_RE = re.compile(
    r"(想看看|想看|看看你|看看|给我看|发张|发个|发一[张张]|搜[一一下下]*图|搜一下|搜搜|"
    r"找张|找个|照片|图片|长什么样|什么样子)",
    re.I,
)
SEE_OBJECT_RE = re.compile(
    r"(?:想看看|想看|看看你(?:在)?(?:吃的|喝的|用的|玩的)?|看看|给我看一下|给我看|"
    r"发张|发个|发一张|搜一下|搜搜|找张|找个)\s*(.+)$",
    re.I,
)


def is_see_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 120:
        return False
    # avoid treating link-only messages as image intent
    if re.search(r"https?://|b23\.tv|xhslink\.com|bilibili\.com|xiaohongshu\.com", t, re.I):
        return False
    return bool(SEE_INTENT_RE.search(t))


def extract_see_query(text: str) -> str:
    t = (text or "").strip()
    m = SEE_OBJECT_RE.search(t)
    if m:
        q = m.group(1).strip(" 。.!！?？～~的了吧呀啊哦呢嘛")
        q = re.sub(r"^(的|一下|一张|一个|张|个)\s*", "", q)
        if q:
            return q[:40]
    # fallback: strip intent words
    q = SEE_INTENT_RE.sub(" ", t)
    q = re.sub(r"\s+", " ", q).strip(" 。.!！?？～~")
    return q[:40] if q else t[:40]


def _guess_ext(url: str, content_type: str = "") -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTS:
        if path.endswith(ext):
            return ext
    return ".jpg"


def _bing_image_urls(query: str, limit: int = 8) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    url = "https://www.bing.com/images/async?" + urlencode(
        {"q": q, "first": "0", "count": str(max(limit, 10)), "mmasync": "1"}
    )
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", "replace")
    urls: list[str] = []
    for m in re.finditer(r"murl&quot;:&quot;(https?://[^&\"']+)", raw):
        u = html.unescape(m.group(1)).replace("\\u0026", "&").replace("\\/", "/")
        if u not in urls:
            urls.append(u)
        if len(urls) >= limit:
            break
    if not urls:
        for m in re.finditer(r'"murl"\s*:\s*"(https?://[^"]+)"', raw):
            u = m.group(1).encode("utf-8").decode("unicode_escape")
            if u not in urls:
                urls.append(u)
            if len(urls) >= limit:
                break
    return urls


def _ddg_image_urls(query: str, limit: int = 8) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    page_url = "https://duckduckgo.com/?" + urlencode({"q": q, "iax": "images", "ia": "images"})
    req = Request(page_url, headers={"User-Agent": UA})
    with urlopen(req, timeout=12) as resp:
        page = resp.read().decode("utf-8", "replace")
    m = re.search(r"vqd=['\"]([^'\"]+)['\"]", page)
    if not m:
        return []
    vqd = m.group(1)
    api = "https://duckduckgo.com/i.js?" + urlencode(
        {"l": "us-en", "o": "json", "q": q, "vqd": vqd, "f": ",,,", "p": "1"}
    )
    req2 = Request(api, headers={"User-Agent": UA, "Referer": "https://duckduckgo.com/"})
    with urlopen(req2, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    urls: list[str] = []
    for row in data.get("results") or []:
        u = str(row.get("image") or "").strip()
        if u.startswith("http") and u not in urls:
            urls.append(u)
        if len(urls) >= limit:
            break
    return urls


def search_image_urls(query: str, limit: int = 8) -> list[str]:
    q = re.sub(r"[\s\|\[\]]+", " ", (query or "")).strip()
    if len(q) > 40:
        q = q[:40]
    for fn in (_bing_image_urls, _ddg_image_urls):
        try:
            urls = fn(q, limit=limit)
            if urls:
                return urls
        except Exception:
            continue
    return []


def download_image(url: str, cache_root: str | None, max_bytes: int = 1_048_576) -> str | None:
    dest_dir = tmp_images_dir(cache_root)
    try:
        req = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=15) as resp:
            data = resp.read(max(max_bytes * 4, 2_000_000))
            ctype = resp.headers.get("Content-Type") or ""
        if not data or data.lstrip().startswith((b"<!DOCTYPE", b"<html", b"{")):
            return None
        # optional recompress with PIL
        out = data
        if len(data) > max_bytes:
            try:
                from io import BytesIO
                from PIL import Image

                img = Image.open(BytesIO(data))
                img.load()
                if img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    alpha = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                    bg.paste(img, mask=alpha)
                    img = bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                w, h = img.size
                out = None
                for quality in (85, 75, 65, 55):
                    scale = 1.0
                    while True:
                        tw, th = max(1, int(w * scale)), max(1, int(h * scale))
                        frame = img if scale == 1.0 else img.resize((tw, th), Image.Resampling.LANCZOS)
                        buf = BytesIO()
                        frame.save(buf, format="JPEG", quality=quality, optimize=True)
                        cand = buf.getvalue()
                        if len(cand) <= max_bytes:
                            out = cand
                            break
                        if tw <= 160 or th <= 160:
                            break
                        scale *= 0.75
                    if out:
                        break
                if not out:
                    return None
                ext = ".jpg"
            except Exception:
                if len(data) > max_bytes:
                    return None
                ext = _guess_ext(url, ctype)
        else:
            ext = _guess_ext(url, ctype)
            if out.startswith(b"\xff\xd8"):
                ext = ".jpg"
        name = f"chat_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
        path = dest_dir / name
        path.write_bytes(out if isinstance(out, (bytes, bytearray)) else data)
        return str(path.resolve())
    except Exception:
        return None


def search_and_download(query: str, cache_root: str | None, max_bytes: int = 1_048_576) -> str | None:
    for u in search_image_urls(query, limit=8):
        path = download_image(u, cache_root, max_bytes=max_bytes)
        if path:
            return path
    return None


def cleanup_temp(path: str | None, cache_root: str | None = None) -> None:
    if not path:
        return
    try:
        p = Path(path).resolve()
        root = tmp_images_dir(cache_root).resolve()
        if root in p.parents or p.parent == root:
            if p.is_file():
                p.unlink(missing_ok=True)
    except Exception:
        pass


def try_ollama_generate(
    prompt: str,
    *,
    base: str,
    model: str,
    cache_root: str | None,
) -> tuple[str | None, str]:
    """Return (path, error_message)."""
    model = (model or "").strip()
    if not model:
        return None, "还没配生图模型，我只能搜图给你呀～"
    base = (base or "http://127.0.0.1:11434").rstrip("/")
    # list models
    try:
        tags = json.loads(
            urlopen(Request(base + "/api/tags", headers={"User-Agent": UA}), timeout=5)
            .read()
            .decode("utf-8", "replace")
        )
        names = [str(m.get("name") or "") for m in (tags.get("models") or [])]
        if not any(model == n or n.startswith(model + ":") or model.startswith(n.split(":")[0]) for n in names):
            return None, f"本机 Ollama 没有生图模型「{model}」（现在大概只有嵌入模型），先搜图凑合～"
    except Exception as e:
        return None, f"连不上 Ollama（{e}），生图先跳过啦"
    # Many ollama image models use /api/generate with images field differently;
    # keep as soft stub unless a known image model responds with binary.
    try:
        body = json.dumps(
            {"model": model, "prompt": f"photo of {prompt}, realistic", "stream": False}
        ).encode()
        req = Request(
            base + "/api/generate",
            data=body,
            headers={"User-Agent": UA, "Content-Type": "application/json"},
            method="POST",
        )
        raw = urlopen(req, timeout=60).read().decode("utf-8", "replace")
        data = json.loads(raw)
        # If response contains no image bytes, treat as unsupported
        return None, "当前 Ollama 模型不像能出图，生图先关掉，等你装好再开～"
    except Exception as e:
        return None, f"生图调用失败：{e}"
