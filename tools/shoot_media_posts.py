# -*- coding: utf-8 -*-
"""给两条验收帖截图：Akkoma 帖子页 + X 帖子页（注入 cookie 查看）"""
import json
import os

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

AK_URL = 'https://akkoma.skyneil.net/notice/BAr68N6KZvYVMlFO4m'
TW_URL = 'https://x.com/i/status/2104416439713280079'
SHOTS = '/home/fanfou-sender/evidence'
cookies = json.load(open('/home/fanfou-sender/state/tw_cookies.json'))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, executable_path='/usr/bin/chromium',
                                args=['--no-sandbox', '--disable-dev-shm-usage'])

    # ---- Akkoma 帖子页 ----
    try:
        ctx = browser.new_context(viewport={'width': 1000, 'height': 920})
        page = ctx.new_page()
        page.goto(AK_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)
        page.screenshot(path=f'{SHOTS}/media_akkoma_post.png')
        print('akkoma shot OK')
        ctx.close()
    except Exception as e:
        print('akkoma shot fail:', str(e)[:160])

    # ---- X 帖子页（注入登录 cookie）----
    try:
        ctx2 = browser.new_context(viewport={'width': 1100, 'height': 980})
        ctx2.add_cookies([
            {'name': 'auth_token', 'value': cookies['auth_token'], 'domain': '.x.com', 'path': '/'},
            {'name': 'ct0', 'value': cookies['ct0'], 'domain': '.x.com', 'path': '/'},
        ])
        page2 = ctx2.new_page()
        page2.goto(TW_URL, wait_until='domcontentloaded', timeout=90000)
        try:
            page2.wait_for_selector('article', timeout=30000)
            print('article 已出现')
            page2.wait_for_timeout(4000)
        except Exception:
            page2.wait_for_timeout(4000)
        page2.screenshot(path=f'{SHOTS}/media_twitter_post.png')
        print('twitter shot OK | title:', page2.title()[:70])
        ctx2.close()
    except Exception as e:
        print('twitter shot fail:', str(e)[:160])

    browser.close()

print('DONE')
