# -*- coding: utf-8 -*-
"""
Kodi (Local) library bridge — ponta intre local_sync.db si biblioteca Kodi (MyVideos.db).

- set_playcount(tmdb_id, ...): write-through instant la mark/unwatch din addon
  (aceeasi tehnica direct-SQL ca _sync_watched_direct_sql din library.py — zero
  anunțuri JSON-RPC, zero flicker).
- import_kodi_watchstate(): reverse-import la Library Sync (playcount Kodi ->
  local_watched_*), polita: itemii din biblioteca cistiga, itemii ne-biblioteca
  pastrati (marcajele pe itemi non-biblioteca nu se pierd).

Itemii fara uniqueid type='tmdb' in biblioteca nu pot fi mapati -> sunt ignorați
(silencios): functiile sunt no-op pentru ei.
"""

import os
import xbmc
import xbmcvfs

# Timeout mic: Kodi poate tine lock pe MyVideos la write nativ; la conflict
# aceasta functie esueaza silențios (batch-ul din Library Sync reconciliaza).
_MV_TIMEOUT = 3


def find_myvideos_db():
    import glob
    try:
        db_dir = xbmcvfs.translatePath('special://userdata/Database/')
        dbs = glob.glob(os.path.join(db_dir, 'MyVideos*.db'))
        if not dbs:
            return None
        # Conventia din library.py: cel mai recent modificat e cel activ.
        return max(dbs, key=os.path.getmtime)
    except Exception:
        return None


def _myvideos_connection(db_path=None):
    import sqlite3
    path = db_path or find_myvideos_db()
    if not path or not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(path, timeout=_MV_TIMEOUT)
        return conn
    except Exception as e:
        xbmc.log(f'[LOCAL] MyVideos connect error: {e}', xbmc.LOGWARNING)
        return None


def _fmt_ts(ts):
    """Formateaza timestamp pentru lastPlayed: YYYY-MM-DD HH:MM:SS (format MyVideos)."""
    if not ts:
        return None
    return str(ts)[:19].replace('T', ' ')


def set_playcount(tmdb_id, content_type='movie', season=None, episode=None, count=1):
    """Write-through playCount in MyVideos.db pentru itemii cu uniqueid tmdb.

    - count=1: playCount max(playCount,1), lastPlayed=now daca nu avea deja
    - count=0: playCount=NULL + lastPlayed=NULL. NULL (nu 0 explicit!) pentru
      ca view-ul Kodi tvshowcounts face COUNT(files.playCount), iar COUNT
      numara valorile non-NULL — un 0 explicit ar ramane "vizionat" pentru
      widget-ul nativ In Progress (7/47 in loc de 1/47). lastPlayed=NULL din
      acelasi motiv (widget-ul numara si episoadele cu lastPlayed setat).
    - no-op silențios pentru itemii care nu sunt in biblioteca.
    """
    try:
        conn = _myvideos_connection()
        if conn is None:
            return
        c = conn.cursor()
        import datetime as _dt
        now_str = _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        updates = []
        like = '%%tmdb_id=%s%%' % tmdb_id

        if content_type == 'movie':
            q = ("SELECT f.idFile, COALESCE(f.playCount,0) FROM uniqueid u "
                 "JOIN movie m ON m.idMovie=u.media_id "
                 "JOIN files f ON f.idFile=m.idFile "
                 "WHERE u.media_type='movie' AND u.type='tmdb' AND u.value=?")
            for idf, pc in c.execute(q, (str(tmdb_id),)).fetchall():
                if count >= 1 and (pc or 0) < 1:
                    updates.append((count, now_str, idf))
                elif count < 1 and (pc or 0) >= 1:
                    updates.append((0, None, idf))
        else:
            q = ("SELECT e.c12, e.c13, f.idFile, COALESCE(f.playCount,0) FROM episode e "
                 "JOIN tvshow s ON s.idShow=e.idShow "
                 "JOIN uniqueid us ON us.media_id=s.idShow AND us.media_type='tvshow' AND us.type='tmdb' "
                 "JOIN files f ON f.idFile=e.idFile "
                 "WHERE us.value=?")
            for sn, en, idf, pc in c.execute(q, (str(tmdb_id),)).fetchall():
                try:
                    key = (int(sn), int(en))
                except (TypeError, ValueError):
                    continue
                if season is not None and episode is not None:
                    if key != (int(season), int(episode)):
                        continue
                elif season is not None:
                    if key[0] != int(season):
                        continue
                if count >= 1 and (pc or 0) < 1:
                    updates.append((count, now_str, idf))
                elif count < 1 and (pc or 0) >= 1:
                    updates.append((0, None, idf))

        if updates:
            for cnt, lp, idf in updates:
                if cnt < 1:
                    c.execute("UPDATE files SET playCount=NULL, lastPlayed=NULL WHERE idFile=?", (idf,))
                elif lp:
                    c.execute("UPDATE files SET playCount=?, lastPlayed=? WHERE idFile=?", (cnt, lp, idf))
                else:
                    c.execute("UPDATE files SET playCount=? WHERE idFile=?", (cnt, idf))
            conn.commit()
            xbmc.log(f'[LOCAL] playCount write-through: {len(updates)} rows (tmdb={tmdb_id}, count={count})', xbmc.LOGINFO)
        conn.close()
    except Exception as e:
        xbmc.log(f'[LOCAL] playCount write-through error: {e}', xbmc.LOGWARNING)


