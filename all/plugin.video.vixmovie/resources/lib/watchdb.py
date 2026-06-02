# -*- coding: utf-8 -*-
"""Watch progress database for Continue Watching feature.

Stores playback progress in a local SQLite database so the user can resume
movies and TV episodes from where they left off.
"""
import os
import sqlite3
import time

import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
WATCHED_DB = os.path.join(PROFILE_PATH, "watched.db")

# Minimum seconds of playback before we consider it "in progress"
MIN_POSITION = 5
# Percentage threshold to consider something "watched" (fully completed)
WATCHED_THRESHOLD_PCT = 90


def _ensure_profile():
    """Ensure the profile directory exists."""
    if not xbmcvfs.exists(PROFILE_PATH):
        xbmcvfs.mkdirs(PROFILE_PATH)


def _conn():
    """Get a database connection, creating tables if needed."""
    _ensure_profile()
    c = sqlite3.connect(WATCHED_DB, timeout=5)
    c.execute("""CREATE TABLE IF NOT EXISTS movies (
                    tmdb_id TEXT PRIMARY KEY,
                    title TEXT,
                    played_at INTEGER,
                    position INTEGER,
                    total INTEGER,
                    watched INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS episodes (
                    tmdb_id TEXT,
                    season INTEGER,
                    episode INTEGER,
                    title TEXT,
                    show_title TEXT,
                    played_at INTEGER,
                    position INTEGER,
                    total INTEGER,
                    watched INTEGER DEFAULT 0,
                    PRIMARY KEY (tmdb_id, season, episode))""")
    return c


# ---------- Record Progress ----------

def record_movie_progress(tmdb_id, title="", position=0, total=0):
    """Record playback progress for a movie."""
    try:
        c = _conn()
        position = int(position)
        total = int(total)
        watched = 0
        if total > 0:
            pct = (position / total) * 100.0
            if pct >= WATCHED_THRESHOLD_PCT:
                watched = 1

        existing = c.execute(
            "SELECT position, total, watched FROM movies WHERE tmdb_id=?",
            (str(tmdb_id),)).fetchone()
        if existing and not watched:
            old_position = int(existing[0] or 0)
            old_total = int(existing[1] or 0)
            old_watched = int(existing[2] or 0)
            if not old_watched and old_position > position:
                c.close()
                return
            if old_total > 0 and total <= 0:
                total = old_total

        c.execute("""INSERT OR REPLACE INTO movies
                        (tmdb_id, title, played_at, position, total, watched)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                  (str(tmdb_id), title, int(time.time()),
                   position, total, watched))
        c.commit()
        c.close()
    except Exception as e:
        _log(f"record_movie_progress error: {e}")


def record_episode_progress(tmdb_id, season, episode, title="",
                            show_title="", position=0, total=0):
    """Record playback progress for a TV episode."""
    try:
        c = _conn()
        season = int(season)
        episode = int(episode)
        position = int(position)
        total = int(total)
        watched = 0
        if total > 0:
            pct = (position / total) * 100.0
            if pct >= WATCHED_THRESHOLD_PCT:
                watched = 1

        existing = c.execute(
            """SELECT position, total, watched FROM episodes
               WHERE tmdb_id=? AND season=? AND episode=?""",
            (str(tmdb_id), season, episode)).fetchone()
        if existing and not watched:
            old_position = int(existing[0] or 0)
            old_total = int(existing[1] or 0)
            old_watched = int(existing[2] or 0)
            if not old_watched and old_position > position:
                c.close()
                return
            if old_total > 0 and total <= 0:
                total = old_total

        c.execute("""INSERT OR REPLACE INTO episodes
                        (tmdb_id, season, episode, title, show_title,
                         played_at, position, total, watched)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (str(tmdb_id), season, episode, title, show_title,
                   int(time.time()), position, total, watched))
        c.commit()
        c.close()
    except Exception as e:
        _log(f"record_episode_progress error: {e}")


# ---------- Continue Watching Queries ----------

