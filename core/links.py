# -*- coding: utf-8 -*-
"""Fetch Bilibili / Xiaohongshu link metadata for private-chat summaries."""
from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

URL_RE = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+|b23\.tv/[^\s<>\"']+|xhslink\.com/[^\s<>\"']+",
    re.I,
)
BV_RE = re.compile(r"(BV[\w]+)", re.I)
XHS_NOTE_RE = re.compile(
    r"(?:xiaohongshu\.com/(?:explore|discovery/item)/|xhslink\.com/)([0-9a-f]{24})",
    re.I,
)
XHS_NOTE_BARE = re.compile(r"^[0-9a-f]{24}$", re.I)


def extract_urls(text: str) -> list[str]:
    found: list[str] = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip("\u3002\uFF09).,，、；;!?）]")
        if u.startswith("www."):
            u = "https://" + u
        if not u.startswith("http"):
            u = "https://" + u
        if u not in found:
            found.append(u)
    if not found:
        m = BV_RE.search(text or "")
        if m:
            found.append(f"https://www.bilibili.com/video/{m.group(1)}")
    return found


def classify_url(url: str) -> str | None:
    low = (url or "").lower()
    if "bilibili.com" in low or "b23.tv" in low:
        return "bilibili"
    if "xiaohongshu.com" in low or "xhslink.com" in low:
        return "xiaohongshu"
    return None


def _http_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 15) -> bytes:
    h = {
        "User-Agent": UA_DESKTOP,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        h.update(headers)
    req = Request(url, headers=h)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(2_000_000)


def _http_get_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    raw = _http_get(url, headers=headers)
    return json.loads(raw.decode("utf-8", "replace"))


def _resolve_redirect(url: str) -> str:
    try:
        req = Request(url, headers={"User-Agent": UA_MOBILE})
        with urlopen(req, timeout=12) as resp:
            return str(resp.geturl() or url)
    except Exception:
        return url


def _og(html_text: str, prop: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for p in patterns:
        m = re.search(p, html_text, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def _tag_title(html_text: str) -> str:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html_text, re.I)
    if not m:
        return ""
    t = html.unescape(m.group(1)).strip()
    t = re.sub(r"_?\s*哔哩哔哩.*$", "", t).strip()
    t = re.sub(r"\s*-\s*哔哩哔哩.*$", "", t).strip()
    return t


def _fill_from_html(info: dict[str, str], page_url: str) -> None:
    for ua in (UA_DESKTOP, UA_MOBILE):
        try:
            raw = _http_get(
                page_url,
                headers={"User-Agent": ua, "Referer": "https://www.bilibili.com/"},
            ).decode("utf-8", "replace")
        except Exception:
            continue
        title = _og(raw, "og:title") or _tag_title(raw)
        desc = _og(raw, "og:description")
        cover = _og(raw, "og:image")
        if not title:
            m = re.search(r'"title"\s*:\s*"([^"\\]{2,120})"', raw)
            if m:
                title = html.unescape(m.group(1))
        if title and not info.get("title"):
            info["title"] = title[:200]
        if desc and not info.get("desc"):
            info["desc"] = desc[:500]
        if cover and not info.get("cover"):
            if cover.startswith("//"):
                cover = "https:" + cover
            info["cover"] = cover
        if info.get("title"):
            return


def fetch_bilibili(url: str) -> dict[str, str]:
    resolved = _resolve_redirect(url) if "b23.tv" in url.lower() else url
    m = BV_RE.search(resolved) or BV_RE.search(url)
    bvid = m.group(1) if m else ""
    info: dict[str, str] = {
        "source": "bilibili",
        "url": resolved if resolved.startswith("http") else url,
        "title": "",
        "desc": "",
        "author": "",
        "cover": "",
    }
    if bvid:
        info["url"] = f"https://www.bilibili.com/video/{bvid}"
        endpoints = [
            "https://api.bilibili.com/x/web-interface/view?" + urlencode({"bvid": bvid}),
            "https://api.bilibili.com/x/web-interface/view/detail?" + urlencode({"bvid": bvid}),
        ]
        headers = {
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "User-Agent": UA_DESKTOP,
        }
        for endpoint in endpoints:
            try:
                data = _http_get_json(endpoint, headers=headers)
                payload = data.get("data") if isinstance(data, dict) else None
                if data.get("code") != 0 or not isinstance(payload, dict):
                    continue
                # view/detail nests under View
                d = payload.get("View") if isinstance(payload.get("View"), dict) else payload
                info["title"] = str(d.get("title") or "").strip()
                info["desc"] = str(d.get("desc") or "").strip()[:500]
                owner = d.get("owner") if isinstance(d.get("owner"), dict) else {}
                info["author"] = str(owner.get("name") or "").strip()
                cover = str(d.get("pic") or "").strip()
                if cover.startswith("//"):
                    cover = "https:" + cover
                info["cover"] = cover
                if info["title"]:
                    return info
            except HTTPError:
                continue
            except Exception:
                continue
    _fill_from_html(info, info["url"])
    if not info["title"] and bvid:
        info["title"] = f"B站视频 {bvid}"
        info["desc"] = info["desc"] or "接口有点抽风，我只拿到链接本身，你先点开看看？"
    return info


def fetch_xiaohongshu(url: str) -> dict[str, str]:
    resolved = _resolve_redirect(url)
    info: dict[str, str] = {
        "source": "xiaohongshu",
        "url": resolved,
        "title": "",
        "desc": "",
        "author": "",
        "cover": "",
    }
    m = XHS_NOTE_RE.search(resolved) or XHS_NOTE_RE.search(url)
    note_id = ""
    if m:
        note_id = m.group(1)
    elif XHS_NOTE_BARE.match(url.strip()):
        note_id = url.strip()
    if note_id:
        info["url"] = f"https://www.xiaohongshu.com/explore/{note_id}"
    for target in (info["url"], url):
        if not target.startswith("http"):
            continue
        try:
            raw = _http_get(
                target,
                headers={
                    "User-Agent": UA_MOBILE,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            ).decode("utf-8", "replace")
            title = _og(raw, "og:title") or _tag_title(raw)
            desc = _og(raw, "og:description")
            cover = _og(raw, "og:image")
            if not title:
                m2 = re.search(r'"title"\s*:\s*"([^"\\]{2,120})"', raw)
                if m2:
                    title = html.unescape(m2.group(1))
            if not desc:
                m2 = re.search(r'"desc"\s*:\s*"([^"\\]{2,300})"', raw)
                if m2:
                    desc = html.unescape(m2.group(1))
            if title or desc:
                info["title"] = title[:200]
                info["desc"] = desc[:500]
                info["cover"] = cover
                break
        except Exception:
            continue
    if not info["title"] and not info["desc"]:
        info["title"] = "\u5c0f\u7ea2\u4e66\u7b14\u8bb0"
        info["desc"] = "\u9875\u9762\u9700\u8981\u767b\u5f55\u6216\u53cd\u722c\u8f83\u4e25\uff0c\u53ea\u80fd\u544a\u8bc9\u4f60\u8fd9\u662f\u4e00\u6761\u5c0f\u7ea2\u4e66\u94fe\u63a5\uff5e"
    return info


def fetch_link(url: str) -> dict[str, str] | None:
    kind = classify_url(url)
    if kind == "bilibili":
        return fetch_bilibili(url)
    if kind == "xiaohongshu":
        return fetch_xiaohongshu(url)
    return None


def first_supported_url(text: str) -> tuple[str, str] | None:
    for u in extract_urls(text):
        kind = classify_url(u)
        if kind:
            return u, kind
    return None
