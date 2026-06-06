# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcvfs, xbmcaddon
import os, sys, re, json, time
import urllib.parse, urllib.request, urllib.error
import threading

# ═══════════════════════════════════════════════════════════════════
#  CONFIGURATION
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
#  COLORED NAME + ICON
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
    xbmc.log(f"ROBOT ERROR: {msg}", xbmc.LOGERROR)

# ═══════════════════════════════════════════════════════════════════
#  NOTIFICATION HELPER
# ═══════════════════════════════════════════════════════════════════
def _notify(msg, icon_type=xbmcgui.NOTIFICATION_INFO, duration=4000):
    xbmcgui.Dialog().notification(ADDON_NAME, msg, _get_addon_icon(), duration)


def _player_has_media():
    """
    100% PASSIVE verification — does not touch the C++ xbmc.Player() object.
    getCondVisibility is just a UI property read, always safe.
    """
    try:
        # Player.HasMedia is a safer global tag in Kodi 19/20/21
        has_media = xbmc.getCondVisibility('Player.HasMedia')
        
        # On some skins, when paused, HasVideo might return False, 
        # but Player.Paused is clearly True. 
        is_paused = xbmc.getCondVisibility('Player.Paused')
        
        if has_media or is_paused:
            return True
            
        return False
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
#  KEY BLACKLIST
# ═══════════════════════════════════════════════════════════════════
_blocked_keys = set()
_blocked_lock = threading.Lock()

def _is_blocked(key):
    with _blocked_lock:
        return key in _blocked_keys

def _block_key(key):
    with _blocked_lock:
        _blocked_keys.add(key)
    _log_warn(f"Blocked key: ...{key[-4:]}")

def _reset_blocked():
    global _blocked_keys
    with _blocked_lock:
        _blocked_keys = set()
    _log_debug("Key blacklist reset.")


# ═══════════════════════════════════════════════════════════════════
#  SRT PARSING
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
        # FIX: Permanently remove ASS formatting/alignment tags (e.g., {\an8}, {\pos...})
        text = re.sub(r'\{.*?\}', '', text)
        
        text = text.strip()
        if text:
            blocks.append((bid.strip(), timing.strip(), text))

    _log_debug(f"parse_srt: {len(blocks)} blocks parsed")
    return blocks


# ═══════════════════════════════════════════════════════════════════
#  UNIVERSAL PROFESSIONAL PROMPT
# ═══════════════════════════════════════════════════════════════════
def _build_prompt(target_lang, num_texts):
    """
    Builds the translation prompt adapted for the target language.
    Universal — works for any language.
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
                '- "But" (conjunction) → "Dar" — NEVER leave "But" untranslated at sentence start\n'
                '- Convert imperial units to metric for Romanian audiences:\n'
                '  "square feet" → "metri pătrați" (1 sq ft ≈ 0.093 m²)\n'
                '  "feet" → "metri" (1 ft ≈ 0.30 m)\n'
                '  "miles" → "kilometri" (1 milă ≈ 1.6 km)\n'
                '  "pounds" → "kilograme" (1 lb ≈ 0.45 kg)\n'
                '  "Fahrenheit" → "Celsius" (formula: (F−32)×5/9)\n'
                '- Romanian number format: use "." for thousands — 130,000 → 130.000\n'
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
- Example: [{{"index": "1", "text": "Hello"}}, {{"index": "2", "text": "How are you?"}}]
- You MUST return exactly {num_texts} items in the array.

**MULTILINGUAL SOURCE HANDLING:**
- The source text may be in ANY language (English, Arabic, French, etc.).
- Identify the source language and translate accurately into {lang_name}.
- Preserve the original meaning 100%.
- EVERY text item MUST be translated into {lang_name}. Leaving ANY text in the source language is STRICTLY FORBIDDEN.
- Even if you are unsure, always produce a {lang_name} translation. NEVER copy the source text as the output.

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

**CRITICAL ANTI-UNTRANSLATED RULE:**
- ALL text items in the batch MUST be translated into {lang_name}. No exceptions.
- It is ABSOLUTELY FORBIDDEN to output the original source text unchanged as the translated value.
- EVERY sentence, phrase, and expression must appear in {lang_name} in the output.
- Only proper names, internationally recognized abbreviations, and loan words already used in {lang_name} may remain in their original form.
- When in doubt: TRANSLATE. Never leave source language text in the output.
- BAD EXAMPLE: orig: "But fortunately," → bad: "But fortunately," or "But din fericire,"
- GOOD EXAMPLE: orig: "But fortunately," → good: "Dar din fericire,"

**CRITICAL ANTI-SHIFTING RULES (READ CAREFULLY):**
- You are translating TIMED subtitle blocks. 
- Text from input index X MUST remain in output index X. NEVER move words to neighboring indices!
- If a single sentence is broken across two indices, translate the broken parts EXACTLY where they are. Do NOT combine them.
- BAD EXAMPLE (Shifting text - DO NOT DO THIS):
  Input: [{{"index": "5", "text": "I am a man,"}}, {{"index": "6", "text": "a very good man."}}]
  Bad Output: [{{"index": "5", "text": "I am a man, a very good man."}}, {{"index": "6", "text": "(nothing)"}}]
- GOOD EXAMPLE (Strict 1-to-1 Mapping):
  Good Output: [{{"index": "5", "text": "I am a man,"}}, {{"index": "6", "text": "a very good man."}}]

**CONTENT RULES:**
- MULTI-LINE BLOCKS: Translate ALL lines of a block as ONE unit under the SAME index.
- Translate ALL content including aggressive language — do NOT censor or block.
- Preserve names, places, and technical terms as-is.
- If source text is "(nothing)" or empty, output "(nothing)" exactly.
"""
    return prompt


