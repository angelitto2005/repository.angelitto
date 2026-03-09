# -*- coding: utf-8 -*-
import os, sys, re, json, unicodedata, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__    = __addon__.getAddonInfo('id')

ADDON_NAME = '[B][COLOR FFB048B5]Sub[/COLOR][COLOR FF00BFFF]Studio[/COLOR][/B]'
ADDON_ICON = os.path.join(__addon__.getAddonInfo('path'), 'icon.png')

lib_path = xbmcvfs.translatePath(
    os.path.join(__addon__.getAddonInfo('path'), 'resources', 'lib'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

robot  = None
loader = None
try:
    import robot
except Exception as e:
    xbmc.log(f"SUBSTUDIO: robot import failed: {e}", xbmc.LOGERROR)
try:
    import loader
except Exception as e:
    xbmc.log(f"SUBSTUDIO: loader import failed: {e}", xbmc.LOGERROR)

# ── HANDLE — protejat contra RunScript ───────────────────────────
try:
    HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
except (ValueError, IndexError):
    HANDLE = 0

LANGS      = ["ro","en","es","fr","de","it","hu","pt","ru","tr",
              "bg","el","pl","cs","nl"]

LANG_MAP = {
    'ro':'Romanian','en':'English','es':'Spanish','fr':'French',
    'de':'German','it':'Italian','hu':'Hungarian','pt':'Portuguese',
    'ru':'Russian','tr':'Turkish','bg':'Bulgarian','el':'Greek',
    'pl':'Polish','cs':'Czech','nl':'Dutch','ar':'Arabic',
    'zh':'Chinese','ja':'Japanese','ko':'Korean','sv':'Swedish',
    'da':'Danish','fi':'Finnish','no':'Norwegian','hr':'Croatian',
    'sr':'Serbian','sk':'Slovak','sl':'Slovenian','uk':'Ukrainian',
    'he':'Hebrew','th':'Thai','vi':'Vietnamese','id':'Indonesian',
    'ms':'Malay','hi':'Hindi','fa':'Persian','ca':'Catalan',
    'eu':'Basque','gl':'Galician','et':'Estonian','lv':'Latvian',
    'lt':'Lithuanian','mk':'Macedonian','sq':'Albanian',
    'bs':'Bosnian','is':'Icelandic','mt':'Maltese','cy':'Welsh',
    'ga':'Irish','ka':'Georgian','af':'Afrikaans','sw':'Swahili',
    'ta':'Tamil','te':'Telugu','ur':'Urdu','bn':'Bengali',
    'ml':'Malayalam','kn':'Kannada','si':'Sinhala','my':'Burmese',
    'km':'Khmer','lo':'Lao','mn':'Mongolian','ne':'Nepali',
    'am':'Amharic','zu':'Zulu','tl':'Filipino',
    'rum':'Romanian','eng':'English','spa':'Spanish','fre':'French',
    'ger':'German','ita':'Italian','hun':'Hungarian','por':'Portuguese',
    'rus':'Russian','tur':'Turkish','bul':'Bulgarian','gre':'Greek',
    'pol':'Polish','cze':'Czech','dut':'Dutch','ara':'Arabic',
    'chi':'Chinese','jpn':'Japanese','kor':'Korean','swe':'Swedish',
    'dan':'Danish','fin':'Finnish','nor':'Norwegian','hrv':'Croatian',
    'srp':'Serbian','slv':'Slovenian','slo':'Slovak','ukr':'Ukrainian',
    'heb':'Hebrew','tha':'Thai','vie':'Vietnamese','per':'Persian',
    'cat':'Catalan','baq':'Basque','glg':'Galician','est':'Estonian',
    'lav':'Latvian','lit':'Lithuanian','mac':'Macedonian',
    'alb':'Albanian','bos':'Bosnian','ice':'Icelandic',
    'ind':'Indonesian','may':'Malay','hin':'Hindi',
    'pb':'Portuguese-BR','pob':'Portuguese-BR',
    'spa_la':'Spanish-LatAm','zht':'Chinese-Trad',
    'zhe':'Chinese-Simp',
}

NORM = {
    'eng':'en','spa':'es','fre':'fr','ger':'de','ita':'it',
    'dut':'nl','rum':'ro','gre':'el','cze':'cs','pol':'pl',
    'hun':'hu','tur':'tr','bul':'bg','rus':'ru','por':'pt',
    'spa_la':'es','pb':'pt','pob':'pt','cat':'ca',
    'hrv':'hr','srp':'sr','slv':'sl','slo':'sk','ukr':'uk',
    'ara':'ar','heb':'he','tha':'th','vie':'vi',
    'jpn':'ja','kor':'ko','chi':'zh','swe':'sv',
    'dan':'da','fin':'fi','nor':'no','ind':'id',
    'may':'ms','hin':'hi','per':'fa','alb':'sq',
    'bos':'bs','ice':'is','mac':'mk','baq':'eu',
    'glg':'gl','est':'et','lav':'lv','lit':'lt',
}

def _get_lang_name(code):
    if not code:
        return 'Unknown'
    return LANG_MAP.get(code, LANG_MAP.get(code.lower(), code.upper()))

def _safe_filename(name):
    name = re.sub(r'[<>:"|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def _normalize(s):
    """Elimină diacritice și caractere speciale pentru comparare."""
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-z0-9\s]', '', s.lower())
    s = re.sub(r'\s+', ' ', s).strip()
    return s


# ════════════════════════════════════════════════════════════════════
#  FOLDER SUBTITRĂRI SALVATE
# ════════════════════════════════════════════════════════════════════
def _get_saved_folder():
    profile = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
    saved_dir = os.path.join(profile, 'Subtitrari traduse')
    if not xbmcvfs.exists(saved_dir + os.sep):
        xbmcvfs.mkdirs(saved_dir + os.sep)
    return saved_dir


def _clean_saved_folder():
    saved_dir = _get_saved_folder()
    try:
        _, files = xbmcvfs.listdir(saved_dir)
        count = 0
        for f in files:
            try:
                xbmcvfs.delete(os.path.join(saved_dir, f))
                count += 1
            except Exception:
                pass

        if count > 0:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                f'[B][COLOR lime]{count}[/COLOR][/B] fișiere șterse!',
                ADDON_ICON, 4000)
        else:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                'Folderul era deja gol.',
                ADDON_ICON, 3000)
        xbmc.log(f"SUBSTUDIO: Șterse {count} fișiere (inclusiv index).",
                 xbmc.LOGINFO)
    except Exception as e:
        xbmc.log(f"SUBSTUDIO: Eroare ștergere: {e}", xbmc.LOGERROR)


