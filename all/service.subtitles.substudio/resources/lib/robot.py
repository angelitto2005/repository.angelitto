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

FIRST_BATCH_MODEL   = "gemini-2.5-flash-lite"   # ← NOU
FIRST_BATCH_TIMEOUT = 30                          # ← NOU

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


def _player_has_media():
    """
    Verifică dacă playerul are un fișier video activ.
    Returnează False dacă utilizatorul a OPRIT complet filmul.
    Pauza returnează True (traducerea continuă).
    """
    try:
        player = xbmc.Player()

        # Metoda 1: isPlayingVideo() — True și pe pauză
        try:
            if player.isPlayingVideo():
                return True
        except Exception:
            pass

        # Metoda 2: getPlayingFile() — există și pe pauză
        try:
            playing_file = player.getPlayingFile()
            if playing_file and len(playing_file) > 0:
                return True
        except Exception:
            pass

        # Metoda 3: Kodi condition — verificare completă
        try:
            if xbmc.getCondVisibility('Player.HasVideo'):
                return True
        except Exception:
            pass

        return False
    except Exception:
        return False

def _auto_pause():
    """Pune filmul pe pauză automat."""
    try:
        player = xbmc.Player()
        if player.isPlaying() and not xbmc.getCondVisibility('Player.Paused'):
            player.pause()
            _log_info("Player pus pe pauză automat.")
            return True
    except Exception as e:
        _log_debug(f"Auto-pause error: {e}")
    return False


