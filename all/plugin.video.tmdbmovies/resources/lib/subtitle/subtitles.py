import os
import requests
import xbmc
import xbmcgui
import xbmcvfs
import time
from resources.lib.config import ADDON

ADDON_PATH = ADDON.getAddonInfo('path')
TMDbmovies_ICON = os.path.join(ADDON_PATH, 'icon.png')

OS_REST_HEADERS = {'User-Agent': 'HotSubtitlesV1'}

NORM_LANG = {
    'rum': 'ro', 'ron': 'ro', 'ro': 'ro',
    'eng': 'en', 'en': 'en',
    'spa': 'es', 'es': 'es', 'spa_la': 'es',
    'fre': 'fr', 'fra': 'fr', 'fr': 'fr',
    'ger': 'de', 'de': 'de',
    'ita': 'it', 'it': 'it',
    'hun': 'hu', 'hu': 'hu',
    'por': 'pt', 'pt': 'pt',
    'rus': 'ru', 'ru': 'ru',
    'tur': 'tr', 'tr': 'tr',
    'bul': 'bg', 'bg': 'bg',
    'ell': 'el', 'gre': 'el', 'el': 'el',
    'pol': 'pl', 'pl': 'pl',
    'cze': 'cs', 'cs': 'cs',
    'dut': 'nl', 'nl': 'nl',
    'ara': 'ar', 'ar': 'ar',
    'chi': 'zh', 'zh': 'zh',
    'jpn': 'ja', 'ja': 'ja',
    'kor': 'ko', 'ko': 'ko',
    'swe': 'sv', 'sv': 'sv',
    'dan': 'da', 'da': 'da',
    'fin': 'fi', 'fi': 'fi',
    'nor': 'no', 'no': 'no',
    'hrv': 'hr', 'hr': 'hr',
    'srp': 'sr', 'sr': 'sr',
    'slv': 'sl', 'sl': 'sl',
    'slo': 'sk', 'sk': 'sk',
    'ukr': 'uk', 'uk': 'uk',
    'heb': 'he', 'he': 'he',
    'tha': 'th', 'th': 'th',
    'vie': 'vi', 'vi': 'vi',
    'ind': 'id', 'id': 'id',
    'may': 'ms', 'ms': 'ms',
    'hin': 'hi', 'hi': 'hi',
    'per': 'fa', 'fa': 'fa',
    'cat': 'ca', 'ca': 'ca',
    'baq': 'eu', 'eu': 'eu',
    'glg': 'gl', 'gl': 'gl',
    'est': 'et', 'et': 'et',
    'lav': 'lv', 'lv': 'lv',
    'lit': 'lt', 'lt': 'lt',
    'mac': 'mk', 'mk': 'mk',
    'alb': 'sq', 'sq': 'sq',
    'bos': 'bs', 'bs': 'bs',
    'ice': 'is', 'is': 'is'
}

REST_LANG = {
    'ro': 'rum', 'en': 'eng', 'es': 'spa', 'fr': 'fre',
    'de': 'ger', 'it': 'ita', 'hu': 'hun', 'pt': 'por',
    'ru': 'rus', 'tr': 'tur', 'bg': 'bul', 'el': 'ell',
    'pl': 'pol', 'cs': 'cze', 'nl': 'dut', 'ar': 'ara',
    'zh': 'chi', 'ja': 'jpn', 'ko': 'kor', 'sv': 'swe',
    'da': 'dan', 'fi': 'fin', 'no': 'nor', 'hr': 'hrv',
    'sr': 'srp', 'sk': 'slo', 'sl': 'slv', 'uk': 'ukr',
    'he': 'heb', 'th': 'tha', 'vi': 'vie', 'id': 'ind',
    'ms': 'may', 'hi': 'hin', 'fa': 'per', 'ca': 'cat',
    'eu': 'baq', 'gl': 'glg', 'et': 'est', 'lv': 'lav',
    'lt': 'lit', 'mk': 'mac', 'sq': 'alb', 'bs': 'bos',
    'is': 'ice'
}


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[tmdbmovies-subs] {msg}", level)


def get_subs_folder():
    temp_dir = xbmcvfs.translatePath('special://temp/')
    subs_path = os.path.join(temp_dir, 'tmdbmovies_subs')
    if not xbmcvfs.exists(subs_path):
        xbmcvfs.mkdirs(subs_path)
    return subs_path


def cleanup_subs():
    subs_path = get_subs_folder()
    try:
        dirs, files = xbmcvfs.listdir(subs_path)
        for f in files:
            xbmcvfs.delete(os.path.join(subs_path, f))
    except Exception as e:
        log(f"Cleanup error: {e}", xbmc.LOGERROR)
    try:
        from resources.lib.downloader import cleanup_empty_download_folders
        cleanup_empty_download_folders()
    except:
        pass


