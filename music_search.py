#!/usr/bin/env python3
"""
music_search.py — 聚合音乐搜索 + 下载 CLI

用法:
    python music_search.py 弱水三千
    python music_search.py "周杰伦 稻香" -n 5 -o ~/Music
    python music_search.py 晴天 -p kg ne

流程:
    1. 并行搜索各平台 (~2s)
    2. 显示编号列表
    3. 输入编号选择
    4. 立刻下载歌词 (<2s)
    5. 后台下载音频 (musicdl, 通知完成)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import time
import hashlib
import base64
import zlib
import argparse
import concurrent.futures
from pathlib import Path

import requests

# ── 颜色 ─────────────────────────────────────────────────────────────────────

RESET  = '\033[0m'
BOLD   = '\033[1m'
GREEN  = '\033[92m'
YELLOW = '\033[93m'
GREY   = '\033[90m'
RED    = '\033[91m'
CYAN   = '\033[96m'

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0'})

# ── 工具 ──────────────────────────────────────────────────────────────────────

def fmt_dur(sec):
    try:
        s = int(float(sec))
        return f'{s // 60}:{s % 60:02d}'
    except Exception:
        return '--:--'


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


# ─────────────────────────────────────────────────────────────────────────────
# 酷狗 KG
# ─────────────────────────────────────────────────────────────────────────────

_KG_SECRET  = 'LnT6xpN3khm36zse0QzvmgTZ3waWdRSA'
_KRC_KEY    = b"@Gaw^2tGQ61-\xce\xd2ni"


def _kg_sign(params: dict) -> str:
    body = ''.join(f'{k}={v}' for k, v in sorted(params.items()))
    return hashlib.md5(f'{_KG_SECRET}{body}{_KG_SECRET}'.encode()).hexdigest()


def _krc_decrypt(data: bytes) -> str:
    enc = bytearray(data)[4:]
    dec = bytearray(b ^ _KRC_KEY[i % len(_KRC_KEY)] for i, b in enumerate(enc))
    return zlib.decompress(dec).decode('utf-8')


def kg_check_krc(song: dict) -> bool:
    params = {
        'appid': '3116', 'clientver': '11070',
        'album_audio_id': str(song['album_audio_id']),
        'duration': str(song['duration'] * 1000),
        'hash': song['hash'],
        'keyword': f"{song['singername']} - {song['songname']}",
        'lrctxt': '1', 'man': 'no',
    }
    params['signature'] = _kg_sign(params)
    try:
        r = SESSION.get('https://lyrics.kugou.com/v1/search', params=params,
                        headers={'User-Agent': 'Android14-1070-11070-201-0-Lyric-wifi'},
                        timeout=6)
        cands = r.json().get('candidates', [])
        if not cands or cands[0].get('krctype') != 1:
            return False
        return True
    except Exception:
        return False


def kg_search(keyword: str, limit: int) -> list[dict]:
    r = SESSION.get('https://mobileservice.kugou.com/api/v3/search/song', params={
        'keyword': keyword, 'page': 1, 'pagesize': limit,
        'userid': '-1', 'clientver': '20000', 'platform': 'WebFilter',
    }, timeout=8)
    songs = r.json().get('data', {}).get('info', [])[:limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(songs) or 1) as pool:
        futures = {pool.submit(kg_check_krc, s): s for s in songs}
        krc_map = {id(s): f.result() for f, s in [(f, futures[f]) for f in concurrent.futures.as_completed(futures)]}
    return [{
        'platform': 'kg', 'label': '酷狗',
        'name': s.get('songname', ''), 'artist': s.get('singername', ''),
        'dur': fmt_dur(s.get('duration')), 'has_word': krc_map.get(id(s), False),
        '_raw': s,
    } for s in songs]


def kg_download_lyrics(song: dict, out_dir: Path) -> Path | None:
    """下载 KRC 歌词，返回保存路径"""
    s = song['_raw']
    params = {
        'appid': '3116', 'clientver': '11070',
        'album_audio_id': str(s['album_audio_id']),
        'duration': str(s['duration'] * 1000),
        'hash': s['hash'],
        'keyword': f"{s['singername']} - {s['songname']}",
        'lrctxt': '1', 'man': 'no',
    }
    params['signature'] = _kg_sign(params)
    r = SESSION.get('https://lyrics.kugou.com/v1/search', params=params,
                    headers={'User-Agent': 'Android14-1070-11070-201-0-Lyric-wifi'},
                    timeout=8)
    cands = r.json().get('candidates', [])
    if not cands:
        return None

    c = cands[0]
    dl_params = {
        'appid': '3116', 'clientver': '11070',
        'accesskey': c['accesskey'], 'charset': 'utf8',
        'client': 'mobi', 'fmt': 'krc', 'id': str(c['id']), 'ver': '1',
    }
    dl_params['signature'] = _kg_sign(dl_params)
    r2 = SESSION.get('http://lyrics.kugou.com/download', params=dl_params,
                     headers={'User-Agent': 'Android14-1070-11070-201-0-Lyric-wifi'},
                     timeout=8)
    content_b64 = r2.json().get('content', '')
    if not content_b64:
        return None

    j2 = r2.json()
    content_type = j2.get('contenttype', 1)
    if content_type == 2:  # 纯文本
        lyric_text = base64.b64decode(content_b64).decode('utf-8')
        ext = 'lrc'
    else:  # KRC
        lyric_text = _krc_decrypt(base64.b64decode(content_b64))
        # 校验：比较 KRC 头部 [ti:] 与歌曲名，不匹配才 fallback（避免同歌不同音质 hash 不同误判）
        krc_title = (re.search(r'\[ti:([^\]]*)\]', lyric_text) or type('', (), {'group': lambda s, n: ''})()).group(1).strip()
        song_title = s['songname'].strip()
        wrong_song = bool(krc_title) and krc_title.lower() not in song_title.lower() and song_title.lower() not in krc_title.lower()
        if wrong_song:
            # 明显是另一首歌的 KRC，改取 LRC
            lrc_params = dict(dl_params, fmt='lrc')
            lrc_params['signature'] = _kg_sign({k: v for k, v in lrc_params.items() if k != 'signature'})
            rl = SESSION.get('http://lyrics.kugou.com/download', params=lrc_params,
                             headers={'User-Agent': 'Android14-1070-11070-201-0-Lyric-wifi'}, timeout=8)
            lrc_b64 = rl.json().get('content', '')
            if not lrc_b64:
                return None
            lyric_text = base64.b64decode(lrc_b64).decode('utf-8')
            ext = 'lrc'
        else:
            ext = 'krc'

    fname = safe_filename(f"{s['songname']}_{s['singername']}") + f'.{ext}'
    path = out_dir / fname
    path.write_text(lyric_text, encoding='utf-8')
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 网易云 NE
# ─────────────────────────────────────────────────────────────────────────────

def ne_check_yrc(song_id: int) -> tuple[bool, bool]:
    try:
        r = SESSION.post('https://interface3.music.163.com/api/song/lyric',
            data={'id': song_id, 'yv': '1', 'lv': '0', 'tv': '0',
                  'rv': '0', 'kv': '0', 'cp': 'false', 'ytv': '0', 'yrv': '0'},
            headers={'Referer': 'https://music.163.com/'}, timeout=6)
        j = r.json()
        return (bool(j.get('yrc', {}).get('lyric', '').strip()),
                bool(j.get('lrc', {}).get('lyric', '').strip()))
    except Exception:
        return False, False


def ne_search(keyword: str, limit: int) -> list[dict]:
    r = SESSION.post('https://music.163.com/api/cloudsearch/pc',
        data={'s': keyword, 'type': 1, 'limit': limit},
        headers={'Referer': 'https://music.163.com/'}, timeout=8)
    songs = r.json().get('result', {}).get('songs', [])[:limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(songs) or 1) as pool:
        futures = {pool.submit(ne_check_yrc, s['id']): s for s in songs}
        lyric_map = {s['id']: f.result() for f, s in [(f, futures[f]) for f in concurrent.futures.as_completed(futures)]}
    return [{
        'platform': 'ne', 'label': '网易云',
        'name': s.get('name', ''), 'artist': '/'.join(a['name'] for a in s.get('ar', [])),
        'dur': fmt_dur(s.get('dt', 0) / 1000), 'has_word': lyric_map.get(s['id'], (False, False))[0],
        '_raw': s,
    } for s in songs]


def ne_download_lyrics(song: dict, out_dir: Path) -> Path | None:
    s = song['_raw']
    r = SESSION.post('https://interface3.music.163.com/api/song/lyric',
        data={'id': s['id'], 'yv': '1', 'lv': '0', 'tv': '0',
              'rv': '0', 'kv': '0', 'cp': 'false', 'ytv': '0', 'yrv': '0'},
        headers={'Referer': 'https://music.163.com/'}, timeout=8)
    j = r.json()
    yrc = j.get('yrc', {}).get('lyric', '').strip()
    lrc = j.get('lrc', {}).get('lyric', '').strip()
    text = yrc or lrc
    if not text:
        return None
    ext = 'yrc' if yrc else 'lrc'
    artists = '/'.join(a['name'] for a in s.get('ar', []))
    fname = safe_filename(f"{s['name']}_{artists}") + f'.{ext}'
    path = out_dir / fname
    path.write_text(text, encoding='utf-8')
    return path


# ─────────────────────────────────────────────────────────────────────────────
# QQ音乐 QQ
# ─────────────────────────────────────────────────────────────────────────────

def qq_check_qrc(mid: str, song_id: int) -> tuple[bool, bool]:
    try:
        r = SESSION.post('https://u.y.qq.com/cgi-bin/musicu.fcg',
            json={'req_0': {'module': 'music.musichallSong.PlayLyricInfo',
                            'method': 'GetPlayLyricInfo',
                            'param': {'songMid': mid, 'songID': song_id, 'musicID': song_id}}},
            headers={'Referer': 'https://y.qq.com'}, timeout=6)
        d = r.json().get('req_0', {}).get('data', {})
        return d.get('qrc', 0) == 1, bool(d.get('lyric', ''))
    except Exception:
        return False, False


def qq_search(keyword: str, limit: int) -> list[dict]:
    r = SESSION.post('https://u.y.qq.com/cgi-bin/musicu.fcg',
        json={'req_0': {'module': 'music.search.SearchCgiService',
                        'method': 'DoSearchForQQMusicDesktop',
                        'param': {'query': keyword, 'num_per_page': limit,
                                  'page_num': 1, 'search_type': 0}}},
        headers={'Referer': 'https://y.qq.com'}, timeout=8)
    songs = r.json().get('req_0', {}).get('data', {}).get('body', {}).get('song', {}).get('list', [])[:limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(songs) or 1) as pool:
        futures = {pool.submit(qq_check_qrc, s.get('mid', ''), s.get('id', 0)): s for s in songs}
        lyric_map = {s['id']: f.result() for f, s in [(f, futures[f]) for f in concurrent.futures.as_completed(futures)]}
    return [{
        'platform': 'qq', 'label': 'QQ',
        'name': s.get('title', s.get('songname', '')),
        'artist': '/'.join(sg['name'] for sg in s.get('singer', [])),
        'dur': fmt_dur(s.get('interval')),
        'has_word': lyric_map.get(s.get('id', 0), (False, False))[0],
        '_raw': s,
    } for s in songs]


def qq_download_lyrics(song: dict, out_dir: Path) -> Path | None:
    s = song['_raw']
    r = SESSION.post('https://u.y.qq.com/cgi-bin/musicu.fcg',
        json={'req_0': {'module': 'music.musichallSong.PlayLyricInfo',
                        'method': 'GetPlayLyricInfo',
                        'param': {'songMid': s.get('mid', ''), 'songID': s.get('id', 0), 'musicID': s.get('id', 0)}}},
        headers={'Referer': 'https://y.qq.com'}, timeout=8)
    d = r.json().get('req_0', {}).get('data', {})
    lyric_b64 = d.get('lyric', '')
    if not lyric_b64:
        return None
    text = base64.b64decode(lyric_b64).decode('utf-8')
    artists = '/'.join(sg['name'] for sg in s.get('singer', []))
    fname = safe_filename(f"{s.get('title', '')}_{artists}") + '.lrc'
    path = out_dir / fname
    path.write_text(text, encoding='utf-8')
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 音频下载 (musicdl 后台)
# ─────────────────────────────────────────────────────────────────────────────

PLATFORM_SOURCE = {'kg': 'kugou', 'ne': 'netease', 'qq': 'qq'}

def download_audio(song: dict, out_dir: Path, fname: str) -> Path | None:
    """同步下载音频（子进程，避免 ThreadPoolExecutor 冲突）"""
    import subprocess
    script = Path(__file__).parent / 'audio_dl.py'
    query  = f"{song['name']} {song['artist']}"
    proc = subprocess.Popen(
        [sys.executable, str(script), song['platform'], query, str(out_dir), fname],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    out, _ = proc.communicate()
    line = out.strip().splitlines()[-1] if out.strip() else ''
    _AUDIO_EXTS = {'.mp3', '.flac', '.m4a', '.ogg', '.wma', '.aac', '.wav'}
    if '✓' in line and proc.returncode == 0:
        for f in out_dir.iterdir():
            if f.stem == fname and f.suffix.lower() in _AUDIO_EXTS:
                return f
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 平台配置
# ─────────────────────────────────────────────────────────────────────────────

PLATFORMS = {
    'kg': ('酷狗',  kg_search,  kg_download_lyrics),
    'ne': ('网易云', ne_search,  ne_download_lyrics),
    'qq': ('QQ',   qq_search,  qq_download_lyrics),
}

PREC_COLORS = {True: f'{GREEN}逐字{RESET}', False: f'{YELLOW}逐行{RESET}'}


# ─────────────────────────────────────────────────────────────────────────────
# 主逻辑
# ─────────────────────────────────────────────────────────────────────────────

def search_all(query: str, platforms: list, limit: int) -> list[dict]:
    """并行搜索，返回合并列表（按平台顺序）"""
    order = {k: i for i, k in enumerate(p[0] for p in platforms)}
    results_map = {}

    def _search(key, label, fn, dl_fn):
        try:
            rows = fn(query, limit)
            return key, rows
        except Exception as e:
            return key, []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(platforms)) as pool:
        futures = {pool.submit(_search, k, l, fn, dl): k for k, l, fn, dl in platforms}
        for f in concurrent.futures.as_completed(futures):
            key, rows = f.result()
            results_map[key] = rows

    all_rows = []
    for k, *_ in platforms:
        all_rows.extend(results_map.get(k, []))
    return all_rows


def print_list(rows: list[dict]):
    platform_colors = {'kg': CYAN, 'ne': '\033[35m', 'qq': '\033[34m'}
    print(f'\n{BOLD}  #   平台    {"歌名":<30} {"作者":<22} {"时长":>6}  歌词{RESET}')
    print('  ' + '─' * 75)
    for i, r in enumerate(rows, 1):
        pc = platform_colors.get(r['platform'], '')
        label = f'{pc}{r["label"]:<4}{RESET}'
        name   = r['name'][:28]   + ('…' if len(r['name'])   > 28 else '')
        artist = r['artist'][:20] + ('…' if len(r['artist']) > 20 else '')
        prec   = PREC_COLORS[r['has_word']]
        print(f'  {i:<3} {label}  {name:<30} {artist:<22} {r["dur"]:>6}  {prec}')


def parse_selection(text: str, max_n: int) -> list[int]:
    """解析 '1,3,5-7' → [1,3,5,6,7]"""
    nums = set()
    for part in text.split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-', 1)
            nums.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            nums.add(int(part))
    return sorted(n for n in nums if 1 <= n <= max_n)


def download_song(song: dict, out_dir: Path, audio: bool, lyrics: bool = True):
    dl_fn = PLATFORMS[song['platform']][2]
    fname = safe_filename(f"{song['name']}_{song['artist']}")
    song_dir = out_dir / fname
    song_dir.mkdir(parents=True, exist_ok=True)

    # 歌词
    if lyrics:
        print(f'  {CYAN}⬇ 歌词下载中...{RESET}', end='', flush=True)
        try:
            path = dl_fn(song, song_dir)
            if path:
                print(f'\r  {GREEN}✓ 歌词：{path.name}{RESET}')
            else:
                print(f'\r  {YELLOW}! 无歌词{RESET}')
        except Exception as e:
            print(f'\r  {RED}✗ 歌词失败：{e}{RESET}')

    # 音频
    if audio:
        print(f'  {CYAN}⬇ 音频下载中...{RESET}', end='', flush=True)
        try:
            apath = download_audio(song, song_dir, fname)
            if apath:
                if apath.suffix.lower() != '.mp3':
                    # 转 MP3
                    mp3_path = apath.with_suffix('.mp3')
                    import subprocess as _sp
                    _sp.run(['ffmpeg', '-y', '-i', str(apath), '-q:a', '0', str(mp3_path)],
                            stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, check=True)
                    apath.unlink()
                    apath = mp3_path
                size = apath.stat().st_size / 1024 / 1024
                print(f'\r  {GREEN}✓ 音频：{apath.name}  ({size:.1f} MB){RESET}')
            else:
                print(f'\r  {YELLOW}! 音频下载失败{RESET}')
        except Exception as e:
            print(f'\r  {RED}✗ 音频失败：{e}{RESET}')

    print(f'  {GREY}→ {song_dir}{RESET}')


def main():
    parser = argparse.ArgumentParser(description='聚合音乐搜索 + 下载')
    parser.add_argument('query', nargs='+', help='搜索关键词')
    parser.add_argument('-n',    type=int,   default=None, help='每平台返回条数，指定后进入列表选择模式')
    parser.add_argument('-o', '--output',    default='~/Music/lddc', help='保存目录')
    parser.add_argument('-p', '--platforms', nargs='+', choices=['kg','ne','qq'], default=None)
    parser.add_argument('--lrc',             action='store_true', help='同时下载歌词')
    args = parser.parse_args()

    query   = ' '.join(args.query)
    out_dir = Path(args.output).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 快捷模式（默认）：酷狗第一条，仅音频
    if args.n is None:
        platform = args.platforms[0] if args.platforms else 'kg'
        search_fn = PLATFORMS[platform][1]
        print(f'{BOLD}⚡ {query}{RESET}  {GREY}({PLATFORMS[platform][0]}){RESET}')
        rows = search_fn(query, 1)
        if not rows:
            print(f'{RED}无结果{RESET}')
            return
        song = rows[0]
        print(f'{GREY}{song["name"]} — {song["artist"]} {song["dur"]}{RESET}')
        download_song(song, out_dir, audio=True, lyrics=args.lrc)
        return

    # 列表选择模式
    platforms = args.platforms or ['kg', 'ne', 'qq']
    selected_platforms = [(k, *PLATFORMS[k]) for k in platforms]

    print(f'\n{BOLD}搜索：{query}{RESET}  {GREY}(并行中…){RESET}')
    t0   = time.time()
    rows = search_all(query, selected_platforms, args.n)
    print(f'{GREY}完成 {time.time()-t0:.1f}s，共 {len(rows)} 条{RESET}')

    if not rows:
        print(f'{RED}无结果{RESET}')
        return

    print_list(rows)

    try:
        sel = input(f'\n{BOLD}选择编号 (1-{len(rows)}，多个用逗号，回车取消): {RESET}').strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    if not sel:
        return

    indices = parse_selection(sel, len(rows))
    if not indices:
        print(f'{RED}无效编号{RESET}')
        return

    print(f'\n{BOLD}保存到：{out_dir}{RESET}')
    for idx in indices:
        song = rows[idx - 1]
        print(f'\n[{idx}] {song["name"]} — {song["artist"]} ({song["label"]})')
        download_song(song, out_dir, audio=True, lyrics=args.lrc)

    print()


if __name__ == '__main__':
    main()
