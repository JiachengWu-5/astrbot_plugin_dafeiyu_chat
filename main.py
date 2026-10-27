# -*- coding: utf-8 -*-
"""大肥鱼私聊助手：链接摘要 + 搜图/生图。\n\nAuthor: Grok Bot (Ideas Implementation)."""
from __future__ import annotations

import asyncio
import re
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .core import images as img_mod
from .core import links as link_mod
from .core.cache_paths import ensure_cache_dirs
from .core.llm_helper import short_chat

DEFAULT_SUMMARY_PROMPT = (
    "你是大肥鱼，说话短、软、口语化，像朋友私聊。"
    "用户发来 B站或小红书链接时，根据提供的标题/简介写一段 2～4 句的短摘要，"
    "带一点你的吐槽或情绪，不要机械复述，不要用 markdown，不要说「作为AI」。"
)


class DafeiyuChat(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        ensure_cache_dirs(self._cache_root())

    def _cache_root(self) -> str:
        return str(self.conf.get("cache_root") or r"D:\AstrBot\chat_cache")

    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _owner_ok(self, event: AstrMessageEvent) -> bool:
        owner = str(self.conf.get("owner_qq") or "").strip()
        if not owner:
            return True
        try:
            sid = str(event.get_sender_id() or "")
        except Exception:
            sid = ""
        return sid == owner or event.is_admin()

    def _link_cfg(self) -> dict[str, Any]:
        v = self.conf.get("link_summarize")
        return v if isinstance(v, dict) else {}

    def _img_cfg(self) -> dict[str, Any]:
        v = self.conf.get("image")
        return v if isinstance(v, dict) else {}

    def _mark_handled(self, event: AstrMessageEvent) -> None:
        try:
            event.should_call_llm(False)
        except Exception:
            pass
        try:
            event.stop_event()
        except Exception:
            pass

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=80)
    async def on_private(self, event: AstrMessageEvent):
        if not self._enabled() or not self._owner_ok(event):
            return
        text = (event.message_str or "").strip()
        if not text:
            return

        # 1) Link summarize takes priority when a supported URL is present
        hit = link_mod.first_supported_url(text)
        if hit and bool(self._link_cfg().get("enabled", True)):
            await self._handle_link(event, hit[0], hit[1])
            return

        # 2) Image see-intent
        if bool(self._img_cfg().get("enabled", True)) and img_mod.is_see_intent(text):
            await self._handle_see(event, text)
            return

    async def _handle_link(self, event: AstrMessageEvent, url: str, kind: str) -> None:
        self._mark_handled(event)
        await event.send(event.plain_result("我去瞅瞅这条链接～"))
        try:
            meta = await asyncio.to_thread(link_mod.fetch_link, url)
        except Exception as e:
            logger.warning(f"[dafeiyu_chat] fetch fail: {e}")
            meta = None
        if not meta:
            await event.send(event.plain_result("这条链接我打不开呀，你换个能点的再发我一次？"))
            return

        title = meta.get("title") or ""
        desc = meta.get("desc") or ""
        author = meta.get("author") or ""
        final_url = meta.get("url") or url
        src = "B站" if kind == "bilibili" else "小红书"

        facts = (
            f"来源：{src}\n标题：{title}\n作者：{author}\n简介：{desc}\n链接：{final_url}"
        )
        cfg = self._link_cfg()
        system = str(cfg.get("system_prompt") or DEFAULT_SUMMARY_PROMPT)
        summary = await short_chat(
            self.context,
            event,
            system_prompt=system,
            prompt=f"请根据下面信息用大肥鱼语气写短摘要：\n{facts}",
            provider_id=str(cfg.get("provider_id") or ""),
        )
        if not summary:
            # fallback without LLM
            bits = [f"我翻到了这条{src}～"]
            if title:
                bits.append(f"标题是「{title}」。")
            if desc:
                bits.append(desc[:80] + ("…" if len(desc) > 80 else ""))
            if final_url:
                bits.append(final_url)
            summary = "\n".join(bits)
        elif final_url and final_url not in summary:
            summary = f"{summary}\n{final_url}"
        await event.send(event.plain_result(summary))

    async def _handle_see(self, event: AstrMessageEvent, text: str) -> None:
        self._mark_handled(event)
        query = img_mod.extract_see_query(text) or "可爱日常"
        cfg = self._img_cfg()
        max_bytes = int(cfg.get("max_bytes") or 1_048_576)
        prefer_search = bool(cfg.get("prefer_search", True))
        cache = self._cache_root()

        await event.send(event.plain_result(f"我去找找「{query}」的图～"))

        path = None
        kind = "none"
        gen_note = ""

        if prefer_search:
            try:
                path = await asyncio.to_thread(
                    img_mod.search_and_download, query, cache, max_bytes
                )
                if path:
                    kind = "search"
            except Exception as e:
                logger.warning(f"[dafeiyu_chat] search fail: {e}")

        if not path:
            backend = str(cfg.get("gen_backend") or "stub").lower()
            if backend == "ollama":
                path2, err = await asyncio.to_thread(
                    img_mod.try_ollama_generate,
                    query,
                    base=str(cfg.get("ollama_base") or "http://127.0.0.1:11434"),
                    model=str(cfg.get("ollama_model") or ""),
                    cache_root=cache,
                )
                if path2:
                    path, kind = path2, "gen"
                else:
                    gen_note = err or "生图暂时不行～"
            else:
                gen_note = (
                    "搜图没找到合适的，生图也还没配好模型（本机 Ollama 目前不像有出图模型），"
                    "你换个说法我再搜搜？"
                )

        if not path:
            await event.send(event.plain_result(gen_note or "这回图没找着，稍后再试？"))
            return

        caption = ""
        if bool(cfg.get("caption_with_llm", True)):
            caption = await short_chat(
                self.context,
                event,
                system_prompt="你是大肥鱼，说话短软口语化。用户让你找图，你发图时附一句很短的配文，不要 markdown。",
                prompt=f"我准备发一张和「{query}」有关的图（来源：{kind}），写一句 15 字以内的配文。",
                provider_id=str(self._link_cfg().get("provider_id") or ""),
            ) or ""
        if not caption:
            caption = f"找到啦，给你看「{query}」～"

        try:
            await event.send(
                event.chain_result([Plain(caption), Image.fromFileSystem(path)])
            )
        except Exception as e:
            logger.error(f"[dafeiyu_chat] send image fail: {e}")
            await event.send(event.plain_result(f"{caption}\n（图发出去失败了：{e}）"))
        finally:
            img_mod.cleanup_temp(path, cache)

    @filter.command("私聊助手状态", alias={"chat助手状态", "看图状态"})
    async def status_cmd(self, event: AstrMessageEvent):
        if not self._owner_ok(event):
            return
        self._mark_handled(event)
        ensure_cache_dirs(self._cache_root())
        msg = (
            f"大肥鱼私聊助手 v0.1.0\n"
            f"启用={self._enabled()} 链接={self._link_cfg().get('enabled', True)} "
            f"看图={self._img_cfg().get('enabled', True)}\n"
            f"生图后端={self._img_cfg().get('gen_backend', 'stub')} "
            f"模型={self._img_cfg().get('ollama_model') or '(空)'}\n"
            f"缓存={self._cache_root()}"
        )
        yield event.plain_result(msg)