def _auto_resume():
    """Repornește filmul din pauză automat."""
    try:
        player = xbmc.Player()
        if xbmc.getCondVisibility('Player.Paused'):
            player.pause()  # toggle pause = resume
            _log_info("Player repornit automat.")
            return True
    except Exception as e:
        _log_debug(f"Auto-resume error: {e}")
    return False


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
#  PROMPT PROFESIONAL UNIVERSAL
# ═══════════════════════════════════════════════════════════════════
def _build_prompt(target_lang, num_texts):
    """
    Construiește promptul de traducere adaptat pentru limba țintă.
    Universal — funcționează pentru orice limbă.
    """

    # Reguli specifice pe limbă (diacritice, stil)
    LANG_SPECIFIC = {
        'ro': {
            'name': 'Romanian',
            'diacritics': 'Use all Romanian diacritics correctly: ă, â, î, ș, ț.',
            'style': (
                '- Adapt profanity to strong but non-vulgar Romanian expressions.\n'
                '- "marry me" → "căsătorește-te cu mine"\n'
                '- "babe/honey" → "iubire", "dragoste", "iubi"\n'
                '- "baby" → "puiule"\n'
                '- "Oh my God" → "Doamne Dumnezeule"\n'
                '- "my treat" → "fac eu cinste"\n'
                '- Adapt threats stylistically: "Kill them" → "Elimină-i" (not "Ucide-i")\n'
                '- "lakh" = sută de mii, "crore" = zece milioane\n'
            ),
        },
        'es': {
            'name': 'Spanish',
            'diacritics': 'Use all Spanish accents and punctuation correctly: á, é, í, ó, ú, ñ, ü, ¿, ¡.',
            'style': (
                '- Use natural Latin American/Castilian Spanish as appropriate.\n'
                '- Adapt profanity to culturally appropriate expressions.\n'
                '- "Oh my God" → "Dios mío"\n'
                '- Use voseo or tuteo consistently based on context.\n'
            ),
        },
        'fr': {
            'name': 'French',
            'diacritics': 'Use all French accents correctly: é, è, ê, ë, à, â, ù, û, ô, î, ï, ç, œ, æ.',
            'style': (
                '- Use natural, modern spoken French.\n'
                '- Adapt profanity to culturally appropriate expressions.\n'
                '- "Oh my God" → "Mon Dieu"\n'
                '- Use appropriate vouvoiement/tutoiement based on context.\n'
            ),
        },
        'de': {
            'name': 'German',
            'diacritics': 'Use all German special characters correctly: ä, ö, ü, ß.',
            'style': (
                '- Use natural, modern spoken German.\n'
                '- Adapt profanity to culturally appropriate expressions.\n'
                '- Use appropriate Sie/du based on context.\n'
            ),
        },
        'it': {
            'name': 'Italian',
            'diacritics': 'Use all Italian accents correctly: à, è, é, ì, ò, ù.',
            'style': (
                '- Use natural, modern spoken Italian.\n'
                '- Adapt profanity to culturally appropriate expressions.\n'
                '- "Oh my God" → "Dio mio"\n'
            ),
        },
        'pt': {
            'name': 'Portuguese',
            'diacritics': 'Use all Portuguese accents correctly: á, â, ã, à, é, ê, í, ó, ô, õ, ú, ç.',
            'style': (
                '- Use natural Brazilian/European Portuguese as appropriate.\n'
                '- Adapt profanity to culturally appropriate expressions.\n'
            ),
        },
        'hu': {
            'name': 'Hungarian',
            'diacritics': 'Use all Hungarian accents correctly: á, é, í, ó, ö, ő, ú, ü, ű.',
            'style': '- Use natural, modern spoken Hungarian.\n',
        },
        'ru': {
            'name': 'Russian',
            'diacritics': 'Use correct Russian Cyrillic characters.',
            'style': (
                '- Use natural, modern spoken Russian.\n'
                '- Adapt profanity to culturally appropriate expressions.\n'
                '- Use appropriate ты/вы based on context.\n'
            ),
        },
        'tr': {
            'name': 'Turkish',
            'diacritics': 'Use all Turkish special characters correctly: ç, ğ, ı, İ, ö, ş, ü.',
            'style': '- Use natural, modern spoken Turkish.\n',
        },
        'bg': {
            'name': 'Bulgarian',
            'diacritics': 'Use correct Bulgarian Cyrillic characters.',
            'style': '- Use natural, modern spoken Bulgarian.\n',
        },
        'el': {
            'name': 'Greek',
            'diacritics': 'Use correct Greek characters with proper accents (tonos).',
            'style': '- Use natural, modern spoken Greek (Demotic).\n',
        },
        'pl': {
            'name': 'Polish',
            'diacritics': 'Use all Polish diacritics correctly: ą, ć, ę, ł, ń, ó, ś, ź, ż.',
            'style': '- Use natural, modern spoken Polish.\n',
        },
        'cs': {
            'name': 'Czech',
            'diacritics': 'Use all Czech diacritics correctly: á, č, ď, é, ě, í, ň, ó, ř, š, ť, ú, ů, ý, ž.',
            'style': '- Use natural, modern spoken Czech.\n',
        },
        'nl': {
            'name': 'Dutch',
            'diacritics': 'Use correct Dutch spelling.',
            'style': '- Use natural, modern spoken Dutch.\n',
        },
        'en': {
            'name': 'English',
            'diacritics': '',
            'style': '- Use natural, modern American/British English.\n',
        },
    }

    # Ia regulile specifice sau generice
    lang_info = LANG_SPECIFIC.get(target_lang, {
        'name': target_lang.upper(),
        'diacritics': f'Use correct {target_lang.upper()} characters and diacritics.',
        'style': f'- Use natural, modern spoken {target_lang.upper()}.\n',
    })

    lang_name = lang_info['name']
    diacritics_rule = lang_info.get('diacritics', '')
    style_rules = lang_info.get('style', '')

    prompt = f"""**MISSION:**
You are a world-class expert in video subtitle localization and cultural adaptation.
Translate ALL subtitle texts below into natural, modern, impactful {lang_name}.

**OUTPUT FORMAT (CRITICAL):**
- Return ONLY a valid JSON object. No markdown, no code fences, no explanations.
- Keys = subtitle IDs (strings). Values = translated texts (strings).
- Example: {{"1": "translated line", "2": "another line"}}
- You MUST return exactly {num_texts} entries.

**MULTILINGUAL SOURCE HANDLING:**
- The source text may be in ANY language (English, Arabic, French, etc.).
- Identify the source language and translate accurately into {lang_name}.
- Preserve the original meaning 100%.

**STYLE AND TONE ({lang_name.upper()}):**
- Sound natural, as if spoken by a talented actor in a contemporary {lang_name} film.
- Use modern, spoken {lang_name} — avoid rigid, literal translations.
- Adapt idioms and expressions to culturally equivalent {lang_name} ones.
- Adapt profanity to strong but appropriate {lang_name} expressions (not literal).
{style_rules}
**FORMATTING RULES (STRICT):**
- Each line must NOT exceed 43 characters.
- If translation exceeds 43 chars, split logically across two lines with \\n.
- If still too long, rephrase for brevity.
- Dialogue lines starting with "-" must be followed by space + capital letter.
- When a sentence is split across lines, the second line starts lowercase (unless proper noun).
- Maintain the original number of text lines per subtitle block.
{f'- {diacritics_rule}' if diacritics_rule else ''}
- Final output must be grammatically flawless.

**INTERJECTION CLEANUP (REMOVE COMPLETELY):**
Remove these filler sounds/interjections from the translated text entirely.
Do NOT leave empty lines — just remove them from the text:
Aaah, Aah, Ah, Ahem, Ahh, Argh, Aw, Aww, Eh, Ehm, Er, Erm, Err,
Gah, Ha, Heh, Hm, Hmm, Hmmm, Hmph, Huh, Mm, Mmm, Mhm, Oh, Ohh,
Ooh, Oops, Ouch, Ow, Pff, Pfft, Phew, Psst, Sh, Shh, Shhh,
Ugh, Uh, Uhh, Uhm, Um, Umm, Whew, Whoa, Wow, Yikes.

**CONTENT RULES:**
- Translate ALL content including aggressive language — do NOT censor or block.
- Adapt threats/violence stylistically rather than literally.
- Preserve names, places, and technical terms as-is.
- If source text is "(nothing)" or empty, output "(nothing)" exactly.
- Do NOT alter, merge, or skip any subtitle block.
- Number values: translate units (lakh = hundred thousand, crore = ten million).
"""

    return prompt


