# -*- coding: utf-8 -*-
"""标签对 X 生效验证：to=akkoma,twitter + tags（无图）→ 两端都应带 #标签；测完清理"""
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


def send(payload, timeout=240):
    r = requests.post(S + '/send', json=payload, timeout=timeout)
    return r.status_code, r.json()


print('== to=akkoma,twitter + 两个标签（无图）==')
code, j = send({'token': TOKEN, 'text': '【通道测试】标签对 X 生效验证（稍后自动删除）',
                'to': 'akkoma,twitter', 'tags': ['通道标签甲', '通道标签乙']})
print(' ', code, json.dumps(j, ensure_ascii=False)[:400])
ak = j.get('results', {}).get('akkoma', {})
tw = j.get('results', {}).get('twitter', {})
ak_id, tw_id = ak.get('id'), tw.get('id')

if ak_id:
    d = requests.get(AK + '/api/v1/statuses/' + ak_id, headers=AKH, timeout=30).json()
    c = d.get('content') or ''
    print('  akkoma 含 #通道标签甲:', '#通道标签甲' in c, '| 含 #通道标签乙:', '#通道标签乙' in c)
    print('  akkoma tags 字段:', ak.get('tags'))

if tw_id:
    r = subprocess.run([TW_PY, '-c', f'''
import asyncio, sys
sys.path.insert(0, "/home/fanfou-sender")
import twitter_sender as ts
async def m():
    c = ts.make_client()
    t = await c.get_tweet_by_id("{tw_id}")
    print(t.text)
asyncio.run(m())
'''], capture_output=True, text=True, timeout=150)
    txt = (r.stdout or '').strip()
    print('  x 推文文本:', txt[:140])
    print('  x 含 #通道标签甲:', '#通道标签甲' in txt, '| 含 #通道标签乙:', '#通道标签乙' in txt)
    print('  x twitter.tags 字段:', tw.get('tags'))

print('== 清理 ==')
if ak_id:
    print('  akkoma del:', requests.delete(AK + '/api/v1/statuses/' + ak_id, headers=AKH, timeout=30).status_code)
if tw_id:
    r = subprocess.run([TW_PY, '/home/fanfou-sender/twitter_sender.py', 'delete', str(tw_id)],
                       capture_output=True, text=True, timeout=120)
    print('  twitter del:', r.returncode, (r.stdout or r.stderr).strip()[:90])

me = requests.get(AK + '/api/v1/accounts/verify_credentials', headers=AKH, timeout=30).json()
sts = requests.get(AK + "/api/v1/accounts/%s/statuses?limit=6" % me['id'], headers=AKH, timeout=30).json()
print('akkoma 剩余帖子:', len(sts))
print('DONE')
