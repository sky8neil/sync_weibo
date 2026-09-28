# -*- coding: utf-8 -*-
"""服务 v5 边界测试：Akkoma+X 五图（X 只取前 4）、饭否带图拒绝；测完清理"""
import base64
import json
import subprocess
import sys

sys.path.insert(0, '/home/fanfou-sender')
import requests  # noqa: E402

TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
S = 'http://127.0.0.1:8788'
AK = 'https://akkoma.skyneil.net'
AKH = {'Authorization': 'Bearer ' + open('/home/fanfou-sender/state/akkoma_token.txt').read().strip()}
TW_PY = '/home/fanfou-sender/.venv-tw/bin/python'
TW_SENDER = '/home/fanfou-sender/twitter_sender.py'
WEBP = base64.b64encode(open('/tmp/akk_media/test.webp', 'rb').read()).decode()


def send(payload, timeout=240):
    r = requests.post(S + '/send', json=payload, timeout=timeout)
    return r.status_code, r.json()


print('== 1) to=akkoma,twitter + 5 张图（ak 全收 / X 取前 4）==')
imgs = [{'name': f't{i}.webp', 'mime': 'image/webp', 'data': WEBP} for i in range(5)]
code, j = send({'token': TOKEN, 'text': '【通道测试】五图边界：ak 5 张 / X 取前 4（稍后自动删除）',
                'to': 'akkoma,twitter', 'images': imgs})
print(' ', code, json.dumps(j, ensure_ascii=False)[:340])
print('  warnings:', j.get('warnings'))
ak_id = j.get('results', {}).get('akkoma', {}).get('id')
tw_id = j.get('results', {}).get('twitter', {}).get('id')
if ak_id:
    d = requests.get(AK + '/api/v1/statuses/' + ak_id, headers=AKH, timeout=30).json()
    print('  akkoma 实际图片数:', len(d.get('media_attachments') or []))
print('  twitter media_count:', j.get('results', {}).get('twitter', {}).get('media_count'))

print('== 2) to=fanfou + 图片（应 400）==')
code, j = send({'token': TOKEN, 'text': 'x', 'to': 'fanfou',
                'images': [{'name': 'a.webp', 'mime': 'image/webp', 'data': WEBP}]})
print(' ', code, j.get('error'))

print('== 3) 清理 ==')
if ak_id:
    r = requests.delete(AK + '/api/v1/statuses/' + ak_id, headers=AKH, timeout=30)
    print('  akkoma del:', r.status_code)
if tw_id:
    r = subprocess.run([TW_PY, TW_SENDER, 'delete', str(tw_id)], capture_output=True, text=True, timeout=120)
    print('  twitter del:', r.returncode, (r.stdout or r.stderr).strip()[:90])

me = requests.get(AK + '/api/v1/accounts/verify_credentials', headers=AKH, timeout=30).json()
sts = requests.get(AK + "/api/v1/accounts/%s/statuses?limit=5" % me['id'], headers=AKH, timeout=30).json()
print('akkoma 剩余帖子:', len(sts))
print('DONE')