# ═══════════════════════════════════════════════════════════════════
#  APEL GEMINI API
# ═══════════════════════════════════════════════════════════════════
def translate_gemini(texts_dict, target_lang, api_key, model_name, timeout=API_TIMEOUT):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={api_key}"
    )

    prompt = _build_prompt(target_lang, len(texts_dict))

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt + "\n\n" + json.dumps(texts_dict, ensure_ascii=False)
            }]
        }],
        "generationConfig": {
            "temperature": 0.15,
            "response_mime_type": "application/json",
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
        ],
    }

    _log_debug(f"API call: model={model_name}, cheie=...{api_key[-4:]}, "
               f"{len(texts_dict)} texte, limba={target_lang}, timeout={timeout}s")

    request_start = time.time()

    result_container = {'response': None, 'error': None, 'code': 0}

    def _do_request():
        try:
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            _log_debug(f"Request body: {len(body)} bytes")

            req = urllib.request.Request(
                url, data=body,
                headers={'Content-Type': 'application/json; charset=utf-8'},
                method='POST',
            )

            with urllib.request.urlopen(req, timeout=timeout) as resp:   # ← AICI
                raw = resp.read().decode('utf-8')
                result_container['response'] = raw

        except urllib.error.HTTPError as e:
            result_container['code'] = e.code
            try:
                result_container['error'] = e.read().decode('utf-8', errors='replace')[:300]
            except Exception:
                result_container['error'] = str(e)

        except urllib.error.URLError as e:
            result_container['error'] = str(e.reason)

        except Exception as e:
            result_container['error'] = f"{type(e).__name__}: {e}"

    req_thread = threading.Thread(target=_do_request, daemon=True)
    req_thread.start()

    while req_thread.is_alive():
        req_thread.join(timeout=1.0)
        if not _player_has_media():
            _log_info("Player oprit în timpul API call, abandonez.")
            return None, -1

    elapsed = round(time.time() - request_start, 1)

    # ── Eroare HTTP ──────────────────────────────────────────────
    if result_container['code'] > 0:
        code = result_container['code']
        _log_error(f"HTTP {code} [{model_name}] după {elapsed}s: "
                   f"{result_container.get('error', '')}")
        return None, code

    # ── Altă eroare ──────────────────────────────────────────────
    if result_container['error'] and not result_container['response']:
        _log_error(f"ERR [{model_name}] după {elapsed}s: "
                   f"{result_container['error']}")
        return None, 0

    # ── Fără răspuns ─────────────────────────────────────────────
    if not result_container['response']:
        _log_error(f"Răspuns gol [{model_name}] după {elapsed}s")
        return None, 0

    # ── Parsare răspuns ──────────────────────────────────────────
    raw = result_container['response']
    _log_debug(f"API răspuns în {elapsed}s, {len(raw)} bytes")

    try:
        res_data = json.loads(raw)
    except json.JSONDecodeError as e:
        _log_error(f"JSON decode error [{model_name}]: {e}")
        return None, 0

    # ── Eroare în body ───────────────────────────────────────────
    if 'error' in res_data:
        code = res_data['error'].get('code', 0)
        msg = res_data['error'].get('message', '')[:200]
        _log_error(f"API ERR {code} [{model_name}]: {msg}")
        return None, code

    # ── Verificare candidates ────────────────────────────────────
    candidates = res_data.get('candidates', [])
    if not candidates:
        _log_error(f"Fără candidates [{model_name}]")
        _log_debug(f"Răspuns complet: {json.dumps(res_data)[:500]}")
        return None, 0

    candidate = candidates[0]

    # ── Verificare safety block ──────────────────────────────────
    finish_reason = candidate.get('finishReason', '')
    if finish_reason == 'SAFETY':
        _log_warn(f"Blocat de safety filter [{model_name}].")
        try:
            for sr in candidate.get('safetyRatings', []):
                if sr.get('blocked', False):
                    _log_debug(f"  Safety: {sr.get('category')} = "
                               f"{sr.get('probability')}")
        except Exception:
            pass
        return None, 0

    # ── Extrage textul răspunsului ───────────────────────────────
    text_r = None
    try:
        text_r = candidate['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError):
        _log_error(f"Structură răspuns invalidă [{model_name}]")
        _log_debug(f"Candidate: {json.dumps(candidate)[:500]}")
        return None, 0

    if not text_r:
        _log_error(f"Text răspuns gol [{model_name}]")
        return None, 0

    _log_debug(f"Text răspuns: {len(text_r)} car, preview: {text_r[:100]}...")

    # ── Parsare JSON din text (3 metode) ─────────────────────────
    for attempt_parse in range(3):
        try:
            if attempt_parse == 0:
                parse_candidate = text_r
                method = "direct"
            elif attempt_parse == 1:
                parse_candidate = re.sub(r'```(?:json)?\s*', '', text_r)
                parse_candidate = re.sub(r'```', '', parse_candidate).strip()
                method = "clean markdown"
            else:
                m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',
                              text_r, re.DOTALL)
                parse_candidate = m.group() if m else ""
                method = "regex extract"

            if parse_candidate:
                result = json.loads(parse_candidate)
                if isinstance(result, dict) and len(result) > 0:
                    _log_debug(f"JSON OK ({method}), {len(result)} intrări")
                    return result, 0
        except (json.JSONDecodeError, ValueError, AttributeError):
            _log_debug(f"JSON fail metoda {attempt_parse}: {method}")
            continue

    _log_error(f"JSON parse fail total [{model_name}]: {text_r[:200]}")
    return None, 0


