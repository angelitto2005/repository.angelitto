# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, sys, re, json, time
import urllib.parse, urllib.request, urllib.error
import threading

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURARE
# ═══════════════════════════════════════════════════════════════════
MODEL_PREFERAT = []
FIRST_BATCH_MODEL = ""
FIRST_BATCH_TIMEOUT = 300

FIRST_BATCH_SIZE  = 100
NEXT_BATCH_SIZE   = 300
PAUZA_INTRE_BATCH = 12
PAUZA_DUPA_EROARE = 15
MAX_RETRIES       = 10
API_TIMEOUT       = 300

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
    getCondVisibility e doar o citire de proprietate UI, mereu sigură.
    """
    try:
        # Player.HasMedia e un tag global mai sigur în Kodi 19/20/21
        has_media = xbmc.getCondVisibility('Player.HasMedia')
        
        # Pe unele skin-uri, când e pe pauză, HasVideo poate returna False, 
        # dar Player.Paused este clar True. 
        is_paused = xbmc.getCondVisibility('Player.Paused')
        
        if has_media or is_paused:
            return True
            
        return False
    except Exception:
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
        # FIX: Eliminăm definitiv din fașă tag-urile ASS de formatare/aliniere (ex: {\an8}, {\pos...})
        text = re.sub(r'\{.*?\}', '', text)
        
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

**CRITICAL ANTI-SHIFTING RULES (READ CAREFULLY):**
- You are translating TIMED subtitle blocks. 
- Text from input index X MUST remain in output index X. NEVER move words to neighboring indices!
- If a single sentence is broken across two indices, translate the broken parts EXACTLY where they are. Do NOT combine them.
- BAD EXAMPLE (Shifting text - DO NOT DO THIS):
  Input: [{{"index": "5", "text": "I am a man,"}}, {{"index": "6", "text": "a very good man."}}]
  Bad Output: [{{"index": "5", "text": "Sunt un om, un om foarte bun."}}, {{"index": "6", "text": "(nothing)"}}]
- GOOD EXAMPLE (Strict 1-to-1 Mapping):
  Good Output: [{{"index": "5", "text": "Sunt un om,"}}, {{"index": "6", "text": "un om foarte bun."}}]

**CONTENT RULES:**
- MULTI-LINE BLOCKS: Translate ALL lines of a block as ONE unit under the SAME index.
- Translate ALL content including aggressive language — do NOT censor or block.
- Preserve names, places, and technical terms as-is.
- If source text is "(nothing)" or empty, output "(nothing)" exactly.
"""
    return prompt


