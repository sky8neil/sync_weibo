#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chat_post.py — hermes 发帖助手（走本机 fanfoux 服务）

给 hermes skill「fanfoux-post」用的稳定发送入口。

用法:
  python3 tools/chat_post.py --to all --text "内容" [--tag 标签]... [--image 图片路径]...
  python3 tools/chat_post.py --to fanfou --text "只在饭否"

说明:
  * --to: all | fanfou | akkoma | twitter（或组合：akkoma,twitter —— 与服务端同规则）
  * 图片会自动压缩为 webp ≤2MB（长边 ≤2560）再传给服务；
    饭否那侧由服务自动转 jpg（饭否只收 jpg/png/gif ≤2MB）
  * 多图分流（服务端内置）：同时发且 ≥2 张 → 第 1 张发饭否，其余发 Akkoma/X
  * 饭否帖会自动去掉 #标签（服务端内置）
  * 输出：JSON 结果 + 摘要行；退出码 0=全部成功，1=部分/全部失败，2=参数错

环境: 本机 fanfoux 服务需在跑（systemctl status fanfoux）；token 读 state/service_token.txt
"""
import argparse
import base64
import io
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TOKEN_FILE = os.path.join(ROOT, "state", "service_token.txt")
SERVICE = os.environ.get("FANFOUX_URL", "http://127.0.0.1:8788")
MAX_BYTES = 2 * 1024 * 1024
MAX_SIDE = 2560


def compress_image(path: str) -> dict:
    """压成 webp ≤2MB；动画 GIF 原样直传（≤2MB）。返回 {name,mime,b64}。"""
    data = open(path, "rb").read()
    name = (os.path.splitext(os.path.basename(path))[0] or "image")[:40]
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) <= MAX_BYTES:
        return {"name": name + ".gif", "mime": "image/gif",
                "data": base64.b64encode(data).decode()}
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("需要 Pillow 做图片压缩（pip install Pillow）")
    im = Image.open(io.BytesIO(data))
    if getattr(im, "is_animated", False):
        im.seek(0)
    im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > MAX_SIDE:
        r = MAX_SIDE / max(w, h)
        im = im.resize((max(1, int(w * r)), max(1, int(h * r))))
    buf = None
    for q in (85, 75, 65, 55, 45):
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=q, method=4)
        if buf.tell() <= MAX_BYTES:
            break
    if buf is None or buf.tell() > MAX_BYTES:
        raise SystemExit(f"图片压不进 2MB：{path}")
    return {"name": name + ".webp", "mime": "image/webp",
            "data": base64.b64encode(buf.getvalue()).decode()}


def main() -> int:
    p = argparse.ArgumentParser(description="hermes 发帖助手（走本机 fanfoux 服务）")
    p.add_argument("--to", default="all", help="all | fanfou | akkoma | twitter（可组合，如 akkoma,twitter）")
    p.add_argument("--text", required=True, help="正文")
    p.add_argument("--tag", action="append", default=[], help="标签（可多次；追加给 Akkoma/X，饭否自动去掉）")
    p.add_argument("--image", action="append", default=[], help="图片路径（可多次；自动压 webp ≤2MB）")
    a = p.parse_args()

    if not os.path.exists(TOKEN_FILE):
        print(f"错误：找不到 {TOKEN_FILE}", file=sys.stderr)
        return 2
    token = open(TOKEN_FILE).read().strip()

    images = []
    for path in a.image:
        if not os.path.exists(path):
            print(f"错误：图片不存在 {path}", file=sys.stderr)
            return 2
        images.append(compress_image(path))

    payload = {"token": token, "text": a.text, "to": a.to}
    if a.tag:
        payload["tags"] = a.tag
    if images:
        payload["images"] = images

    try:
        r = requests.post(SERVICE + "/send", json=payload, timeout=360)
    except requests.RequestException as e:
        print(f"错误：连不上本机服务 {SERVICE}（systemctl status fanfoux）—— {e}", file=sys.stderr)
        return 1
    try:
        j = r.json()
    except ValueError:
        print(f"错误：服务返回非 JSON（HTTP {r.status_code}）：{r.text[:200]}", file=sys.stderr)
        return 1

    print(json.dumps(j, ensure_ascii=False, indent=2))
    print()
    print("———— 摘要 ————")
    res = j.get("results", {})
    for plat, name in (("fanfou", "饭否"), ("akkoma", "Akkoma"), ("twitter", "X")):
        if plat in res:
            item = res[plat]
            if item.get("ok"):
                extra = []
                if item.get("media_count"):
                    extra.append(f"{item['media_count']} 图")
                if item.get("tags"):
                    extra.append("标签 " + " ".join("#" + t for t in item["tags"]))
                if item.get("tags_removed"):
                    extra.append(f"已去掉 {item['tags_removed']} 个 #标签")
                if item.get("truncated"):
                    extra.append("已截断")
                url = item.get("url") or ""
                fid = item.get("id") or ""
                print(f"  {name}: ✓ {fid} {' '.join(extra)} {url}".rstrip())
            else:
                print(f"  {name}: ✗ {item.get('error')}")
    for w in j.get("warnings", []):
        print(f"  提示：{w}")
    return 0 if j.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
