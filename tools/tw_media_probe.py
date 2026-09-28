# -*- coding: utf-8 -*-
"""Twitter 图片上传真机验证：bytes 直传（jpg + webp）→ 发推 → 核实 → 删除"""
import asyncio
import sys

sys.path.insert(0, '/home/fanfou-sender')
import twitter_sender as ts  # noqa: E402


async def main():
    c = ts.make_client()
    print('1) 登录:', await c.is_logged_in())

    jpg = open('/tmp/akk_media/big.jpg', 'rb').read()
    webp = open('/tmp/akk_media/big.webp', 'rb').read()
    print(f'2) 测试素材: jpg {len(jpg)//1024}KB / webp {len(webp)//1024}KB')

    mid_jpg = await c.upload_media(jpg, media_type='image/jpeg')
    print('3) jpg 上传 → media_id:', mid_jpg)
    mid_webp = await c.upload_media(webp, media_type='image/webp')
    print('   webp 上传 → media_id:', mid_webp)

    tweet = await c.create_tweet(
        text='【通道测试】X 图片上传联调：jpg + webp（稍后自动删除）',
        media_ids=[mid_jpg, mid_webp],
    )
    print('4) 发推 → id:', tweet.id)

    t = await c.get_tweet_by_id(tweet.id)
    print('5) 核实正文:', t.text[:60])
    media = getattr(t, 'media', None) or []
    print('   媒体数:', len(media))
    for m in media:
        print('   -', getattr(m, 'type', '?'), '|', str(getattr(m, 'media_url', getattr(m, 'url', '?')))[:80])

    print('6) 删除:', (await c.delete_tweet(tweet.id)))


asyncio.run(main())
print('PROBE DONE')