# ═══════════════════════════════════════════════════════════════════
#  GEMINI API CALL (Adapted for Kodi, emulates google.genai)
# ═══════════════════════════════════════════════════════════════════
def translate_gemini(texts_dict, target_lang, api_key, model_name, timeout=API_TIMEOUT, thinking_level=None, temperature=None):
    # 3.0 models require the v1alpha endpoint. The rest work on v1beta.
    api_version = "v1alpha" if "gemini-3" in model_name else "v1beta"
    url = (
        f"https://generativelanguage.googleapis.com/{api_version}/models/"
        f"{model_name}:generateContent?key={api_key}"
    )

    prompt = _build_prompt(target_lang, len(texts_dict))
    json_input = [{"index": str(k), "text": v} for k, v in texts_dict.items()]

    generation_config = {
        "temperature": temperature if temperature is not None else 0.9,
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
    }

    # If the model is Gemini 3 and we have thinking_level, add it to generationConfig
    is_gemini_3 = any(ver in model_name for ver in ["3.0", "3.5", "gemini-3"])
    if is_gemini_3 and thinking_level:
        generation_config["thinkingConfig"] = {
            "thinkingLevel": thinking_level.upper()
        }

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt + "\n\n" + json.dumps(json_input, ensure_ascii=False)
            }]
        }],
        "generationConfig": generation_config,
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
        ],
    }

    _log_debug(f"API call: model={model_name} ({api_version}), key=...{api_key[-4:]}, "
               f"{len(texts_dict)} texts, language={target_lang}, timeout={timeout}s")

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

    # CLEAR ERROR DISPLAY IN LOG (If Google gives an HTTP code, like 400, 404, 500)
    if result_container['code'] > 0: 
        _log_error(f"HTTP Error {result_container['code']} from API: {result_container['error']}")
        return None, result_container['code']
    
    # CLEAR ERROR DISPLAY IN LOG (If timeout occurred or connection dropped)
    if not result_container['response']: 
        if result_container['error']:
            _log_error(f"Connection/Timeout Error: {result_container['error']}")
        else:
            _log_error("Timeout expired or response was completely empty.")
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

    # CRITICAL FIX FOR "Error 0": New models sometimes add "```json" to the response.
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
#  INTERJECTION CLEANUP FROM SOURCE AND TRANSLATED TEXT
# ═══════════════════════════════════════════════════════════════════
# 1. Interjections for SOURCE text (English)
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

# 2. Interjections for TRANSLATED text (Romanian + English)
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
    """Removes interjections. Uses the correct dictionary based on the stage."""
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
        
        # ── BEGINNING ──
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

        # ── END ──
        for _ in range(3):
            match = re.search(r'^(.+?)\s*[,;:\s]+\s*(' + _WORD_PAT + r')\s*([,;:.!?…]*)\s*$', cleaned, re.IGNORECASE | re.UNICODE)
            if match:
                main  = match.group(1).strip()
                word  = match.group(2).strip()
                trail = match.group(3).strip()
                if word.lower() in current_dict and main:
                    # FIX: Preserve EXACT original punctuation (?, !, ending comma, or ellipses).
                    # We no longer force adding a period.
                    cleaned = main + trail
                else:
                    break
            else:
                break

        # ── MIDDLE ──
        _inj_alt = '|'.join(re.escape(i) for i in sorted(current_dict, key=len, reverse=True))
        
        # NEW: Interjection followed by ellipses ("E, ăă..." -> "E...")
        cleaned = re.sub(
            r',\s*(?:' + _inj_alt + r')\s*([.!?…]+)',
            r'\1',
            cleaned, flags=re.IGNORECASE | re.UNICODE
        )
        
        cleaned = re.sub(r',\s*(?:' + _inj_alt + r')\s*,', ', ', cleaned, flags=re.IGNORECASE | re.UNICODE)
        
        if is_translated:
            # Remove the filler "gen" (translation of "like")
            cleaned = re.sub(r',\s*gen\s*,', ', ', cleaned, flags=re.IGNORECASE | re.UNICODE)
            cleaned = re.sub(r',\s*gen\s*([.!?…]+)$', r'\1', cleaned, flags=re.IGNORECASE | re.UNICODE)

        # Clean any remaining double spaces or commas
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        cleaned = re.sub(r',\s*,', ',', cleaned).strip()

        # ── AFTER PERIOD IN THE MIDDLE (e.g. "Thanks. Uh, I really don't" -> "Thanks. I really don't") ──
        # Remove the interjection if it's after . ! ?
        cleaned = re.sub(
            r'([.!?])\s+(?:' + _inj_alt + r')\s*[,\s]+\s*(.)',
            lambda m: m.group(1) + ' ' + m.group(2).upper(),
            cleaned, flags=re.IGNORECASE | re.UNICODE
        )
        
        # NEW: Remove the interjection if it's trapped EXACTLY BETWEEN PERIODS ("Yes. Mm-hmm. Thanks.")
        # Turns ". Mm-hmm." into a simple period "."
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
    # FIX: We allow the script to return an EMPTY STRING (meaning it completely deletes the line)
    # if the line was just an interjection, instead of returning the original text.
    return result.strip()


# ═══════════════════════════════════════════════════════════════════
#  HEARING IMPAIRED (HI) CLEANUP
# ═══════════════════════════════════════════════════════════════════
def _clean_hi_text(text):
    """
    Removes hearing impaired content from the SRT text:
    - Text in square brackets (even multi-line): [DOOR SLAMS] → removed
    - UPPERCASE speaker prefix: MARIA: text → text
    """
    if not text or not text.strip():
        return text

    # FIX: Delete brackets even if the text is split across 2 lines (using re.DOTALL)
    text = re.sub(r'\[.*?\]', '', text, flags=re.DOTALL)

    lines = text.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue

        # Remove UPPERCASE_SPEAKER prefix:
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
    """Converts -- into ... or removes it at the start of a line."""
    if not text: return text
    # Remove double-dash from the beginning of the line (Ex: '--She thought' -> 'She thought')
    text = re.sub(r'^--+\s*', '', text, flags=re.MULTILINE)
    # Turn the remaining -- into ...
    text = re.sub(r'--+', '...', text)
    return text


# ═══════════════════════════════════════════════════════════════════
#  REBALANCING / SPLITTING SUBTITLE LINES
# ═══════════════════════════════════════════════════════════════════
SINGLE_LINE_MAX     = 42
REBALANCE_THRESHOLD = 18

