import os
import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs


ADDON = xbmcaddon.Addon("plugin.video.vixmovie")
ADDON_PATH = ADDON.getAddonInfo("path")
VIXMOVIE_ICON = os.path.join(ADDON_PATH, "icon.png")

OS_V3_BASE_URL = "https://opensubtitles-v3.strem.io/subtitles"
OS_REST_BASE_URL = "https://rest.opensubtitles.org/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

NORM_LANG = {
    "rum": "ro",
    "ron": "ro",
    "ro": "ro",
    "eng": "en",
    "en": "en",
    "spa": "es",
    "es": "es",
    "spa_la": "es",
    "fre": "fr",
    "fra": "fr",
    "fr": "fr",
    "ger": "de",
    "de": "de",
    "ita": "it",
    "it": "it",
    "hun": "hu",
    "hu": "hu",
}

REST_LANG = {
    "ro": "rum",
    "en": "eng",
    "es": "spa",
    "fr": "fre",
    "de": "ger",
    "it": "ita",
    "hu": "hun",
}


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[vixmovie-subs] {msg}", level)


def get_subs_folder():
    temp_dir = xbmcvfs.translatePath("special://temp/")
    subs_path = os.path.join(temp_dir, "vixmovie_subs")
    if not xbmcvfs.exists(subs_path):
        xbmcvfs.mkdirs(subs_path)
    return subs_path


def cleanup_subs():
    subs_path = get_subs_folder()
    try:
        _, files = xbmcvfs.listdir(subs_path)
        for filename in files:
            xbmcvfs.delete(os.path.join(subs_path, filename))
    except Exception as e:
        log(f"Cleanup error: {e}", xbmc.LOGERROR)


