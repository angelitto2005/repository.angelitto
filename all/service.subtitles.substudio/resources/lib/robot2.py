# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, re, json, urllib.parse, urllib.request, time
from threading import Thread, Lock

LINGVA_INSTANCES = [
    "https://lingva.ml",
    "https://translate.plausibility.cloud",
    "https://lingva.lunar.icu",
    "https://translate.projectsegfau.lt",
    "https://translate.dr460nf1r3.org"
]

def smart_wrap(text, limit=40):
    if not text or '\n' in text or len(text) <= limit: return text
    words = text.split(' ')
    mid = len(text) // 2
    curr = 0
    for i, w in enumerate(words):
        curr += len(w) + 1
        if curr >= mid:
            return ' '.join(words[:i+1]).strip() + '\n' + ' '.join(words[i+1:]).strip()
    return text

def _player_has_media():
    try:
        return xbmc.getCondVisibility('Player.HasVideo') or xbmc.Player().isPlayingVideo()
    except Exception:
        return False

class PerfectRocket:
    def __init__(self, target_lang):
        self.target_lang = target_lang
        self.results = {}
        self.failed_indices = set()
        self.lock = Lock()
        self.mirror_idx = 0
        self.sep = " @@@ "
        self.br = " [n] "
        self.stop_requested = False

    def check_stop(self):
        if not _player_has_media():
            self.stop_requested = True
        return self.stop_requested

    def _fetch_raw(self, text_batch):
        if self.check_stop(): return ""
        for _ in range(len(LINGVA_INSTANCES) * 2):
            if self.check_stop(): return ""
            with self.lock:
                base_url = LINGVA_INSTANCES[self.mirror_idx]
                self.mirror_idx = (self.mirror_idx + 1) % len(LINGVA_INSTANCES)
            try:
                url = f"{base_url}/api/v1/auto/{self.target_lang}/{urllib.parse.quote(text_batch)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=7) as r:
                    res = json.loads(r.read().decode('utf-8'))
                    return res.get('translation', "")
            except Exception:
                time.sleep(0.3)
        return ""

    def _process_recursive(self, lines, start_offset):
        if self.check_stop() or not lines: return []
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
        
        if len(lines) > 1:
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
        if self.check_stop(): return
        res = self._process_recursive(chunk, start_idx)
        if self.check_stop(): return
        with self.lock:
            for i, line in enumerate(res):
                self.results[start_idx + i] = line
        xbmc.log(f"Lingva Worker: Translated {len(res)} lines from index {start_idx}", xbmc.LOGINFO)

