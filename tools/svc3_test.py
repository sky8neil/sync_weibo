# -*- coding: utf-8 -*-
"""服务 v3 端到端测试：图片（base64）、标签、限制校验、双端，全链路后清理"""
import base64
import json
import sys

sys.path.insert(0, '/home/fanfou-sender')
import requests  # noqa: E402
from fanfou_sender import FanfouClient  # noqa: E402

TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
S = 'http://127.0.0.1:8788'
AK = 'https://akkoma.skyneil.net'
AKH = {'Authorization': 'Bearer ' + open('/home/fanfou-sender/state/akkoma_token.txt').read().strip()}


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


WEBP = b64('/tmp/akk_media/test.webp')
JPG = b64('/tmp/akk_media/test.jpg')


def send(payload):
    r = requests.post(S + '/send', json=payload, timeout=240)
    return r.status_code, r.json()


ak_del = []
fan_ids = []

print('== a) health ==')
print(' ', requests.get(S + '/health').json())

print('== b) limits ==')
lj = requests.get(S + '/limits').json()
print(' ', json.dumps(lj['limits'], ensure_ascii=False))

print('== c) akkoma + 2 图 + 标签 ==')
code, j = send({'token': TOKEN, 'text': '【插件功能测试】带图与标签的 Akkoma 链路。', 'to': 'akkoma',
                'tags': ['插件功能测试标签', '日常'],
                'images': [{'name': 'a.webp', 'mime': 'image/webp', 'data': WEBP},
                           {'name': 'b.jpg', 'mime': 'image/jpeg', 'data': JPG}]})
print(' ', code, json.dumps(j, ensure_ascii=False)[:260])
ar = j.get('results', {}).get('akkoma', {})
if ar.get('ok'):
    sid = ar['id']
    ak_del.append(sid)
    d = requests.get(AK + '/api/v1/statuses/' + sid, headers=AKH, timeout=30).json()
    content = d.get('content') or ''
    print('   含#插件功能测试标签:', '#插件功能测试标签' in content,
          '| media 数:', len(d.get('media_attachments') or []),
          '| tags 字段:', ar.get('tags'))

print('== d) both + 1 图 + 标签（饭否仅文字）==')
code, j = send({'token': TOKEN, 'text': '【插件功能测试】双发带图：饭否仅文字。', 'to': 'both',
                'tags': ['双发测试标签'],
                'images': [{'name': 'a.webp', 'mime': 'image/webp', 'data': WEBP}]})
print(' ', code, json.dumps(j, ensure_ascii=False)[:300])
if j.get('results', {}).get('akkoma', {}).get('ok'):
    ak_del.append(j['results']['akkoma']['id'])
if j.get('results', {}).get('fanfou', {}).get('ok'):
    fan_ids.append(j['results']['fanfou']['id'])
print('   warnings:', j.get('warnings'))
print('   fanfou.images_skipped:', j.get('results', {}).get('fanfou', {}).get('images_skipped'))

print('== d2) 复核饭否正文不含标签 ==')
if fan_ids:
    c = FanfouClient('/home/fanfou-sender/state')
    sts = c._scan_statuses(c._get_profile_html())
    txt = next((t for f, t in sts if f == fan_ids[-1]), None)
    print('   正文:', (txt or '<未找到>')[:70])
    print('   不含#双发测试标签:', ('#双发测试标签' not in (txt or '')))

print('== e) to=fanfou 带图（应 400）==')
code, j = send({'token': TOKEN, 'text': 'x', 'to': 'fanfou',
                'images': [{'name': 'a.webp', 'mime': 'image/webp', 'data': WEBP}]})
print(' ', code, j.get('error'))

print('== f) 超 2MB 图（应 400）==')
big = base64.b64encode(b'\x00' * (2200 * 1024)).decode()
code, j = send({'token': TOKEN, 'text': 'x', 'to': 'akkoma',
                'images': [{'name': 'big.webp', 'mime': 'image/webp', 'data': big}]})
print(' ', code, j.get('error'))

print('== g) 17 张（应 400）==')
imgs = [{'name': f'{i}.webp', 'mime': 'image/webp', 'data': WEBP} for i in range(17)]
code, j = send({'token': TOKEN, 'text': 'x', 'to': 'akkoma', 'images': imgs})
print(' ', code, j.get('error'))

print('== h) 非法类型 image/tiff（应 400）==')
code, j = send({'token': TOKEN, 'text': 'x', 'to': 'akkoma',
                'images': [{'name': 'a.tiff', 'mime': 'image/tiff', 'data': WEBP}]})
print(' ', code, j.get('error'))

print('== i) 只有标签（无图）→ akkoma 追加标签 ==')
code, j = send({'token': TOKEN, 'text': '【插件功能测试】纯标签测试', 'to': 'akkoma',
                'tags': '测试标签A 测试标签B'})
print(' ', code, json.dumps(j, ensure_ascii=False)[:200])
if j.get('results', {}).get('akkoma', {}).get('ok'):
    sid = j['results']['akkoma']['id']
    ak_del.append(sid)
    d = requests.get(AK + '/api/v1/statuses/' + sid, headers=AKH, timeout=30).json()
    print('   含两个标签:', '#测试标签A' in (d.get('content') or '') and '#测试标签B' in (d.get('content') or ''))

print()
print('== 清理 Akkoma 测试帖 ==')
for sid in ak_del:
    r = requests.delete(AK + '/api/v1/statuses/' + sid, headers=AKH, timeout=30)
    print('  del', sid, r.status_code)
print('（饭否测试帖保留到收尾统一清理）:', fan_ids)
print('DONE')
