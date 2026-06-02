# -*- coding: utf-8 -*-
"""Player utilities for VixMovie extended resolvers.
Contains sort_streams_for_autoplay (full logic from tmdbmovies) and check_url_validity.
"""
import requests
import xbmc


def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[VIXMOVIE-EXT-PLAYER] {msg}", level)


def check_url_validity(url, headers=None, max_timeout=None):
    """Check if a stream URL is valid/reachable."""
    timeout = max_timeout or 8
    try:
        if not url or not url.startswith("http"):
            return False

        actual_url = url
        req_headers = headers or {}
        if "|" in url:
            actual_url, header_str = url.split("|", 1)
            from urllib.parse import parse_qsl
            req_headers.update(dict(parse_qsl(header_str)))

        if not req_headers.get("User-Agent"):
            req_headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            )

        resp = requests.head(actual_url, headers=req_headers, timeout=timeout,
                             allow_redirects=True, verify=False)
        if resp.status_code < 400:
            return True

        resp = requests.get(actual_url, headers=req_headers, timeout=timeout,
                            allow_redirects=True, verify=False, stream=True)
        resp.close()
        return resp.status_code < 400

    except Exception:
        return False


def sort_streams_by_quality(streams):
    """Sort streams by quality (resolution) and file size."""
    qual_scores = {'4k': 120, '2160p': 120, '1080p': 100, '720p': 80, '480p': 60, '360p': 40, 'sd': 40}

    def get_score(stream):
        q = stream.get('quality', '').lower()
        for key, score in qual_scores.items():
            if key in q:
                return score
        return 40

    return sorted(streams, key=get_score, reverse=True)


def sort_streams_for_autoplay(streams, profile_idx=0):
    """
    Full autoplay sorting logic from tmdbmovies.
    profile_idx: 0 = Windows 1080p, 1 = Android 4K, 2 = Android 1080p
    
    Priority order:
    - VAPlayer > MeowTV > VixSrc (top tier - fast, reliable)
    - Pixel/CloudR2 sources (good for Windows)
    - Everything else sorted by quality
    
    Excludes 4K on 1080p profiles.
    """
    if not streams:
        return streams

    # Exclude 4K if profile is 1080p (Windows or Android 1080p)
    if profile_idx == 0 or profile_idx == 2:
        streams = [s for s in streams if '4k' not in s.get('quality', '').lower()
                   and '2160' not in s.get('quality', '').lower()
                   and '2160' not in s.get('name', '').lower()]

    # Android profiles: simple quality sort
    if profile_idx == 1 or profile_idx == 2:
        return sort_streams_by_quality(streams)

    # Windows 1080p: advanced sorting logic
    if profile_idx == 0:
        top_streams = []       # VAPlayer, MeowTV, VixSrc
        priority_streams = []  # Pixel, CloudR2 (good on Windows)
        other_streams = []

        for s in streams:
            raw_name = s.get('name', '').lower()
            provider_id = s.get('provider_id', '').lower()
            url = s.get('url', '').lower()

            is_vix = 'vixsrc' in provider_id or 'vix' in raw_name
            is_meow = 'meowtv' in provider_id or 'meow' in raw_name
            is_vaplayer = 'vaplayer' in provider_id or 'vaplayer' in raw_name

            # Detect Pixel & CloudR2 (Priority 2 - work well on Windows)
            is_good_windows = False
            if 'pixel' in raw_name or 'pix' in raw_name or 'hubpix' in raw_name:
                is_good_windows = True
            elif 'pixeldrain' in url or 'pixel' in url:
                is_good_windows = True
            elif 'cloudr2' in raw_name:
                is_good_windows = True
            elif 'pub-' in url or 'r2.dev' in url:
                is_good_windows = True

            # Distribute
            if is_vaplayer or is_meow or is_vix:
                top_streams.append(s)
            elif is_good_windows:
                priority_streams.append(s)
            else:
                other_streams.append(s)

        # Sort each group by quality
        top_streams = sort_streams_by_quality(top_streams)
        priority_streams = sort_streams_by_quality(priority_streams)
        other_streams = sort_streams_by_quality(other_streams)

        # Within top_streams: VAPlayer (3) > MeowTV (2) > VixSrc (1)
        def get_top_score(stream):
            p_id = stream.get('provider_id', '').lower()
            n_m = stream.get('name', '').lower()
            if 'vaplayer' in p_id or 'vaplayer' in n_m:
                return 3
            if 'meow' in p_id or 'meow' in n_m:
                return 2
            if 'vix' in p_id or 'vix' in n_m:
                return 1
            return 0

        top_streams.sort(key=get_top_score, reverse=True)

        final_list = top_streams + priority_streams + other_streams
        log(f"[AUTOPLAY] Windows: {len(top_streams)} Top (VAPlayer>Meow>Vix), "
            f"{len(priority_streams)} Pixel/Cloud, {len(other_streams)} Other")
        return final_list

    # Default fallback
    return sort_streams_by_quality(streams)