# ═══════════════════════════════════════════════════════════════════
#  APEL GEMINI API (Adaptat pentru Kodi, emulează google.genai)
# ═══════════════════════════════════════════════════════════════════
def translate_gemini(texts_dict, target_lang, api_key, model_name, timeout=API_TIMEOUT):
    # Modelele 3.0 necesită endpoint-ul v1alpha. Restul funcționează pe v1beta.
    api_version = "v1alpha" if "gemini-3" in model_name else "v1beta"
    url = (
        f"https://generativelanguage.googleapis.com/{api_version}/models/"
        f"{model_name}:generateContent?key={api_key}"
    )

    prompt = _build_prompt(target_lang, len(texts_dict))
    json_input = [{"index": str(k), "text": v} for k, v in texts_dict.items()]

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt + "\n\n" + json.dumps(json_input, ensure_ascii=False)
            }]
        }],
        "generationConfig": {
            "temperature": 0.9,  # Setat pe 0.9, ca în scriptul de Windows
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

    _log_debug(f"API call: model={model_name} ({api_version}), cheie=...{api_key[-4:]}, "
               f"{len(texts_dict)} texte, limba={target_lang}, timeout={timeout}s")

    result_container = {'response': None, 'error': None, 'code': 0}
    request_start = time.time()

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
        except Exception as e: 
            result_container['error'] = f"{type(e).__name__}: {e}"

    req_thread = threading.Thread(target=_do_request, daemon=True)
    req_thread.start()

    while req_thread.is_alive():
        req_thread.join(timeout=1.0)
        if not _player_has_media(): return None, -1

    # AFIȘARE EROARE CLARĂ ÎN LOG (Dacă Google dă un cod HTTP, gen 400, 404, 500)
    if result_container['code'] > 0: 
        _log_error(f"Eroare HTTP {result_container['code']} de la API: {result_container['error']}")
        return None, result_container['code']
    
    # AFIȘARE EROARE CLARĂ ÎN LOG (Dacă a dat timeout sau a picat conexiunea)
    if not result_container['response']: 
        if result_container['error']:
            _log_error(f"Eroare Conexiune/Timeout: {result_container['error']}")
        else:
            _log_error("Timpul de așteptare a expirat sau răspunsul a fost complet gol.")
        return None, 0

    raw = result_container['response']
    try: res_data = json.loads(raw)
    except json.JSONDecodeError: return None, 0

    if 'error' in res_data: return None, res_data['error'].get('code', 0)
    
    candidates = res_data.get('candidates', [])
    if not candidates: return None, 0
    if candidates[0].get('finishReason', '') == 'SAFETY': return None, 0

    try: text_r = candidates[0]['content']['parts'][0]['text']
    except (KeyError, IndexError, TypeError): return None, 0
    if not text_r: return None, 0

    # FIX CRITIC PENTRU "Error 0": Modelele noi mai adaugă "```json" la răspuns.
    text_r = text_r.strip()
    if text_r.startswith("```"):
        text_r = re.sub(r"^```(?:json)?\n|\n```$", "", text_r).strip()

    try:
        parsed_array = json.loads(text_r)
        result_dict = {str(item['index']): str(item['text']) for item in parsed_array if 'index' in item and 'text' in item}
        return result_dict, 0
    except Exception as e:
        _log_error(f"JSON Parse Error: {e}")
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
    'hoo','huh','mh','mhm','mm','mmhmm','mm-hmm','mmm','mmmm','mmm-hmm',
    'mwah','oh','ohh','ohhh','oo','ooh','ooh-la-la','oooh',
    'oops','ops','ouch','ow','oww','owww','pf','pff','pfff','pffft',
    'pfft','phew','pssh','psst','sh','shh','shhh','ssh','ssshh','sst',
    'uf','uff','ugh','ughh','uh','uh-oh','uh-huh','uhh','uhhh','uhm','uhmm',
    'uhu','uhuu','um','umm','uu','whew','whoa','whoo','whoo-hoo','woo-hoo',
    'whooo','whoooo','whoooooo','whoop','whoops','whup','wooh','woo-hoo-hoo',
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

        if re.match(r'^-\s*', stripped):
            is_dialogue = True
            dialogue_text = re.sub(r'^-\s*', '', stripped).strip()
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
                    # FIX: Păstrăm EXACT punctuația originală (?, !, virgula de final sau puncte de suspensie).
                    # Nu mai forțăm adăugarea unui punct.
                    cleaned = main + trail
                else:
                    break
            else:
                break

        # ── MIJLOC ──
        _inj_alt = '|'.join(re.escape(i) for i in sorted(current_dict, key=len, reverse=True))
        
        # NOU: Interjecție urmată de puncte de suspensie ("E, ăă..." -> "E...")
        cleaned = re.sub(
            r',\s*(?:' + _inj_alt + r')\s*([.!?…]+)',
            r'\1',
            cleaned, flags=re.IGNORECASE | re.UNICODE
        )
        
        cleaned = re.sub(r',\s*(?:' + _inj_alt + r')\s*,', ', ', cleaned, flags=re.IGNORECASE | re.UNICODE)
        
        if is_translated:
            # Elimină englezismul "gen" (traducerea lui "like" ca filler)
            cleaned = re.sub(r',\s*gen\s*,', ', ', cleaned, flags=re.IGNORECASE | re.UNICODE)
            cleaned = re.sub(r',\s*gen\s*([.!?…]+)$', r'\1', cleaned, flags=re.IGNORECASE | re.UNICODE)

        # Curăță eventualele spații sau virgule duble lăsate în urmă
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        cleaned = re.sub(r',\s*,', ',', cleaned).strip()

        # ── DUPĂ PUNCT LA MIJLOC (ex: "Mulțumesc. Ăă, chiar nu" -> "Mulțumesc. Chiar nu") ──
        # Elimină interjecția dacă se află după . ! ?
        cleaned = re.sub(
            r'([.!?])\s+(?:' + _inj_alt + r')\s*[,\s]+\s*(.)',
            lambda m: m.group(1) + ' ' + m.group(2).upper(),
            cleaned, flags=re.IGNORECASE | re.UNICODE
        )
        
        # NOU: Elimină interjecția dacă este prinsă EXACT ÎNTRE PUNCTE ("Da. Mm-hmm. Mulțumesc.")
        # Transformă ". Mm-hmm." într-un simplu punct "."
        cleaned = re.sub(
            r'([.!?])\s*(?:' + _inj_alt + r')\s*([.!?])',
            r'\1',
            cleaned, flags=re.IGNORECASE | re.UNICODE
        )

        cleaned = cleaned.strip()

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
    """Convertește -- în ... sau îl elimină la început de rând."""
    if not text: return text
    # Elimină dubla-cratimă de la începutul rândului (Ex: '--She thought' -> 'She thought')
    text = re.sub(r'^--+\s*', '', text, flags=re.MULTILINE)
    # Transformă restul de -- în ...
    text = re.sub(r'--+', '...', text)
    return text


# ═══════════════════════════════════════════════════════════════════
#  REECHILIBRARE / ÎMPĂRȚIRE LINII SUBTITRARE
# ═══════════════════════════════════════════════════════════════════
SINGLE_LINE_MAX     = 42
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

    # Extragem HTML-ul doar pentru a citi corect cratima și a vedea dacă sunt 2 vorbitori diferiți
    c1_clean = re.sub(r'<[^>]+>', '', lines[0] if len(lines) > 0 else '').strip()
    c2_clean = re.sub(r'<[^>]+>', '', lines[1] if len(lines) > 1 else '').strip()

    is_two_speakers = len(lines) == 2 and c2_clean.startswith('-')

    def visible(t):
        """Lungime vizibilă, doar fără tag-uri HTML. Simbolul ♪ rămâne pentru calculul lățimii reale."""
        return re.sub(r'</?[a-zA-Z]+>', '', t).strip()

    def _find_smart_split(full_text, full_clean):
        ideal = len(full_clean) // 2
        space_indices = [m.start() for m in re.finditer(r'\s', full_clean)]
        
        if not space_indices:
            return None
            
        best_idx = -1
        best_score = 99999
        
        for idx in space_indices:
            l1_len = idx
            l2_len = len(full_clean) - idx - 1
            
            penalty = 1000 if (l1_len > SINGLE_LINE_MAX or l2_len > SINGLE_LINE_MAX) else 0
                
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
    if len(lines) == 1 and not is_two_speakers:
        vis = visible(text)
        if len(vis) > SINGLE_LINE_MAX:
            result = _find_smart_split(text, vis)
            if result:
                return f"{result[0]}\n{result[1]}"

    #  Calea 2: DOUĂ LINII
    elif len(lines) == 2 and not is_two_speakers:
        c1 = visible(lines[0])
        c2 = visible(lines[1])

        # Îmbinare linii scurte (Single sentence merge)
        if len(c1) + 1 + len(c2) <= SINGLE_LINE_MAX:
            merged = f"{lines[0].strip()} {lines[1].strip()}"
            merged = re.sub(r'</i>\s*<i>', ' ', merged)
            return merged

        # Reechilibrare
        if abs(len(c1) - len(c2)) > REBALANCE_THRESHOLD or len(c1) > SINGLE_LINE_MAX or len(c2) > SINGLE_LINE_MAX:
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
                return f"{result[0]}\n{result[1]}"

    return text


def _fix_dialog_format(text):
    """Corectează formatarea liniilor de dialog și elimină cratimele orfane."""
    if not text: return text
    lines = text.split('\n')
    
    for i in range(len(lines)):
        m_html = re.match(r'^(<[^>]+>)*', lines[i])
        html_prefix = m_html.group(0) if m_html else ''
        content = lines[i][len(html_prefix):].lstrip()
        
        m_dash = re.match(r'^-\s*', content)
        dash_prefix = '- ' if m_dash else ''
        content = content[len(m_dash.group(0)):] if m_dash else content
        
        content = re.sub(r'^\.\.\.+\s*', '', content)
        content = re.sub(r'^…+\s*', '', content)
        
        lines[i] = html_prefix + dash_prefix + content

    if len(lines) == 2:
        l1_clean = re.sub(r'<[^>]+>', '', lines[0]).strip()
        l2_clean = re.sub(r'<[^>]+>', '', lines[1]).strip()
        
        # Dialog valid: Linia 2 are cratimă, forțăm cratimă și pe Linia 1
        if l2_clean.startswith('-') and l1_clean and not l1_clean.startswith('-'):
            m_html = re.match(r'^(<[^>]+>)*', lines[0])
            idx = len(m_html.group(0)) if m_html else 0
            lines[0] = lines[0][:idx] + '- ' + lines[0][idx:]
            
        # FALS DIALOG: Linia 1 are cratimă, dar Linia 2 NU are!
        # Scoatem cratima orfană complet de pe prima linie.
        elif l1_clean.startswith('-') and not l2_clean.startswith('-'):
            lines[0] = re.sub(r'^(<[^>]+>)*-\s*', r'\1', lines[0])

    # FALS DIALOG: A rămas o singură linie în bloc, dar are cratimă. O scoatem.
    if len(lines) == 1:
        lines[0] = re.sub(r'^(<[^>]+>)*-\s*', r'\1', lines[0])

    return '\n'.join(lines)


def _split_inline_dialogue(text):
    """
    Forțează separarea pe 2 rânduri dacă 2 vorbitori sunt pe același rând.
    Ex: '...fructe? -Brânză.' -> '...fructe?\n-Brânză.'
    """
    if not text: return text
    # Caută punctuație (. ! ? ") urmată de spațiu și o cratimă de dialog
    text = re.sub(r'([.!?"])\s+(-\s*\S)', r'\1\n\2', text)
    return text

def _restore_formatting(original, translated):
    """Restaurează și echilibrează tag-urile <i> și ♪ uitate sau dezechilibrate."""
    if not translated: return translated
    orig_clean = original.strip()
    tr_clean = translated.strip()

    # 1. Recuperăm notele muzicale uitate COMPLET de Gemini
    if '♪' in orig_clean and '♪' not in tr_clean:
        if orig_clean.startswith('♪') and orig_clean.endswith('♪'):
            tr_clean = f"♪ {tr_clean} ♪"
        elif orig_clean.startswith('♪'):
            tr_clean = f"♪ {tr_clean}"
        elif orig_clean.endswith('♪'):
            tr_clean = f"{tr_clean} ♪"

    # 2. Recuperăm italicul uitat COMPLET
    if orig_clean.startswith('<i>') and orig_clean.endswith('</i>') and not (tr_clean.startswith('<i>') and tr_clean.endswith('</i>')):
        # Scoatem orice fragment de italic ramas aiurea în interior și învelim totul
        tr_clean = re.sub(r'</?i>', '', tr_clean)
        tr_clean = f"<i>{tr_clean}</i>"

    # 3. Echilibrăm ghilimelele orfane
    if tr_clean.count('"') % 2 != 0:
        if tr_clean.lstrip('<i>- ♪').startswith('"'):
            if tr_clean.endswith('</i>'):
                tr_clean = tr_clean[:-4] + '"</i>'
            elif tr_clean.endswith('♪'):
                tr_clean = tr_clean[:-1].strip() + '" ♪'
            else:
                tr_clean += '"'
        elif tr_clean.rstrip('</i>♪ ').endswith('"'):
            if tr_clean.startswith('<i>'):
                tr_clean = '<i>"' + tr_clean[3:]
            elif tr_clean.startswith('♪ '):
                tr_clean = '♪ "' + tr_clean[2:]
            elif tr_clean.startswith('- '):
                tr_clean = '- "' + tr_clean[2:]
            else:
                tr_clean = '"' + tr_clean

    # 4. ECHILIBRAREA INTELIGENTĂ PE LINII (Note Muzicale și Italice)
    lines = tr_clean.split('\n')
    
    # Verificăm dacă blocul este dialog (2 linii, ambele cu cratimă la început, excluzând tag-urile)
    def is_dialog_line(l):
        return l.lstrip('<i>♪ ').startswith('-')
        
    is_dialogue = len(lines) == 2 and is_dialog_line(lines[0]) and is_dialog_line(lines[1])
    
    if is_dialogue:
        # Echilibrăm fiecare vorbitor independent
        new_lines = []
        for line in lines:
            prefix = ""
            content = line.strip()
            
            # Extragem prefixele pentru a nu încurca cratimele
            m = re.match(r'^(?:<i>|♪|\s)*-\s*', content)
            if m:
                prefix_raw = m.group(0)
                content = content[len(prefix_raw):].strip()
                prefix = "- "
            elif content.startswith('-'):
                prefix = "- "
                content = content[1:].strip()
            
            # Echilibrează ♪
            if content.startswith('♪') and not content.endswith('♪'): content += " ♪"
            elif content.endswith('♪') and not content.startswith('♪'): content = "♪ " + content
            
            # Echilibrează <i>
            if content.startswith('<i>') and not content.endswith('</i>'): content += "</i>"
            elif content.endswith('</i>') and not content.startswith('<i>'): content = "<i>" + content
            
            # Repunem prefixul cratimei în interiorul tag-urilor pentru estetică
            if prefix:
                if content.startswith('♪') or content.startswith('<i>'):
                    content = re.sub(r'^(♪\s*|<i>\s*)+', r'\g<0>- ', content)
                else:
                    content = "- " + content
                    
            new_lines.append(content)
        tr_clean = '\n'.join(new_lines)
        
    else:
        # Bloc normal (o singură frază întinsă pe 1 sau 2 rânduri)
        content = tr_clean.strip()
        
        # Identificăm dacă are cratimă la început
        has_dash = False
        if content.lstrip('<i>♪ ').startswith('-'):
            has_dash = True
            content = content.replace('- ', '', 1).strip()
            
        # Echilibrează ♪ la nivel de BLOC
        if content.startswith('♪') and not content.endswith('♪'): content += " ♪"
        elif content.endswith('♪') and not content.startswith('♪'): content = "♪ " + content
        
        # Echilibrează <i> la nivel de BLOC
        if content.startswith('<i>') and not content.endswith('</i>'): content += "</i>"
        elif content.endswith('</i>') and not content.startswith('<i>'): content = "<i>" + content
        
        # Repunem cratima (dacă era doar un vorbitor cu frază pe 2 rânduri)
        if has_dash:
            if content.startswith('♪') or content.startswith('<i>'):
                content = re.sub(r'^(♪\s*|<i>\s*)+', r'\g<0>- ', content)
            else:
                content = "- " + content
                
        tr_clean = content

    # Cleanups finale (aranjarea corectă a tagurilor: mereu ♪ în fața <i>)
    tr_clean = tr_clean.replace('<i>♪', '♪ <i>').replace('♪</i>', '</i> ♪')
    tr_clean = re.sub(r'\s+♪$', ' ♪', tr_clean)
    tr_clean = re.sub(r'^♪\s+', '♪ ', tr_clean)
    tr_clean = re.sub(r'♪\s+♪', '♪', tr_clean) # Elimină dublurile
    
    return tr_clean


# ═══════════════════════════════════════════════════════════════════
#  POST-PROCESARE TEXT TRADUS (pipeline complet)
# ═══════════════════════════════════════════════════════════════════
def _post_process_text(text):
    """
    Aplică pe textul tradus:
    1. Fix inline dialog
    2. Fix -- → ...
    3. Reechilibrare/împărțire linii
    4. Fix formatare dialog
    5. Curățări gramaticale finale
    """
    if not text: return text
    text = _split_inline_dialogue(text)
    text = _fix_double_dash(text)
    
    # Reechilibrarea poate uni 2 linii scurte. De asta rulează ÎNAINTE de formatarea de dialog.
    text = _rebalance_lines(text)
    
    # Acum că știm exact câte linii au mai rămas, curățăm cratimele orfane
    text = _fix_dialog_format(text)
    
    # FIX FINAL: Transfomă 4 puncte (sau mai multe) în 3 puncte ("...." -> "...")
    text = re.sub(r'\.{4,}', '...', text)
    
    # FIX FINAL: Elimină dublura de cratime tradusă de Gemini ("- - Nu" -> "- Nu")
    text = re.sub(r'^-\s*-\s*', '- ', text, flags=re.MULTILINE)
    
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
        clean = _split_inline_dialogue(clean)
        clean = _fix_dialog_format(clean)
        clean = _fix_double_dash(clean)
        clean = _clean_interjections(clean, is_translated=False)

        # ---- ADAUGĂ ASTEA DOUĂ RÂNDURI AICI ----
        # Transformă în text gol rândurile care conțin STRICT note muzicale sau puncte de suspensie
        if re.fullmatch(r'[♪\s]+', clean) or re.fullmatch(r'[.\s]+', clean):
            clean = ""
        # ----------------------------------------

        if clean != original:
            cleaned_count += 1
            _log_debug(f"  Pre-curățat [{b_id}]: '{original}' → '{clean}'")

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
                return None, "ABORT"

            if result is not None:
                sent_count = len(to_translate)
                
                # PROTECȚIA 1: Validarea Integrității Indicilor
                sent_indices = set(str(bid) for bid in to_translate.keys())
                received_indices = set(str(item) for item in result.keys())

                diff_missing = sent_indices - received_indices
                diff_extra = received_indices - sent_indices

                if diff_missing:
                    _log_warn(f"LIPSESC indicii: {diff_missing}. Facem RETRY.")
                    continue
                elif diff_extra:
                    _log_warn(f"Indici în plus detectați și ignorați: {diff_extra}")
                    for extra_id in diff_extra:
                        result.pop(extra_id, None)

                # PROTECȚIA 2: Logica EXACTĂ din scriptul de Windows
                validation_failed = False
                for b_id, orig_text in to_translate.items():
                    trans_text = result.get(str(b_id), "").strip()
                    orig_is_nothing = orig_text.lower() == "(nothing)"
                    trans_is_nothing = trans_text.lower() in ["(nothing)", "(nimic)", "[nothing]", ""] # AM ADAUGAT SI STRING GOL "" AICI

                    # Check 1: False (nothing) - INTELLIGENT
                    if not orig_is_nothing and trans_is_nothing:
                        # Daca originalul are sub 10 caractere (probabil o exclamatie/nume), ii permitem sa fie gol
                        if len(orig_text.strip()) > 10:
                            _log_warn(f"FALSE (nothing) la index {b_id}. Orig: '{orig_text[:20]}'. RETRY.")
                            validation_failed = True
                            break
                        else:
                            _log_debug(f"FALSE (nothing) tolerat la index {b_id} (Text scurt: '{orig_text}')")
                    
                    # Check 2: Merge Suspected
                    if not orig_is_nothing and not trans_is_nothing:
                        orig_len = len(orig_text)
                        trans_len = len(trans_text)
                        
                        if orig_len >= 15:
                            ratio = trans_len / orig_len if orig_len > 0 else 0
                            # Dacă traducerea e de >2.2x mai lungă și are peste 70 caractere
                            if ratio > 2.2 and trans_len > 70:
                                orig_newlines = orig_text.count('\n')
                                trans_newlines = trans_text.count('\n')
                                # Dacă a și adăugat linii noi, e clar o îmbinare
                                if trans_newlines > orig_newlines:
                                    _log_warn(f"MERGE SUSPECTED la index {b_id}. "
                                              f"Orig: {orig_len} chars -> Trans: {trans_len} chars. RETRY.")
                                    validation_failed = True
                                    break

                if validation_failed:
                    continue

                _log_debug(f"Traducere validată complet: {len(result)}/{sent_count}")

                _log_debug(f"Traducere validată complet: {len(result)}/{sent_count}")
                chunk = ""
                for b_id, timing, original_srt_text in batch:
                    sent_text = to_translate.get(b_id, "")

                    if sent_text == "(nothing)":
                        tr = ""
                    else:
                        tr = result.get(str(b_id), "")
                        
                        # Previne ca Gemini să adauge rânduri goale multiple care strică fișierul SRT
                        tr = re.sub(r'\n{2,}', '\n', tr)

                        clean_tr = tr.strip().lower()
                        if clean_tr in ["(nothing)", "(nimic)", "[nothing]", "[nimic]"]:
                            tr = ""

                    if tr:
                        tr = _clean_hi_text(tr)
                        tr = _clean_interjections(tr, is_translated=True)

                    if tr:
                        tr = _post_process_text(tr)
                        tr = _restore_formatting(original_srt_text, tr)

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
def _write_and_activate(output_path, all_chunks, target_lang="ro", activate=True):
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

    # ACTIVĂM ÎN PLAYER DOAR DACĂ ACTIVATE=TRUE (evită crash-ul Libass)
    if activate:
        try:
            # Verificare pasivă înainte să interacționăm cu C++ Kodi
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
            # Extragem ID-urile EXACT cum o face și service.py la căutare
            imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)") or ""
            tmdb_id = xbmc.getInfoLabel("VideoPlayer.TMDbId") or xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or xbmc.getInfoLabel("Window(10000).Property(tmdb_id)") or ""
            video_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title") or ""
            video_year = xbmc.getInfoLabel("VideoPlayer.Year") or ""
            
            # Adăugăm obligatoriu sezonul și episodul
            season = xbmc.getInfoLabel("VideoPlayer.Season") or ""
            episode = xbmc.getInfoLabel("VideoPlayer.Episode") or ""

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
                'season': season,
                'episode': episode,
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

            _log_info(f"Index: {output_name} → imdb={imdb_id}, tmdb={tmdb_id}, S{season}E{episode}")

        except Exception as e:
            _log_warn(f"Index update failed (non-fatal): {e}")

        _notify(f'[B][COLOR lime]Salvat permanent: [COLOR orange]{output_name}[/COLOR][/B]', duration=3000)

    except Exception as e:
        _log_error(f"Eroare salvare permanentă: {e}")


