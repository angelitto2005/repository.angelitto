# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, sys, re, json, time
import urllib.parse, urllib.request, urllib.error
import threading

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURARE
# ═══════════════════════════════════════════════════════════════════
MODEL_PREFERAT = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
]

FIRST_BATCH_SIZE  = 100
NEXT_BATCH_SIZE   = 500
PAUZA_INTRE_BATCH = 12
PAUZA_DUPA_EROARE = 15
MAX_RETRIES       = 3
API_TIMEOUT       = 120

# ═══════════════════════════════════════════════════════════════════
#  NUME COLORAT + ICON
# ═══════════════════════════════════════════════════════════════════
ADDON_NAME = '[B][COLOR FFB048B5]Sub[/COLOR][COLOR FF00BFFF]Studio[/COLOR][/B]'

def _get_addon_icon():
    try:
        return os.path.join(xbmcaddon.Addon().getAddonInfo('path'), 'icon.png')
    except Exception:
        return ''

# ═══════════════════════════════════════════════════════════════════
#  DEBUG LOGGER
# ═══════════════════════════════════════════════════════════════════
_debug_enabled = False

def _init_debug(addon):
    global _debug_enabled
    try:
        _debug_enabled = addon.getSetting('debug_logging') == 'true'
    except Exception:
        _debug_enabled = False

def _log_debug(msg):
    if _debug_enabled:
        xbmc.log(f"ROBOT DEBUG: {msg}", xbmc.LOGINFO)

def _log_info(msg):
    xbmc.log(f"ROBOT: {msg}", xbmc.LOGINFO)

def _log_warn(msg):
    xbmc.log(f"ROBOT: {msg}", xbmc.LOGWARNING)

def _log_error(msg):
    xbmc.log(f"ROBOT: {msg}", xbmc.LOGERROR)

# ═══════════════════════════════════════════════════════════════════
#  NOTIFICARE HELPER
# ═══════════════════════════════════════════════════════════════════
def _notify(msg, icon_type=xbmcgui.NOTIFICATION_INFO, duration=4000):
    xbmcgui.Dialog().notification(ADDON_NAME, msg, _get_addon_icon(), duration)

# ═══════════════════════════════════════════════════════════════════
#  BLACKLIST CHEI
# ═══════════════════════════════════════════════════════════════════
_blocked_keys = set()
_blocked_lock = threading.Lock()

def _is_blocked(key):
    with _blocked_lock:
        return key in _blocked_keys

def _block_key(key):
    with _blocked_lock:
        _blocked_keys.add(key)
    _log_warn(f"Cheie blocată: ...{key[-4:]}")

def _reset_blocked():
    global _blocked_keys
    with _blocked_lock:
        _blocked_keys = set()
    _log_debug("Blacklist chei resetată.")


# ═══════════════════════════════════════════════════════════════════
#  PARSARE SRT
# ═══════════════════════════════════════════════════════════════════
def parse_srt(content):
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='replace')

    content = content.replace('\r\n', '\n').replace('\r', '\n')
    if content.startswith('\ufeff'):
        content = content[1:]
    content = content.strip() + '\n\n'

    pattern = re.compile(
        r'(\d+)\n'
        r'(\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3})\n'
        r'(.*?)(?=\n\n)',
        re.DOTALL,
    )

    blocks = []
    for bid, timing, text in pattern.findall(content):
        text = text.strip()
        if text:
            blocks.append((bid.strip(), timing.strip(), text))

    _log_debug(f"parse_srt: {len(blocks)} blocuri parsate")
    return blocks