def _rebalance_lines(text):
    """
    Translated text post-processing:
    1) If it has 3 or more lines → force merge to max 2.
    2) Single line > 43 visible chars → split into two balanced lines.
    3) Two unbalanced lines or one line > 43 chars → rebalance.
    Skips dialogue blocks (with '-').
    Keeps tags (<i>, </i>, ♪) intact.
    """
    if not text or not text.strip():
        return text

    # Clean empty lines and form a clear list
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # --- 3 LINES BUG FIX ---
    if len(lines) > 2:
        new_lines = []
        for line in lines:
            if line.startswith('-') or not new_lines:
                new_lines.append(line)
            else:
                new_lines[-1] = new_lines[-1] + " " + line
        
        while len(new_lines) > 2:
            next_line = new_lines.pop(1)
            if next_line.startswith('-'):
                next_line = next_line[1:].strip()
            new_lines[0] = new_lines[0] + " " + next_line

        text = '\n'.join(new_lines)
        lines = new_lines
    # -------------------------

    # Extract HTML just to correctly read the dash and see if there are 2 different speakers
    c1_clean = re.sub(r'<[^>]+>', '', lines[0] if len(lines) > 0 else '').strip()
    c2_clean = re.sub(r'<[^>]+>', '', lines[1] if len(lines) > 1 else '').strip()

    is_two_speakers = len(lines) == 2 and c2_clean.startswith('-')

    def visible(t):
        """Visible length, just without HTML tags. The ♪ symbol remains for true width calculation."""
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

    #  Path 1: SINGLE LINE TOO LONG
    if len(lines) == 1 and not is_two_speakers:
        vis = visible(text)
        if len(vis) > SINGLE_LINE_MAX:
            result = _find_smart_split(text, vis)
            if result:
                return f"{result[0]}\n{result[1]}"

    #  Path 2: TWO LINES
    elif len(lines) == 2 and not is_two_speakers:
        c1 = visible(lines[0])
        c2 = visible(lines[1])

        # Short lines merge (Single sentence merge)
        if len(c1) + 1 + len(c2) <= SINGLE_LINE_MAX:
            merged = f"{lines[0].strip()} {lines[1].strip()}"
            merged = re.sub(r'</i>\s*<i>', ' ', merged)
            return merged

        # Rebalancing
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
    """Fixes dialog line formatting and removes orphan dashes."""
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
        
        # Valid dialog: Line 2 has a dash, force dash on Line 1 too
        if l2_clean.startswith('-') and l1_clean and not l1_clean.startswith('-'):
            m_html = re.match(r'^(<[^>]+>)*', lines[0])
            idx = len(m_html.group(0)) if m_html else 0
            lines[0] = lines[0][:idx] + '- ' + lines[0][idx:]
            
        # FALSE DIALOG: Line 1 has a dash, but Line 2 does NOT!
        # Completely remove the orphan dash from the first line.
        elif l1_clean.startswith('-') and not l2_clean.startswith('-'):
            lines[0] = re.sub(r'^(<[^>]+>)*-\s*', r'\1', lines[0])

    # FALSE DIALOG: Only one line left in the block, but it has a dash. We remove it.
    if len(lines) == 1:
        lines[0] = re.sub(r'^(<[^>]+>)*-\s*', r'\1', lines[0])

    return '\n'.join(lines)


def _split_inline_dialogue(text):
    """
    Forces split onto 2 lines if 2 speakers are on the same line.
    Ex: '...fruits? -Cheese.' -> '...fruits?\n-Cheese.'
    """
    if not text: return text
    # Look for punctuation (. ! ? ") followed by a space and a dialog dash
    text = re.sub(r'([.!?"])\s+(-\s*\S)', r'\1\n\2', text)
    return text

def _restore_formatting(original, translated):
    """Restores and balances forgotten or unbalanced <i> and ♪ tags."""
    if not translated: return translated
    orig_clean = original.strip()
    tr_clean = translated.strip()

    # 1. Recover musical notes COMPLETELY forgotten by Gemini
    if '♪' in orig_clean and '♪' not in tr_clean:
        if orig_clean.startswith('♪') and orig_clean.endswith('♪'):
            tr_clean = f"♪ {tr_clean} ♪"
        elif orig_clean.startswith('♪'):
            tr_clean = f"♪ {tr_clean}"
        elif orig_clean.endswith('♪'):
            tr_clean = f"{tr_clean} ♪"

    # 2. Recover COMPLETELY forgotten italic
    if orig_clean.startswith('<i>') and orig_clean.endswith('</i>') and not (tr_clean.startswith('<i>') and tr_clean.endswith('</i>')):
        # Remove any stray italic fragments inside and wrap everything
        tr_clean = re.sub(r'</?i>', '', tr_clean)
        tr_clean = f"<i>{tr_clean}</i>"

    # 3. Balance orphan quotes
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

    # 4. SMART LINE BALANCING (Musical Notes and Italics)
    lines = tr_clean.split('\n')
    
    # Check if the block is a dialog (2 lines, both with a dash at the start, excluding tags)
    def is_dialog_line(l):
        return l.lstrip('<i>♪ ').startswith('-')
        
    is_dialogue = len(lines) == 2 and is_dialog_line(lines[0]) and is_dialog_line(lines[1])
    
    if is_dialogue:
        # Balance each speaker independently
        new_lines = []
        for line in lines:
            prefix = ""
            content = line.strip()
            
            # Extract prefixes so we don't mess up dashes
            m = re.match(r'^(?:<i>|♪|\s)*-\s*', content)
            if m:
                prefix_raw = m.group(0)
                content = content[len(prefix_raw):].strip()
                prefix = "- "
            elif content.startswith('-'):
                prefix = "- "
                content = content[1:].strip()
            
            # Balance ♪
            if content.startswith('♪') and not content.endswith('♪'): content += " ♪"
            elif content.endswith('♪') and not content.startswith('♪'): content = "♪ " + content
            
            # Balance <i>
            if content.startswith('<i>') and not content.endswith('</i>'): content += "</i>"
            elif content.endswith('</i>') and not content.startswith('<i>'): content = "<i>" + content
            
            # Put the dash prefix back inside the tags for aesthetics
            if prefix:
                if content.startswith('♪') or content.startswith('<i>'):
                    content = re.sub(r'^(♪\s*|<i>\s*)+', r'\g<0>- ', content)
                else:
                    content = "- " + content
                    
            new_lines.append(content)
        tr_clean = '\n'.join(new_lines)
        
    else:
        # Normal block (a single sentence spread over 1 or 2 lines)
        content = tr_clean.strip()
        
        # Identify if it has a dash at the start
        has_dash = False
        if content.lstrip('<i>♪ ').startswith('-'):
            has_dash = True
            content = content.replace('- ', '', 1).strip()
            
        # Balance ♪ at the BLOCK level
        if content.startswith('♪') and not content.endswith('♪'): content += " ♪"
        elif content.endswith('♪') and not content.startswith('♪'): content = "♪ " + content
        
        # Balance <i> at the BLOCK level
        if content.startswith('<i>') and not content.endswith('</i>'): content += "</i>"
        elif content.endswith('</i>') and not content.startswith('<i>'): content = "<i>" + content
        
        # Restore the dash (if it was just one speaker with a sentence on 2 lines)
        if has_dash:
            if content.startswith('♪') or content.startswith('<i>'):
                content = re.sub(r'^(♪\s*|<i>\s*)+', r'\g<0>- ', content)
            else:
                content = "- " + content
                
        tr_clean = content

    # Final cleanups (correct tag arrangement: always ♪ in front of <i>)
    tr_clean = tr_clean.replace('<i>♪', '♪ <i>').replace('♪</i>', '</i> ♪')
    tr_clean = re.sub(r'\s+♪$', ' ♪', tr_clean)
    tr_clean = re.sub(r'^♪\s+', '♪ ', tr_clean)
    tr_clean = re.sub(r'♪\s+♪', '♪', tr_clean) # Remove duplicates
    
    return tr_clean


