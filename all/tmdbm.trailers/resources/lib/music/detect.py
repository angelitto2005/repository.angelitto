import re
import unicodedata

EXCLUDED = (
    'trailer', 'teaser', 'film clip', 'movie clip', 'episode', 'documentary',
    'gameplay', 'walkthrough', 'full movie', 'audiobook', 'lecture',
    'news', 'review', 'reaction', 'podcast',
)

MARKERS = (
    'music video', 'official video', 'official audio', 'official lyric',
    'lyric video', 'lyrics', 'official song', 'music', 'musica', 'cancion',
    'song', 'bachata', 'reggaeton', 'reggaeton', 'salsa', 'merengue',
    'remix', 'mix ', ' mix', 'dj set', 'album completo', 'full album',
    'live performance', 'concert', 'cover',
)

_TRACK_PATTERN = re.compile(
    r'\s[-–—]\s.+\(\s*(?:official\s+)?(?:music\s+)?video\s*\)')


def normalize(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize(
        'NFKC', str(value or '')).casefold()).strip()


def is_excluded(entry):
    entry = entry or {}
    if entry.get('is_live'):
        return True
    title = normalize(entry.get('title'))
    return any(token in title for token in EXCLUDED)


def looks_like_music(entry, hint=''):
    entry = entry or {}
    if is_excluded(entry):
        return False
    title = normalize(entry.get('title'))
    text = '{} {}'.format(title, normalize(hint))
    if _TRACK_PATTERN.search(title):
        return True
    return any(marker in text for marker in MARKERS)