# ═══════════════════════════════════════════════════════════════════
#  APEL GEMINI API
# ═══════════════════════════════════════════════════════════════════
def translate_gemini(texts_dict, target_lang, api_key, model_name,
                     style_instruction=""):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )

    prompt = (
        f"Translate the following subtitle texts to {target_lang}.\n"
        f"{style_instruction}\n"
        "Rules:\n"
        "- Return ONLY a valid JSON object, nothing else.\n"
        "- Keys are the subtitle IDs (as strings).\n"
        "- Values are the translated texts.\n"
        "- Keep all formatting tags if present.\n"
        "- Do NOT add markdown, explanations, or code fences.\n"
        '- Example: {"1": "translated line one", "2": "translated line two"}\n'
    )

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt + "\n\n" + json.dumps(texts_dict, ensure_ascii=False)
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    }

    _log_debug(f"API call: model={model_name}, cheie=...{api_key[-4:]}, "
               f"{len(texts_dict)} texte")

    request_start = time.time()

    try:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        _log_debug(f"Request body: {len(body)} bytes")

        req = urllib.request.Request(
            url, data=body,
            headers={'Content-Type': 'application/json; charset=utf-8'},
            method='POST',
        )

        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            raw = resp.read().decode('utf-8')
            res_data = json.loads(raw)

        elapsed = round(time.time() - request_start, 1)
        _log_debug(f"API răspuns în {elapsed}s, {len(raw)} bytes")

        if 'error' in res_data:
            code = res_data['error'].get('code', 0)
            msg = res_data['error'].get('message', '')[:200]
            _log_error(f"API ERR {code} [{model_name}]: {msg}")
            return None, code

        try:
            text_r = res_data['candidates'][0]['content']['parts'][0]['text']
        except (KeyError, IndexError, TypeError):
            _log_error(f"Răspuns invalid [{model_name}]")
            _log_debug(f"Răspuns: {json.dumps(res_data)[:500]}")
            return None, 0

        _log_debug(f"Text răspuns: {len(text_r)} car, preview: {text_r[:100]}...")

        for attempt_parse in range(3):
            try:
                if attempt_parse == 0:
                    candidate = text_r
                    method = "direct"
                elif attempt_parse == 1:
                    candidate = re.sub(r'```(?:json)?\s*', '', text_r)
                    candidate = re.sub(r'```', '', candidate).strip()
                    method = "clean markdown"
                else:
                    m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
                                  text_r, re.DOTALL)
                    candidate = m.group() if m else ""
                    method = "regex extract"

                if candidate:
                    result = json.loads(candidate)
                    if isinstance(result, dict) and len(result) > 0:
                        _log_debug(f"JSON OK ({method}), {len(result)} intrări")
                        return result, 0
            except (json.JSONDecodeError, ValueError, AttributeError):
                _log_debug(f"JSON fail metoda {attempt_parse}: {method}")
                continue

        _log_error(f"JSON parse fail total [{model_name}]: {text_r[:200]}")
        return None, 0

    except urllib.error.HTTPError as e:
        code = e.code
        elapsed = round(time.time() - request_start, 1)
        try:
            err_body = e.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            err_body = ""
        _log_error(f"HTTP {code} [{model_name}] după {elapsed}s: {err_body}")
        return None, code

    except urllib.error.URLError as e:
        _log_error(f"URL ERR [{model_name}]: {e.reason}")
        return None, 0

    except Exception as e:
        _log_error(f"EXCEPTION [{model_name}]: {type(e).__name__}: {e}")
        return None, 0


# ═══════════════════════════════════════════════════════════════════
#  TRADUCE UN BATCH
# ═══════════════════════════════════════════════════════════════════
def translate_one_batch(batch, target_lang, all_keys, style_instruction):
    to_translate = {}
    for b_id, _timing, text in batch:
        clean = re.sub(r'<[^>]*>', '', text).strip()
        to_translate[b_id] = clean if clean else text.strip()

    _log_debug(f"translate_one_batch: {len(to_translate)} texte, "
               f"{len(all_keys)} chei")

    for key_idx, current_key in enumerate(all_keys):
        if _is_blocked(current_key):
            _log_debug(f"Cheie {key_idx+1} ...{current_key[-4:]} blocată, skip")
            continue

        _log_debug(f"Încerc cheie {key_idx+1}/{len(all_keys)}: "
                   f"...{current_key[-4:]}")

        for model_idx, current_model in enumerate(MODEL_PREFERAT):
            _log_debug(f"  Model {model_idx+1}/{len(MODEL_PREFERAT)}: "
                       f"{current_model}")

            result, err_code = translate_gemini(
                to_translate, target_lang, current_key,
                current_model, style_instruction,
            )

            if result is not None:
                received = len(result)
                sent = len(to_translate)
                if received < sent:
                    _log_warn(f"Traducere parțială: {received}/{sent}")
                else:
                    _log_debug(f"Traducere completă: {received}/{sent}")

                chunk = ""
                for b_id, timing, orig_text in batch:
                    tr = result.get(str(b_id), result.get(b_id, orig_text))
                    chunk += f"{b_id}\n{timing}\n{tr}\n\n"
                return chunk, current_model

            if err_code == 403:
                _block_key(current_key)
                break
            elif err_code == 429:
                _log_warn(f"429 (quota) pe ...{current_key[-4:]}")
                time.sleep(PAUZA_DUPA_EROARE)
                break
            elif err_code in (503, 504):
                _log_debug(f"  {err_code} pe {current_model}, alt model")
                time.sleep(PAUZA_DUPA_EROARE)
                continue
            elif err_code == 404:
                _log_debug(f"  404 pe {current_model}, alt model")
                continue
            else:
                _log_debug(f"  Eroare {err_code}, alt model")
                time.sleep(PAUZA_DUPA_EROARE)
                continue

    _log_error("Toate cheile/modelele epuizate!")
    return None, ""