# ═══════════════════════════════════════════════════════════════════
#  CURĂȚARE INTERJECȚII DIN TEXT SURSĂ
# ═══════════════════════════════════════════════════════════════════
_INTERJECTIONS = {
    'aaaa','aaa','aaaaah','aaaah','aaah','aah','aargh','agh',
    'ah','a-ha','ahem','ahh','ahhh','ahhhh','argh','aw','aww',
    'awww','bleah','eh','ehh','ehhh','ehm','er','erm','err','errr',
    'gah','ha','hahaha','heh','hm','hmm','hmmm','hmph','hoho',
    'hoo','huh','mh','mhm','mm','mmhmm','mm-hmm','mmm','mmmm',
    'mwah','oh','ohh','ohhh','oo','ooh','ooh-la-la','oooh',
    'oops','ops','ouch','ow','oww','owww','pf','pff','pfff','pffft',
    'pfft','phew','pssh','psst','sh','shh','shhh','ssh','ssshh','sst',
    'uf','uff','ugh','ughh','uh','uhh','uhhh','uhm','uhmm',
    'uhu','uhuu','um','umm','uu','whew','whoa','whoo','whoooooo',
    'whoop','whoops','whup','wooh','woo-hoo','woo-hoo-hoo','wow',
    'yikes','yoo','yoo-hoo','haha','hehe',
}


def _is_only_interjections(text):
    """
    Verifică dacă textul conține DOAR interjecții
    (separate prin punctuație/spații).
    'Oh. Wow.' → True,  'Oh, look!' → False
    """
    words = re.split(r'[,;.!?\s…]+', text)
    words = [w.strip() for w in words if w.strip()]
    if not words:
        return True
    return all(w.lower() in _INTERJECTIONS for w in words)