def import_kodi_watchstate():
    """Reverse-import: playcount din MyVideos.db -> local_watched_*.

    - Items in library: biblioteca cistiga (INSERT OR REPLACE episod; INSERT OR IGNORE
      film — nu stricam last_watched_at existent fara lastplayed in Kodi).
    - Items NE-biblioteca din local_*: pastrati (nu se sterg).
    - Returneaza numarul de rinduri scrise.
    """
    written = 0
    conn = _myvideos_connection()
    if conn is None:
        return 0
    try:
        from resources.lib import local_sync
        local_sync.init_database()
        lc = local_sync.get_connection()
        lc_c = lc.cursor()
        c = conn.cursor()
        import datetime as _dt

        # ── Movies ──
        # MyVideos NU are coloane title/year pe movie (titlul e c00, anul din premiered)
        q = ("SELECT u.value, m.c00, SUBSTR(m.premiered,1,4), f.lastPlayed FROM uniqueid u "
             "JOIN movie m ON m.idMovie=u.media_id "
             "JOIN files f ON f.idFile=m.idFile "
             "WHERE u.media_type='movie' AND u.type='tmdb' AND COALESCE(f.playCount,0)>=1")
        for tid, title, year, lp in c.execute(q).fetchall():
            if not tid:
                continue
            lc_c.execute("SELECT 1 FROM local_watched_movies WHERE tmdb_id=?", (str(tid),))
            if lc_c.fetchone() is None:
                lc_c.execute("INSERT OR IGNORE INTO local_watched_movies (tmdb_id, title, year, last_watched_at) VALUES (?,?,?,?)",
                             (str(tid), title or 'Unknown', str(year or ''), _fmt_ts(lp)))
                written += 1

        # ── Episodes ──
        q = ("SELECT us.value, e.c12, e.c13, s.c00, f.lastPlayed FROM episode e "
             "JOIN tvshow s ON s.idShow=e.idShow "
             "JOIN uniqueid us ON us.media_id=s.idShow AND us.media_type='tvshow' AND us.type='tmdb' "
             "JOIN files f ON f.idFile=e.idFile "
             "WHERE COALESCE(f.playCount,0)>=1")
        show_names = {}
        for tid, sn, en, show_title_col, lp in c.execute(q).fetchall():
            if not tid:
                continue
            try:
                s_num, e_num = int(sn), int(en)
            except (TypeError, ValueError):
                continue
            # tvshow.c00 = titlul serialului in schema MyVideos
            show_name = show_names.get(str(tid))
            if show_name is None:
                show_name = (show_title_col or 'Unknown Show')
                show_names[str(tid)] = show_name
            ep_title = f"{show_name} - S{s_num:02d}E{e_num:02d}"
            lc_c.execute("INSERT OR REPLACE INTO local_watched_episodes (tmdb_id, season, episode, title, last_watched_at) VALUES (?,?,?,?,?)",
                         (str(tid), s_num, e_num, ep_title, _fmt_ts(lp)))
            written += 1

        lc.commit()
        lc.close()
        conn.close()
        xbmc.log(f'[LOCAL] import_kodi_watchstate: {written} rows from MyVideos', xbmc.LOGINFO)
        return written
    except Exception as e:
        xbmc.log(f'[LOCAL] import_kodi_watchstate error: {e}', xbmc.LOGWARNING)
        try:
            conn.close()
        except:
            pass
        return written