# ═══════════════════════════════════════════════════════════════════
#  CONSTRUIEȘTE SRT VALID
# ═══════════════════════════════════════════════════════════════════
def _build_srt_from_chunks(all_chunks):
    full_srt = ""
    counter = 1

    for chunk_idx, chunk in enumerate(all_chunks):
        entries = parse_srt(chunk)
        _log_debug(f"Chunk {chunk_idx+1}: {len(entries)} intrări")
        for _bid, timing, text in entries:
            full_srt += f"{counter}\r\n{timing}\r\n{text}\r\n\r\n"
            counter += 1

    _log_debug(f"SRT total: {counter-1} blocuri, {len(full_srt)} caractere")
    return full_srt, counter - 1


# ═══════════════════════════════════════════════════════════════════
#  SCRIE SRT + ACTIVEAZĂ
# ═══════════════════════════════════════════════════════════════════
def _write_and_activate(output_path, all_chunks, target_lang="ro"):
    srt_content, total_blocks = _build_srt_from_chunks(all_chunks)

    if total_blocks == 0:
        _log_error("SRT construit e gol!")
        return False

    raw_bytes = srt_content.encode('utf-8')

    try:
        fh = xbmcvfs.File(output_path, 'w')
        success = fh.write(raw_bytes)
        fh.close()
        if not success:
            with open(output_path, 'wb') as f:
                f.write(raw_bytes)
    except Exception as e:
        _log_error(f"Eroare scriere SRT: {e}")
        try:
            with open(output_path, 'wb') as f:
                f.write(raw_bytes)
        except Exception as e2:
            _log_error(f"Fallback scriere eșuat: {e2}")
            return False

    try:
        size = os.path.getsize(output_path)
        _log_info(f"SRT scris OK ({size} bytes, {total_blocks} blocuri)")
    except Exception:
        pass

    try:
        player = xbmc.Player()
        if player.isPlaying():
            player.setSubtitles(output_path)
            _log_info("Subtitrare activată în player.")
        else:
            _log_debug("Player nu rulează, skip activare.")
    except Exception as e:
        _log_error(f"Activare error: {e}")

    return True


# ═══════════════════════════════════════════════════════════════════
#  CREARE BATCH-URI
# ═══════════════════════════════════════════════════════════════════
def _make_batches(blocks):
    batches = []
    if len(blocks) <= FIRST_BATCH_SIZE:
        batches.append(blocks)
    else:
        batches.append(blocks[:FIRST_BATCH_SIZE])
        rest = blocks[FIRST_BATCH_SIZE:]
        for i in range(0, len(rest), NEXT_BATCH_SIZE):
            batches.append(rest[i:i + NEXT_BATCH_SIZE])
    return batches


# ═══════════════════════════════════════════════════════════════════
#  GENEREAZĂ NUMELE FIȘIERULUI TRADUS
# ═══════════════════════════════════════════════════════════════════
def _make_output_name(original_name, target_lang):
    base, ext = os.path.splitext(original_name)
    return f"{base}.{target_lang}{ext}"