# ════════════════════════════════════════════════════════════════════
#  POTRIVIRE FILM
# ════════════════════════════════════════════════════════════════════
def _extract_title_key(filename):
    name = os.path.splitext(filename)[0]
    for lang in LANGS:
        if name.lower().endswith(f'.{lang}'):
            name = name[:-len(lang)-1]
            break

    name = re.sub(r'[._\-]', ' ', name)

    stop_words = ['1080p','720p','2160p','4k','web','webrip','webdl',
                  'web-dl','bluray','brrip','hdrip','dvdrip','hdtv',
                  'x264','x265','h264','h265','hevc','aac','dts',
                  'ddp','dd5','atmos','amzn','nf','hulu','dsnp',
                  'hmax','atvp','pcok','mp4','mkv','avi']

    words = name.split()
    title_words = []
    for w in words:
        if w.lower() in stop_words:
            break
        title_words.append(w)

    key = ' '.join(title_words).strip().lower()
    return key if key else filename.lower()


def _find_saved_subtitle(imdb_id, tmdb_id, video_title):
    saved_dir = _get_saved_folder()

    try:
        _, files = xbmcvfs.listdir(saved_dir)
    except Exception:
        return []

    srt_files = [f for f in files if f.lower().endswith('.srt')]
    if not srt_files:
        return []

    matches = []

    # ── METODA 1: index.json ─────────────────────────────────────
    index_path = os.path.join(saved_dir, 'index.json')
    index = {}

    if xbmcvfs.exists(index_path):
        try:
            fh = xbmcvfs.File(index_path)
            raw = fh.read()
            fh.close()
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode('utf-8', errors='replace')
                index = json.loads(raw)
        except Exception as e:
            xbmc.log(f"SUBSTUDIO: Eroare citire index: {e}", xbmc.LOGERROR)

    if index:
        xbmc.log(f"SUBSTUDIO: Index: {len(index)} intrări.", xbmc.LOGINFO)

        for filename, info in index.items():
            # SKIP traduceri incomplete!
            if not info.get('complete', False):
                xbmc.log(f"SUBSTUDIO: Skip incomplet: {filename}", xbmc.LOGINFO)
                # Șterge fișierul incomplet
                incomplete_path = os.path.join(saved_dir, filename)
                if xbmcvfs.exists(incomplete_path):
                    xbmcvfs.delete(incomplete_path)
                    xbmc.log(f"SUBSTUDIO: Șters incomplet: {filename}", xbmc.LOGINFO)
                continue

            full_path = os.path.join(saved_dir, filename)
            if not xbmcvfs.exists(full_path):
                continue

            # Potrivire IMDB
            if imdb_id and info.get('imdb'):
                if imdb_id.lower().strip() == info['imdb'].lower().strip():
                    matches.append((full_path, filename))
                    xbmc.log(f"SUBSTUDIO: Match IMDB: {filename}", xbmc.LOGINFO)
                    continue

            # Potrivire TMDB
            if tmdb_id and info.get('tmdb'):
                if str(tmdb_id).strip() == str(info['tmdb']).strip():
                    matches.append((full_path, filename))
                    xbmc.log(f"SUBSTUDIO: Match TMDB: {filename}", xbmc.LOGINFO)
                    continue

            # Potrivire titlu normalizat
            if video_title and info.get('title'):
                n_idx = _normalize(info['title'])
                n_vid = _normalize(video_title)

                if n_idx and n_vid and (n_idx == n_vid or
                    n_idx.startswith(n_vid) or n_vid.startswith(n_idx)):
                    matches.append((full_path, filename))
                    xbmc.log(f"SUBSTUDIO: Match TITLE: "
                             f"'{info['title']}' ≈ '{video_title}'", xbmc.LOGINFO)
                    continue

    # ── METODA 2: Fallback filename ──────────────────────────────
    if not matches:
        current_key = _normalize(video_title) if video_title else ""

        for f in srt_files:
            saved_key = _normalize(_extract_title_key(f)) if current_key else ""

            if imdb_id and imdb_id.lower() in f.lower():
                matches.append((os.path.join(saved_dir, f), f))
                continue

            if current_key and saved_key:
                ck_words = current_key.split()[:3]
                sk_words = saved_key.split()[:3]

                if len(ck_words) >= 1 and ck_words == sk_words:
                    matches.append((os.path.join(saved_dir, f), f))
                    continue

                if len(current_key) >= 3 and (current_key in saved_key
                                               or saved_key in current_key):
                    matches.append((os.path.join(saved_dir, f), f))
                    continue

    xbmc.log(f"SUBSTUDIO: {len(matches)} potriviri locale.", xbmc.LOGINFO)
    return matches

