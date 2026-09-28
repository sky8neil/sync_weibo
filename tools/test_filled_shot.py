# -*- coding: utf-8 -*-
"""补拍「填写完成态」截图 + 校验修订后的 UI 文案"""
import os
import shutil

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/ext-tw-test-v3'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
SHOTS = '/home/fanfou-sender/evidence'

shutil.rmtree(UD, ignore_errors=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False,
        executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 460, 'height': 1000},
    )
    page = ctx.new_page()
    logs = []
    page.on('console', lambda m: logs.append(f'[{m.type}] {m.text[:140]}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {str(e)[:180]}'))
    page.goto(f'chrome-extension://{EXT_ID}/popup.html')
    page.wait_for_timeout(1500)
    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    page.reload()
    page.wait_for_timeout(2500)

    page.fill('#msg', '今天的分享：整理了几张照片，顺手试试双发小助手的新功能。')
    page.fill('#tags', '摄影 日常')
    page.click('#tagBtn')
    page.wait_for_timeout(400)
    page.set_input_files('#file', ['/tmp/akk_media/big.jpg'])
    page.wait_for_selector('.thumb', timeout=30000)
    page.wait_for_timeout(600)
    page.screenshot(path=f'{SHOTS}/popup_v2_filled.png')

    print('字数:', page.inner_text('#counter'))
    print('正文:', repr(page.input_value('#msg')[:90]))
    print('imgInfo:', page.inner_text('#imgInfo'))
    print('状态条:', page.inner_text('#statusbar'))
    print('控制台:', logs[-5:] if logs else '（无日志）')
    ctx.close()

print('截图: popup_v2_filled.png')
