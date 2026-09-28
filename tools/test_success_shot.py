# -*- coding: utf-8 -*-
"""状态回放截图：把一条真实的成功结果写进 storage，截取最终版成功态 UI（不发起真实发送）"""
import os
import shutil
import time

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/ext-suppl-tw'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
SHOTS = '/home/fanfou-sender/evidence'

shutil.rmtree(UD, ignore_errors=True)

state = {
    'status': 'success',
    'ts': int(time.time() * 1000),
    'target': 'akkoma',
    'entry': {
        'ts': int(time.time() * 1000),
        'ok': True,
        'target': 'akkoma',
        'summary': 'Akkoma ✓',
        'images': 2,
        'results': {
            'akkoma': {'ok': True, 'id': 'BAqwxsdc5O1mP2jlwW',
                       'url': 'https://akkoma.skyneil.net/notice/BAqwxsdc5O1mP2jlwW',
                       'media_count': 2, 'tags': ['摄影', '日常']},
        },
        'error': None,
    },
}
logseed = [state['entry'], {
    'ts': int(time.time() * 1000) - 90000, 'ok': False, 'target': 'fanfou',
    'summary': '网络/服务错误', 'images': 0, 'error': '服务响应异常（HTTP 502）',
}]

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False, executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 460, 'height': 1000},
    )
    page = ctx.new_page()
    page.goto(f'chrome-extension://{EXT_ID}/popup.html')
    page.wait_for_timeout(1200)
    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://199.47.241.134:8788', 'token': TOKEN})
    page.evaluate("([st, lg]) => new Promise(r => chrome.storage.local.set({lastState: st, log: lg}, r))",
                  [state, logseed])
    page.reload()
    page.wait_for_timeout(2000)
    page.screenshot(path=f'{SHOTS}/popup_v2_success.png')
    print('状态条:', page.inner_text('#statusbar').replace('\n', ' / '))
    print('日志首条:', page.eval_on_selector('#log .item', 'el => el && el.innerText'))
    ctx.close()
print('截图: popup_v2_success.png')