# ════════════════════════════════════════════════════════════════════
#  SEARCH
# ════════════════════════════════════════════════════════════════════
def search():
    base_url = 'https://sub.wyzie.ru/search'

    imdb_id = (xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
               or xbmc.getInfoLabel("ListItem.Property(imdb_id)"))
    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    v_id = imdb_id or tmdb_id

    video_title = (xbmc.getInfoLabel("VideoPlayer.Title")
                   or xbmc.getInfoLabel("ListItem.Label")
                   or "")

    # Încearcă și titlul din filename-ul video
    video_file = xbmc.getInfoLabel("Player.Filename")
    if not video_title and video_file:
        video_title = os.path.splitext(video_file)[0]

    if not v_id:
        xbmc.log("SUBSTUDIO: No video ID found", xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(HANDLE)
        return

    try:
        l_code = LANGS[__addon__.getSettingInt('subs_languages')]
    except Exception:
        l_code = "ro"

    robot_activat = False
    try:
        robot_activat = __addon__.getSettingBool('robot_activat')
    except Exception:
        pass

    show_all = False
    try:
        show_all = __addon__.getSettingBool('show_all_langs')
    except Exception:
        pass

    s = xbmc.getInfoLabel("VideoPlayer.Season")
    e = xbmc.getInfoLabel("VideoPlayer.Episode")

    all_results = []
    seen_urls   = set()

    # ── 1. SUBTITRĂRI LOCALE ─────────────────────────────────────
    try:
        l_code_name = _get_lang_name(l_code)
    except Exception:
        l_code_name = l_code.upper()

    saved_matches = _find_saved_subtitle(imdb_id, tmdb_id, video_title)
    for saved_path, saved_name in saved_matches:
        if saved_path in seen_urls:
            continue
        seen_urls.add(saved_path)

        all_results.append({
            'language_name': f'[B][COLOR yellow]LOCAL[/COLOR][/B]',
            'filename':      saved_name,
            'url':           saved_path,
            'l_code':        l_code,
            'api_filename':  saved_name,
            'is_chosen':     True,
            'is_local':      True,
        })

    # ── 2. ONLINE ────────────────────────────────────────────────
    def fetch_and_add(search_params, mark_chosen=False):
        try:
            r = requests.get(base_url, params=search_params, timeout=10)
            if not r.ok:
                return
            for sub in r.json():
                url = sub.get('url', '')
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                t_code    = sub.get('language', '') or 'unknown'
                full_lang = _get_lang_name(t_code)
                fname     = sub.get('fileName', 'sub.srt') or 'sub.srt'

                all_results.append({
                    'language_name': full_lang,
                    'filename':      fname,
                    'url':           url,
                    'l_code':        t_code,
                    'api_filename':  fname,
                    'is_chosen':     mark_chosen and (t_code == l_code),
                    'is_local':      False,
                })
        except Exception as ex:
            xbmc.log(f"SUBSTUDIO SEARCH ERR: {ex}", xbmc.LOGERROR)

    bp = {'id': v_id}
    if s and s != "0":
        bp['season'] = s
        bp['episode'] = e

    if show_all:
        fetch_and_add(bp, mark_chosen=True)
    else:
        p1 = dict(bp); p1['language'] = l_code
        fetch_and_add(p1, mark_chosen=True)

        if l_code != 'en' and robot_activat:
            p2 = dict(bp); p2['language'] = 'en'
            fetch_and_add(p2, mark_chosen=False)

    if len(all_results) <= len(saved_matches) and robot_activat:
        fetch_and_add(bp, mark_chosen=False)

    # Sortare: LOCAL → limba preferată → restul
    all_results.sort(key=lambda x: (
        not x.get('is_local', False),
        not x['is_chosen'],
        x['language_name']
    ))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(res['filename'])

        # Steagul limbii — pentru LOCAL folosim limba preferată
        if res.get('is_local', False):
            flag_code = l_code[:2]
        else:
            flag_code = res['l_code'][:2] if len(res['l_code']) >= 2 else res['l_code']

        li.setArt({'thumb': flag_code, 'icon': flag_code})

        d_params = {
            'action':       'download',
            'url':          res['url'],
            'l_code':       res['l_code'],
            'api_filename': res['api_filename'],
            'is_local':     '1' if res.get('is_local', False) else '0',
        }
        xbmcplugin.addDirectoryItem(
            handle=HANDLE,
            url=f"{sys.argv[0]}?{urlencode(d_params)}",
            listitem=li,
        )

    xbmcplugin.endOfDirectory(HANDLE)


# ════════════════════════════════════════════════════════════════════
#  DOWNLOAD
# ════════════════════════════════════════════════════════════════════
def download(params):
    try:
        url       = unquote(params.get('url', ''))
        l_code    = params.get('l_code', 'unknown')
        is_local  = params.get('is_local', '0') == '1'

        api_filename = params.get('api_filename') or 'subtitle.srt'
        if not api_filename.lower().endswith('.srt'):
            api_filename += '.srt'

        safe_name = _safe_filename(api_filename)

        try:
            chosen_lang = LANGS[__addon__.getSettingInt('subs_languages')]
        except Exception:
            chosen_lang = "ro"

        dest_dir = xbmcvfs.translatePath(__addon__.getAddonInfo('profile'))
        if not xbmcvfs.exists(dest_dir):
            xbmcvfs.mkdirs(dest_dir)

        # Șterge SRT-uri vechi (NU din Subtitrari traduse!)
        try:
            _, old_files = xbmcvfs.listdir(dest_dir)
            for f in old_files:
                if f.lower().endswith('.srt'):
                    try:
                        xbmcvfs.delete(os.path.join(dest_dir, f))
                    except Exception:
                        pass
        except Exception:
            pass

        # Șterge TempSubtitle vechi
        try:
            temp_dir = xbmcvfs.translatePath('special://temp/')
            _, temp_files = xbmcvfs.listdir(temp_dir)
            for f in temp_files:
                if f.lower().startswith('tempsubtitle') and f.lower().endswith('.srt'):
                    try:
                        xbmcvfs.delete(os.path.join(temp_dir, f))
                    except Exception:
                        pass
        except Exception:
            pass

        dest_path = os.path.join(dest_dir, safe_name)

        # ── DESCĂRCARE ───────────────────────────────────────────
        if is_local:
            xbmcvfs.copy(url, dest_path)
            xbmc.log(f"SUBSTUDIO: Local → {dest_path}", xbmc.LOGINFO)
        else:
            r = requests.get(url, timeout=20)
            if not r.ok:
                xbmc.log(f"SUBSTUDIO: HTTP {r.status_code}", xbmc.LOGERROR)
                xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
                return
            try:
                fh = xbmcvfs.File(dest_path, 'w')
                fh.write(r.content)
                fh.close()
            except Exception:
                with open(dest_path, 'wb') as f:
                    f.write(r.content)

        xbmc.log(f"SUBSTUDIO: Saved → {dest_path} (local={is_local})",
                 xbmc.LOGINFO)

        normalized_lcode = NORM.get(l_code, l_code)

        if is_local:
            needs_translation = False
        else:
            needs_translation = (normalized_lcode != chosen_lang)

        robot_on = False
        if robot is not None:
            try:
                robot_on = __addon__.getSettingBool('robot_activat')
            except Exception:
                pass

        # ── Copiază în temp ──────────────────────────────────────
        try:
            temp_dir = xbmcvfs.translatePath('special://temp/')
            if needs_translation and robot_on:
                temp_lang = chosen_lang
            else:
                temp_lang = NORM.get(l_code, l_code)
            temp_name = f"TempSubtitle.{temp_lang}.srt"
            temp_path = os.path.join(temp_dir, temp_name)
            xbmcvfs.copy(dest_path, temp_path)
        except Exception:
            temp_path = dest_path

        li = xbmcgui.ListItem(label=safe_name)
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=temp_path, listitem=li)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True)

        if is_local:
            xbmcgui.Dialog().notification(
                ADDON_NAME,
                f'Subtitrare locală [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] activată!',
                ADDON_ICON, 3000)
        elif needs_translation:
            if robot_on:
                xbmc.log(f"SUBSTUDIO: Translate {l_code} → {chosen_lang}",
                         xbmc.LOGINFO)
                xbmcgui.Dialog().notification(
                    ADDON_NAME,
                    f'Traducere [B][COLOR orange]{chosen_lang.upper()}[/COLOR][/B] pornită...',
                    ADDON_ICON, 3000)
                threading.Thread(
                    target=robot.run_translation,
                    args=(__id__,),
                    daemon=True,
                ).start()
            elif robot is None:
                xbmcgui.Dialog().notification(
                    ADDON_NAME, 'Robotul nu e disponibil!',
                    ADDON_ICON, 4000)
            else:
                xbmcgui.Dialog().notification(
                    ADDON_NAME, 'Robot dezactivat',
                    ADDON_ICON, 4000)
        else:
            xbmc.log(f"SUBSTUDIO: Limba OK ({l_code}).", xbmc.LOGINFO)

    except Exception as e:
        xbmc.log(f"SUBSTUDIO DL ERROR: {e}", xbmc.LOGERROR)
        try:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # ── Verifică dacă e RunScript (clean_saved) ──────────────────
    # RunScript trimite parametrii ca sys.argv[1], sys.argv[2], etc.
    # NU ca query string
    for arg in sys.argv:
        if 'clean_saved' in str(arg):
            _clean_saved_folder()
            sys.exit(0)

    # ── Flow normal (subtitle module) ────────────────────────────
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download':
        download(p)
    else:
        search()