# ═══════════════════════════════════════════════════════════════════
#  POST-PROCESS TRANSLATED TEXT (full pipeline)
# ═══════════════════════════════════════════════════════════════════
def _post_process_text(text):
    """
    Applies to the translated text:
    1. Fix inline dialog
    2. Fix -- → ...
    3. Rebalance/split lines
    4. Fix dialog format
    5. Final grammatical cleanups
    """
    if not text: return text
    text = _split_inline_dialogue(text)
    text = _fix_double_dash(text)
    
    # Rebalancing can merge 2 short lines. That's why it runs BEFORE dialog formatting.
    text = _rebalance_lines(text)
    
    # Now that we know exactly how many lines are left, we clean up orphan dashes
    text = _fix_dialog_format(text)
    
    # FINAL FIX: Turns 4 dots (or more) into 3 dots ("...." -> "...")
    text = re.sub(r'\.{4,}', '...', text)
    
    # FINAL FIX: Removes double dash translated by Gemini ("- - No" -> "- No")
    text = re.sub(r'^-\s*-\s*', '- ', text, flags=re.MULTILINE)
    
    return text

# ═══════════════════════════════════════════════════════════════════
#  TRANSLATES ONE BATCH WITH INDEX AND MERGING PROTECTIONS
# ═══════════════════════════════════════════════════════════════════
def translate_one_batch(batch, target_lang, all_keys, batch_index=0, thinking_level=None, temperature=None):
    to_translate = {}
    cleaned_count = 0

    for b_id, _timing, text in batch:
        clean = re.sub(r'<[^>]*>', '', text).strip()
        if not clean: clean = text.strip()
        original = clean
        
        # Pre-translation processing
        clean = _clean_hi_text(clean)
        clean = _split_inline_dialogue(clean)
        clean = _fix_dialog_format(clean)
        clean = _fix_double_dash(clean)
        clean = _clean_interjections(clean, is_translated=False)

        # ---- ADD THESE TWO LINES HERE ----
        # Transform lines into empty text if they contain STRICTLY musical notes or ellipses
        if re.fullmatch(r'[♪\s]+', clean) or re.fullmatch(r'[.\s]+', clean):
            clean = ""
        # ----------------------------------------

        if clean != original:
            cleaned_count += 1
            _log_debug(f"  Pre-cleaned [{b_id}]: '{original}' → '{clean}'")

        if not clean or clean.strip() == '': 
            clean = '(nothing)'
            
        to_translate[b_id] = clean

    if cleaned_count > 0:
        _log_info(f"Pre-cleaned {cleaned_count} texts before translation.")

    if batch_index == 0:
        models_to_use = [FIRST_BATCH_MODEL]
        batch_timeout = FIRST_BATCH_TIMEOUT
        _log_info(f"First batch: model={FIRST_BATCH_MODEL}, timeout={FIRST_BATCH_TIMEOUT}s")
    else:
        models_to_use = MODEL_PREFERAT
        batch_timeout = API_TIMEOUT

    _but_retry_count = 0
    for key_idx, current_key in enumerate(all_keys):
        if _is_blocked(current_key): continue
        _log_debug(f"Trying key {key_idx+1}/{len(all_keys)}: ...{current_key[-4:]}")

        for model_idx, current_model in enumerate(models_to_use):
            result, err_code = translate_gemini(
                to_translate, target_lang, current_key,
                current_model, timeout=batch_timeout,
                thinking_level=thinking_level,
                temperature=temperature
            )

            if err_code == -1:
                _log_info("Player stopped, aborting batch.")
                return None, "ABORT"

            if result is not None:
                sent_count = len(to_translate)
                
                # PROTECTION 1: Index Integrity Validation
                sent_indices = set(str(bid) for bid in to_translate.keys())
                received_indices = set(str(item) for item in result.keys())

                diff_missing = sent_indices - received_indices
                diff_extra = received_indices - sent_indices

                if diff_missing:
                    _log_warn(f"MISSING indices: {diff_missing}. RETRYING.")
                    continue
                elif diff_extra:
                    _log_warn(f"Extra indices detected and ignored: {diff_extra}")
                    for extra_id in diff_extra:
                        result.pop(extra_id, None)

                # PROTECTION 2: EXACT logic from the Windows script
                validation_failed = False
                for b_id, orig_text in to_translate.items():
                    trans_text = result.get(str(b_id), "").strip()
                    orig_is_nothing = orig_text.lower() == "(nothing)"
                    trans_is_nothing = trans_text.lower() in ["(nothing)", "(nimic)", "[nothing]", ""] # I ADDED EMPTY STRING "" HERE TOO

                    # Check 1: False (nothing) - INTELLIGENT
                    if not orig_is_nothing and trans_is_nothing:
                        # If the original is under 10 chars (probably an exclamation/name), allow it to be empty
                        if len(orig_text.strip()) > 10:
                            _log_warn(f"FALSE (nothing) at index {b_id}. Orig: '{orig_text[:20]}'. RETRY.")
                            validation_failed = True
                            break
                        else:
                            _log_debug(f"FALSE (nothing) tolerated at index {b_id} (Short text: '{orig_text}')")
                    
                    # Check 2: Merge Suspected
                    if not orig_is_nothing and not trans_is_nothing:
                        orig_len = len(orig_text)
                        trans_len = len(trans_text)
                        
                        if orig_len >= 15:
                            ratio = trans_len / orig_len if orig_len > 0 else 0
                            # If the translation is >2.2x longer and has over 70 chars
                            if ratio > 2.2 and trans_len > 70:
                                orig_newlines = orig_text.count('\n')
                                trans_newlines = trans_text.count('\n')
                                # If it also added new lines, it's clearly a merge
                                if trans_newlines > orig_newlines:
                                    _log_warn(f"MERGE SUSPECTED at index {b_id}. "
                                              f"Orig: {orig_len} chars -> Trans: {trans_len} chars. RETRY.")
                                    validation_failed = True
                                    break

                    # Check 3: Untranslated text detection (source == translation)
                    if not orig_is_nothing and not trans_is_nothing:
                        orig_stripped = orig_text.strip()
                        trans_stripped = trans_text.strip()
                        # If translation is identical to source for texts longer than 20 chars, it was skipped
                        if trans_stripped == orig_stripped and len(orig_stripped) > 20:
                            _log_warn(f"UNTRANSLATED text at index {b_id}: '{orig_text[:40]}'. RETRY.")
                            validation_failed = True
                            break

