# -*- coding: utf-8 -*-
import os, sys, re, xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs, requests, threading
from urllib.parse import unquote, urlencode, parse_qsl

__addon__ = xbmcaddon.Addon()
__id__    = __addon__.getAddonInfo('id')

# ── Nume colorat + icon pentru notificări ────────────────────────
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

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else 0

LANGS      = ["ro","en","es","fr","de","it","hu","pt","ru","tr",
              "bg","el","pl","cs","nl"]
LANG_NAMES = ["Romanian","English","Spanish","French","German","Italian",
              "Hungarian","Portuguese","Russian","Turkish","Bulgarian",
              "Greek","Polish","Czech","Dutch"]

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


# ════════════════════════════════════════════════════════════════════
#  SEARCH
# ════════════════════════════════════════════════════════════════════
def search():
    base_url = 'https://sub.wyzie.ru/search'

    imdb_id = (xbmc.getInfoLabel("VideoPlayer.IMDBNumber")
               or xbmc.getInfoLabel("ListItem.Property(imdb_id)"))
    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    v_id = imdb_id or tmdb_id

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

    if not all_results and robot_activat:
        fetch_and_add(bp, mark_chosen=False)

    all_results.sort(key=lambda x: (not x['is_chosen'], x['language_name']))

    for res in all_results:
        li = xbmcgui.ListItem(label=res['language_name'])
        li.setLabel2(res['filename'])

        flag_code = res['l_code'][:2] if len(res['l_code']) >= 2 else res['l_code']
        li.setArt({'thumb': flag_code, 'icon': flag_code})

        d_params = {
            'action':       'download',
            'url':          res['url'],
            'l_code':       res['l_code'],
            'api_filename': res['api_filename'],
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
        url    = unquote(params.get('url', ''))
        l_code = params.get('l_code', 'unknown')

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

        r = requests.get(url, timeout=20)
        if not r.ok:
            xbmc.log(f"SUBSTUDIO: Download HTTP {r.status_code}", xbmc.LOGERROR)
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
            return

        try:
            fh = xbmcvfs.File(dest_path, 'w')
            fh.write(r.content)
            fh.close()
        except Exception:
            with open(dest_path, 'wb') as f:
                f.write(r.content)

        xbmc.log(f"SUBSTUDIO: Saved → {dest_path} (lang={l_code})", xbmc.LOGINFO)

        normalized_lcode = NORM.get(l_code, l_code)
        needs_translation = (normalized_lcode != chosen_lang)

        robot_on = False
        if robot is not None:
            try:
                robot_on = __addon__.getSettingBool('robot_activat')
            except Exception:
                pass

        try:
            temp_dir = xbmcvfs.translatePath('special://temp/')
            if needs_translation and robot_on:
                temp_lang = chosen_lang
            else:
                temp_lang = NORM.get(l_code, l_code)
            temp_name = f"TempSubtitle.{temp_lang}.srt"
            temp_path = os.path.join(temp_dir, temp_name)
            xbmcvfs.copy(dest_path, temp_path)
            xbmc.log(f"SUBSTUDIO: Temp → {temp_name}", xbmc.LOGINFO)
        except Exception as e:
            temp_path = dest_path
            xbmc.log(f"SUBSTUDIO: Temp copy failed: {e}", xbmc.LOGWARNING)

        li = xbmcgui.ListItem(label=safe_name)
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=temp_path, listitem=li)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=True)

        if needs_translation:
            if robot_on:
                xbmc.log(f"SUBSTUDIO: Translate {l_code}({normalized_lcode}) "
                         f"→ {chosen_lang}", xbmc.LOGINFO)
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
                xbmc.log("SUBSTUDIO: Robot INDISPONIBIL!", xbmc.LOGERROR)
                xbmcgui.Dialog().notification(
                    ADDON_NAME,
                    f'Limba {l_code.upper()} – robotul nu e disponibil!',
                    ADDON_ICON, 4000)
            else:
                xbmc.log("SUBSTUDIO: Robot dezactivat.", xbmc.LOGINFO)
                xbmcgui.Dialog().notification(
                    ADDON_NAME,
                    f'Limba {l_code.upper()} (robot dezactivat)',
                    ADDON_ICON, 4000)
        else:
            xbmc.log(f"SUBSTUDIO: Limba OK ({l_code}), directă.", xbmc.LOGINFO)

    except Exception as e:
        xbmc.log(f"SUBSTUDIO DL ERROR: {e}", xbmc.LOGERROR)
        try:
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2].lstrip('?'))) if len(sys.argv) > 2 else {}
    if p.get('action') == 'download':
        download(p)
    else:
        search()