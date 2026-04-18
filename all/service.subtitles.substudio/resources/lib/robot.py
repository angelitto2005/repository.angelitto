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
]

FIRST_BATCH_MODEL   = "gemini-2.5-flash-lite"   # ← NOU
FIRST_BATCH_TIMEOUT = 30                          # ← NOU

FIRST_BATCH_SIZE  = 100
NEXT_BATCH_SIZE   = 300
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
    Verificare 100% PASIVĂ — nu atinge obiectul xbmc.Player() C++.
    getCondVisibility e doar o citire de proprietate UI, mereu sigură,
    chiar dacă playerul tocmai se oprește sau se distruge.
    Returnează False dacă utilizatorul a OPRIT complet filmul.
    Pauza returnează True (traducerea continuă).
    """
    try:
        if xbmc.getCondVisibility('Player.HasVideo') or xbmc.getCondVisibility('Player.HasAudio'):
            return True
        return False
    except Exception:
        return False

def _auto_pause():
    """Pune filmul pe pauză automat."""
    try:
        # Verificare pasivă — jucăm DOAR dacă playerul rulează activ (nu e deja pe pauză)
        if xbmc.getCondVisibility('Player.HasVideo') and not xbmc.getCondVisibility('Player.Paused'):
            xbmc.Player().pause()
            _log_info("Player pus pe pauză automat.")
            return True
    except Exception as e:
        _log_debug(f"Auto-pause error: {e}")
    return False


def _auto_resume():
    """Repornește filmul din pauză automat."""
    try:
        # Verificare pasivă — nu atingem Player() dacă nu știm că există
        if xbmc.getCondVisibility('Player.Paused') and xbmc.getCondVisibility('Player.HasVideo'):
            xbmc.Player().pause()  # toggle pause = resume
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
- Return ONLY a valid JSON array of objects. No markdown, no code fences.
- Format strictly as: [{{"index": "ID", "text": "translated text"}}]
- Example: [{{"index": "1", "text": "Buna ziua"}}, {{"index": "2", "text": "Ce faci?"}}]
- You MUST return exactly {num_texts} items in the array.

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
- NEVER output more than 2 text lines per subtitle block. If original has 3+ lines, merge them into max 2 lines.
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
    
    # Transformăm dicționarul într-o listă pentru a o trimite lui Gemini
    json_input = [{"index": str(k), "text": v} for k, v in texts_dict.items()]

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt + "\n\n" + json.dumps(json_input, ensure_ascii=False)
            }]
        }],
        "generationConfig": {
            "temperature": 0.15,
            "response_mime_type": "application/json",
            "responseSchema": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "index": {"type": "STRING"},
                        "text": {"type": "STRING"}
                    },
                    "required": ["index", "text"]
                }
            }
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
            req = urllib.request.Request(
                url, data=body,
                headers={'Content-Type': 'application/json; charset=utf-8'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode('utf-8')
                result_container['response'] = raw
        except urllib.error.HTTPError as e:
            result_container['code'] = e.code
            try: result_container['error'] = e.read().decode('utf-8', errors='replace')[:300]
            except Exception: result_container['error'] = str(e)
        except urllib.error.URLError as e: result_container['error'] = str(e.reason)
        except Exception as e: result_container['error'] = f"{type(e).__name__}: {e}"

    req_thread = threading.Thread(target=_do_request, daemon=True)
    req_thread.start()

    while req_thread.is_alive():
        req_thread.join(timeout=1.0)
        if not _player_has_media():
            _log_info("Player oprit în timpul API call, abandonez.")
            return None, -1

    elapsed = round(time.time() - request_start, 1)

    if result_container['code'] > 0: return None, result_container['code']
    if result_container['error'] and not result_container['response']: return None, 0
    if not result_container['response']: return None, 0

    raw = result_container['response']
    try: res_data = json.loads(raw)
    except json.JSONDecodeError: return None, 0

    if 'error' in res_data: return None, res_data['error'].get('code', 0)
    
    candidates = res_data.get('candidates', [])
    if not candidates: return None, 0
    
    candidate = candidates[0]
    if candidate.get('finishReason', '') == 'SAFETY': return None, 0

    try: text_r = candidate['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError): return None, 0

    if not text_r: return None, 0

    # Parsăm JSON-ul primit care acum e obligatoriu ARRAY
    try:
        parsed_array = json.loads(text_r)
        # Transformăm înapoi în dicționar pentru compatibilitate cu restul scriptului
        result_dict = {str(item['index']): str(item['text']) for item in parsed_array if 'index' in item and 'text' in item}
        return result_dict, 0
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        _log_error(f"JSON Parse/Format Error: {e}")
        return None, 0

# ═══════════════════════════════════════════════════════════════════
#  CURĂȚARE INTERJECȚII DIN TEXT SURSĂ ȘI TRADUS
# ═══════════════════════════════════════════════════════════════════
# 1. Interjecții pentru textul SURSĂ (Engleză)
_INTERJECTIONS_SRC = {
    'aa','aaaa','aaa','aaaaah','aaaah','aaah','aah','aargh','agh',
    'ah','a-ha','aha','ahem','ahh','ahhh','ahhhh','argh','aw','aww',
    'awww','bleah','eh','ehh','ehhh','ehm','er','erm','err','errr',
    'gah','ha','hahaha','heh','hm','hmm','hmmm','hmph','hoho',
    'hoo','huh','mh','mhm','mm','mmhmm','mm-hmm','mmm','mmmm',
    'mwah','oh','ohh','ohhh','oo','ooh','ooh-la-la','oooh',
    'oops','ops','ouch','ow','oww','owww','pf','pff','pfff','pffft',
    'pfft','phew','pssh','psst','sh','shh','shhh','ssh','ssshh','sst',
    'uf','uff','ugh','ughh','uh','uhh','uhhh','uhm','uhmm',
    'uhu','uhuu','um','umm','uu','whew','whoa','whoo','whooo','whoooo',
    'whoooooo','whoop','whoops','whup','wooh','woo-hoo','woo-hoo-hoo',
    'wow','yikes','yoo','yoo-hoo','haha','hehe',
}

# 2. Interjecții pentru textul TRADUS (Română + Engleză)
_INTERJECTIONS_DST = _INTERJECTIONS_SRC.union({
    'ăă','ăăă','ăăăă','ăăăăă','îhî', 'ptiu','brr'
})


def _is_only_interjections(text, is_translated=False):
    words = re.split(r'[,;.!?\s…]+', text)
    words = [w.strip() for w in words if w.strip()]
    if not words:
        return True
    
    current_dict = _INTERJECTIONS_DST if is_translated else _INTERJECTIONS_SRC
    return all(w.lower() in current_dict for w in words)


def _clean_interjections(text, is_translated=False):
    """Elimină interjecțiile. Folosește dicționarul corect în funcție de stadiu."""
    if not text or not text.strip():
        return text

    current_dict = _INTERJECTIONS_DST if is_translated else _INTERJECTIONS_SRC
    _WORD_PAT = r'[A-Za-zăâîșțĂÂÎȘȚÀ-žА-я\-]+'

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_dialogue = False
        dialogue_text = stripped

        if re.match(r'^-\s+', stripped):
            is_dialogue = True
            dialogue_text = re.sub(r'^-\s+', '', stripped).strip()
        elif stripped in ('-', '-.', '-!', '-?'):
            continue

        if not dialogue_text:
            continue

        word_check = dialogue_text.rstrip('.!?,;:… ').strip()
        if not word_check or _is_only_interjections(word_check, is_translated):
            continue

        cleaned = dialogue_text
        
        # ── ÎNCEPUT ──
        for _ in range(5):
            match = re.match(r'^(' + _WORD_PAT + r')\s*[,!.;:\s]+\s*(.+)$', cleaned, re.IGNORECASE | re.UNICODE)
            if match:
                word = match.group(1).strip()
                rest = match.group(2).strip()
                if word.lower() in current_dict and rest:
                    if word[0].isupper():
                        cleaned = (rest[0].upper() + rest[1:] if len(rest) > 1 else rest.upper())
                    else:
                        cleaned = rest
                else:
                    break
            else:
                break

        # ── SFÂRȘIT ──
        for _ in range(3):
            match = re.search(r'^(.+?)\s*[,;:\s]+\s*(' + _WORD_PAT + r')\s*([,;:.!?…]*)\s*$', cleaned, re.IGNORECASE | re.UNICODE)
            if match:
                main  = match.group(1).strip()
                word  = match.group(2).strip()
                trail = match.group(3).strip()
                if word.lower() in current_dict and main:
                    if main[-1] not in '.!?,;:…':
                        if '...' in trail or '…' in trail:
                            main += '...'
                        else:
                            main += '.'
                    cleaned = main
                else:
                    break
            else:
                break

        # ── MIJLOC ──
        _inj_alt = '|'.join(re.escape(i) for i in sorted(current_dict, key=len, reverse=True))
        cleaned = re.sub(r',\s*(' + _inj_alt + r')\s*,', ' ', cleaned, flags=re.IGNORECASE | re.UNICODE)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        cleaned = re.sub(r',\s*,', ',', cleaned).strip()

        final_check = cleaned.rstrip('.!?,;:… ').strip()
        if not final_check or _is_only_interjections(final_check, is_translated):
            continue

        if is_dialogue:
            cleaned_lines.append(f"- {cleaned}")
        else:
            cleaned_lines.append(cleaned)

    if len(cleaned_lines) == 1 and cleaned_lines[0].startswith('- '):
        cleaned_lines[0] = cleaned_lines[0][2:].strip()

    result = '\n'.join(cleaned_lines)
    # FIX: Îi permitem scriptului să returneze STRING GOL (adică să șteargă linia complet)
    # dacă replica era doar o interjecție, în loc să ne dea înapoi textul original.
    return result.strip()


# ═══════════════════════════════════════════════════════════════════
#  CURĂȚARE HEARING IMPAIRED (HI)
# ═══════════════════════════════════════════════════════════════════
def _clean_hi_text(text):
    """
    Elimină conținut hearing impaired din textul SRT:
    - Text în paranteze drepte (chiar și multi-linie): [DOOR SLAMS] → eliminat
    - Prefix vorbitor UPPERCASE: MARIA: text → text
    """
    if not text or not text.strip():
        return text

    # FIX: Șterge parantezele chiar dacă textul e spart pe 2 rânduri (folosind re.DOTALL)
    text = re.sub(r'\[.*?\]', '', text, flags=re.DOTALL)

    lines = text.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Scoate prefix UPPERCASE_SPEAKER:
        s = re.sub(
            r'^(-\s*)?([A-ZÀ-Ü][A-ZÀ-Ü0-9\.\s]{1,28}):\s*',
            lambda m: (m.group(1) or ''),
            s
        )
        s = s.strip()
        if s:
            cleaned.append(s)

    return '\n'.join(cleaned)

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
    1) Dacă are 3 sau mai multe linii → forțează contopirea la maxim 2.
    2) Linie unică > 43 car vizibile → împarte în două echilibrate.
    3) Două linii dezechilibrate sau cu o linie > 43 car → reechilibrează.
    Sare peste blocurile de dialog (cu '-').
    Păstrează tag-urile (<i>, </i>, ♪) intacte.
    """
    if not text or not text.strip():
        return text

    # Curățăm liniile goale și formăm o listă clară
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # --- FIX BUG 3 RANDURI ---
    if len(lines) > 2:
        new_lines = []
        for line in lines:
            if line.startswith('-') or not new_lines:
                new_lines.append(line)
            else:
                new_lines[-1] = new_lines[-1] + " " + line
        
        while len(new_lines) > 2:
            urmatorul = new_lines.pop(1)
            if urmatorul.startswith('-'):
                urmatorul = urmatorul[1:].strip()
            new_lines[0] = new_lines[0] + " " + urmatorul

        text = '\n'.join(new_lines)
        lines = new_lines
    # -------------------------

    is_dialogue = any(line.startswith('-') for line in lines)

    def visible(t):
        """Lungime vizibilă, fără tag-uri HTML și simboluri muzicale."""
        return re.sub(r'</?[a-zA-Z]+>|♪', '', t).strip()

    def _find_smart_split(full_text, full_clean):
        """Algoritm inteligent de split bazat pe scoruri pentru a găsi mijlocul perfect."""
        ideal = len(full_clean) // 2
        space_indices = [m.start() for m in re.finditer(r'\s', full_clean)]
        
        if not space_indices:
            return None
            
        best_idx = -1
        best_score = 99999
        
        for idx in space_indices:
            l1_len = idx
            l2_len = len(full_clean) - idx - 1
            
            # Penalizare masivă dacă vreo linie trece de SINGLE_LINE_MAX
            penalty = 1000 if (l1_len > SINGLE_LINE_MAX or l2_len > SINGLE_LINE_MAX) else 0
                
            # Bonus pentru punctuație naturală (pauze logice în vorbire)
            bonus = 0
            if idx > 0:
                prev_char = full_clean[idx-1]
                if prev_char in '.?!':
                    bonus = -12
                elif prev_char == ',':
                    bonus = -6
                    
            distance = abs(idx - ideal)
            score = distance + penalty + bonus
            
            if score < best_score:
                best_score = score
                best_idx = idx
                
        if best_idx == -1:
            return None
            
        # Fallback de urgență: dacă absolut nicio tăietură nu respectă SINGLE_LINE_MAX,
        # o tăiem strict pe cel mai apropiat spațiu de centru.
        if best_score >= 1000:
            best_idx = min(space_indices, key=lambda i: abs(i - ideal))
            
        n_words = len(full_clean[:best_idx].strip().split())
        
        parts = re.split(r'(\s+)', full_text)
        word_count = 0
        split_idx = -1
        
        for i, part in enumerate(parts):
            if part.strip():
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
        return l1, l2

    #  Calea 1: LINIE UNICĂ PREA LUNGĂ
    if len(lines) == 1 and not is_dialogue:
        vis = visible(text)
        if len(vis) > SINGLE_LINE_MAX:
            result = _find_smart_split(text, vis)
            if result:
                l1, l2 = result
                return f"{l1}\n{l2}"

    #  Calea 2: DOUĂ LINII (Reechilibrare)
    elif len(lines) == 2 and not is_dialogue:
        c1 = visible(lines[0])
        c2 = visible(lines[1])

        # FORȚĂM REECHILIBRAREA dacă diferența e mare SAU dacă orice linie depășește limita admisă pe ecran
        if abs(len(c1) - len(c2)) > REBALANCE_THRESHOLD or len(c1) > SINGLE_LINE_MAX or len(c2) > SINGLE_LINE_MAX:
            
            # Anulăm doar dacă ambele linii respectă mărimea pe ecran ȘI sunt două propoziții clar separate (Punct la final)
            if len(c1) <= SINGLE_LINE_MAX and len(c2) <= SINGLE_LINE_MAX and c1 and c1[-1] in '.?!':
                return text

            has_internal_italic = (
                ('</i>' in lines[0] and not lines[0].strip().endswith('</i>')) or
                ('</i>' in lines[1] and not lines[1].strip().endswith('</i>'))
            )
            if has_internal_italic:
                return text

            full_orig = f"{lines[0].strip()} {lines[1].strip()}"
            full_clean = f"{c1} {c2}"
            result = _find_smart_split(full_orig, full_clean)
            if result:
                l1, l2 = result
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
#  TRADUCE UN BATCH CU PROTECȚII LA INDEX ȘI MERGING
# ═══════════════════════════════════════════════════════════════════
def translate_one_batch(batch, target_lang, all_keys, batch_index=0):
    to_translate = {}
    cleaned_count = 0

    for b_id, _timing, text in batch:
        clean = re.sub(r'<[^>]*>', '', text).strip()
        if not clean: clean = text.strip()
        original = clean
        
        # Procesare înainte de traducere
        clean = _clean_hi_text(clean)
        clean = _fix_double_dash(clean)
        clean = _clean_interjections(clean, is_translated=False) # Doar engleză

        if clean != original:
            cleaned_count += 1
            _log_debug(f"  Pre-curățat [{b_id}]: '{original}' → '{clean}'")

        # FIX CRITIC: Dacă e gol acum, rămâne '(nothing)'.
        # Nu îi dăm înapoi originalul, altfel robotul va vedea și va traduce [Music]
        if not clean or clean.strip() == '': 
            clean = '(nothing)'
            
        to_translate[b_id] = clean

    if cleaned_count > 0:
        _log_info(f"Pre-curățate {cleaned_count} texte înainte de traducere.")

    if batch_index == 0:
        models_to_use = [FIRST_BATCH_MODEL]
        batch_timeout = FIRST_BATCH_TIMEOUT
        _log_info(f"Primul batch: model={FIRST_BATCH_MODEL}, timeout={FIRST_BATCH_TIMEOUT}s")
    else:
        models_to_use = MODEL_PREFERAT
        batch_timeout = API_TIMEOUT

    for key_idx, current_key in enumerate(all_keys):
        if _is_blocked(current_key): continue
        _log_debug(f"Încerc cheie {key_idx+1}/{len(all_keys)}: ...{current_key[-4:]}")

        for model_idx, current_model in enumerate(models_to_use):
            result, err_code = translate_gemini(
                to_translate, target_lang, current_key,
                current_model, timeout=batch_timeout,
            )

            if err_code == -1:
                _log_info("Player oprit, abandonez batch-ul.")
                return None, "ABORT"  # <--- Asigură-te că returnează "ABORT" aici

            if result is not None:
                sent_count = len(to_translate)
                received_count = len(result)
                
                # PROTECȚIA 1: Validarea Numărului de Linii (Previne pierderile de Index și replicile în Engleză)
                if received_count != sent_count:
                    _log_warn(f"Eroare Index! Trimise: {sent_count}, Primite: {received_count}. Facem RETRY.")
                    continue 

                # PROTECȚIA 2: Detectarea falsului (nothing) și a Îmbinărilor (Merge)
                validation_passed = True
                for b_id, orig_text in to_translate.items():
                    trans_text = result.get(str(b_id), "").strip()
                    orig_len = len(orig_text)
                    trans_len = len(trans_text)
                    
                    # FIX: Dacă i-am trimis noi (nothing), e absolut normal ca Gemini să ne dea text gol!
                    # Nu e eroare, deci dăm skip la verificare!
                    if orig_text == "(nothing)":
                        continue
                    
                    # RELAXARE: Se dă eroare DOAR dacă s-a șters o propoziție lungă (> 15 caractere)
                    if orig_len > 15 and (trans_text.lower() == "(nothing)" or trans_text == ""):
                        _log_warn(f"Ștergere suspectă la index {b_id}. Text orig: '{orig_text[:20]}...'. Facem RETRY.")
                        validation_passed = False
                        break
                        
                    # Verificare Îmbinare (Merge Suspected) - Previne unirea a două replici într-una
                    if orig_len >= 15 and trans_len > 70:
                        ratio = trans_len / orig_len if orig_len > 0 else 0
                        if ratio > 2.2:
                            trans_newlines = trans_text.count('\n')
                            orig_newlines = orig_text.count('\n')
                            if trans_newlines > orig_newlines:
                                _log_warn(f"Îmbinare suspectă detectată la index {b_id} (raport {ratio:.1f}x). Facem RETRY.")
                                validation_passed = False
                                break
                
                if not validation_passed:
                    continue # Validare eșuată, forțăm Retry

                _log_debug(f"Traducere validată complet: {received_count}/{sent_count}")
                chunk = ""
                for b_id, timing, original_srt_text in batch:
                    # Verificăm ce i-am trimis NOI lui Gemini, nu ce a fost în SRT original
                    sent_text = to_translate.get(b_id, "")
                    
                    # 1. Dacă i-am trimis textul fantomă, îl forțăm să fie gol, 
                    # indiferent dacă Gemini l-a tradus în "(nimic)"
                    if sent_text == "(nothing)":
                        tr = ""
                    else:
                        tr = result.get(str(b_id), original_srt_text)
                        
                        # 2. Fallback de siguranță: dacă Gemini a pus parantezele
                        clean_tr = tr.strip().lower()
                        if clean_tr in ["(nothing)", "(nimic)", "[nothing]", "[nimic]"]:
                            tr = ""

                    if tr:
                        # Curățare POST-Traducere: curățăm și [Muzică] și interjecțiile Românești apărute
                        tr = _clean_hi_text(tr)
                        tr = _clean_interjections(tr, is_translated=True)
                        
                    if tr:
                        tr = _post_process_text(tr)

                    # Scriem blocul DOAR dacă a mai rămas text valabil
                    if tr.strip():
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
    # PROTECȚIE CRITICĂ KODI CRASH: Nu facem nimic dacă filmul s-a oprit
    if not _player_has_media():
        return False

    srt_content, total_blocks = _build_srt_from_chunks(all_chunks)

    if total_blocks == 0:
        _log_error("SRT construit e gol!")
        return False

    raw_bytes = b'\xef\xbb\xbf' + srt_content.encode('utf-8')

    try:
        fh = xbmcvfs.File(output_path, 'wb')
        fh.write(raw_bytes)
        fh.close()
    except Exception as e:
        _log_error(f"Eroare scriere SRT VFS: {e}")
        try:
            with open(output_path, 'wb') as f:
                f.write(raw_bytes)
        except Exception as e2:
            _log_error(f"Fallback scriere eșuat: {e2}")
            return False

    try:
        size = os.path.getsize(output_path)
        _log_info(f"SRT scris OK ({size} bytes, {total_blocks} blocuri)")
    except Exception: pass

    try:
        # Verificare pasivă înainte să interacționăm cu C++ Kodi
        # Player.HasVideo e True și pe pauză — setSubtitles funcționează în ambele cazuri
        if xbmc.getCondVisibility('Player.HasVideo'):
            temp_dir = xbmcvfs.translatePath('special://temp/substudio_subs/')
            if not xbmcvfs.exists(temp_dir):
                xbmcvfs.mkdirs(temp_dir)
                
            import time
            timestamp = int(time.time())
            unique_robot_folder = os.path.join(temp_dir, f"robot_{timestamp}")
            xbmcvfs.mkdirs(unique_robot_folder)
            
            temp_sub = os.path.join(unique_robot_folder, os.path.basename(output_path))
            
            f_temp = xbmcvfs.File(temp_sub, 'wb')
            f_temp.write(raw_bytes)
            f_temp.close()
            
            xbmc.Player().setSubtitles(temp_sub)
            _log_info("Subtitrare tradusă activată în player.")
    except Exception as e:
        _log_debug(f"Subtitrarea nu s-a mai activat (player oprit între timp): {e}")

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
    # Eliminăm codul de limbă original dacă există (ex: 'Film.en' devine 'Film')
    base = re.sub(r'\.[a-z]{2,3}$', '', base, flags=re.IGNORECASE)
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

    # 1. PROTECȚIE LIPSĂ CHEI: Dacă nu există absolut nicio cheie introdusă
    if not all_keys:
        xbmcgui.Dialog().ok(
            "SubStudio – Eroare",
            "Nicio cheie API configurată!\n\n"
            "1. Mergi la aistudio.google.com\n"
            "2. Creează o cheie API gratuită\n"
            "3. Adaug-o în Setări → Cheie Gemini API"
        )
        return

    # --- NOU: VALIDARE ONLINE A CHEILOR GEMINI ---
    def _validate_gemini_key(key):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5): return True
        except urllib.error.HTTPError as e:
            if e.code == 400: return False # 400 = API Key Invalid
        except Exception: return True # Eroare de rețea, o lăsăm să treacă
        return True

    # Doar dacă a trecut de verificarea de mai sus (adică ARE chei), le validează online
    valid_keys = [k for k in all_keys if _validate_gemini_key(k)]
    
    # 2. PROTECȚIE CHEI INVALIDE: A introdus chei, dar sunt greșite/expirate
    if not valid_keys:
        xbmcgui.Dialog().notification("Gemini Robot", "Cheile API introduse sunt INVALIDE!", xbmcgui.NOTIFICATION_ERROR, 5000)
        return
        
    all_keys = valid_keys
    # ---------------------------------------------

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

    # ── Setare auto-pauză ────────────────────────────────────────
    auto_pause_enabled = True  # default ON dacă setarea nu există încă
    try:
        auto_pause_enabled = _addon.getSettingBool('auto_pause_traducere')
    except Exception:
        try:
            auto_pause_enabled = _addon.getSetting('auto_pause_traducere').lower() == 'true'
        except Exception:
            pass

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

    # ── Pune filmul pe pauză automat (doar dacă e activat în setări) ────
    was_paused = False
    if auto_pause_enabled:
        was_paused = _auto_pause()
        if was_paused:
            _notify(f'Traducere [B][COLOR orange]{target_lang.upper()}[/COLOR][/B] pornită... [B][COLOR red]Așteptați.[/COLOR][/B]')
        else:
            _notify(f'[B][COLOR orange]{target_lang.upper()}[/COLOR][/B]: [B][COLOR yellow]{total_lines}[/COLOR][/B] linii, '
                    f'[B][COLOR lime]{total_batches}[/COLOR][/B] pachete')
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
            
            # --- AFIȘARE EXACTĂ A LINIILOR ÎN LOG ---
            if batch_size > 0:
                first_line_id = batch[0][0]
                last_line_id = batch[-1][0]
                _log_info(f"Batch {batch_idx+1}/{total_batches} ({batch_size} linii: {first_line_id} - {last_line_id})...")
            else:
                _log_info(f"Batch {batch_idx+1}/{total_batches} (0 linii)...")

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

                chunk, model_used = translate_one_batch(
                    batch, target_lang, active_keys, batch_index=batch_idx)

                # 1. PROTECȚIE CRITICĂ: Verificăm ABORT-ul PRIMUL, înainte de orice
                if model_used == "ABORT" or not _player_has_media():
                    player_stopped = True
                    break

                # 2. Dacă traducerea a reușit, trecem la batch-ul următor
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
                    # Repornim DOAR dacă robotul a pus pauza (nu dacă userul a dat pauză manual)
                    if was_paused:
                        _auto_resume()
                    _notify(f'Primele [B][COLOR yellow]{batch_size}[/COLOR][/B] linii traduse [B][COLOR lime]({elapsed}s)[/COLOR][/B]!')
            else:
                # Folosim originalul CA FALLBACK doar dacă eșuează din motiv de rețea/chei, 
                # NU dacă userul a dat STOP!
                if not player_stopped and _player_has_media():
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