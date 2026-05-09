import sqlite3 as database
from pathlib import Path
from datetime import datetime, timedelta
import xbmc, xbmcaddon, xbmcgui, xbmcvfs

dialog = xbmcgui.Dialog()

def notification(line1, time=3000, sound=False):
	addon_info = xbmcaddon.Addon().getAddonInfo
	dialog.notification(addon_info('name'), line1, addon_info('icon'), time, sound)

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
	current_date = datetime.date(datetime.utcnow())
	back_date = (current_date - timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
	dbcon = database.connect(str(dbfile))
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""SELECT COUNT(*) FROM files""")
	total = dbcur.fetchone()[0]
	dbcur.execute("""
		SELECT idFile, idPath FROM files
		WHERE lastPlayed >= ? AND lastPlayed IS NOT NULL AND strFilename IS NOT NULL
	""", (str(back_date), ))
	result = dbcur.fetchall()
	expired = total - len(result)
	if not expired > 0: return notification('No Streams to Clear')
	if not dialog.yesno('POV', '[CR][CR]Delete %d Items?' % expired): return
	progress_dialog = xbmcgui.DialogProgress()
	progress_dialog.create('Streams Remover', '')
	progress_dialog.update(0, 'Gathering Streams Info...')
	try:
		file_ids = ','.join(f"{i[0]}" for i in result)
		line = 'Removing %d Database Entries...[CR]Please Wait...[CR]%s' % (expired, '%s')
		progress_dialog.update(25, line % 'Removing File IDS...')
		dbcur.execute("""DELETE FROM files WHERE idFile NOT IN (%s)""" % file_ids)
		progress_dialog.update(50, line % 'Removing Stream IDS...')
		dbcur.execute("""DELETE FROM streamdetails WHERE idFile NOT IN (%s)""" % file_ids)
		progress_dialog.update(75, line % 'Removing Path IDS...')
		dbcur.execute("""DELETE FROM path WHERE idPath NOT IN (%s)""" % ','.join(f"{i[1]}" for i in result))
		progress_dialog.update(99, line % 'Cleaning Database...')
		dbcon.commit()
		xbmc.sleep(500)
		dbcur.execute("""VACUUM""")
		notification('Success')
	finally: progress_dialog.close()

def clear_thumbnails():
	thumbs_path = Path(xbmcvfs.translatePath('special://thumbnails/'))
	dbfile = Path(xbmcvfs.translatePath('special://database/'), 'Textures13.db')
	if not dbfile.exists(): return notification('Failed')
	minimum_uses = 30
	days = dialog.numeric(0, 'Remove Thumbs Older Than (Days)...', defaultt=str(minimum_uses))
	if not days: return notification('No Days Set')
	current_date = datetime.date(datetime.utcnow())
	back_date = (current_date - timedelta(days=int(days))).strftime('%Y-%m-%d %H:%M:%S')
	dbcon = database.connect(str(dbfile))
	dbcur = dbcon.cursor()
	dbcur.execute("""PRAGMA synchronous = OFF""")
	dbcur.execute("""PRAGMA journal_mode = OFF""")
	dbcur.execute("""SELECT COUNT(*) FROM sizes""")
	total = dbcur.fetchone()[0]
	dbcur.execute("""SELECT idtexture FROM sizes WHERE lastusetime >= ?""", (str(back_date), ))
	result = dbcur.fetchall()
	expired = total - len(result)
	if not expired > 0: return notification('No Thumbnails to Clear')
	if not dialog.yesno('POV', '[CR][CR]Delete %d Items?' % expired): return
	progress_dialog = xbmcgui.DialogProgress()
	progress_dialog.create('Thumbnails Remover', '')
	progress_dialog.update(0, 'Gathering Thumbnail Info...')
	try:
		texture_ids = ','.join(f"{i[0]}" for i in result)
		dbcur.execute("""SELECT cachedurl FROM texture WHERE id IN (%s)""" % texture_ids)
		cached = dbcur.fetchall()
		cached = {i[0].split('/')[-1] for i in cached}
		for file in thumbs_path.glob('**/?/*'):
			if progress_dialog.iscanceled(): return
			if not file.is_file() or file.name in cached: continue
			file.unlink(missing_ok=True)
			line = '[CR][CR][B]Removing:[/B] %s[CR][B]Path: [/B]%s'
			progress_dialog.update(25, line % (str(file.name), str(file.parent)))
		line = 'Removing %d Database Entries...[CR]Please Wait...[CR]%s' % (expired, '%s')
		progress_dialog.update(50, line % 'Removing Sizes IDS...')
		dbcur.execute("""DELETE FROM sizes WHERE idtexture NOT IN (%s)""" % texture_ids)
		progress_dialog.update(75, line % 'Removing Texture IDS...')
		dbcur.execute("""DELETE FROM texture WHERE id NOT IN (%s)""" % texture_ids)
		progress_dialog.update(99, line % 'Cleaning Database...')
		dbcon.commit()
		xbmc.sleep(500)
		dbcur.execute("""VACUUM""")
		notification('Success')
	finally: progress_dialog.close()