# Check 4 (RO only): "But" la inceput de fraza → max 2 retry-uri
                    if target_lang == 'ro' and not orig_is_nothing and not trans_is_nothing:
                        clean_start = re.sub(r'^[\s\-♪]+', '', trans_text)
                        clean_start = re.sub(r'^(?:<[^>]+>\s*)+', '', clean_start)
                        if re.match(r'^But\b', clean_start, re.IGNORECASE):
                            if _but_retry_count < 2:
                                _but_retry_count += 1
                                _log_warn(f"'But' in RO [{b_id}]: '{trans_text[:40]}'. Retry {_but_retry_count}/2.")
                                validation_failed = True
                                break
                            else:
                                _log_warn(f"'But' la [{b_id}] dupa 2 retry-uri — lasam sa treaca.")

                if validation_failed:
                    continue

                _log_debug(f"Translation fully validated: {len(result)}/{sent_count}")
                chunk = ""
                for b_id, timing, original_srt_text in batch:
                    sent_text = to_translate.get(b_id, "")

                    if sent_text == "(nothing)":
                        tr = ""
                    else:
                        tr = result.get(str(b_id), "")
                        
                        # Prevents Gemini from adding multiple empty lines that break the SRT file
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
                _log_warn(f"429 (quota) on ...{current_key[-4:]}")
                time.sleep(PAUZA_DUPA_EROARE)
                break
            elif err_code in (503, 504):
                _log_debug(f"  {err_code} on {current_model}, different model")
                time.sleep(PAUZA_DUPA_EROARE)
                continue
            elif err_code == 404:
                _log_debug(f"  404 on {current_model}, different model")
                continue
            else:
                _log_debug(f"  Error {err_code}, different model")
                time.sleep(PAUZA_DUPA_EROARE)
                continue

    _log_error("All keys/models exhausted!")
    return None, ""


# ═══════════════════════════════════════════════════════════════════
#  BUILD VALID SRT
# ═══════════════════════════════════════════════════════════════════
def _build_srt_from_chunks(all_chunks):
    full_srt = ""
    counter = 1

    for chunk_idx, chunk in enumerate(all_chunks):
        entries = parse_srt(chunk)
        _log_debug(f"Chunk {chunk_idx+1}: {len(entries)} entries")
        for _bid, timing, text in entries:
            full_srt += f"{counter}\r\n{timing}\r\n{text}\r\n\r\n"
            counter += 1

    _log_debug(f"Total SRT: {counter-1} blocks, {len(full_srt)} characters")
    return full_srt, counter - 1


# ═══════════════════════════════════════════════════════════════════
#  ADJUST DURATIONS (V1.0 Windows logic adapted for standard Kodi library)
# ═══════════════════════════════════════════════════════════════════
from datetime import timedelta

def parse_time(time_str):
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))

def format_time(td):
    total_seconds = int(td.total_seconds())
    ms = int(td.microseconds / 1000)
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def adjust_srt_durations(srt_content):
    # Normalize newlines
    srt_content = srt_content.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not srt_content:
         return ""
         
    # Regex to split blocks
    pattern = re.compile(
        r'(\d+)\n'
        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\n'
        r'(.*?)(?=\n\n|\Z)',
        re.DOTALL
    )
    
    parsed_blocks = []
    for match in pattern.finditer(srt_content + '\n\n'):
        bid = int(match.group(1))
        start_str = match.group(2)
        end_str = match.group(3)
        text = match.group(4).strip()
        
        parsed_blocks.append({
            'index': bid,
            'start': parse_time(start_str),
            'end': parse_time(end_str),
            'content': text
        })
        
    if not parsed_blocks:
        return srt_content

    READING_SPEED = 14
    MIN_DUR_MS = 1000
    MAX_DUR_MS = 10000
    
    for i, sub in enumerate(parsed_blocks):
        original_dur = int((sub['end'] - sub['start']).total_seconds() * 1000)
        clean_text = sub['content'].strip().lower()
        chars = 0 if clean_text == "(nothing)" else len(re.sub(r'<.*?>|♪|\n', '', sub['content']))
        ideal_dur = max(MIN_DUR_MS, int((chars / READING_SPEED) * 1000))
        
        if original_dur < ideal_dur:
            new_end = sub['start'] + timedelta(milliseconds=ideal_dur)
            if i < len(parsed_blocks) - 1 and parsed_blocks[i + 1]['start'] > sub['start'] and new_end >= parsed_blocks[i + 1]['start']:
                new_end = parsed_blocks[i + 1]['start'] - timedelta(milliseconds=41)
            sub['end'] = min(new_end, sub['start'] + timedelta(milliseconds=MAX_DUR_MS))
            
    rebuilt_srt = ""
    for sub in parsed_blocks:
        start_str = format_time(sub['start'])
        end_str = format_time(sub['end'])
        rebuilt_srt += f"{sub['index']}\r\n{start_str} --> {end_str}\r\n{sub['content']}\r\n\n"
        
    return rebuilt_srt