def get_continue_watching_movies(limit=30):
    """Get movies with resume position but not fully watched.

    Returns list of dicts with keys: tmdb_id, title, position, total, played_at
    """
    out = []
    try:
        c = _conn()
        rows = c.execute(
            """SELECT tmdb_id, title, position, total, played_at FROM movies
               WHERE watched=0 AND position > ?
               ORDER BY played_at DESC LIMIT ?""",
            (MIN_POSITION, limit)).fetchall()
        c.close()
        for tmdb_id, title, pos, total, ts in rows:
            out.append({
                "tmdb_id": tmdb_id,
                "title": title or "",
                "position": pos,
                "total": total,
                "played_at": ts,
            })
    except Exception as e:
        _log(f"get_continue_watching_movies error: {e}")
    return out


def get_continue_watching_shows(limit=30):
    """Get TV shows with episodes in progress (not fully watched).

    For each show, returns the most recently played episode that is not complete.

    Returns list of dicts with keys: tmdb_id, show_title, season, episode,
    title, position, total, played_at
    """
    out = []
    try:
        c = _conn()
        # Get the most recent in-progress episode per show
        rows = c.execute(
            """SELECT tmdb_id, season, episode, title, show_title,
                      position, total, played_at
               FROM episodes
               WHERE watched=0 AND position > ?
               ORDER BY played_at DESC""",
            (MIN_POSITION,)).fetchall()
        c.close()

        # Group by show and pick the most recent episode per show
        seen_shows = set()
        for tmdb_id, season, episode, title, show_title, pos, total, ts in rows:
            if tmdb_id not in seen_shows:
                seen_shows.add(tmdb_id)
                out.append({
                    "tmdb_id": tmdb_id,
                    "show_title": show_title or "",
                    "season": season,
                    "episode": episode,
                    "title": title or "",
                    "position": pos,
                    "total": total,
                    "played_at": ts,
                })
            if len(out) >= limit:
                break
    except Exception as e:
        _log(f"get_continue_watching_shows error: {e}")
    return out


# ---------- Resume Lookup ----------

def get_movie_progress(tmdb_id):
    """Return saved movie progress, or None if there is no resumable point."""
    try:
        c = _conn()
        row = c.execute(
            """SELECT position, total FROM movies
               WHERE tmdb_id=? AND watched=0 AND position > ?""",
            (str(tmdb_id), MIN_POSITION)).fetchone()
        c.close()
        if row:
            return {"position": int(row[0] or 0), "total": int(row[1] or 0)}
    except Exception as e:
        _log(f"get_movie_progress error: {e}")
    return None


def get_episode_progress(tmdb_id, season, episode):
    """Return saved episode progress, or None if there is no resumable point."""
    try:
        c = _conn()
        row = c.execute(
            """SELECT position, total FROM episodes
               WHERE tmdb_id=? AND season=? AND episode=?
                 AND watched=0 AND position > ?""",
            (str(tmdb_id), int(season), int(episode), MIN_POSITION)).fetchone()
        c.close()
        if row:
            return {"position": int(row[0] or 0), "total": int(row[1] or 0)}
    except Exception as e:
        _log(f"get_episode_progress error: {e}")
    return None


# ---------- Utility ----------

def format_resume_label(position, total):
    """Format a resume position as a human-readable string."""
    if total > 0:
        pct = int((position / total) * 100)
        return f"{pct}%"
    else:
        mins = position // 60
        return f"{mins}min"


def clear_movie_progress(tmdb_id):
    """Remove a movie from continue watching."""
    try:
        c = _conn()
        c.execute("DELETE FROM movies WHERE tmdb_id=?", (str(tmdb_id),))
        c.commit()
        c.close()
    except Exception as e:
        _log(f"clear_movie_progress error: {e}")


def clear_episode_progress(tmdb_id, season, episode):
    """Remove an episode from continue watching."""
    try:
        c = _conn()
        c.execute("DELETE FROM episodes WHERE tmdb_id=? AND season=? AND episode=?",
                  (str(tmdb_id), int(season), int(episode)))
        c.commit()
        c.close()
    except Exception as e:
        _log(f"clear_episode_progress error: {e}")


def clear_all():
    """Clear all watch progress data."""
    try:
        if os.path.exists(WATCHED_DB):
            os.remove(WATCHED_DB)
    except Exception:
        pass


def _log(msg):
    """Simple logging helper."""
    import xbmc
    xbmc.log(f"[VIXMOVIE-WATCHDB] {msg}", xbmc.LOGINFO)
