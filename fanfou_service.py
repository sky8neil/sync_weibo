#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanfou_service.py — 多平台发送 HTTP 服务（饭否 + Akkoma + Twitter，支持图片与标签）

给浏览器插件 / 其它程序提供一个简单的 HTTP 接口，把消息发到：
  * 饭否（复用 fanfou_sender.py 的网页会话通道）
  * 自建 Akkoma（akkoma_sender.py，Mastodon 兼容 API；支持图片、#标签）
  * Twitter / X（twitter_sender.py + twifork；cookie 会话，仅文字、按权重限 280）

接口一览：
  GET  /                            帮助页（无鉴权）
  GET  /health                      {"ok": true}（无鉴权，探活用）
  GET  /send?token=..&text=..&to=   发送（to: fanfou | akkoma | twitter | both | all，默认 fanfou；可用 &tags=a,b）
  POST /send                        发送；token 可放 query / X-Token 头 / body 字段
       正文支持：JSON、表单、纯文本 body；可选字段 to / target、tags、images
  GET  /status?token=..             两端账号状态 + 平台限制（limits）+ 最近发送记录

图片（Akkoma + Twitter/X；饭否不支持）：
  * JSON 里 "images": [{"name":"a.webp","mime":"image/webp","data":"<base64>"}]
    也接受 dataURL（"data:image/webp;base64,...."）或省略 mime（默认 image/webp）；
  * 插件端已压好再传：webp、每张 ≤2MB；Akkoma ≤16 张/次（实测），X ≤4 张（超出自动只发前 4 张）；
  * 服务端会按同一套限制复核，不合规直接 400 并说明原因。

标签（tags）：
  * "tags": ["科技","日常"] 或 "科技 日常"（逗号/空格/#分隔均可）；
  * 追加给 Akkoma 与 Twitter（#标签 形式加在结尾；已在正文里的不重复追加），饭否不追加。

返回（全部成功）: {"ok": true, "target": "both", "results": {...}, "warnings": [...]}
失败/部分失败   : {"ok": false, "results": {...}}（HTTP 502，results 里带各自错误）
参数/鉴权错误   : {"ok": false, "error": "..."}（400/403/413/429）

其它：
  * 饭否超过 140 字自动截断（响应里 truncated 标记）；Akkoma 正文上限 5000 字；
  * 除 /health 和帮助页外均需 token（state/service_token.txt 或环境变量 FANFOU_API_TOKEN）；
  * 默认只监听 127.0.0.1，对外部署时用 --host 0.0.0.0 显式暴露。
