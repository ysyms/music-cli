"""
musicdl_patch.py
Monkey-patch musicdl to:
1. Fetch word-level (逐字) lyrics: KRC for Kugou, YRC for NetEase
2. Speed up by skipping third-party API parsing

Usage:
    import musicdl_patch
    musicdl_patch.apply()

    # Then use musicdl normally:
    from musicdl.modules.sources import kugou, netease
    src = kugou.KugouMusicClient()
    results = src.search('周杰伦 稻香')
"""

import zlib
import base64
import logging

log = logging.getLogger(__name__)

# KRC decryption key (same as LDDC)
_KRC_KEY = b"@Gaw^2tGQ61-\xce\xd2ni"


def _krc_decrypt(data: bytes) -> str:
    """Decrypt KRC lyrics: skip 4-byte header, XOR with key, zlib decompress."""
    encrypted = bytearray(data)[4:]
    decrypted = bytearray(b ^ _KRC_KEY[i % len(_KRC_KEY)] for i, b in enumerate(encrypted))
    return zlib.decompress(decrypted).decode('utf-8')


def _patch_kugou():
    """
    Patch KugouMusicClient._parsewithofficialapiv1:
    - After fetching LRC, also try to get KRC (word-level) if krctype==1
    - KRC replaces LRC in song_info.lyric; raw KRC stored in raw_data['lyric']['krc_raw']
    """
    from musicdl.modules.sources import kugou as _kugou_mod
    from musicdl.modules.utils import resp2json, cleanlrc, safeextractfromdict

    _orig = _kugou_mod.KugouMusicClient._parsewithofficialapiv1

    def _patched(self, search_result, request_overrides=None,
                 song_info_flac=None, lossless_quality_is_sufficient=True):
        song_info = _orig(self, search_result, request_overrides,
                          song_info_flac, lossless_quality_is_sufficient)

        if not song_info.with_valid_download_url:
            return song_info

        # Try KRC (逐字) upgrade
        try:
            candidates = song_info.raw_data.get('lyric', {}).get('candidates', [])
            if candidates and candidates[0].get('krctype') == 1:
                c = candidates[0]
                url = (
                    f"http://lyrics.kugou.com/download?ver=1&client=pc"
                    f"&id={c['id']}&accesskey={c['accesskey']}&fmt=krc&charset=utf8"
                )
                resp = self.get(url, **(request_overrides or {}))
                resp.raise_for_status()
                krc_b64 = resp2json(resp).get('content', '')
                if krc_b64:
                    krc_raw = _krc_decrypt(base64.b64decode(krc_b64))
                    song_info.raw_data['lyric']['krc_raw'] = krc_raw
                    song_info.lyric = krc_raw  # word-level KRC replaces LRC
                    log.debug('KugouMusicClient: upgraded to KRC (逐字)')
        except Exception as e:
            log.debug(f'KugouMusicClient: KRC upgrade failed, keeping LRC: {e}')

        return song_info

    _kugou_mod.KugouMusicClient._parsewithofficialapiv1 = _patched
    log.info('musicdl_patch: KugouMusicClient patched (KRC 逐字)')