def _clean_interjections(text):
    """
    Elimină interjecțiile din textul sursă ÎNAINTE de traducere.
    Gestionează corect liniile de dialog (cu '-').
    """
    if not text or not text.strip():
        return text

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # ── Detectează prefix de dialog: "- text" ───────────────
        is_dialogue = False
        dialogue_text = stripped

        if re.match(r'^-\s+', stripped):
            is_dialogue = True
            dialogue_text = re.sub(r'^-\s+', '', stripped).strip()
        elif stripped in ('-', '-.', '-!', '-?'):
            # Linie de dialog degenerată — sari complet
            continue

        if not dialogue_text:
            continue

        # ── Verifică dacă textul e DOAR interjecții ─────────────
        word_check = dialogue_text.rstrip('.!?,;:… ').strip()
        if not word_check or _is_only_interjections(word_check):
            continue  # Sari peste linia întreagă

        # ── Curăță interjecții la ÎNCEPUT ────────────────────────
        cleaned = dialogue_text
        for _ in range(5):
            match = re.match(
                r'^([A-Za-z\-]+)\s*[,!.;:\s]+\s*(.+)$',
                cleaned, re.IGNORECASE
            )
            if match:
                word = match.group(1).strip()
                rest = match.group(2).strip()
                if word.lower() in _INTERJECTIONS and rest:
                    # Majusculă doar dacă cuvântul eliminat era
                    # la început de propoziție (prima literă mare)
                    if word[0].isupper():
                        cleaned = (rest[0].upper() + rest[1:]
                                   if len(rest) > 1 else rest.upper())
                    else:
                        cleaned = rest
                else:
                    break
            else:
                break

        # ── Curăță interjecții la SFÂRȘIT ────────────────────────
        for _ in range(3):
            match = re.search(
                r'^(.+?)\s*[,;:\s]+\s*([A-Za-z\-]+)\s*([.!?…]*)\s*$',
                cleaned, re.IGNORECASE
            )
            if match:
                main  = match.group(1).strip()
                word  = match.group(2).strip()
                trail = match.group(3).strip()
                if word.lower() in _INTERJECTIONS and main:
                    # Păstrează stilul de punctuație final
                    if main[-1] not in '.!?,;:…':
                        if '...' in trail or '…' in trail:
                            main += '...'   # era "but, uh..." → "but..."
                        else:
                            main += '.'
                    cleaned = main
                else:
                    break
            else:
                break

        # ── Re-verifică dacă după curățare a rămas doar interjecție
        final_check = cleaned.rstrip('.!?,;:… ').strip()
        if not final_check or _is_only_interjections(final_check):
            continue  # Sari peste linia întreagă

        # ── Reconstruiește cu prefix de dialog dacă era ──────────
        if is_dialogue:
            cleaned_lines.append(f"- {cleaned}")
        else:
            cleaned_lines.append(cleaned)

    # ── POST: dacă a rămas O SINGURĂ linie de dialog, scoate '-'
    if len(cleaned_lines) == 1 and cleaned_lines[0].startswith('- '):
        cleaned_lines[0] = cleaned_lines[0][2:].strip()

    result = '\n'.join(cleaned_lines)
    return result if result.strip() else text


# ═══════════════════════════════════════════════════════════════════
#  FIX DOUBLE-DASH → ELLIPSIS
# ═══════════════════════════════════════════════════════════════════
def _fix_double_dash(text):
    """
    Convertește -- (dialog întrerupt) în ...
    Exemple:
      'Did you hear--'      → 'Did you hear...'
      'I-- I didn't know'   → 'I... I didn't know'
      'What are you--\nHey' → 'What are you...\nHey'
    """
    if not text:
        return text
    # -- la sfârșit de linie
    text = re.sub(r'--+\s*$', '...', text, flags=re.MULTILINE)
    # -- urmat de spațiu (bâlbâială la mijloc)
    text = re.sub(r'--+(?=\s)', '...', text)
    return text


# ═══════════════════════════════════════════════════════════════════
#  REECHILIBRARE / ÎMPĂRȚIRE LINII SUBTITRARE
# ═══════════════════════════════════════════════════════════════════
SINGLE_LINE_MAX     = 43
REBALANCE_THRESHOLD = 18