"""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from fanfou_sender import FanfouClient, FanfouError, UsageError, MAX_LEN  # noqa: E402
from akkoma_sender import AkkomaClient, AkkomaError  # noqa: E402

import requests  # noqa: E402

TOKEN_BODY_KEYS = ("token", "apikey", "api_key")
TEXT_KEYS = ("text", "message", "msg", "content", "notes", "selection",
             "selectedtext", "selected_text")
NESTED_KEYS = ("customfields", "custom_fields", "fields", "data")
TARGET_KEYS = ("to", "target", "platform", "dest", "destination")
TAGS_KEYS = ("tags", "tag", "topics", "labels")
IMAGES_KEYS = ("images", "files", "pics", "photos")

RATE_PER_MINUTE = 15
MAX_BODY = 64 * 1024 * 1024  # 64MB（图片 base64 需要）

# ---- 平台限制（2026-09-28 实测；Akkoma 3.20.0 / X 图片规格官方核对） ----
MAX_IMAGES_PER_POST = 16     # Akkoma 实测上限
MAX_TW_IMAGES = 4            # X 单推图片上限（官方规格）
PER_IMAGE_LIMIT = 2 * 1024 * 1024  # 插件端压缩目标 ≤2MB/张
ALLOWED_IMAGE_MIMES = {"image/webp", "image/jpeg", "image/png", "image/gif"}
TAGS_MAX = 30
TAG_LEN_MAX = 80

LIMITS = {
    "fanfou_max_chars": MAX_LEN,
    "akkoma_max_chars": 5000,
    "akkoma_upload_limit_bytes": 16_000_000,
    "max_images_per_post": MAX_IMAGES_PER_POST,
    "per_image_limit_bytes": PER_IMAGE_LIMIT,
    "image_mimes": sorted(ALLOWED_IMAGE_MIMES),
    "webp_supported": True,
    "twitter_max_weight": 280,
    "twitter_note": "X 按权重计字数：中文/全角/emoji 计 2、西文计 1；280 权重 ≈ 140 个汉字",
    "twitter_max_images": MAX_TW_IMAGES,
    "twitter_upload_limit_bytes": 5_242_880,
    "tested_at": "2026-09-28",
}

_TARGET_ALIASES = {
    "fanfou": "fanfou", "ff": "fanfou", "fan": "fanfou", "fou": "fanfou", "饭否": "fanfou",
    "akkoma": "akkoma", "ak": "akkoma", "mastodon": "akkoma",
    "twitter": "twitter", "x": "twitter", "tweet": "twitter", "推": "twitter",
    "both": "fanfou+akkoma", "双发": "fanfou+akkoma",
    "all": "fanfou+akkoma+twitter", "全发": "fanfou+akkoma+twitter", "全部": "fanfou+akkoma+twitter",
}

_PLATFORM_ORDER = ("fanfou", "akkoma", "twitter")
_SINGLE_ALIAS = {
    "fanfou": "fanfou", "ff": "fanfou", "fan": "fanfou", "饭否": "fanfou",
    "akkoma": "akkoma", "ak": "akkoma", "mastodon": "akkoma",
    "twitter": "twitter", "x": "twitter", "tw": "twitter", "tweet": "twitter", "推": "twitter",
}


def _lower_map(d):
    return {str(k).lower(): v for k, v in d.items()}


def parse_target(raw):
    """规范成平台组合键（默认 fanfou）。

    支持单平台：fanfou / akkoma / twitter（含别名 ff、ak、x…）
    与组合：both / all，或自由组合（逗号/加号分隔），如 "akkoma,twitter" → "akkoma+twitter"。
    """
    if not raw:
        return "fanfou"
    v = str(raw).strip().lower()
    if v in _TARGET_ALIASES:
        return _TARGET_ALIASES[v]
    parts = [p for p in re.split(r"[,，、+\s/|]+", v) if p]
    plats = []
    for p in parts:
        q = _SINGLE_ALIAS.get(p)
        if q is None:
            raise ValueError(p)
        if q not in plats:
            plats.append(q)
    if not plats:
        raise ValueError(v)
    plats.sort(key=_PLATFORM_ORDER.index)
    return "+".join(plats)


def parse_tags(raw):
    """把 tags 字段（字符串或数组）规范成去重后的标签列表（不带 #）。"""
    if not raw:
        return []
    if isinstance(raw, str):
        items = re.split(r"[,\uFF0C\u3001#\s]+", raw)
    elif isinstance(raw, list):
        items = [str(x) for x in raw]
    else:
        return []
    out, seen = [], set()
    for t in items:
        t = t.strip().lstrip("#").strip()
        if not t:
            continue
        t = t[:TAG_LEN_MAX]
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        out.append(t)
    return out[:TAGS_MAX]


def append_tags(text: str, tags):
    """把标签以 # 形式追加到正文结尾（已在正文里的不重复追加）。

    返回 (新文本, 本次实际追加的标签列表)。Akkoma 与 Twitter 共用同一逻辑。
    """
    missing = [t for t in (tags or []) if ("#" + t) not in text]
    if not missing:
        return text, []
    sep = "\n\n" if "\n" in text else " "
    return text + sep + " ".join("#" + t for t in missing), missing


