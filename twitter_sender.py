#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""twitter_sender.py — X/Twitter 发送模块（基于现成库 twifork，cookie 会话，无官方 API）

依赖：项目内虚拟环境 .venv-tw（Python 3.12 + twifork[impersonate]）
凭据：state/tw_cookies.json —— 浏览器导出的 {"auth_token": "...", "ct0": "..."}
       （twifork 官方说明：密码登录已不可用，必须用 cookie 会话）

实测（2026-09-28）：
  * 图片：jpg / webp 直传均成功（bytes + media_type 指定），发布后核实 2 张图都在；
    X 官方规格：jpg/png/gif/webp、单张 ≤5MB、每推最多 4 张（本项目先压缩到 ≤2MB 再发）；
  * 正文：按权重计 280 上限（中文约 140 字）。

用法：
  .venv-tw/bin/python twitter_sender.py check              # 检查 cookie 是否有效
  .venv-tw/bin/python twitter_sender.py post "文本"         # 发推（纯文本）
  echo "文本" | .venv-tw/bin/python twitter_sender.py post
  echo '{"text":"..","images":[{"name":"a.webp","mime":"image/webp","b64":".."}]}' \
      | .venv-tw/bin/python twitter_sender.py post --json   # 发推（带图，≤4 张）
  .venv-tw/bin/python twitter_sender.py delete <tweet_id>
"""
import asyncio
import base64
import json
import os
import sys

from twikit import Client

STATE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'state')
COOKIES_FILE = os.path.join(STATE_DIR, 'tw_cookies.json')
MAX_IMAGES = 4  # X 单推图片上限（官方规格，2026-09 核实）


class TwitterError(Exception):
    pass


def _load_cookie_dict():
    if not os.path.exists(COOKIES_FILE):
        raise TwitterError(f'缺少 {COOKIES_FILE}（需从浏览器导出 x.com 的 auth_token 与 ct0）')
    with open(COOKIES_FILE, encoding='utf-8') as f:
        raw = json.load(f)
    cookies = {k: v for k, v in raw.items() if k in ('auth_token', 'ct0') and v}
    if len(cookies) < 2:
        raise TwitterError('cookie 不完整：至少需要 auth_token 与 ct0')
    return cookies


def make_client():
    client = Client('en-US', impersonate='chrome124')
    client.set_cookies(_load_cookie_dict())
    return client


async def check():
    client = make_client()
    ok = await client.is_logged_in()
    if not ok:
        raise TwitterError('cookie 已失效，请从浏览器重新导出')
    return 'cookie 有效'


async def post(text, images=None):
    """发推。

    images: [{'name': str, 'mime': str, 'data': bytes}, ...]，最多 4 张（超出忽略）。
    """
    text = (text or '').strip()
    images = (images or [])[:MAX_IMAGES]
    if not text and not images:
        raise TwitterError('内容为空')
    client = make_client()
    if not await client.is_logged_in():
        raise TwitterError('cookie 已失效，请从浏览器重新导出')
    media_ids = []
    for im in images:
        media_type = im.get('mime') or 'image/webp'
        media_ids.append(await client.upload_media(im['data'], media_type=media_type))
    tweet = await client.create_tweet(text=text, media_ids=media_ids or None)
    tid = getattr(tweet, 'id', None) or getattr(tweet, 'rest_id', None)
    return {
        'id': str(tid),
        'url': f'https://x.com/i/status/{tid}',
        'media_count': len(media_ids),
    }


async def delete(tweet_id):
    client = make_client()
    await client.delete_tweet(tweet_id)
    return {'id': tweet_id, 'deleted': True}


def _read_json_payload():
    payload = json.loads(sys.stdin.read())
    text = payload.get('text') or ''
    images = []
    for im in payload.get('images') or []:
        b64 = im.get('b64') or im.get('data') or ''
        pad = (-len(b64)) % 4
        images.append({
            'name': im.get('name') or 'image',
            'mime': im.get('mime') or 'image/webp',
            'data': base64.b64decode(b64 + '=' * pad),
        })
    return text, images


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    cmd = args[0]
    try:
        if cmd == 'check':
            print(asyncio.run(check()))
        elif cmd == 'post':
            rest = args[1:]
            if rest and rest[0] == '--json':
                text, images = _read_json_payload()
            elif rest:
                text, images = rest[0], []
            else:
                text, images = sys.stdin.read(), []
            print(json.dumps(asyncio.run(post(text, images)), ensure_ascii=False))
        elif cmd == 'delete':
            print(json.dumps(asyncio.run(delete(args[1])), ensure_ascii=False))
        else:
            print(__doc__)
            return 1
    except TwitterError as e:
        print(f'错误: {e}', file=sys.stderr)
        return 2
    except Exception as e:
        print(f'异常: {type(e).__name__}: {e}', file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
