# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, time, html
from threading import Thread, Lock

# Import uploader centralizat
try:
    from . import uploader
except:
    try: import uploader
    except: uploader = None

LINGVA_INSTANCES = [
    "https://lingva.ml",
    "https://translate.plausibility.cloud",
    "https://lingva.lunar.icu",
    "https://translate.projectsegfau.lt",
    "https://translate.dr460nf1r3.org"
]

def smart_wrap(text, limit=45):
    try: text = html.unescape(text)
    except: pass
    if not text or '\n' in text or len(text) <= limit:
        return text
    words = text.split(' ')
    mid = len(text) // 2
    curr = 0
    for i, w in enumerate(words):
        curr += len(w) + 1
        if curr >= mid:
            return ' '.join(words[:i+1]).strip() + '\n' + ' '.join(words[i+1:]).strip()
    return text

class PerfectRocket:
    def __init__(self, target_lang):
        self.target_lang = target_lang
        self.results = {}
        self.failed_indices = set()
        self.lock = Lock()
        self.mirror_idx = 0
        self.sep = " @@@ "
        self.br = " [n] "

    def _fetch_raw(self, text_batch):
        if not xbmc.Player().isPlaying(): return ""
        for _ in range(len(LINGVA_INSTANCES) * 2):
            if not xbmc.Player().isPlaying(): break
            with self.lock:
                base_url = LINGVA_INSTANCES[self.mirror_idx]
                self.mirror_idx = (self.mirror_idx + 1) % len(LINGVA_INSTANCES)
            try:
                url = f"{base_url}/api/v1/auto/{self.target_lang}/{urllib.parse.quote(text_batch)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=7) as r:
                    res = json.loads(r.read().decode('utf-8'))
                    return res.get('translation', "")
            except:
                time.sleep(0.3)
        return ""

    def _process_recursive(self, lines, start_offset):
        if not lines or not xbmc.Player().isPlaying(): return []
        batch_text = self.sep.join([l.replace('\n', self.br).strip() for l in lines])
        translated = self._fetch_raw(batch_text)
        parts = [p.strip() for p in translated.split("@@@") if p.strip()]

        if len(parts) == len(lines):
            final = []
            for p in parts:
                clean = p.replace('[n]', '\n').replace('[N]', '\n').replace('<br>', '\n')
                clean = "\n".join([line.strip() for line in clean.split('\n') if line.strip()])
                final.append(smart_wrap(clean))
            return final
        
        if len(lines) > 1 and xbmc.Player().isPlaying():
            mid = len(lines) // 2
            return self._process_recursive(lines[:mid], start_offset) + \
                   self._process_recursive(lines[mid:], start_offset + mid)
        else:
            txt = lines[0] if isinstance(lines, list) else lines
            res = self._fetch_raw(txt.replace('\n', self.br))
            if res: return [smart_wrap(res.replace('[n]', '\n'))]
            else:
                with self.lock: self.failed_indices.add(start_offset)
                return [txt]

    def worker(self, start_idx, chunk):
        if not xbmc.Player().isPlaying(): return
        res = self._process_recursive(chunk, start_idx)
        with self.lock:
            for i, line in enumerate(res): self.results[start_idx + i] = line

def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return
    
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except: target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not (f.startswith('Google-') or f.startswith('Gemini-') or f.startswith('Lingva-'))]
    if not srt_files: return
    
    orig_full_name = srt_files[0]
    sub_path = os.path.join(profile_path, orig_full_name)
    base_name = orig_full_name.rsplit('.', 1)[0]
    final_name = "Lingva-{}.{}.srt".format(base_name, target_lang)
    output_path = os.path.join(profile_path, final_name)

    # --- VERIFICARE CLOUD ---
    if uploader:
        # 1. Luăm calea (ex: "Seriale/tt123_S-01_E-01" sau "Filme/tt123")
        cale_cloud = uploader.get_folder_grup() 
        auth = uploader.koofr_get_auth()
        
        # 2. Folosim variabila CORECtĂ (cale_cloud) în URL
        remote_url = "https://app.koofr.net/dav/Koofr/Subtitrari/{}/{}".format(cale_cloud, urllib.parse.quote(final_name))
        
        try:
            req_c = urllib.request.Request(remote_url, method='GET', headers={"Authorization": auth})
            with urllib.request.urlopen(req_c, timeout=10) as r:
                if r.getcode() == 200:
                    xbmc.executebuiltin('Notification("Cloud", "Subtitrare găsită!", 2000)')
                    with xbmcvfs.File(output_path, 'wb') as f_o: f_o.write(r.read())
                    xbmc.Player().setSubtitles(output_path)
                    return # Oprim robotul aici dacă am găsit-o deja
        except:
            pass


    try:
        start_time = time.time()
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        original_texts = [re.sub(r'<[^>]*>', '', b[2]).strip() for b in blocks]
        rocket = PerfectRocket(target_lang)

        def sync_player(curr_count):
            if not xbmc.Player().isPlaying(): return
            srt_output = ""
            with rocket.lock:
                for k in range(len(blocks)):
                    idx, timing, _ = blocks[k]
                    t_text = rocket.results.get(k, original_texts[k])
                    srt_output += f"{idx}\n{timing}\n{t_text}\n\n"
            with xbmcvfs.File(output_path, 'w') as f_out: f_out.write(srt_output)
            xbmc.Player().setSubtitles(output_path)
            xbmc.executebuiltin('Notification("Lingva", "Linii: {}/{}", 1200)'.format(curr_count, len(original_texts)))

        i, total = 0, len(original_texts)
        # Start rapid (primele 60 linii)
        for _ in range(3):
            if i < total and xbmc.Player().isPlaying():
                chunk = original_texts[i:i+20]
                rocket.worker(i, chunk)
                i += len(chunk); sync_player(i)

        # Restul cu thread-uri
        batch_size = 20
        while i < total and xbmc.Player().isPlaying():
            threads = []
            for _ in range(8):
                if i >= total or not xbmc.Player().isPlaying(): break
                t = Thread(target=rocket.worker, args=(i, original_texts[i : i + batch_size]))
                threads.append(t); t.start(); i += batch_size
            for t in threads: t.join()
            if xbmc.Player().isPlaying(): sync_player(i)

        # Upload final
        if xbmc.Player().isPlaying() and uploader:
            Thread(target=uploader.upload_now, args=(output_path, final_name)).start()

    except Exception as e:
        xbmc.log(f"Robot Lingva Error: {str(e)}", xbmc.LOGERROR)
