# -*- coding: utf-8 -*-
"""Thin LLM helper using AstrBot provider."""
from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.core.provider.provider import Provider


async def get_provider(context, provider_id: str, event) -> Provider | None:
    provider = None
    if provider_id:
        provider = context.get_provider_by_id(provider_id)
    if not isinstance(provider, Provider):
        umo = getattr(event, "unified_msg_origin", None)
        try:
            provider = context.get_using_provider(umo)
        except Exception:
            provider = context.get_using_provider()
    return provider if isinstance(provider, Provider) else None


async def short_chat(
    context,
    event,
    *,
    system_prompt: str,
    prompt: str,
    provider_id: str = "",
) -> str | None:
    provider = await get_provider(context, provider_id, event)
    if not isinstance(provider, Provider):
        logger.warning("[dafeiyu_chat] no LLM provider")
        return None
    try:
        resp = await provider.text_chat(system_prompt=system_prompt, prompt=prompt)
        text = (resp.completion_text or "").strip()
        # strip markdown fences lightly
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("text"):
                text = text[4:].lstrip()
        return text.strip() or None
    except Exception as e:
        logger.error(f"[dafeiyu_chat] LLM fail: {e}")
        return None