# ═══════════════════════════════════════════════════════════════════
#  FUNCȚIA PRINCIPALĂ
# ═══════════════════════════════════════════════════════════════════
def run_translation(sub_addon_id, mode="fast"):
    _reset_blocked()

    try:
        _addon = xbmcaddon.Addon(sub_addon_id)
    except Exception as e:
        _log_error(f"Nu pot accesa addon {sub_addon_id}: {e}")
        return

    # --- DEFINIRE MOTOARE ȘI MĂRIME PACHETE DINAMIC ---
    global MODEL_PREFERAT, FIRST_BATCH_MODEL, FIRST_BATCH_TIMEOUT
    global FIRST_BATCH_SIZE, NEXT_BATCH_SIZE

    # Citim indexul ales în setările Kodi
    try:
        robot_idx = _addon.getSettingInt('robot_selectat')
    except Exception:
        robot_idx = 0

    if robot_idx == 1:
        # --- OPȚIUNEA: Gemini Slow (Flash 3 Preview) ---
        MODEL_PREFERAT = ["gemini-3-flash-preview"]
        FIRST_BATCH_MODEL = "gemini-3-flash-preview"
        FIRST_BATCH_TIMEOUT = 300
        FIRST_BATCH_SIZE = 200
        
        try:
            slow_idx = _addon.getSettingInt('gemini_slow_batch')
            if slow_idx == 0: NEXT_BATCH_SIZE = 300
            elif slow_idx == 1: NEXT_BATCH_SIZE = 500
            elif slow_idx == 2: NEXT_BATCH_SIZE = 700
            else: NEXT_BATCH_SIZE = 300
        except Exception:
            NEXT_BATCH_SIZE = 300
            
        _log_info(f"Mod SLOW (Flash 3 Preview) activat: Primul pachet={FIRST_BATCH_SIZE}, Următoarele={NEXT_BATCH_SIZE}.")

    elif robot_idx == 2 or mode == "slow":
        # --- OPȚIUNEA: Gemini Slow (Flash 3.5) ---
        MODEL_PREFERAT = ["gemini-3.5-flash"]
        FIRST_BATCH_MODEL = "gemini-3.5-flash"
        FIRST_BATCH_TIMEOUT = 300
        FIRST_BATCH_SIZE = 200
        
        try:
            slow_idx = _addon.getSettingInt('gemini_slow_batch')
            if slow_idx == 0: NEXT_BATCH_SIZE = 300
            elif slow_idx == 1: NEXT_BATCH_SIZE = 500
            elif slow_idx == 2: NEXT_BATCH_SIZE = 700
            else: NEXT_BATCH_SIZE = 300
        except Exception:
            NEXT_BATCH_SIZE = 300
            
        _log_info(f"Mod SLOW (Flash 3.5) activat: Primul pachet={FIRST_BATCH_SIZE}, Următoarele={NEXT_BATCH_SIZE}.")

    else:
        # --- OPȚIUNEA: Gemini Fast (Lite) (robot_idx == 0 sau default) ---
        MODEL_PREFERAT = [
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
        ]
        FIRST_BATCH_MODEL = "gemini-2.5-flash-lite"
        FIRST_BATCH_TIMEOUT = 300
        FIRST_BATCH_SIZE = 100
        NEXT_BATCH_SIZE = 300
        _log_info("Mod FAST activat: Modele Lite (2.5 fallback 3.1). Pachete: 100 / 300.")
    # ------------------------------------------------

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
    # AUTO_PAUSE ELIMINAT — cauza principală a crash-ului pe Android.
    # setSubtitles chemat în timp ce playerul era pauzat/reluat → race condition Libass.

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

                # NOU: Activăm subtitrarea pe ecran de FIECARE dată când se traduce un batch
                # Astfel, Kodi reîncarcă fișierul SRT actualizat și nu mai dispare textul la minutul 6.
                ok = _write_and_activate(output_path, all_chunks, target_lang, activate=True)

                if not first_done and ok:
                    first_done = True
                    elapsed = int(time.time() - start_time)
                    _notify(f'Primele [B][COLOR yellow]{batch_size}[/COLOR][/B] linii traduse [B][COLOR lime]({elapsed}s)[/COLOR][/B]!')
            else:
                # FALLBACK INVIZIBIL: Dacă Gemini eșuează absolut după toate cele 10 încercări,
                # construim segmentul SRT, dar cu text GOL. Astfel, Kodi va sări peste aceste rânduri 
                # și ecranul va rămâne curat, fără să afișeze limba engleză.
                failed += 1
                fallback = ""
                for b_id, timing, text in batch:
                    # Lăsăm textul gol în mod intenționat. (Kodi va ignora blocul la redare).
                    fallback += f"{b_id}\n{timing}\n \n\n"
                    
                all_chunks.append(fallback)
                is_last_batch = (batch_idx == total_batches - 1)
                _write_and_activate(output_path, all_chunks, target_lang,
                                    activate=not first_done or is_last_batch)
                _log_warn(f"Batch {batch_idx+1} EȘUAT DEFINITIV după {MAX_RETRIES} încercări. Au fost scrise {batch_size} rânduri goale.")

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

        if fully_complete:
            _save_translation(output_path, output_name, sub_addon_id)
            xbmc.sleep(3200)  # Lăsăm "Salvat permanent" să apară, apoi "Complet!"
        _notify(msg, duration=5000)
    else:
        _notify('[B][COLOR red]Traducere eșuată complet![/COLOR][/B]', duration=5000)

    _log_info(f"FINALIZAT — {completed}/{total_batches} OK, "
              f"{failed} erori, {minutes}m{seconds}s. "
              f"Complet: {fully_complete}")
    _log_debug("═══ SFÂRȘIT TRADUCERE ═══")