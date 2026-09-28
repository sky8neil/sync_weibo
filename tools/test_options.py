# -*- coding: utf-8 -*-
"""测试扩展设置页：保存配置 + 测试连接按钮"""
import os
import shutil
import time

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'  # manifest 的 key 固定了这个 ID
UD = '/tmp/ext-profile-test2'
shutil.rmtree(UD, ignore_errors=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False,
        executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 760, 'height': 720},
    )
    ext_id = EXT_ID
    print('ext id:', ext_id)

    page = ctx.new_page()
    logs = []
    page.on('console', lambda m: logs.append(f'[console:{m.type}] {m.text}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {e}'))
    page.goto(f'chrome-extension://{ext_id}/options.html')

    token = open('/home/fanfou-sender/state/service_token.txt').read().strip()
    page.fill('#serviceUrl', 'http://127.0.0.1:8788')
    page.fill('#token', token)
    page.click('#save')
    page.wait_for_timeout(600)
    print('保存后状态:', page.inner_text('#status'))

    page.click('#test')
    page.wait_for_timeout(9000)
    print('=== 测试连接结果 ===')
    print(page.inner_text('#status'))
    page.screenshot(path='/home/fanfou-sender/evidence/options_page.png')
    print('screenshot → /home/fanfou-sender/evidence/options_page.png')
    if logs:
        print('=== 日志 ===')
        print('\n'.join(logs[-10:]))
    ctx.close()
