# -*- coding: utf-8 -*-
"""Chat plugin cache paths.

Default: D:\\AstrBot\\chat_cache (大肥鱼本机布局).
Override via plugin config `cache_root` — not a hard requirement for others.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CACHE_ROOT = Path(r"D:\AstrBot\chat_cache")
TMP_IMAGES_DIR_NAME = "tmp_images"


def cache_root(configured: str | None = None) -> Path:
    if configured and str(configured).strip():
        return Path(configured.strip())
    env = os.environ.get("DAFEIYU_CHAT_CACHE", "").strip()
    if env:
        return Path(env)
    return DEFAULT_CACHE_ROOT


def tmp_images_dir(configured: str | None = None) -> Path:
    d = cache_root(configured) / TMP_IMAGES_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_cache_dirs(configured: str | None = None) -> Path:
    root = cache_root(configured)
    root.mkdir(parents=True, exist_ok=True)
    (root / TMP_IMAGES_DIR_NAME).mkdir(parents=True, exist_ok=True)
    return root