def run_translation(sub_addon_id):
    _addon = xbmcaddon.Addon(sub_addon_id)
    if _addon.getSetting('robot_activat') != 'true': return
    
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr", "bg", "el", "pl", "cs", "nl"]
    try: target_lang = langs[_addon.getSettingInt('subs_languages')]
    except Exception: target_lang = "ro"

    profile_path = xbmcvfs.translatePath('special://profile/addon_data/%s/' % sub_addon_id)
    _, files = xbmcvfs.listdir(profile_path)
    srt_files = [f for f in files if f.lower().endswith('.srt') and not f.startswith('robot_tradus')]
    if not srt_files: return
    
    original_name = srt_files[0]
    sub_path = os.path.join(profile_path, original_name)
    out_path = os.path.join(profile_path, f"robot_tradus.{target_lang}.srt")

    pDialog = xbmcgui.DialogProgressBG()
    
    try:
        start_time = time.time()
        f = xbmcvfs.File(sub_path); content = f.read(); f.close()
        pattern = re.compile(r'(\d+)\r?\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\r?\n|$)')
        blocks = pattern.findall(content)
        original_texts = [re.sub(r'<[^>]*>', '', b[2]).strip() for b in blocks]

        rocket = PerfectRocket(target_lang)
        pDialog.create('SubStudio', f'Lingva: Translating to {target_lang.upper()}...')

        def sync_player():
            srt_output = ""
            with rocket.lock:
                for k in range(len(blocks)):
                    idx, timing, _ = blocks[k]
                    t_text = rocket.results.get(k, original_texts[k])
                    srt_output += f"{idx}\n{timing}\n{t_text}\n\n"
            
            raw_bytes = b'\xef\xbb\xbf' + srt_output.encode('utf-8')
            f_out = xbmcvfs.File(out_path, 'wb'); f_out.write(raw_bytes); f_out.close()
            
            if rocket.check_stop(): return
            try:
                temp_dir = xbmcvfs.translatePath('special://temp/substudio_subs/')
                if not xbmcvfs.exists(temp_dir): xbmcvfs.mkdirs(temp_dir)
                ts = int(time.time())
                tf = os.path.join(temp_dir, f"robot_{ts}")
                xbmcvfs.mkdirs(tf)
                
                base = re.sub(r'\.[a-z]{2,3}$', '', os.path.splitext(original_name)[0], flags=re.IGNORECASE)
                clean_name = f"{base}.{target_lang}.srt"
                temp_sub = os.path.join(tf, clean_name)
                
                ft = xbmcvfs.File(temp_sub, 'wb'); ft.write(raw_bytes); ft.close()
                xbmc.Player().setSubtitles(temp_sub)
            except Exception: pass

        i = 0
        total = len(original_texts)

        for _ in range(3):
            if rocket.check_stop() or i >= total: break
            chunk = original_texts[i:i+20]
            rocket.worker(i, chunk)
            i += len(chunk)
            sync_player()
            pDialog.update(int((i / total) * 100))

        batch_size = 20
        while i < total:
            if rocket.check_stop(): break
            threads = []
            for _ in range(8):
                if i >= total or rocket.check_stop(): break
                chunk = original_texts[i : i + batch_size]
                t = Thread(target=rocket.worker, args=(i, chunk))
                threads.append(t); t.start()
                i += len(chunk)
                
            for t in threads:
                if rocket.check_stop(): break
                t.join(1.0) # wait with timeout
            
            if rocket.check_stop(): break
            sync_player()
            pDialog.update(int((i / total) * 100))
            time.sleep(0.05)

        pDialog.close()

        total_time = int(time.time() - start_time)

        if rocket.stop_requested:
            xbmcgui.Dialog().notification('Lingva Robot', 'Translation stopped by user', xbmcgui.NOTIFICATION_WARNING, 3000)
            xbmc.log("Lingva Robot stopped (Player Closed)", xbmc.LOGINFO)
            return
        
        # Permanent save (index.json)
        if _addon.getSetting('save_translations') == 'true':
            try:
                base = re.sub(r'\.[a-z]{2,3}$', '', os.path.splitext(original_name)[0], flags=re.IGNORECASE)
                final_name = f"{base}.{target_lang}.srt"
                
                saved_dir = os.path.join(profile_path, 'Translated Subtitles')
                if not xbmcvfs.exists(saved_dir): xbmcvfs.mkdirs(saved_dir)
                saved_path = os.path.join(saved_dir, final_name)
                xbmcvfs.copy(out_path, saved_path)
                
                imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or ""
                tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or ""
                video_title = xbmc.getInfoLabel("VideoPlayer.Title") or ""
                index_path = os.path.join(saved_dir, 'index.json')
                
                index = {}
                if xbmcvfs.exists(index_path):
                    try:
                        f_idx = xbmcvfs.File(index_path); raw = f_idx.read(); f_idx.close()
                        if raw: index = json.loads(raw.decode('utf-8'))
                    except Exception: pass
                    
                index[final_name] = {'imdb': imdb_id, 'tmdb': tmdb_id, 'title': video_title, 'file': final_name, 'complete': True}
                index_data = json.dumps(index, ensure_ascii=False, indent=2)
                f_idx_w = xbmcvfs.File(index_path, 'w'); f_idx_w.write(index_data.encode('utf-8')); f_idx_w.close()
            except Exception as ex:
                xbmc.log(f"Lingva permanent save error: {ex}", xbmc.LOGERROR)

        xbmcgui.Dialog().notification('Lingva Finished', f'Translation complete in {total_time}s', xbmcgui.NOTIFICATION_INFO, 5000)

    except Exception as e:
        try: pDialog.close()
        except Exception: pass
        xbmc.log(f"Lingva Error: {str(e)}", xbmc.LOGERROR)