def parse_images(raw):
    """校验并解码图片数组。返回 (列表, 错误信息)。

    每张: {"name":..., "mime":..., "data": base64 或 dataURL}
    """
    if not raw:
        return [], None
    if not isinstance(raw, list):
        return None, "images 必须是数组"
    if len(raw) > MAX_IMAGES_PER_POST:
        return None, f"一次最多 {MAX_IMAGES_PER_POST} 张图（Akkoma 实测上限）"
    out = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            return None, f"第 {i} 张格式错误（应为对象）"
        data = item.get("data") or item.get("base64") or item.get("content")
        if not isinstance(data, str) or not data:
            return None, f"第 {i} 张缺少 data（base64）"
        mime = str(item.get("mime") or item.get("type") or "").strip().lower()
        if data.startswith("data:"):
            head, _, b64 = data.partition(",")
            if not b64:
                return None, f"第 {i} 张 dataURL 格式错误"
            if not mime:
                mime = head[5:].split(";")[0].strip().lower()
            data = b64
        mime = mime or "image/webp"
        if mime not in ALLOWED_IMAGE_MIMES:
            return None, f"第 {i} 张类型不支持：{mime}（支持 webp/jpeg/png/gif）"
        try:
            pad = (-len(data)) % 4
            blob = base64.b64decode(data + "=" * pad)
        except Exception:
            return None, f"第 {i} 张 base64 解码失败"
        if len(blob) > PER_IMAGE_LIMIT:
            return None, f"第 {i} 张 {len(blob) // 1024}KB，超过 2MB 限制（请先压缩）"
        name = str(item.get("name") or f"image{i}")[:120]
        out.append({"name": name, "mime": mime, "data": blob})
    return out, None


def extract_request(obj, raw_body: bytes):
    """从请求体中提取 (消息文本, token, to, tags, images)。"""
    if obj is None:
        s = raw_body.decode("utf-8", "replace").strip()
        return (s or None), None, None, None, None
    if isinstance(obj, str):
        return (obj.strip() or None), None, None, None, None
    if not isinstance(obj, dict):
        return None, None, None, None, None
    lm = _lower_map(obj)
    token = None
    for k in TOKEN_BODY_KEYS:
        v = lm.get(k)
        if isinstance(v, str) and v:
            token = v
            break
    text = None
    for k in TEXT_KEYS:
        v = lm.get(k)
        if isinstance(v, str) and v.strip():
            text = v.strip()
            break
    if text is None:
        for nk in NESTED_KEYS:
            nested = lm.get(nk)
            if isinstance(nested, dict):
                nl = _lower_map(nested)
                for k in TEXT_KEYS:
                    v = nl.get(k)
                    if isinstance(v, str) and v.strip():
                        text = v.strip()
                        break
            if text:
                break
    to_raw = None
    for k in TARGET_KEYS:
        v = lm.get(k)
        if isinstance(v, str) and v.strip():
            to_raw = v.strip()
            break
    tags_raw = None
    for k in TAGS_KEYS:
        v = lm.get(k)
        if v:
            tags_raw = v
            break
    images_raw = None
    for k in IMAGES_KEYS:
        v = lm.get(k)
        if isinstance(v, list) and v:
            images_raw = v
            break
    return text, token, to_raw, tags_raw, images_raw


class TwitterError(Exception):
    """Twitter（X）通道错误"""


PROJECT_DIR = os.path.dirname(os.path.realpath(__file__))
TW_VENV_PY = os.path.join(PROJECT_DIR, ".venv-tw", "bin", "python")
TW_MODULE = os.path.join(PROJECT_DIR, "twitter_sender.py")


def twitter_weight(text: str) -> int:
    """X（Twitter）加权字数：CJK/全角/emoji 计 2，其余计 1；上限 280。"""
    w = 0
    for ch in text:
        o = ord(ch)
        if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or 0xAC00 <= o <= 0xD7A3
                or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F or 0xFF00 <= o <= 0xFF60
                or 0xFFE0 <= o <= 0xFFE6 or 0x1F000 <= o <= 0x1FAFF or 0x20000 <= o <= 0x3FFFD):
            w += 2
        else:
            w += 1
    return w


