#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""akkoma_sender.py — Akkoma（Mastodon 兼容 API）发帖 + 图片上传模块

供 fanfou_service / 其它脚本复用：把消息（可带图）发到自建 Akkoma。

凭据：state/akkoma_token.txt（一行纯 token）；或环境变量 AKKOMA_TOKEN
地址：默认 https://akkoma.skyneil.net ；或环境变量 AKKOMA_BASE_URL

实测（2026-09-28，Akkoma 3.20.0）：
  * POST /api/v2/media 上传（jpg/webp 均可，webp 支持 ✓）
  * POST /api/v1/statuses 带 media_ids[] 发帖（10 张、16 张实测通过）
  * 单文件上限 16MB（实例 config upload_limit: 16_000_000）
  * 帖子正文上限 5000 字
  * DELETE /api/v1/media/:id 不支持（404）；删除状态后附件由实例自动清理
"""

from __future__ import annotations

import os
import time

import requests

DEFAULT_BASE = "https://akkoma.skyneil.net"

# 实例限制（2026-09-28 实测/配置读出）
MAX_MEDIA_PER_POST = 16          # 实测 10、16 张均通过
UPLOAD_LIMIT_BYTES = 16_000_000  # 实例 config: upload_limit
SUPPORTED_IMAGE_MIMES = ("image/webp", "image/jpeg", "image/png", "image/gif")


class AkkomaError(Exception):
    """Akkoma 操作失败"""


class AkkomaClient:
    def __init__(self, state_dir: str, base_url: str = None, token: str = None, timeout: int = 30):
        self.state_dir = os.path.abspath(state_dir)
        self.base = (base_url or os.environ.get("AKKOMA_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self.timeout = timeout
        self.token = token or os.environ.get("AKKOMA_TOKEN") or self._load_token()

    def _load_token(self) -> str:
        path = os.path.join(self.state_dir, "akkoma_token.txt")
        try:
            with open(path, encoding="utf-8") as f:
                t = f.read().strip()
        except OSError:
            t = ""
        if not t:
            raise AkkomaError(f"缺少 Akkoma token（{path} 或环境变量 AKKOMA_TOKEN）")
        return t

    def _headers(self) -> dict:
        return {"Authorization": "Bearer " + self.token}

    # ---------- 媒体 ----------
    def upload_media(self, data: bytes, filename: str = "file.webp", mime: str = "image/webp",
                     description: str = "") -> dict:
        """上传媒体到 /api/v2/media。成功返回 {"id":..., "url":...}

        v2 为异步接口（返回 202）：若响应里没有 url，则轮询 /api/v1/media/:id 直到就绪。
        """
        files = {"file": (filename, data, mime)}
        extra = {"description": description} if description else None
        r = requests.post(
            f"{self.base}/api/v2/media",
            headers=self._headers(),
            files=files,
            data=extra,
            timeout=180,
        )
        if r.status_code not in (200, 202):
            raise AkkomaError(f"图片上传失败 HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        media_id = str(d.get("id"))
        url = d.get("url")
        for _ in range(30):
            if url:
                break
            time.sleep(1)
            rr = requests.get(f"{self.base}/api/v1/media/{media_id}", headers=self._headers(), timeout=30)
            if rr.status_code == 200:
                url = rr.json().get("url")
        return {"id": media_id, "url": url}

    # ---------- 发帖 ----------
    def post(self, text: str, media_ids=None, visibility: str = "public") -> dict:
        """发帖（可带图）。media_ids: list[str]，不超过 MAX_MEDIA_PER_POST。"""
        data = {"status": text, "visibility": visibility}
        media_ids = [str(m) for m in (media_ids or [])]
        if media_ids:
            data["media_ids[]"] = media_ids
        r = requests.post(
            f"{self.base}/api/v1/statuses",
            headers=self._headers(),
            data=data,
            timeout=90,
        )
        if r.status_code not in (200, 202):
            raise AkkomaError(f"发帖失败 HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        return {
            "id": str(d.get("id")),
            "url": d.get("url"),
            "visibility": d.get("visibility"),
            "media_count": len(media_ids),
        }

    def delete(self, status_id: str) -> bool:
        r = requests.delete(
            f"{self.base}/api/v1/statuses/{status_id}",
            headers=self._headers(),
            timeout=30,
        )
        if r.status_code not in (200, 202, 204):
            raise AkkomaError(f"删帖失败 HTTP {r.status_code}: {r.text[:200]}")
        return True

    def verify(self, status_id: str) -> bool:
        """核实帖子可见（返回 True/False）"""
        try:
            r = requests.get(
                f"{self.base}/api/v1/statuses/{status_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            return r.status_code == 200
        except requests.RequestException:
            return False

    def me(self) -> dict:
        """校验 token 并返回账号信息"""
        r = requests.get(
            f"{self.base}/api/v1/accounts/verify_credentials",
            headers=self._headers(),
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise AkkomaError(f"token 校验失败 HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        return {"acct": d.get("acct"), "display_name": d.get("display_name"), "url": d.get("url")}
