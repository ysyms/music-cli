#!/usr/bin/env python3
"""audio_dl.py — 独立进程音频下载（被 music_search.py 调用）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import urllib.request
from pathlib import Path

platform = sys.argv[1]   # kg / ne / qq
query    = sys.argv[2]   # "name artist"
out_dir  = Path(sys.argv[3])
fname    = sys.argv[4]   # 目标文件名（不含扩展名）

import musicdl_patch
musicdl_patch.apply(word_level_lyrics=False, speed_mode=False, skip_link_test=False)

if platform == 'kg':
    from musicdl.modules.sources import kugou as mod
    client = mod.KugouMusicClient()
elif platform == 'ne':
    from musicdl.modules.sources import netease as mod
    client = mod.NeteaseMusicClient()
else:
    from musicdl.modules.sources import qq as mod
    client = mod.QQMusicClient()

results = client.search(query)
if not results:
    print('✗ 无搜索结果', flush=True)
    sys.exit(1)

r = results[0]
url = r.download_url
ext = r.ext or 'mp3'
path = out_dir / f'{fname}.{ext}'

try:
    urllib.request.urlretrieve(url, path)
    size = path.stat().st_size / 1024 / 1024
    print(f'✓ 音频已保存：{path}  ({size:.1f} MB)', flush=True)
except Exception as e:
    print(f'✗ 下载失败：{e}', flush=True)
    sys.exit(1)