def _rebalance_lines(text):
    """
    Post-procesare text tradus:
    1) Linie unică > 43 car vizibile → împarte în două echilibrate
    2) Două linii cu diferență > 18 car → reechilibrează
    Sare peste blocurile de dialog (cu '-').
    Păstrează tag-urile (<i>, </i>, ♪) intacte.
    """
    if not text or not text.strip():
        return text

    lines = text.split('\n')
    is_dialogue = any(line.strip().startswith('-') for line in lines)

    def visible(t):
        """Lungime vizibilă, fără tag-uri HTML și simboluri muzicale."""
        return re.sub(r'</?[a-zA-Z]+>|♪', '', t).strip()

    def visible_len(t):
        return len(visible(t))

    def _find_split_and_apply(full_text, full_clean, target_words_on_l1=None):
        """
        Găsește cel mai bun punct de împărțire pe textul curat,
        apoi aplică împărțirea pe textul original (cu tag-uri).
        Returnează (line1, line2) sau None dacă nu se poate.
        """
        ideal = len(full_clean) // 2
        best = -1

        # Prioritate 1: sfârșit de propoziție (.?! urmat de spațiu)
        breaks = [m.end() for m in re.finditer(r'[.?!]\s', full_clean)]
        if breaks:
            best = min(breaks, key=lambda p: abs(p - ideal))

        # Prioritate 2: virgulă în raza ±15 de ideal
        if best == -1:
            radius = 15
            start_s = max(0, ideal - radius)
            end_s = min(len(full_clean), ideal + radius)
            comma = full_clean.rfind(',', start_s, end_s)
            if comma != -1:
                best = comma + 1

        # Prioritate 3: ultimul spațiu înainte de ideal
        if best == -1:
            best = full_clean.rfind(' ', 0, ideal + 1)

        if best <= 0:
            return None

        # Numără cuvintele din prima linie (pe textul curat)
        n_words = len(full_clean[:best].strip().split())
        if target_words_on_l1 is not None:
            n_words = target_words_on_l1

        # Aplică împărțirea pe textul original, numărând cuvinte
        parts = re.split(r'(\s+)', full_text)
        word_count = 0
        split_idx = -1
        for i, part in enumerate(parts):
            if part.strip():
                # Nu numără tag-urile ca și cuvinte
                clean_part = re.sub(r'</?[a-zA-Z]+>|♪', '', part).strip()
                if clean_part:
                    word_count += 1
            if word_count == n_words:
                split_idx = i
                break

        if split_idx == -1:
            return None

        l1 = "".join(parts[:split_idx + 1]).strip()
        l2 = "".join(parts[split_idx + 1:]).strip()

        # Verificare finală: ambele linii au conținut și sunt ≤ limită
        if (l1 and l2 and visible(l1) and visible(l2) and
                visible_len(l1) <= SINGLE_LINE_MAX and
                visible_len(l2) <= SINGLE_LINE_MAX):
            return l1, l2

        return None

    # ────────────────────────────────────────────────────────────
    #  Calea 1: LINIE UNICĂ PREA LUNGĂ → împarte în două
    # ────────────────────────────────────────────────────────────
    if len(lines) == 1 and not is_dialogue:
        vis = visible(text)
        if len(vis) > SINGLE_LINE_MAX:
            result = _find_split_and_apply(text, vis)
            if result:
                l1, l2 = result
                _log_debug(f"Split: '{text}' → '{l1}\\n{l2}'")
                return f"{l1}\n{l2}"

    # ────────────────────────────────────────────────────────────
    #  Calea 2: DOUĂ LINII DEZECHILIBRATE → reechilibrează
    # ────────────────────────────────────────────────────────────
    elif len(lines) == 2 and not is_dialogue:
        c1 = visible(lines[0])
        c2 = visible(lines[1])

        # Nu reechilibra dacă linia 1 se termină cu punct
        if c1 and c1[-1] in '.?!':
            return text

        # Nu reechilibra dacă tag-urile italic sunt "deschise" la mijloc
        has_internal_italic = (
            ('</i>' in lines[0] and not lines[0].strip().endswith('</i>')) or
            ('</i>' in lines[1] and not lines[1].strip().endswith('</i>'))
        )
        if has_internal_italic:
            return text

        if abs(len(c1) - len(c2)) > REBALANCE_THRESHOLD:
            full_orig = f"{lines[0].strip()} {lines[1].strip()}"
            full_clean = f"{c1} {c2}"

            result = _find_split_and_apply(full_orig, full_clean)
            if result:
                l1, l2 = result
                _log_debug(f"Rebalance: '{c1}' + '{c2}' → "
                           f"'{visible(l1)}' + '{visible(l2)}'")
                return f"{l1}\n{l2}"

    return text


# ═══════════════════════════════════════════════════════════════════
#  POST-PROCESARE TEXT TRADUS (pipeline complet)
# ═══════════════════════════════════════════════════════════════════
def _post_process_text(text):
    """
    Aplică pe textul tradus:
    1. Fix -- → ...
    2. Reechilibrare/împărțire linii
    """
    if not text:
        return text
    text = _fix_double_dash(text)
    text = _rebalance_lines(text)
    return text