def _run_tw_cli(action: str, stdin_text: str = None, timeout: int = 180, cmd_args=None) -> str:
    """在 .venv-tw（Py3.12 + twifork）里跑 twitter_sender.py（子进程隔离）。"""
    if not os.path.exists(TW_VENV_PY):
        raise TwitterError("未安装 twifork 环境（.venv-tw 不存在）")
    r = subprocess.run(
        [TW_VENV_PY, TW_MODULE, action] + list(cmd_args or []),
        input=stdin_text, capture_output=True, text=True, timeout=timeout, cwd=PROJECT_DIR,
    )
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or "").strip().splitlines()
        raise TwitterError(lines[-1][:300] if lines else f"退出码 {r.returncode}")
    return (r.stdout or "").strip()


def twitter_post(text: str, images=None) -> dict:
    """发推（复用 twitter_sender.py；凭据 state/tw_cookies.json）。

    images: [{'name','mime','data'(bytes)}] —— 最多 4 张（超出忽略）。
    """
    images = (images or [])[:MAX_TW_IMAGES]
    if images:
        payload = {
            "text": text,
            "images": [
                {"name": im.get("name") or "image",
                 "mime": im.get("mime") or "image/webp",
                 "b64": base64.b64encode(im["data"]).decode()}
                for im in images
            ],
        }
        out = _run_tw_cli("post", stdin_text=json.dumps(payload), cmd_args=["--json"])
    else:
        out = _run_tw_cli("post", stdin_text=text)
    try:
        return json.loads(out.splitlines()[-1])
    except (ValueError, IndexError):
        raise TwitterError(f"返回解析失败: {out[:200]}")


def twitter_check() -> str:
    """检查 cookie 是否有效，返回说明文本。"""
    return _run_tw_cli("check", timeout=90)


