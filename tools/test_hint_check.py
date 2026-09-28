# -*- coding: utf-8 -*-
"""插件标签字数提示校验（不发帖）：标签计入 X 权重；placeholder 更新检查"""
import os
import shutil

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/ext-hint-test'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
shutil.rmtree(UD, ignore_errors=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False, executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 460, 'height': 1080},
    )
    page = ctx.new_page()
    logs = []
    page.on('pageerror', lambda e: logs.append(str(e)[:150]))
    page.goto(f'chrome-extension://{EXT_ID}/popup.html')
    page.wait_for_timeout(1200)
    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    page.reload()
    page.wait_for_timeout(2500)

    page.fill('#msg', '测' * 138)
    page.wait_for_timeout(300)
    print('138 汉字（无标签，276 权重）:', page.inner_text('#counterHint') or '（无提示）')

    page.fill('#tags', '摄影 日常')
    page.wait_for_timeout(300)
    print('加上标签（+11 → 287）:', page.inner_text('#counterHint'))

    page.fill('#tags', '')
    page.wait_for_timeout(300)
    print('清掉标签:', page.inner_text('#counterHint') or '（无提示）')

    print('标签框 placeholder:', page.get_attribute('#tags', 'placeholder'))
    print('图片提示:', page.inner_text('#imgInfo'))
    print('页面错误:', logs if logs else '（无）')
    ctx.close()
print('DONE')