# ═══════════════════════════════════════════════════════════════════
#  TRADUCE UN BATCH
# ═══════════════════════════════════════════════════════════════════
def translate_one_batch(batch, target_lang, all_keys, batch_index=0):
    to_translate = {}
    cleaned_count = 0

    for b_id, _timing, text in batch:
        clean = re.sub(r'<[^>]*>', '', text).strip()
        if not clean:
            clean = text.strip()

        original = clean

        # ── PRE-PROCESARE 1: Fix -- → ... ────────────────────────
        clean = _fix_double_dash(clean)

        # ── PRE-PROCESARE 2: Curăță interjecții ──────────────────
        clean = _clean_interjections(clean)

        if clean != original:
            cleaned_count += 1
            _log_debug(f"  Pre-curățat [{b_id}]: '{original}' → '{clean}'")

        if not clean or clean == '(nothing)':
            clean = text.strip()

        to_translate[b_id] = clean

    if cleaned_count > 0:
        _log_info(f"Pre-curățate {cleaned_count} texte înainte de traducere.")

    # ── Selectează modelele și timeout-ul pentru acest batch ─────
    if batch_index == 0:
        models_to_use = [FIRST_BATCH_MODEL]
        batch_timeout = FIRST_BATCH_TIMEOUT
        _log_info(f"Primul batch: model={FIRST_BATCH_MODEL}, timeout={FIRST_BATCH_TIMEOUT}s")
    else:
        models_to_use = MODEL_PREFERAT
        batch_timeout = API_TIMEOUT

    _log_debug(f"translate_one_batch: {len(to_translate)} texte, "
               f"{len(all_keys)} chei, modele={[m.split('-')[-1] for m in models_to_use]}")

    for key_idx, current_key in enumerate(all_keys):
        if _is_blocked(current_key):
            _log_debug(f"Cheie {key_idx+1} ...{current_key[-4:]} blocată, skip")
            continue

        _log_debug(f"Încerc cheie {key_idx+1}/{len(all_keys)}: "
                   f"...{current_key[-4:]}")

        for model_idx, current_model in enumerate(models_to_use):
            _log_debug(f"  Model {model_idx+1}/{len(models_to_use)}: "
                       f"{current_model}")

            result, err_code = translate_gemini(
                to_translate, target_lang, current_key,
                current_model, timeout=batch_timeout,       # ← TIMEOUT
            )

            if err_code == -1:
                _log_info("Player oprit, abandonez batch-ul.")
                return None, ""

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
                    tr = _post_process_text(tr)
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