# ═══════════════════════════════════════════════════════════════════
#  WRITE SRT + ACTIVATE
# ═══════════════════════════════════════════════════════════════════
def _write_and_activate(output_path, all_chunks, target_lang="ro", activate=True, is_final=False):
    # CRITICAL KODI CRASH PROTECTION: Do nothing if the movie stopped
    if not _player_has_media():
        return False

    srt_content, total_blocks = _build_srt_from_chunks(all_chunks)

    if total_blocks == 0:
        _log_error("Built SRT is empty!")
        return False

    # NEW: If it's the fully translated final file, apply duration adjustments
    if is_final:
        _log_info("--- Adjusting subtitle durations (final) ---")
        try:
            srt_content = adjust_srt_durations(srt_content)
            _log_info("✓ Durations adjusted successfully.")
        except Exception as e:
            _log_error(f"Error adjusting durations: {e}")

    raw_bytes = b'\xef\xbb\xbf' + srt_content.encode('utf-8')

    try:
        fh = xbmcvfs.File(output_path, 'wb')
        fh.write(raw_bytes)
        fh.close()
    except Exception as e:
        _log_error(f"VFS SRT write error: {e}")
        try:
            with open(output_path, 'wb') as f:
                f.write(raw_bytes)
        except Exception as e2:
            _log_error(f"Fallback write failed: {e2}")
            return False

    try:
        size = os.path.getsize(output_path)
        _log_info(f"SRT written OK ({size} bytes, {total_blocks} blocks)")
    except Exception: pass

    # WE ONLY ACTIVATE IN PLAYER IF ACTIVATE=TRUE (avoids Libass crash)
    if activate:
        try:
            # Passive check before interacting with Kodi C++
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
                _log_info("Translated subtitle activated in player.")
        except Exception as e:
            _log_debug(f"Subtitle was not activated (player stopped in the meantime): {e}")

    return True


# ═══════════════════════════════════════════════════════════════════
#  CREATE BATCHES
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
#  GENERATE TRANSLATED FILE NAME
# ═══════════════════════════════════════════════════════════════════
def _make_output_name(original_name, target_lang):
    base, ext = os.path.splitext(original_name)
    # Remove original language code if it exists (e.g. 'Movie.en' becomes 'Movie')
    base = re.sub(r'\.[a-z]{2,3}$', '', base, flags=re.IGNORECASE)
    return f"{base}.{target_lang}{ext}"


def _save_translation(output_path, output_name, sub_addon_id):
    """Copies the COMPLETE translation to 'Translated Subtitles' + updates index."""
    try:
        _addon = xbmcaddon.Addon(sub_addon_id)
        if _addon.getSetting('save_translations') != 'true':
            _log_debug("Permanent save disabled.")
            return

        profile = xbmcvfs.translatePath(
            f'special://profile/addon_data/{sub_addon_id}/')
        saved_dir = os.path.join(profile, 'Translated Subtitles')

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
                _log_error(f"Fallback save failed: {e2}")
                return

        _log_info(f"Translation saved: {output_name}")

        # ── Index with IMDB/TMDB + complete flag ───────────────────
        try:
            # Extract IDs EXACTLY as service.py does when searching
            imdb_id = xbmc.getInfoLabel("VideoPlayer.IMDBNumber") or xbmc.getInfoLabel("ListItem.Property(imdb_id)") or ""
            tmdb_id = xbmc.getInfoLabel("VideoPlayer.TMDbId") or xbmc.getInfoLabel("ListItem.Property(tmdb_id)") or xbmc.getInfoLabel("Window(10000).Property(tmdb_id)") or ""
            video_title = xbmc.getInfoLabel("VideoPlayer.TVShowTitle") or xbmc.getInfoLabel("VideoPlayer.OriginalTitle") or xbmc.getInfoLabel("VideoPlayer.Title") or ""
            video_year = xbmc.getInfoLabel("VideoPlayer.Year") or ""
            
            # Season and episode are mandatory
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

        _notify(f'[B][COLOR lime]Saved permanently: [COLOR orange]{output_name}[/COLOR][/B]', duration=3000)

    except Exception as e:
        _log_error(f"Permanent save error: {e}")