class Service:
    def __init__(self, state_dir: str, token: str):
        self.state_dir = state_dir
        self.token = token
        self.client = FanfouClient(state_dir)
        self.lock = threading.Lock()
        self.hits: deque = deque()
        self.recent = deque(maxlen=10)
        self.akkoma = None
        try:
            self.akkoma = AkkomaClient(state_dir)
        except AkkomaError as e:
            self.log(f"akkoma 未启用：{e}")

    def rate_ok(self) -> bool:
        now = time.time()
        while self.hits and now - self.hits[0] > 60:
            self.hits.popleft()
        if len(self.hits) >= RATE_PER_MINUTE:
            return False
        self.hits.append(now)
        return True

    def log(self, line: str) -> None:
        try:
            with open(os.path.join(self.state_dir, "service.log"), "a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
        except OSError:
            pass

    def remember(self, entry: dict) -> None:
        self.recent.append(entry)


class Handler(BaseHTTPRequestHandler):
    server_version = "fanfoux/3.0"
    protocol_version = "HTTP/1.1"

    @property
    def svc(self) -> Service:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, *args):
        pass

    def _path(self) -> str:
        """兼容未做百分号编码、直接发原始 UTF-8 的客户端。"""
        p = self.path
        if any(ord(c) > 127 for c in p):
            try:
                p = p.encode("iso-8859-1", "ignore").decode("utf-8", "strict")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return p

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _html(self, code: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token, X-Api-Key, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self._path())
        qs = {k: v[-1] for k, v in parse_qs(u.query).items()}
        if u.path == "/health":
            self._json(200, {"ok": True, "service": "fanfoux"})
            return
        if u.path in ("/send", "/"):
            if qs.get("text"):
                self._handle_send(text=qs["text"], token=qs.get("token"), src="GET",
                                  to_raw=qs.get("to"), tags_raw=qs.get("tags"), images_raw=None)
                return
            self._html(200, HELP_HTML)
            return
        if u.path == "/status":
            self._handle_status(token=qs.get("token"))
            return
        if u.path == "/limits":
            self._json(200, {"ok": True, "limits": LIMITS})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        u = urlparse(self._path())
        if u.path not in ("/send", "/"):
            self._json(404, {"ok": False, "error": "not found"})
            return
        qs = {k: v[-1] for k, v in parse_qs(u.query).items()}
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._json(413, {"ok": False, "error": f"请求体过大（>{MAX_BODY // 1024 // 1024}MB）"})
            return
        raw = self.rfile.read(length) if length > 0 else b""
        ctype = (self.headers.get("Content-Type") or "").lower()
        obj = None
        if raw:
            body_text = raw.decode("utf-8", "replace").strip()
            if body_text.startswith("{") or body_text.startswith("["):
                try:
                    obj = json.loads(body_text)
                except ValueError:
                    obj = None
            elif "application/x-www-form-urlencoded" in ctype:
                obj = {k: v[-1] for k, v in parse_qs(body_text).items()}
        text, body_token, body_to, body_tags, body_images = extract_request(obj, raw)
        header_token = (self.headers.get("X-Token") or self.headers.get("X-Api-Key")
                        or self.headers.get("X-Api-Token"))
        auth = self.headers.get("Authorization") or ""
        if not header_token and auth.lower().startswith("bearer "):
            header_token = auth[7:].strip()
        self._handle_send(
            text=text,
            token=qs.get("token") or header_token or body_token,
            src="POST",
            to_raw=qs.get("to") or body_to,
            tags_raw=qs.get("tags") or body_tags,
            images_raw=body_images,
        )

    # ---------- 业务 ----------
    def _auth(self, token) -> bool:
        return bool(token) and hmac.compare_digest(str(token), self.svc.token)

    def _handle_send(self, text, token, src: str, to_raw, tags_raw=None, images_raw=None) -> None:
        if not self._auth(token):
            self._json(403, {"ok": False, "error": "token 缺失或不正确"})
            return
        if not self.svc.rate_ok():
            self._json(429, {"ok": False, "error": "发送频率过高（>15/分钟），请稍后再试"})
            return
        try:
            target = parse_target(to_raw)
        except ValueError as e:
            self._json(400, {"ok": False, "error": f"to 参数不认识：{e}（可选 fanfou / akkoma / twitter / both / all）"})
            return
        tags = parse_tags(tags_raw)
        images, img_err = parse_images(images_raw)
        if img_err:
            self._json(400, {"ok": False, "error": img_err})
            return
        if not text and not images:
            self._json(400, {"ok": False, "error": "没找到消息文本（可用 text/message/content/notes 等字段，或纯文本 body）"})
            return
        if images and target == "fanfou":
            self._json(400, {"ok": False, "error": "饭否不支持图片：请改选「发 Akkoma / 发 Twitter / 同时发」，或去掉图片"})
            return

        platforms = target.split("+")
        results = {}
        warnings = []
        if "fanfou" in platforms:
            truncated = len(text) > MAX_LEN
            try:
                with self.svc.lock:
                    res = self.svc.client.send(text[:MAX_LEN], truncate=True)
                fr = {"ok": True, "id": res["fid"], "verified": res["verified"],
                      "truncated": truncated, "msg": res["server_msg"]}
                if images:
                    fr["images_skipped"] = True
                results["fanfou"] = fr
            except (UsageError, FanfouError, requests.RequestException) as e:
                results["fanfou"] = {"ok": False, "error": str(e)}

        if "akkoma" in platforms:
            if self.svc.akkoma is None:
                results["akkoma"] = {"ok": False, "error": "未配置 Akkoma token（state/akkoma_token.txt）"}
            else:
                ak_text, applied_tags = append_tags(text, tags)
                media_ids = []
                up_err = None
                for i, im in enumerate(images, 1):
                    try:
                        with self.svc.lock:
                            up = self.svc.akkoma.upload_media(im["data"], im["name"], im["mime"])
                        media_ids.append(up["id"])
                    except (AkkomaError, requests.RequestException) as e:
                        up_err = f"第 {i} 张图上传失败：{e}"
                        break
                if up_err:
                    results["akkoma"] = {"ok": False, "error": up_err}
                else:
                    try:
                        with self.svc.lock:
                            res = self.svc.akkoma.post(ak_text, media_ids=media_ids)
                        results["akkoma"] = {"ok": True, "id": res["id"], "url": res["url"],
                                             "media_count": res["media_count"], "tags": applied_tags}
                    except (AkkomaError, requests.RequestException) as e:
                        results["akkoma"] = {"ok": False, "error": str(e)}

        if "twitter" in platforms:
            tw_images = images[:MAX_TW_IMAGES]
            tw_text, tw_tags = append_tags(text, tags)
            if not tw_text.strip() and not tw_images:
                results["twitter"] = {"ok": False, "error": "推文内容为空"}
            else:
                w = twitter_weight(tw_text)
                if w > LIMITS["twitter_max_weight"]:
                    results["twitter"] = {
                        "ok": False,
                        "error": f"推文超限（加权 {w}/{LIMITS['twitter_max_weight']}，约合 {w // 2} 个汉字；含标签）——请精简后重发",
                    }
                else:
                    try:
                        res = twitter_post(tw_text, tw_images)
                        results["twitter"] = {"ok": True, "id": res.get("id"), "url": res.get("url"),
                                              "weight": w, "media_count": res.get("media_count", 0),
                                              "tags": tw_tags}
                    except (TwitterError, subprocess.SubprocessError) as e:
                        results["twitter"] = {"ok": False, "error": f"Twitter 通道失败：{e}"}

        if images and "fanfou" in platforms:
            warnings.append("饭否不支持图片：本次饭否仅发文字（图片发到 Akkoma / X）")
        if ("twitter" in platforms and len(images) > MAX_TW_IMAGES
                and results.get("twitter", {}).get("ok")):
            warnings.append(f"X 单帖最多 {MAX_TW_IMAGES} 张图：本次只发前 {MAX_TW_IMAGES} 张到 X（其余仅发 Akkoma）")

        ok = bool(results) and all(r.get("ok") for r in results.values())
        payload = {"ok": ok, "target": target, "results": results}
        if warnings:
            payload["warnings"] = warnings
        if target == "fanfou" and "fanfou" in results:
            fr = results["fanfou"]
            for k in ("id", "verified", "truncated", "msg"):
                if k in fr:
                    payload[k] = fr[k]
            if not fr["ok"]:
                payload["error"] = fr.get("error")
        if target == "akkoma" and "akkoma" in results:
            ar = results["akkoma"]
            if ar.get("ok"):
                payload["id"], payload["url"] = ar.get("id"), ar.get("url")
                payload["media_count"] = ar.get("media_count", 0)
            else:
                payload["error"] = ar.get("error")
        if target == "twitter" and "twitter" in results:
            tr = results["twitter"]
            if tr.get("ok"):
                payload["id"], payload["url"] = tr.get("id"), tr.get("url")
                payload["weight"] = tr.get("weight")
            else:
                payload["error"] = tr.get("error")

        self.svc.remember({
            "time": datetime.now().isoformat(timespec="seconds"),
            "target": target, "ok": ok, "len": len(text), "images": len(images),
        })
        self.svc.log(
            f"[{src}] target={target} ok={ok} len={len(text)} imgs={len(images)} "
            f"fanfou={results.get('fanfou', {}).get('id')} akkoma={results.get('akkoma', {}).get('id')} "
            f"twitter={results.get('twitter', {}).get('id')}"
        )
        self._json(200 if ok else 502, payload)

    def _handle_status(self, token) -> None:
        if not self._auth(token):
            self._json(403, {"ok": False, "error": "token 缺失或不正确"})
            return
        try:
            with self.svc.lock:
                st = self.svc.client.status()
            fanfou = {
                "ok": True,
                "user": st["display_name"],
                "profile": "https://fanfou.com" + (st["profile_path"] or ""),
                "session_expires": st["session_expires"],
            }
        except (FanfouError, requests.RequestException) as e:
            fanfou = {"ok": False, "error": str(e)}
        akkoma = None
        if self.svc.akkoma is not None:
            try:
                with self.svc.lock:
                    akkoma = {"ok": True, **self.svc.akkoma.me()}
            except (AkkomaError, requests.RequestException) as e:
                akkoma = {"ok": False, "error": str(e)}
        try:
            twitter = {"ok": True, "user": twitter_check()}
        except (TwitterError, subprocess.SubprocessError) as e:
            twitter = {"ok": False, "error": str(e)[:200]}
        self._json(200, {"ok": True, "fanfou": fanfou, "akkoma": akkoma, "twitter": twitter,
                         "limits": LIMITS, "recent": list(self.svc.recent)})


