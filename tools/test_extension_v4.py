# -*- coding: utf-8 -*-
"""正式验收（v0.4）：插件里一张图 → 「Akkoma + X」同时发（帖子保留供查看效果）"""
import os
import shutil

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/ext-tw-test-v5'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
SHOTS = '/home/fanfou-sender/evidence'
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
    page.on('console', lambda m: logs.append(f'[{m.type}] {m.text[:120]}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {str(e)[:160]}'))
    page.goto(f'chrome-extension://{EXT_ID}/popup.html')
    page.wait_for_timeout(1200)
    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    page.reload()
    page.wait_for_timeout(2500)

    print('按钮:', page.evaluate("() => ['sendFanfou','sendAkkoma','sendTwitter','sendAkTw','sendAll'].map(id => !!document.getElementById(id))"))

    page.fill('#msg', '【图片通道测试】一张图，同时发 Akkoma + X —— 用于查看效果。')
    page.fill('#tags', '配图测试')
    page.click('#tagBtn')
    page.set_input_files('#file', '/tmp/akk_media/big.jpg')
    page.wait_for_selector('.thumb', timeout=30000)
    page.wait_for_timeout(800)
    print('imgInfo:', page.inner_text('#imgInfo'))
    print('字数:', page.inner_text('#counter'))
    page.screenshot(path=f'{SHOTS}/popup_v4_filled.png')

    page.click('#sendAkTw')
    page.wait_for_function(
        "() => ['success','error'].includes(document.getElementById('statusbar').className)",
        timeout=180000)
    page.wait_for_timeout(600)
    print('状态条:', page.inner_text('#statusbar').replace('\n', ' / '))
    links = page.eval_on_selector_all('#statusbar a', 'els => els.map(e => e.href)')
    print('链接:', links)
    ak_url = next((u for u in links if 'akkoma' in u), None)
    tw_url = next((u for u in links if 'x.com' in u), None)
    print('AK:', ak_url)
    print('TW:', tw_url)
    page.screenshot(path=f'{SHOTS}/popup_v4_success.png')
    print('日志首条:', page.eval_on_selector('#log .item', 'el => el && el.innerText'))
    print('控制台:', logs[-6:] if logs else '（无）')
    ctx.close()

print('AK_URL=' + str(ak_url))
print('TW_URL=' + str(tw_url))
print('DONE')