# ═══════════════════════════════════════════════════════════════════
#  MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════════
def run_translation(sub_addon_id, mode="fast"):
    _reset_blocked()

    try:
        _addon = xbmcaddon.Addon(sub_addon_id)
    except Exception as e:
        _log_error(f"Cannot access addon {sub_addon_id}: {e}")
        return

    # --- DEFINE ENGINES AND BATCH SIZES DYNAMICALLY ---
    global MODEL_PREFERAT, FIRST_BATCH_MODEL, FIRST_BATCH_TIMEOUT
    global FIRST_BATCH_SIZE, NEXT_BATCH_SIZE

    # Read the chosen index from Kodi settings
    try:
        robot_idx = _addon.getSettingInt('robot_selectat')
    except Exception:
        robot_idx = 0

    try:
        # Read the thinking level setting from Kodi
        thinking_idx = _addon.getSettingInt('gemini_thinking_level')
        thinking_levels = ["minimal", "low", "medium", "high"]
        selected_thinking_level = thinking_levels[thinking_idx] if 0 <= thinking_idx < len(thinking_levels) else "medium"
    except Exception:
        selected_thinking_level = "medium"

    try:
        temperature = _addon.getSettingInt('gemini_temperature') * 0.1
    except:
        temperature = 1.0

    if robot_idx == 1:
        # --- OPTION: Gemini Slow (Flash 3 Preview) ---
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
            
        _log_info(f"SLOW mode (Flash 3 Preview) activated: First batch={FIRST_BATCH_SIZE}, Next={NEXT_BATCH_SIZE}, Temperature={temperature}.")

    elif robot_idx == 2 or mode == "slow":
        # --- OPTION: Gemini Slow (Flash 3.5) ---
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
            
        _log_info(f"SLOW mode (Flash 3.5) activated: First batch={FIRST_BATCH_SIZE}, Next={NEXT_BATCH_SIZE}, Temperature={temperature}.")

    else:
        # --- OPTION: Gemini Fast (Lite) (robot_idx == 0 or default) ---
        MODEL_PREFERAT = [
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
        ]
        FIRST_BATCH_MODEL = "gemini-2.5-flash-lite"
        FIRST_BATCH_TIMEOUT = 300
        FIRST_BATCH_SIZE = 100
        NEXT_BATCH_SIZE = 300
        _log_info("FAST mode activated: Lite models (2.5 fallback 3.1). Batches: 100 / 300.")
    # ------------------------------------------------

    _init_debug(_addon)

    if _addon.getSetting('robot_activat') != 'true':
        _log_info("Disabled from settings.")
        return

    _log_debug("═══ START TRANSLATION ═══")

