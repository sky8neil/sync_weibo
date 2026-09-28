# -*- coding: utf-8 -*-
"""生成双发小助手图标（橙底 + 蓝色圆环 + 白心）"""
import struct, zlib, binascii, os


def make(w, path):
    def chunk(t, d):
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', binascii.crc32(c))

    rows = b''
    for y in range(w):
        row = b'\x00'
        for x in range(w):
            cx = cy = w / 2.0
            dist = ((x + .5 - cx) ** 2 + (y + .5 - cy) ** 2) ** 0.5
            R = w * 0.47
            if dist <= R * 0.42:
                px = (255, 255, 255)
            elif dist <= R:
                px = (47, 111, 224)
            else:
                px = (255, 138, 0)
            row += bytes(px)
        rows += row
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, w, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(rows, 9))
           + chunk(b'IEND', b''))
    open(path, 'wb').write(png)


os.makedirs('/home/fanfou-sender/extension/icons', exist_ok=True)
for s in (16, 48, 128):
    make(s, '/home/fanfou-sender/extension/icons/icon%d.png' % s)
print('icons done')