HELP_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>fanfoux</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:48px auto;padding:0 20px;line-height:1.7}
code{background:#f4f4f4;padding:2px 6px;border-radius:4px}pre{background:#f4f4f4;padding:12px;border-radius:8px;overflow:auto}</style>
</head><body><h1>fanfoux 运行中 ✅</h1>
<p>饭否 + Akkoma 多平台发送接口（供浏览器插件等调用）。</p>
<h3>纯文本</h3>
<pre>POST /send
Content-Type: application/json

{"token": "&lt;token&gt;", "text": "要发的消息", "to": "both"}</pre>
<p><code>to</code> 可选 <code>fanfou</code>（默认）/ <code>akkoma</code> / <code>twitter</code> / <code>both</code>（饭否+Akkoma）/ <code>all</code>（三平台全发）。</p>
<p>Twitter（X）：支持图片（≤4 张）；正文按权重计 280（中文约 140 字）；#标签 同样会追加。</p>
<h3>带图 + 标签（Akkoma 与 X 支持；饭否不支持图片）</h3>
<pre>{"token": "&lt;token&gt;", "text": "正文", "to": "akkoma",
 "tags": ["科技", "日常"],
 "images": [{"name": "a.webp", "mime": "image/webp", "data": "&lt;base64&gt;"}]}</pre>
<p>图片：webp 优先、每张 ≤2MB、最多 16 张/次（Akkoma 实测限制）；<code>tags</code> 会以 #标签 追加到 Akkoma 正文结尾（饭否不追加）。</p>
<p>限制查询：<code>GET /limits</code>；状态：<code>GET /status?token=...</code>；探活：<code>/health</code>。</p>
</body></html>"""


def load_token(state_dir: str, override: str = None) -> str:
    if override:
        return override
    env = os.environ.get("FANFOU_API_TOKEN")
    if env:
        return env
    path = os.path.join(state_dir, "service_token.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    t = secrets.token_urlsafe(18)
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(t + "\n")
    os.chmod(path, 0o600)
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="多平台发送 HTTP 服务（饭否 + Akkoma）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1；对外用 0.0.0.0）")
    ap.add_argument("--port", type=int, default=8788, help="监听端口（默认 8788）")
    ap.add_argument("--state-dir", default=os.path.join(os.path.dirname(os.path.realpath(__file__)), "state"),
                    help="状态目录（默认 ./state）")
    ap.add_argument("--token", default=None, help="鉴权 token（默认读 state/service_token.txt，不存在则生成）")
    a = ap.parse_args(argv)

    token = load_token(a.state_dir, a.token)
    service = Service(a.state_dir, token)
    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    httpd.service = service  # type: ignore[attr-defined]
    print(f"fanfoux listening on http://{a.host}:{a.port} (token: {token[:8]}…)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