def search_subtitles(imdb_id, season=None, episode=None):
    if not imdb_id: return []
    if not str(imdb_id).startswith('tt'):
        imdb_id = f"tt{imdb_id}"

    langs_setting = ADDON.getSetting('osv3_langs') or 'ro,en'
    languages = [l.strip().lower() for l in langs_setting.split(',')]
    found_subs = []
    seen_urls = set()

    try:
        numeric_id = str(imdb_id).replace('tt', '')
        is_tv = season and episode and str(season) != '0' and str(episode) != '0'

        if is_tv:
            query_path = f"episode-{episode}/imdbid-{numeric_id}/season-{season}"
        else:
            query_path = f"imdbid-{numeric_id}"

        os_url = f"https://rest.opensubtitles.org/search/{query_path}"
        r = requests.get(os_url, headers=OS_REST_HEADERS, timeout=10)

        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    file_id = item.get('IDSubtitleFile')
                    if not file_id: continue

                    url = f"https://subs5.strem.io/en/download/subencoding-stremio-utf8/src-api/file/{file_id}"
                    if url in seen_urls: continue

                    sub_lang_raw = item.get('ISO639', 'en')
                    sub_lang = NORM_LANG.get(sub_lang_raw, sub_lang_raw[:2])

                    if sub_lang in languages:
                        seen_urls.add(url)
                        raw_fname = item.get('SubFileName', f'subtitle_{file_id}.srt')
                        release = raw_fname[:-4] if raw_fname.lower().endswith('.srt') else raw_fname

                        found_subs.append({
                            'url': url,
                            'language': sub_lang,
                            'release': release,
                            'format': 'srt',
                            'source': 'OpenSubtitles'
                        })
    except Exception as e:
        log(f"OpenSubtitles REST search error: {e}", xbmc.LOGERROR)

    return found_subs


def download_and_save(sub_data, index):
    try:
        url = sub_data.get('url')
        if not url: return None

        folder = get_subs_folder()
        ext = sub_data.get('format', 'srt')
        lang_code = sub_data.get('language', 'unk')
        release_name = sub_data.get('release', f'Sub_{index}')

        raw_filename = f"{release_name}.{index:02d}.{lang_code}.{ext}"
        safe_filename = "".join(c for c in raw_filename if c not in r'\/:*?"<>|')
        filepath = os.path.join(folder, safe_filename)

        r = requests.get(url, timeout=15, headers=OS_REST_HEADERS)
        if r.status_code == 200:
            raw_content = r.content
            if b'<html' in raw_content.lower():
                return None

            try:
                text = raw_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text = raw_content.decode('cp1250')
                except UnicodeDecodeError:
                    try:
                        text = raw_content.decode('iso-8859-2')
                    except UnicodeDecodeError:
                        text = raw_content.decode('utf-8', errors='replace')

            utf8_content = b'\xef\xbb\xbf' + text.encode('utf-8')

            f = xbmcvfs.File(filepath, 'wb')
            f.write(utf8_content)
            f.close()

            return filepath
    except Exception as e:
        log(f"Download error: {e}", xbmc.LOGERROR)
    return None


def run_wyzie_service(imdb_id, season=None, episode=None):
    if ADDON.getSetting('use_osv3_subs') != 'true':
        return
    if not imdb_id:
        return

    if not str(imdb_id).startswith('tt') and str(imdb_id).isdigit():
        imdb_id = f"tt{imdb_id}"

    player = xbmc.Player()
    monitor = xbmc.Monitor()

    retries = 40
    while not monitor.abortRequested() and retries > 0:
        if player.isPlaying():
            break
        xbmc.sleep(500)
        retries -= 1

    if not player.isPlaying():
        return

    xbmc.sleep(1500)

    try:
        existing_subs = player.getAvailableSubtitleStreams()
        found_embedded_ro = False
        if existing_subs:
            for sub_name in existing_subs:
                name_lower = sub_name.lower()
                if 'romania' in name_lower or 'ro' == name_lower or 'rum' in name_lower:
                    found_embedded_ro = True
                    break
        if found_embedded_ro:
            log("Romanian subtitle detected in video. Canceling download.")
            return
    except Exception as e:
        log(f"Error checking existing subtitles: {e}", xbmc.LOGWARNING)

    log(f"Starting subtitle service (OpenSubtitles REST) for: {imdb_id}")

    cleanup_subs()
    subs_list = search_subtitles(imdb_id, season, episode)

    if not subs_list:
        log("No subtitles found on OpenSubtitles.")
        return

    downloaded_paths = []
    for i, sub in enumerate(subs_list):
        path = download_and_save(sub, i)
        if path:
            downloaded_paths.append(path)

    if not downloaded_paths:
        return

    log(f"Downloaded {len(downloaded_paths)} subtitles.")

    try:
        downloaded_paths.reverse()

        for idx, sub_path in enumerate(downloaded_paths):
            try:
                player.setSubtitles(sub_path)
                xbmc.sleep(350)
            except Exception as e:
                log(f"Error adding sub: {e}", xbmc.LOGERROR)

        player.showSubtitles(True)

        total_subs = len(downloaded_paths)
        first_sub_lang = subs_list[0].get("language", "").upper() if subs_list else ""
        first_sub_source = subs_list[0].get("source", "OpenSubtitles") if subs_list else "OpenSubtitles"
        notif_title = "[B][COLOR FF00CED1]TMDb [COLOR FFCCCCFF]Movies[/COLOR][/B]"
        notif_message = (
            f"Applied: [B][COLOR yellow]{total_subs}[/COLOR][/B] "
            f"[B][COLOR orange]{first_sub_lang}[/COLOR][/B] - "
            f"[B][COLOR FF00BFFF]'{first_sub_source}'[/COLOR][/B]"
        )
        xbmcgui.Dialog().notification(notif_title, notif_message, TMDbmovies_ICON, 4000)

    except Exception as e:
        log(f"Error setting subtitle: {e}", xbmc.LOGERROR)