def _save_translation(output_path, output_name, sub_addon_id):
    """Copiază traducerea COMPLETĂ în 'Subtitrari traduse' + actualizează index."""
    try:
        _addon = xbmcaddon.Addon(sub_addon_id)
        if _addon.getSetting('save_translations') != 'true':
            _log_debug("Salvare permanentă dezactivată.")
            return

        profile = xbmcvfs.translatePath(
            f'special://profile/addon_data/{sub_addon_id}/')
        saved_dir = os.path.join(profile, 'Subtitrari traduse')

        if not xbmcvfs.exists(saved_dir + os.sep):
            xbmcvfs.mkdirs(saved_dir + os.sep)

        saved_path = os.path.join(saved_dir, output_name)

        success = xbmcvfs.copy(output_path, saved_path)
        if not success:
            try:
                with open(output_path, 'rb') as src:
                    data = src.read()
                with open(saved_path, 'wb') as dst:
                    dst.write(data)
            except Exception as e2:
                _log_error(f"Salvare fallback eșuată: {e2}")
                return

        _log_info(f"Traducere salvată: {output_name}")

        # ── Index cu IMDB/TMDB + complete flag ───────────────────
        try:
            imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or ""
            tmdb_id = (xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
                       or xbmc.getInfoLabel("Window(10000).Property(tmdb_id)") or "")
            video_title = (xbmc.getInfoLabel("VideoPlayer.Title")
                           or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or "")
            video_year = xbmc.getInfoLabel("VideoPlayer.Year") or ""

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
                except Exception:
                    index = {}

            index[output_name] = {
                'imdb': imdb_id,
                'tmdb': tmdb_id,
                'title': video_title,
                'year': video_year,
                'file': output_name,
                'complete': True,
                'saved': time.strftime('%Y-%m-%d %H:%M'),
            }

            index_data = json.dumps(index, ensure_ascii=False, indent=2)
            try:
                fh = xbmcvfs.File(index_path, 'w')
                fh.write(index_data.encode('utf-8') if isinstance(index_data, str) else index_data)
                fh.close()
            except Exception:
                with open(index_path, 'w', encoding='utf-8') as f:
                    f.write(index_data)

            _log_info(f"Index: {output_name} → imdb={imdb_id}, "
                      f"tmdb={tmdb_id}, complete=True")

        except Exception as e:
            _log_warn(f"Index update failed (non-fatal): {e}")

        _notify(f'[B][COLOR lime]Salvat permanent: [COLOR orange]{output_name}[/COLOR][/B]', duration=3000)

    except Exception as e:
        _log_error(f"Eroare salvare permanentă: {e}")


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

    # ── Pune filmul pe pauză automat ─────────────────────────────
    was_paused = _auto_pause()
    if was_paused:
        _notify(f'Traducere [B][COLOR orange]{target_lang.upper()}[/COLOR][/B] pornită... [B][COLOR red]Așteptați.[/COLOR][/B]')
    else:
        _notify(f'[B][COLOR orange]{target_lang.upper()}[/COLOR][/B]: [B][COLOR yellow]{total_lines}[/COLOR][/B] linii, '
                f'[B][COLOR lime]{total_batches}[/COLOR][/B] pachete')

    # ── Progress ─────────────────────────────────────────────────
    pDialog = xbmcgui.DialogProgressBG()
    pDialog.create(ADDON_NAME,
                   f'Traducere → [B][COLOR orange]{target_lang.upper()} [COLOR lime](0/{total_batches})[/COLOR][/B]')

    # ══════════════════════════════════════════════════════════════
    #  BUCLA SECVENȚIALĂ (protejată cu try/finally)
    # ══════════════════════════════════════════════════════════════
    completed = 0
    failed = 0
    first_done = False
    start_time = time.time()
    all_chunks = []
    player_stopped = False

    try:
        for batch_idx, batch in enumerate(batches):
            if not _player_has_media():
                _log_info("Player oprit complet, opresc traducerea.")
                player_stopped = True
                break

            batch_size = len(batch)
            batch_start = time.time()
            _log_info(f"Batch {batch_idx+1}/{total_batches} ({batch_size} linii)...")

            chunk = None
            model_used = ""

            for attempt in range(MAX_RETRIES):
                if not _player_has_media():
                    _log_info("Player oprit în timpul retry, opresc.")
                    player_stopped = True
                    break

                active_keys = [k for k in all_keys if not _is_blocked(k)]
                if not active_keys:
                    _log_error("Toate cheile blocate!")
                    _notify('Toate cheile API sunt blocate!', duration=5000)
                    break

                _log_debug(f"Tentativa {attempt+1}/{MAX_RETRIES}, "
                           f"{len(active_keys)} chei active")

                chunk, model_used = translate_one_batch(
                    batch, target_lang, active_keys, batch_index=batch_idx)

                if chunk:
                    break

                wait = PAUZA_DUPA_EROARE * (attempt + 1)
                _log_warn(f"Batch {batch_idx+1} eșuat, retry {attempt+1}/{MAX_RETRIES} "
                          f"(aștept {wait}s)")
                pDialog.update(
                    int(batch_idx / total_batches * 100),
                    ADDON_NAME,
                    f'Retry {attempt+1} batch {batch_idx+1}...')

                for w in range(int(wait)):
                    if not _player_has_media():
                        player_stopped = True
                        break
                    time.sleep(1)
                if player_stopped:
                    break

            if player_stopped:
                break

            batch_elapsed = round(time.time() - batch_start, 1)

            if chunk:
                all_chunks.append(chunk)
                completed += 1

                ok = _write_and_activate(output_path, all_chunks, target_lang)

                if not first_done and ok:
                    first_done = True
                    elapsed = int(time.time() - start_time)
                    _auto_resume()
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
                    if not _player_has_media():
                        _log_info("Player oprit în pauză.")
                        player_stopped = True
                        break
                    time.sleep(1)
                if player_stopped:
                    break

    except Exception as e:
        _log_error(f"EROARE CRITICĂ în bucla de traducere: {type(e).__name__}: {e}")
        _notify('Eroare critică la traducere!', duration=5000)

    finally:
        # ── ÎNCHIDE PROGRESS ÎNTOTDEAUNA ─────────────────────────
        try:
            pDialog.close()
        except Exception:
            pass
        xbmc.sleep(300)
        try:
            pDialog.close()
        except Exception:
            pass

    # ── Verifică completare ──────────────────────────────────────
    all_processed = (completed + failed) >= total_batches
    fully_complete = all_processed and failed == 0

    total_time = int(time.time() - start_time)
    minutes = total_time // 60
    seconds = total_time % 60

    if completed > 0:
        msg = f'[B][COLOR lime]Complet![/COLOR][/B] [B]{completed}/{total_batches}[/B] în [B][COLOR pink]{minutes}m{seconds}s[/COLOR][/B]'
        if failed > 0:
            msg += f' ({failed} erori)'
        if player_stopped:
            msg += ' (oprit)'
        _notify(msg, duration=5000)

        if fully_complete:
            _save_translation(output_path, output_name, sub_addon_id)
        else:
            _log_warn(f"Incomplet ({completed}/{total_batches}), NU salvez.")
    else:
        _notify('[B][COLOR red]Traducere eșuată complet![/COLOR][/B]', duration=5000)

    _log_info(f"FINALIZAT — {completed}/{total_batches} OK, "
              f"{failed} erori, {minutes}m{seconds}s. "
              f"Complet: {fully_complete}")
    _log_debug("═══ SFÂRȘIT TRADUCERE ═══")