def get_detailed_subtitle_names(imdb_id, target_lang=None, season=None, episode=None):
    mapping = {}
    if not imdb_id:
        return mapping

    try:
        numeric_id = str(imdb_id).replace("tt", "")
        parts = []
        if season and str(season) != "0" and episode and str(episode) != "0":
            parts.append(f"episode-{episode}")

        parts.append(f"imdbid-{numeric_id}")

        if season and str(season) != "0":
            parts.append(f"season-{season}")

        if target_lang:
            rest_lang = REST_LANG.get(target_lang, "eng")
            parts.append(f"sublanguageid-{rest_lang}")

        rest_url = f"{OS_REST_BASE_URL}/{'/'.join(parts)}"
        response = requests.get(rest_url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                for item in data:
                    file_name = item.get("SubFileName")
                    if not file_name:
                        continue
                    for key in ("IDSubtitleFile", "IDSubtitle"):
                        value = str(item.get(key, ""))
                        if value:
                            mapping[value] = file_name
    except Exception:
        pass

    return mapping


def search_subtitles(imdb_id, season=None, episode=None):
    if not imdb_id:
        return []

    langs_setting = ADDON.getSetting("osv3_langs") or "ro,en"
    languages = [lang.strip().lower() for lang in langs_setting.split(",") if lang.strip()]
    found_subs = []

    is_tv = season and episode and str(season) != "0" and str(episode) != "0"
    if is_tv:
        media_type = "series"
        query_id = f"{imdb_id}:{season}:{episode}"
    else:
        media_type = "movie"
        query_id = imdb_id

    api_url = f"{OS_V3_BASE_URL}/{media_type}/{query_id}.json"
    try:
        response = requests.get(api_url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return found_subs

        data = response.json()
        subtitles = data.get("subtitles", [])
        if not subtitles:
            return found_subs

        detailed_names = {}
        for lang in languages:
            detailed_names.update(get_detailed_subtitle_names(imdb_id, lang, season, episode))

        seen_urls = set()
        for sub in subtitles:
            sub_lang_raw = sub.get("lang", "").lower()
            sub_lang_2 = NORM_LANG.get(sub_lang_raw, sub_lang_raw)
            if sub_lang_2 not in languages:
                continue

            url = sub.get("url", "")
            if not url or url in seen_urls:
                continue

            seen_urls.add(url)
            sub_id = str(sub.get("id", ""))
            release_name = detailed_names.get(sub_id, f"OpenSubtitles_{sub_id}")
            if release_name.lower().endswith(".srt"):
                release_name = release_name[:-4]

            found_subs.append(
                {
                    "url": url,
                    "language": sub_lang_2,
                    "release": release_name,
                    "format": "srt",
                    "source": "OpenSubtitles",
                }
            )
    except Exception as e:
        log(f"Eroare căutare OpenSubtitles v3: {e}", xbmc.LOGERROR)

    return found_subs


def download_and_save(sub_data, index):
    try:
        url = sub_data.get("url")
        if not url:
            return None

        folder = get_subs_folder()
        ext = sub_data.get("format", "srt")
        lang_code = sub_data.get("language", "unk")
        release_name = sub_data.get("release", f"Sub_{index}")

        raw_filename = f"{release_name}.{index:02d}.{lang_code}.{ext}"
        safe_filename = "".join(c for c in raw_filename if c not in r'\/:*?"<>|')
        filepath = os.path.join(folder, safe_filename)

        response = requests.get(url, timeout=15, headers=HEADERS)
        if response.status_code == 200:
            raw_content = response.content
            if b"<html" in raw_content.lower():
                return None

            try:
                text = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw_content.decode("cp1250")
                except UnicodeDecodeError:
                    try:
                        text = raw_content.decode("iso-8859-2")
                    except UnicodeDecodeError:
                        text = raw_content.decode("utf-8", errors="replace")

            utf8_content = b"\xef\xbb\xbf" + text.encode("utf-8")
            file_handle = xbmcvfs.File(filepath, "wb")
            try:
                file_handle.write(utf8_content)
            finally:
                file_handle.close()

            return filepath
    except Exception as e:
        log(f"Download error: {e}", xbmc.LOGERROR)

    return None


def run_subtitle_service(imdb_id, season=None, episode=None):
    if ADDON.getSetting("use_osv3_subs") != "true":
        return
    if not imdb_id:
        return

    if not str(imdb_id).startswith("tt") and str(imdb_id).isdigit():
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
                if "romania" in name_lower or name_lower == "ro" or "rum" in name_lower:
                    found_embedded_ro = True
                    break
        if found_embedded_ro:
            log("Subtitrare Română detectată în video. Anulez descărcarea.")
            return
    except Exception as e:
        log(f"Eroare verificare subtitrări existente: {e}", xbmc.LOGWARNING)

    log(f"Start serviciu subtitrări (OpenSubtitles) pentru: {imdb_id}")

    cleanup_subs()
    subs_list = search_subtitles(imdb_id, season, episode)
    if not subs_list:
        log("Nu s-au găsit subtitrări pe OpenSubtitles.")
        return

    downloaded_paths = []
    for index, sub in enumerate(subs_list):
        path = download_and_save(sub, index)
        if path:
            downloaded_paths.append(path)

    if not downloaded_paths:
        return

    log(f"S-au descărcat {len(downloaded_paths)} subtitrări.")

    try:
        downloaded_paths.reverse()
        for sub_path in downloaded_paths:
            try:
                player.setSubtitles(sub_path)
                xbmc.sleep(350)
            except Exception as e:
                log(f"Eroare la adăugare sub: {e}", xbmc.LOGERROR)

        player.showSubtitles(True)

        total_subs = len(downloaded_paths)
        first_sub_source = subs_list[0].get("source", "OpenSubtitles") if subs_list else "OpenSubtitles"
        xbmcgui.Dialog().notification(
            "[B][COLOR FFFDBD01]VixMovie Subs[/COLOR][/B]",
            f"Aplicate: [B][COLOR yellow]{total_subs}[/COLOR][/B] [B][COLOR FF00BFFF]'{first_sub_source}'[/COLOR][/B]",
            VIXMOVIE_ICON,
            3000,
        )
    except Exception as e:
        log(f"Eroare setare subtitrare: {e}", xbmc.LOGERROR)


def run_wyzie_service(imdb_id, season=None, episode=None):
    run_subtitle_service(imdb_id, season, episode)