# ═══════════════════════════════════════════════════════════════════
#  FUNCȚIA PRINCIPALĂ
# ═══════════════════════════════════════════════════════════════════
def run_translation(sub_addon_id):
    _reset_blocked()

    try:
        _addon = xbmcaddon.Addon(sub_addon_id)
    except Exception as e:
        _log_error(f"Nu pot accesa addon {sub_addon_id}: {e}")
        return

    _init_debug(_addon)

    if _addon.getSetting('robot_activat') != 'true':
        _log_info("Dezactivat din setări.")
        return

    _log_debug("═══ START TRADUCERE ═══")

    # ── Colectare chei API ───────────────────────────────────────
    all_keys = []
    for i in range(1, 6):
        k = _addon.getSetting(f'api_key_{i}')
        if k and k.strip():
            all_keys.append(k.strip())
            _log_debug(f"Cheie {i}: ...{k.strip()[-4:]} ({len(k.strip())} car)")

    all_keys = list(dict.fromkeys(all_keys))

    if not all_keys:
        xbmcgui.Dialog().ok(
            "SubStudio – Eroare",
            "Nicio cheie API configurată!\n\n"
            "1. Mergi la aistudio.google.com\n"
            "2. Creează o cheie API gratuită\n"
            "3. Adaug-o în Setări → Cheie Gemini API"
        )
        return

    masked = [f"...{k[-4:]}" for k in all_keys]
    _log_info(f"{len(all_keys)} chei API: {masked}")

    # ── Limba țintă ──────────────────────────────────────────────
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr",
             "bg", "el", "pl", "cs", "nl"]
    try:
        lang_idx = _addon.getSettingInt('subs_languages')
        target_lang = langs[lang_idx]
        _log_debug(f"Limba: index={lang_idx}, cod={target_lang}")
    except Exception:
        target_lang = "ro"

    style_instruction = "Use professional, natural localization style."

    # ── Găsește fișierul SRT sursă ───────────────────────────────
    profile_path = xbmcvfs.translatePath(
        f'special://profile/addon_data/{sub_addon_id}/')
    _log_debug(f"Profile path: {profile_path}")

    try:
        res = xbmcvfs.listdir(profile_path)
        files = res[1] if isinstance(res, tuple) else res
        _log_debug(f"Fișiere: {files}")
    except Exception as e:
        _log_error(f"listdir failed: {e}")
        return

    lang_pattern = re.compile(
        r'\.(' + '|'.join(langs) + r')\.srt$', re.IGNORECASE)

    srt_files = [
        f for f in files
        if f.lower().endswith('.srt')
        and not lang_pattern.search(f)
    ]

    if not srt_files:
        srt_files = [f for f in files if f.lower().endswith('.srt')]

    if not srt_files:
        _log_warn("Niciun fișier SRT găsit.")
        _notify('Niciun fișier SRT de tradus!')
        return

    original_name = srt_files[0]
    sub_path = os.path.join(profile_path, original_name)
    _log_info(f"Traducere {original_name} → {target_lang}")

    # ── Citire conținut ──────────────────────────────────────────
    try:
        fh = xbmcvfs.File(sub_path)
        content = fh.read()
        fh.close()
        _log_debug(f"Fișier citit: {len(content) if content else 0} bytes")
    except Exception as e:
        _log_error(f"Nu pot citi fișierul: {e}")
        return

    if not content:
        _log_error("Fișier SRT gol.")
        return

    # ── Parsare SRT ──────────────────────────────────────────────
    blocks = parse_srt(content)
    if not blocks:
        _log_error("0 blocuri SRT valide.")
        _notify('Fișier SRT invalid (0 blocuri)!')
        return

    total_lines = len(blocks)
    _log_debug(f"Primul: ID={blocks[0][0]}, text={blocks[0][2][:50]}")
    _log_debug(f"Ultimul: ID={blocks[-1][0]}, text={blocks[-1][2][:50]}")

    # ── Creare batch-uri ─────────────────────────────────────────
    batches = _make_batches(blocks)
    total_batches = len(batches)
    batch_info = ", ".join([str(len(b)) for b in batches])
    _log_info(f"{total_lines} linii → {total_batches} pachete [{batch_info}]")

    # ── Fișier output ────────────────────────────────────────────
    output_name = _make_output_name(original_name, target_lang)
    output_path = os.path.join(profile_path, output_name)
    _log_info(f"Output → {output_name}")

    if xbmcvfs.exists(output_path):
        xbmcvfs.delete(output_path)

    # ── Notificare start ─────────────────────────────────────────
    _notify(f'[B][COLOR orange]{target_lang.upper()}[/COLOR][/B]: [B][COLOR yellow]{total_lines}[/COLOR][/B] linii, '
            f'[B][COLOR lime]{total_batches}[/COLOR][/B] pachete')

    # ── Progress ─────────────────────────────────────────────────
    pDialog = xbmcgui.DialogProgressBG()
    pDialog.create(ADDON_NAME,
                   f'Traducere → {target_lang.upper()} (0/{total_batches})')

    # ══════════════════════════════════════════════════════════════
    #  BUCLA SECVENȚIALĂ
    # ══════════════════════════════════════════════════════════════
    completed = 0
    failed = 0
    first_done = False
    start_time = time.time()
    all_chunks = []

    for batch_idx, batch in enumerate(batches):
        try:
            if not xbmc.Player().isPlaying():
                _log_info("Player oprit, opresc traducerea.")
                break
        except Exception:
            pass

        batch_size = len(batch)
        batch_start = time.time()
        _log_info(f"Batch {batch_idx+1}/{total_batches} ({batch_size} linii)...")

        chunk = None
        model_used = ""

        for attempt in range(MAX_RETRIES):
            active_keys = [k for k in all_keys if not _is_blocked(k)]
            if not active_keys:
                _log_error("Toate cheile blocate!")
                _notify('Toate cheile API sunt blocate!', duration=5000)
                break

            _log_debug(f"Tentativa {attempt+1}/{MAX_RETRIES}, "
                       f"{len(active_keys)} chei active")

            chunk, model_used = translate_one_batch(
                batch, target_lang, active_keys, style_instruction)

            if chunk:
                break

            wait = PAUZA_DUPA_EROARE * (attempt + 1)
            _log_warn(f"Batch {batch_idx+1} eșuat, retry {attempt+1}/{MAX_RETRIES} "
                      f"(aștept {wait}s)")
            pDialog.update(
                int(batch_idx / total_batches * 100),
                ADDON_NAME,
                f'Retry {attempt+1} batch {batch_idx+1}...')
            time.sleep(wait)

        batch_elapsed = round(time.time() - batch_start, 1)

        if chunk:
            all_chunks.append(chunk)
            completed += 1

            ok = _write_and_activate(output_path, all_chunks, target_lang)

            if not first_done and ok:
                first_done = True
                elapsed = int(time.time() - start_time)
                _notify(f'Primele [B][COLOR yellow]{batch_size}[/COLOR][/B] linii traduse [B][COLOR lime]({elapsed}s)[/COLOR][/B]!')

            _log_info(f"Batch {batch_idx+1}/{total_batches} OK "
                      f"[{model_used}] ({batch_size} linii, {batch_elapsed}s)")
        else:
            failed += 1
            fallback = ""
            for b_id, timing, text in batch:
                fallback += f"{b_id}\n{timing}\n{text}\n\n"
            all_chunks.append(fallback)
            _write_and_activate(output_path, all_chunks, target_lang)
            _log_warn(f"Batch {batch_idx+1} EȘUAT, folosesc originalul.")

        pct = int((batch_idx + 1) / total_batches * 100)
        active = len(all_keys) - len(_blocked_keys)
        elapsed = int(time.time() - start_time)

        if batch_idx + 1 < total_batches:
            avg = elapsed / (batch_idx + 1)
            remaining = int(avg * (total_batches - batch_idx - 1))
            time_str = f"~{remaining}s rămas"
        else:
            time_str = "finalizare..."

        pDialog.update(pct, ADDON_NAME,
                       f'{batch_idx+1}/{total_batches} | '
                       f'Chei: {active}/{len(all_keys)} | {time_str}')

        if batch_idx < total_batches - 1:
            _log_debug(f"Pauză {PAUZA_INTRE_BATCH}s...")
            for sec in range(PAUZA_INTRE_BATCH):
                try:
                    if not xbmc.Player().isPlaying():
                        _log_info("Player oprit în pauză.")
                        break
                except Exception:
                    pass
                time.sleep(1)

    try:
        pDialog.close()
    except Exception:
        pass

    total_time = int(time.time() - start_time)
    minutes = total_time // 60
    seconds = total_time % 60

    if completed > 0:
        msg = f'[B][COLOR lime]Complet![/COLOR][/B] [B]{completed}/{total_batches}[/B] în [B][COLOR pink]{minutes}m{seconds}s[/COLOR][/B]'
        if failed > 0:
            msg += f' ({failed} erori)'
        _notify(msg, duration=5000)
    else:
        _notify('Traducere eșuată complet!', duration=5000)

    _log_info(f"FINALIZAT — {completed}/{total_batches} OK, "
              f"{failed} erori, {minutes}m{seconds}s.")
    _log_debug("═══ SFÂRȘIT TRADUCERE ═══")