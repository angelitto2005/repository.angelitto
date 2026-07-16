import sqlite3 as database
from pathlib import Path
from datetime import datetime, timedelta
import xbmc, xbmcaddon, xbmcgui, xbmcvfs

dialog = xbmcgui.Dialog()
addon = xbmcaddon.Addon()

def notification(line1, time=3000, sound=False):
	dialog.notification(addon.getAddonInfo('name'), line1, addon.getAddonInfo('icon'), time, sound)

def clear_streams():
	dbfile = xbmcvfs.translatePath('special://database/')
	dbfile = dialog.browse(1, 'MyVideos*.db', 'local', defaultt=dbfile)
	dbfile = Path(dbfile)
	if not dbfile.is_file(): return notification('Failed')
	if not dbfile.name.lower().startswith('myvideos'): return notification('Not a valid file')
	if not dialog.yesno('POV', f"{dbfile.name}[CR][CR]Are you sure?"): return
	minimum_uses = 30
	days = dialog.numeric(0, 'Remove Items Older Than (Days)...', defaultt=str(minimum_uses))
	if not days: return notification('No Days Set')
	current_date = datetime.now().date()
	back_date = (current_date - timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
	with database.connect(str(dbfile)) as dbcon:
		dbcur = dbcon.cursor()
		dbcur.execute("""PRAGMA synchronous = OFF""")
		dbcur.execute("""PRAGMA journal_mode = MEMORY""")
		dbcur.execute("""SELECT COUNT(*) FROM files""")
		total = dbcur.fetchone()[0]
		dbcur.execute("""
			SELECT idFile, idPath FROM files
			WHERE lastPlayed >= ? AND lastPlayed IS NOT NULL AND strFilename IS NOT NULL
		""", (str(back_date),))
		result = dbcur.fetchall()
		expired = total - len(result)
		if expired <= 0: return notification('No streams to clear.')
		if not dialog.yesno('POV', '[CR][CR]Delete %d Items?' % expired): return
		progress_dialog = xbmcgui.DialogProgress()
		progress_dialog.create('Streams Remover', '')
		progress_dialog.update(0, 'Gathering Streams Info...')
		try:
			dbcur.execute("""CREATE TEMP TABLE keep_files (idFile INTEGER, idPath INTEGER)""")
			if result: dbcur.executemany("""INSERT INTO keep_files VALUES (?, ?)""", result)
			line = 'Removing %d Database Entries...[CR]Please Wait...[CR]%s' % (expired, '%s')
			progress_dialog.update(25, line % 'Removing File IDS...')
			dbcur.execute("""DELETE FROM files WHERE idFile NOT IN (SELECT idFile FROM keep_files)""")
			progress_dialog.update(50, line % 'Removing Stream IDS...')
			dbcur.execute("""DELETE FROM streamdetails WHERE idFile NOT IN (SELECT idFile FROM keep_files)""")
			progress_dialog.update(75, line % 'Removing Path IDS...')
			dbcur.execute("""DELETE FROM path WHERE idPath NOT IN (SELECT idPath FROM keep_files)""")
			progress_dialog.update(99, line % 'Cleaning Database...')
			dbcon.commit()
			xbmc.sleep(500)
			dbcur.execute("""VACUUM""")
			notification('Success. Cleared %d Entries' % expired)
		finally: progress_dialog.close()

def clear_thumbnails():
	thumbs_path = Path(xbmcvfs.translatePath('special://thumbnails/'))
	dbfile = xbmcvfs.translatePath('special://database/')
	dbfile = dialog.browse(1, 'Textures*.db', 'local', defaultt=dbfile)
	dbfile = Path(dbfile)
	if not dbfile.is_file(): return notification('Failed')
	if not dbfile.name.lower().startswith('textures'): return notification('Not a valid file')
	if not dialog.yesno('POV', f"{dbfile.name}[CR][CR]Are you sure?"): return
	minimum_uses = 30
	days = dialog.numeric(0, 'Remove Thumbs Older Than (Days)...', defaultt=str(minimum_uses))
	if not days: return notification('No Days Set')
	current_date = datetime.now().date()
	back_date = (current_date - timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
	with database.connect(str(dbfile)) as dbcon:
		dbcur = dbcon.cursor()
		dbcur.execute("""PRAGMA synchronous = OFF""")
		dbcur.execute("""PRAGMA journal_mode = MEMORY""")
		dbcur.execute("""SELECT COUNT(*) FROM sizes""")
		total = dbcur.fetchone()[0]
		dbcur.execute("""SELECT idtexture FROM sizes WHERE lastusetime >= ?""", (str(back_date),))
		keep_ids = [(i[0],) for i in dbcur.fetchall()]
		expired = total - len(keep_ids)
		if expired and not dialog.yesno('POV', '[CR][CR]Delete %d Items?' % expired): return
		progress_dialog = xbmcgui.DialogProgress()
		progress_dialog.create('Thumbnails Cleaner', '')
		progress_dialog.update(0, 'Gathering Thumbnail Info...')
		try:
			if expired:
				dbcur.execute("""CREATE TEMP TABLE keep_thumbs (idtexture INTEGER)""")
				if keep_ids: dbcur.executemany("""INSERT INTO keep_thumbs VALUES (?)""", keep_ids)
				line = 'Cleaning Database...[CR]Please Wait...[CR]%s'
				progress_dialog.update(20, line % 'Removing Sizes Entries...')
				dbcur.execute("""DELETE FROM sizes WHERE idtexture NOT IN (SELECT idtexture FROM keep_thumbs)""")
				progress_dialog.update(40, line % 'Removing Texture Entries...')
				dbcur.execute("""DELETE FROM texture WHERE id NOT IN (SELECT idtexture FROM keep_thumbs)""")
				progress_dialog.update(60, line % 'Vacuuming Database...')
				dbcon.commit()
				xbmc.sleep(500)
				dbcur.execute("""VACUUM""")
			progress_dialog.update(80, 'Scanning for Orphaned/Expired Files...')
			dbcur.execute("""SELECT cachedurl FROM texture""")
			keep_files = {i[0].split('/')[-1] for i in dbcur.fetchall() if i[0]}
			line = 'Scanned: %d files...[CR]Removed: %d (Expired/Orphans)'
			deleted_count, count = 0, 0
			for file in thumbs_path.glob('**/?/*'):
				if progress_dialog.iscanceled(): return
				if not file.is_file(): continue
				count += 1
				if file.name in keep_files: continue
				file.unlink(missing_ok=True)
				deleted_count += 1
				progress_dialog.update(0, line % (count, deleted_count))
			notification('Success. Cleared %d files.' % deleted_count)
		finally: progress_dialog.close()