# ── Collect API keys ───────────────────────────────────────
    all_keys = []
    for i in range(1, 6):
        k = _addon.getSetting(f'api_key_{i}')
        if k and k.strip():
            all_keys.append(k.strip())
            _log_debug(f"Key {i}: ...{k.strip()[-4:]} ({len(k.strip())} char)")

    all_keys = list(dict.fromkeys(all_keys))

    # 1. MISSING KEYS PROTECTION: If there are absolutely no keys entered
    if not all_keys:
        xbmcgui.Dialog().ok(
            "SubStudio - Error",
            "No API key configured!\n\n"
            "1. Go to aistudio.google.com\n"
            "2. Create a free API key\n"
            "3. Add it in Settings → Gemini API Key"
        )
        return

    # --- NEW: ONLINE VALIDATION FOR GEMINI KEYS ---
    def _validate_gemini_key(key):
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5): return True
        except urllib.error.HTTPError as e:
            if e.code == 400: return False # 400 = API Key Invalid
        except Exception: return True # Network error, let it pass
        return True

    # Only if it passed the check above (meaning it HAS keys), validate them online
    valid_keys = [k for k in all_keys if _validate_gemini_key(k)]
    
    # 2. INVALID KEYS PROTECTION: Keys were entered, but they are wrong/expired
    if not valid_keys:
        xbmcgui.Dialog().notification("Gemini Robot", "The entered API keys are INVALID!", xbmcgui.NOTIFICATION_ERROR, 5000)
        return
        
    all_keys = valid_keys
    # ---------------------------------------------

    masked = [f"...{k[-4:]}" for k in all_keys]
    _log_info(f"{len(all_keys)} API keys: {masked}")

    # ── Target Language ──────────────────────────────────────────────
    langs = ["ro", "en", "es", "fr", "de", "it", "hu", "pt", "ru", "tr",
             "bg", "el", "pl", "cs", "nl"]
    try:
        lang_idx = _addon.getSettingInt('subs_languages')
        target_lang = langs[lang_idx]
        _log_debug(f"Language: index={lang_idx}, code={target_lang}")
    except Exception:
        target_lang = "ro"

    # ── Auto-pause setting ────────────────────────────────────────
    # AUTO_PAUSE REMOVED — main cause for Android crash.
    # setSubtitles called while player was paused/resumed → Libass race condition.

    # ── Find source SRT file ───────────────────────────────
    profile_path = xbmcvfs.translatePath(
        f'special://profile/addon_data/{sub_addon_id}/')
    _log_debug(f"Profile path: {profile_path}")

    try:
        res = xbmcvfs.listdir(profile_path)
        files = res[1] if isinstance(res, tuple) else res
        _log_debug(f"Files: {files}")
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
        _log_warn("No SRT file found.")
        _notify('No SRT file to translate!')
        return

    original_name = srt_files[0]
    sub_path = os.path.join(profile_path, original_name)
    _log_info(f"Translating {original_name} → {target_lang}")

    # ── Read content ──────────────────────────────────────────
    try:
        fh = xbmcvfs.File(sub_path)
        content = fh.read()
        fh.close()
        _log_debug(f"File read: {len(content) if content else 0} bytes")
    except Exception as e:
        _log_error(f"Cannot read file: {e}")
        return

    if not content:
        _log_error("Empty SRT file.")
        return

    # ── SRT Parsing ──────────────────────────────────────────────
    blocks = parse_srt(content)
    if not blocks:
        _log_error("0 valid SRT blocks.")
        _notify('Invalid SRT file (0 blocks)!')
        return

    total_lines = len(blocks)
    _log_debug(f"First: ID={blocks[0][0]}, text={blocks[0][2][:50]}")
    _log_debug(f"Last: ID={blocks[-1][0]}, text={blocks[-1][2][:50]}")

    # ── Create batches ─────────────────────────────────────────
    batches = _make_batches(blocks)
    total_batches = len(batches)
    batch_info = ", ".join([str(len(b)) for b in batches])
    _log_info(f"{total_lines} lines → {total_batches} batches [{batch_info}]")

    # ── Output file ────────────────────────────────────────────
    output_name = _make_output_name(original_name, target_lang)
    output_path = os.path.join(profile_path, output_name)
    _log_info(f"Output → {output_name}")

    if xbmcvfs.exists(output_path):
        xbmcvfs.delete(output_path)

    _notify(f'[B][COLOR orange]{target_lang.upper()}[/COLOR][/B]: [B][COLOR yellow]{total_lines}[/COLOR][/B] lines, '
            f'[B][COLOR lime]{total_batches}[/COLOR][/B] batches')

    # ── Progress ─────────────────────────────────────────────────
    pDialog = xbmcgui.DialogProgressBG()
    pDialog.create(ADDON_NAME,
                   f'Translating → [B][COLOR orange]{target_lang.upper()} [COLOR lime](0/{total_batches})[/COLOR][/B]')

    # ══════════════════════════════════════════════════════════════
    #  SEQUENTIAL LOOP (protected with try/finally)
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
                _log_info("Player stopped completely, stopping translation.")
                player_stopped = True
                break

            batch_size = len(batch)
            batch_start = time.time()
            
            # --- EXACT LINE DISPLAY IN LOG ---
            if batch_size > 0:
                first_line_id = batch[0][0]
                last_line_id = batch[-1][0]
                _log_info(f"Batch {batch_idx+1}/{total_batches} ({batch_size} lines: {first_line_id} - {last_line_id})...")
            else:
                _log_info(f"Batch {batch_idx+1}/{total_batches} (0 lines)...")

            chunk = None
            model_used = ""

            for attempt in range(MAX_RETRIES):
                if not _player_has_media():
                    _log_info("Player stopped during retry, stopping.")
                    player_stopped = True
                    break

                active_keys = [k for k in all_keys if not _is_blocked(k)]
                if not active_keys:
                    _log_error("All keys blocked!")
                    _notify('All API keys are blocked!', duration=5000)
                    break

                chunk, model_used = translate_one_batch(
                    batch, target_lang, active_keys, batch_index=batch_idx,
                    thinking_level=selected_thinking_level,
                    temperature=temperature)

                # 1. CRITICAL PROTECTION: Check for ABORT FIRST, before anything else
                if model_used == "ABORT" or not _player_has_media():
                    player_stopped = True
                    break

                # 2. If translation succeeded, move to next batch
                if chunk:
                    break

                wait = PAUZA_DUPA_EROARE * (attempt + 1)
                _log_warn(f"Batch {batch_idx+1} failed, retry {attempt+1}/{MAX_RETRIES} "
                          f"(waiting {wait}s)")
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

                # NEW: Activate subtitle on screen EVERY time a batch is translated
                # This way, Kodi reloads the updated SRT file and text no longer disappears at minute 6.
                ok = _write_and_activate(output_path, all_chunks, target_lang, activate=True)

                if not first_done and ok:
                    first_done = True
                    elapsed = int(time.time() - start_time)
                    _notify(f'First [B][COLOR yellow]{batch_size}[/COLOR][/B] lines translated [B][COLOR lime]({elapsed}s)[/COLOR][/B]!')
            else:
                # INVISIBLE FALLBACK: If Gemini absolutely fails after all 10 tries,
                # we build the SRT segment, but with EMPTY text. Thus, Kodi will skip these lines 
                # and the screen will remain clean, without showing English.
                failed += 1
                fallback = ""
                for b_id, timing, text in batch:
                    # Intentionally leave the text empty. (Kodi will ignore the block during playback).
                    fallback += f"{b_id}\n{timing}\n \n\n"
                    
                all_chunks.append(fallback)
                is_last_batch = (batch_idx == total_batches - 1)
                _write_and_activate(output_path, all_chunks, target_lang,
                                    activate=not first_done or is_last_batch)
                _log_warn(f"Batch {batch_idx+1} PERMANENTLY FAILED after {MAX_RETRIES} tries. {batch_size} empty lines were written.")

            pct = int((batch_idx + 1) / total_batches * 100)
            active = len(all_keys) - len(_blocked_keys)
            elapsed = int(time.time() - start_time)

            if batch_idx + 1 < total_batches:
                avg = elapsed / (batch_idx + 1)
                remaining = int(avg * (total_batches - batch_idx - 1))
                time_str = f"~{remaining}s remaining"
            else:
                time_str = "finishing..."

            pDialog.update(pct, ADDON_NAME,
                           f'{batch_idx+1}/{total_batches} | '
                           f'Keys: {active}/{len(all_keys)} | {time_str}')

            if batch_idx < total_batches - 1:
                _log_debug(f"Pause {PAUZA_INTRE_BATCH}s...")
                for sec in range(PAUZA_INTRE_BATCH):
                    if not _player_has_media():
                        _log_info("Player stopped during pause.")
                        player_stopped = True
                        break
                    time.sleep(1)
                if player_stopped:
                    break

    except Exception as e:
        _log_error(f"CRITICAL ERROR in translation loop: {type(e).__name__}: {e}")
        _notify('Critical translation error!', duration=5000)

    finally:
        # ── ALWAYS CLOSE PROGRESS ─────────────────────────
        try:
            pDialog.close()
        except Exception:
            pass
        xbmc.sleep(300)
        try:
            pDialog.close()
        except Exception:
            pass

    # ── Check completion ──────────────────────────────────────
    all_processed = (completed + failed) >= total_batches
    fully_complete = all_processed and failed == 0

    total_time = int(time.time() - start_time)
    minutes = total_time // 60
    seconds = total_time % 60

    if completed > 0:
        # Re-write and activate with duration adjustment at the end (for everything that was translated)
        _write_and_activate(output_path, all_chunks, target_lang, activate=True, is_final=True)

        msg = f'[B][COLOR lime]Complete![/COLOR][/B] [B]{completed}/{total_batches}[/B] in [B][COLOR pink]{minutes}m{seconds}s[/COLOR][/B]'
        if failed > 0:
            msg += f' ({failed} errors)'
        if player_stopped:
            msg += ' (stopped)'

        if fully_complete:
            _save_translation(output_path, output_name, sub_addon_id)
            xbmc.sleep(3200)  # Let "Saved permanently" appear, then "Complete!"
        _notify(msg, duration=5000)
    else:
        _notify('[B][COLOR red]Translation failed completely![/COLOR][/B]', duration=5000)

    _log_info(f"FINISHED — {completed}/{total_batches} OK, "
              f"{failed} errors, {minutes}m{seconds}s. "
              f"Complete: {fully_complete}")
    _log_debug("═══ END TRANSLATION ═══")