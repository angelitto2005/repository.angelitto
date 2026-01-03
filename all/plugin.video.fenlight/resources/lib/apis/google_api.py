# -*- coding: utf-8 -*-
from caches.settings_cache import get_setting
from modules.utils import extract_json_object
# from modules.kodi_utils import logger

# GOOGLE_MODELS = ('gemini-2.5-flash-lite', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemma-3-27b-it', 'gemma-3-12b-it', 'gemma-3-1b-it', 'gemma-3-4b-it', 'gemini-3-flash-preview')

def models():
	return ('gemini-2.5-flash-lite', 'gemini-2.0-flash', 'gemini-2.5-flash', 'gemma-3-27b-it', 'gemma-3-12b-it', 'gemma-3-1b-it', 'gemma-3-4b-it', 'gemini-3-flash-preview')

def similar_prompt():
	return '''
You are a movie/TV recommendation engine.

You will be given:
- MEDIA_TYPE: either "Movie" or "Show"
- TITLE: the title of a movie or TV series
- YEAR: release or first-air year
- PLOT: plot summary
- GENRES: comma-separated list of genres or tags
- KEYWORDS: comma-separated list of keywords

CONTEXT (DO NOT change these values):

MEDIA_TYPE: MEDIA_TYPE_HERE
TITLE: TITLE_HERE
YEAR: YEAR_HERE
PLOT: PLOT_HERE
GENRES: GENRES_HERE
KEYWORDS: KEYWORDS_HERE

INTERPRETATION RULES:

- If MEDIA_TYPE is "Movie":
	The title is a movie.
	You MUST recommend ONLY movies (films, streaming films, anime films).
	Do NOT recommend any TV series or episodes.

- If MEDIA_TYPE is "Show":
	The title is a TV series / mini-series.
	You MUST recommend ONLY TV series / mini-series.
	Do NOT recommend any standalone movies or episodes.

RECOMMENDATION GOAL:

Recommend works with similar plot, themes, atmosphere, or tone to TITLE,
using PLOT and GENRES and KEYWORDS to guide you.

HARD CONSTRAINTS:

- Return EXACTLY LIMIT recommendations. No more, no fewer.
- Every recommendation MUST match MEDIA_TYPE:
	If MEDIA_TYPE is "Movie", every item MUST have "type": "Movie".
	If MEDIA_TYPE is "Show", every item MUST have "type": "Show".

OUTPUT FORMAT (STRICT):

Respond ONLY with one JSON object, in this shape:

{
  "recommendations": [
	{
	  "title": "Title 1",
	  "year": 2000,
	  "type": "Movie"  // or "Show"
	}
  ]
}

Field rules:

- "title": the main English title of the work, if available.
- "year": a single 4-digit year (release year for movies, first-air year for TV series).
		 Use null if you truly don't know.
- "type": MUST ALWAYS be exactly equal to MEDIA_TYPE ("Movie" or "Show").

Do NOT add any other top-level fields.
Do NOT include any text outside the single JSON object.
'''.strip()

def similar_parse(data):
	candidates = data.get('candidates') or []
	if not candidates: return {}
	parts = (candidates[0].get('content') or {}).get('parts') or []
	content = ''.join(part.get('text', '') for part in parts).strip()
	if not content: return {}
	content = extract_json_object(content)
	return content

def make_similar_prompt(media_type, meta, limit):
	meta_get = meta.get
	title, year = meta_get('title').strip(), meta_get('year', '')
	plot, genre = meta_get('plot', '').strip(), ','.join([i for i in meta_get('genre') if i]) if meta_get('genre') else 'unknown'
	keywords = ','.join([i['name'] for i in meta_get('keywords', {}).get('keywords')]) if meta_get('keywords', {}).get('keywords') else ''
	prompt = similar_prompt()
	prompt = prompt.replace('MEDIA_TYPE_HERE', media_type).replace('TITLE_HERE', title).replace('YEAR_HERE', year)
	prompt = prompt.replace('PLOT_HERE', plot).replace('GENRES_HERE', genre).replace('KEYWORDS_HERE', keywords)
	prompt = prompt.replace('LIMIT', str(limit))
	return prompt

def model_info(model_id, media_type, meta, limit):
	return {'similar':
{'headers': {'Content-Type': 'application/json', 'x-goog-api-key': get_api()},
'url': 'https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent' % model_id,
'payload': {'contents': [{'role': 'user', 'parts': [{'text': make_similar_prompt(media_type, meta, limit)}]}]},
'parse': similar_parse}
}

def model_present(model_id):
	return model_id in models()

def get_api():
	return get_setting('fenlight.google_api')