def _patch_netease():
    """
    Patch NeteaseMusicClient._parsewithofficialapiv1:
    - Request yv=1 to get YRC (word-level) lyrics
    - If YRC is available, use it; otherwise fall back to LRC
    - Raw YRC stored in raw_data['lyric']['yrc_raw']
    """
    from musicdl.modules.sources import netease as _ne_mod
    from musicdl.modules.utils import resp2json, cleanlrc, safeextractfromdict

    _orig = _ne_mod.NeteaseMusicClient._parsewithofficialapiv1

    def _patched(self, search_result, request_overrides=None,
                 song_info_flac=None, lossless_quality_is_sufficient=True):
        song_info = _orig(self, search_result, request_overrides,
                          song_info_flac, lossless_quality_is_sufficient)

        if not song_info.with_valid_download_url:
            return song_info

        # Try YRC (逐字) upgrade — re-request with yv=1 via fresh requests session
        # (self.post reuses a closed connection after the first call, causing reset)
        try:
            import requests as _requests
            song_id = search_result['id']
            data = {
                'id': song_id, 'cp': 'false',
                'tv': '0', 'lv': '0', 'rv': '0', 'kv': '0',
                'yv': '1',  # ← request word-level YRC
                'ytv': '0', 'yrv': '0',
            }
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://music.163.com/'}
            resp = _requests.post(
                'https://interface3.music.163.com/api/song/lyric',
                data=data, headers=headers, timeout=10
            )
            resp.raise_for_status()
            lyric_result = resp2json(resp)
            yrc_text = safeextractfromdict(lyric_result, ['yrc', 'lyric'], '')
            if yrc_text and yrc_text.strip():
                song_info.raw_data['lyric']['yrc_raw'] = yrc_text
                song_info.lyric = yrc_text  # word-level YRC replaces LRC
                log.debug('NeteaseMusicClient: upgraded to YRC (逐字)')
            else:
                log.debug('NeteaseMusicClient: YRC empty, keeping LRC')
        except Exception as e:
            log.debug(f'NeteaseMusicClient: YRC upgrade failed, keeping LRC: {e}')

        return song_info

    _ne_mod.NeteaseMusicClient._parsewithofficialapiv1 = _patched
    log.info('musicdl_patch: NeteaseMusicClient patched (YRC 逐字)')


def _patch_speed():
    """
    Speed patch: make _parsewiththirdpartapis a no-op for Kugou and NetEase.

    Third-party APIs are tried to get FLAC when official API fails due to copyright.
    Skipping them saves ~5-30s per song but may reduce download availability
    for paid/restricted tracks. Enable only when you care more about speed.
    """
    from musicdl.modules.sources import kugou as _kg, netease as _ne
    from musicdl.modules.utils import SongInfo

    def _noop_kg(self, search_result, request_overrides=None):
        return SongInfo(source=self.source)

    def _noop_ne(self, search_result, request_overrides=None):
        from musicdl.modules.utils.neteaseutils import MUSIC_QUALITIES
        return SongInfo(source=self.source, raw_data={'quality': MUSIC_QUALITIES[-1]})

    _kg.KugouMusicClient._parsewiththirdpartapis = _noop_kg
    _ne.NeteaseMusicClient._parsewiththirdpartapis = _noop_ne
    log.info('musicdl_patch: third-party API parsing disabled (speed mode)')


def _patch_link_tester():
    """
    Skip audio link HEAD/GET validation — always return ok=True.

    For search-only use cases we don't need real download links validated.
    This saves 1-2 HTTP requests per song and avoids filtering out songs
    whose official download URL is geo-blocked but song info is valid.
    """
    from musicdl.modules.utils import AudioLinkTester

    def _always_ok(self, url: str, request_overrides: dict = None):
        return dict(ok=True, status=200, method='skip', final_url=url,
                    ctype='audio/mpeg', clen=None, range=True, fmt=None, reason='patched')

    AudioLinkTester.test = _always_ok
    log.info('musicdl_patch: AudioLinkTester patched (always ok)')


def apply(word_level_lyrics=True, speed_mode=True, skip_link_test=False):
    """
    Apply patches to musicdl.

    Args:
        word_level_lyrics: Patch Kugou (KRC) and NetEase (YRC) for word-level lyrics.
        speed_mode: Skip third-party API fallbacks for faster results.
        skip_link_test: Skip download URL validation (for search-only use cases).
    """
    if word_level_lyrics:
        _patch_kugou()
        _patch_netease()
    if speed_mode:
        _patch_speed()
    if skip_link_test:
        _patch_link_tester()
    log.info(f'musicdl_patch applied: word_level={word_level_lyrics}, speed={speed_mode}, skip_link_test={skip_link_test}')
