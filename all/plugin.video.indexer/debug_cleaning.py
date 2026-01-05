
import re
import os

# Copying the relevant parts of clean_and_get_year from main.py
def clean_and_get_year(filename):
    """
    Extract title and year from filename
    Aggressively removes all quality indicators and release info
    """
    name_without_ext = os.path.splitext(filename)[0]
    
    # Pre-compile regex patterns (simulated here)
    YEAR_PATTERNS = [
        re.compile(r'\((\d{4})\)'),
        re.compile(r'[\.\s_-](\d{4})[\.\s_-]'),
        re.compile(r'^(\d{4})[\.\s_-]'),
        re.compile(r'[\.\s_-](\d{4})$')
    ]
    
    CLEAN_PATTERNS = [
        re.compile(r'(2160p|1080p|720p|480p|360p|4K|UHD|HD|SD)', re.IGNORECASE),
        re.compile(r'\b(x264|x265|H\.?264|H\.?265|HEVC|AVC|10bit|8bit|HDR|HDR10|DV|DoVi)\b', re.IGNORECASE),
        re.compile(r'\b(BluRay|BRRip|BDRip|WEBRip|WEB-DL|HDTV|DVDRip|DVD|REMUX|NF|AMZN|DSNP)\b', re.IGNORECASE),
        re.compile(r'\b(DTS-HD|DTS|DD|AAC|AC3|TrueHD|FLAC|Atmos|MA|5\.1|7\.1|2\.0)\b', re.IGNORECASE),
        re.compile(r'-[A-Z0-9]+$', re.IGNORECASE),
        re.compile(r'\[.*?\]'),
        re.compile(r'\((?!\d{4}\)).*?\)'),
    ]

    # Step 1: Extract and remove year
    year = None
    for pattern in YEAR_PATTERNS:
        match = pattern.search(name_without_ext)
        if match:
            year = int(match.group(1))
            name_without_ext = pattern.sub(' ', name_without_ext, count=1)
            break
    
    # Step 2: Replace dots/dashes/underscores with spaces
    title = re.sub(r'[\._-]+', ' ', name_without_ext)
    
    # Step 3: Remove all quality tags
    for pattern in CLEAN_PATTERNS:
        title = pattern.sub(' ', title)
    
    # Step 4.0: Remove Season/Episode patterns (S01, E01, S01E01, 1x01, Season 1)
    # This is critical when extracting title from a Season folder name
    title = re.sub(r'\bS\d+E\d+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\bS\d+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\bSeason\s*\d+\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\b\d+x\d+\b', ' ', title, flags=re.IGNORECASE)

    # Step 4: Remove common extra tags
    # Language tags
    title = re.sub(r'\b(CHINESE|KOREAN|JAPANESE|FRENCH|GERMAN|SPANISH|ITALIAN|RUSSIAN|HINDI)\b', ' ', title, flags=re.IGNORECASE)
    # Edition tags  
    title = re.sub(r'\b(DC|EXTENDED|UNRATED|REMASTERED|DIRECTORS\.?CUT|THEATRICAL)\b', ' ', title, flags=re.IGNORECASE)
    # Numbers with dots (like 5.1, 7.1, 2.0, H.265, etc.)
    title = re.sub(r'\b[0-9]+\.[0-9]+\b', ' ', title)
    # Single letters followed by numbers or vice versa (H 265, R 265, etc.) but preserve single letters if they might be part of title (rare)
    # We already removed Sxx, so S 03 won't match here unless spaced
    title = re.sub(r'\b[A-Za-z]\s+[0-9]+\b', ' ', title)
    title = re.sub(r'\b[0-9]+\s+[A-Za-z]\b', ' ', title)
    
    # Step 5: Remove release groups (ALL patterns)
    title = re.sub(r'\b[A-Z]+[0-9]+[A-Z]+[A-Za-z0-9]*\b', ' ', title)
    title = re.sub(r'\b[A-Z]+[a-z]*[A-Z]+[a-z]*[A-Z]*[a-z]*\b', ' ', title)
    title = re.sub(r'\b[A-Za-z]+[@#][A-Za-z]+\b', ' ', title)
    title = re.sub(r'\b[a-z]+[A-Z][a-zA-Z]*\b', ' ', title)
    title = re.sub(r'\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b', ' ', title)
    title = re.sub(r'\s+[A-Z][A-Z0-9]{2,}\s*$', ' ', title)
    
    # Step 6: Remove specific problematic words
    problematic_words = ['True', 'WEB', 'ray', 'ATVP', 'KOGi', 'VERSION', 'Ctrl', 'seedpool', 'Blu', 'Cut', 'Arrow', 'Blood']
    for word in problematic_words:
        title = re.sub(rf'\b{word}\b', ' ', title, flags=re.IGNORECASE)
    
    # Step 7: Remove standalone short words and numbers at the end
    for _ in range(5):  # Repeat 5 times to catch multiple trailing tags
        title = re.sub(r'\s+[A-Z][A-Z0-9]{0,5}\s*$', ' ', title)  # Short CAPS words (up to 5 chars)
        title = re.sub(r'\s+[0-9]+\s*$', ' ', title)  # Numbers
        title = re.sub(r'\s+[a-z]{1,3}\s*$', ' ', title)  # Short lowercase (ray, etc.)
    
    # Step 8: Remove rating tags (R10+, R10Plus, etc.)
    title = re.sub(r'\bR[0-9]+\+?\b', ' ', title, flags=re.IGNORECASE)
    title = re.sub(r'\bR[0-9]+Plus\b', ' ', title, flags=re.IGNORECASE)
    
    return title.strip(), year

# Test cases
test_folder = "Tulsa.King.S03.720p.WEBRip.x264 [DDN]"
print(f"Original: '{test_folder}'")
title, year = clean_and_get_year(test_folder)
print(f"Cleaned: '{title}' (Year: {year})")

test_folder_2 = "Tulsa.King.S01.720p.WEBRip.x264 [DDN]"
print(f"Original: '{test_folder_2}'")
title, year = clean_and_get_year(test_folder_2)
print(f"Cleaned: '{title}' (Year: {year})")
