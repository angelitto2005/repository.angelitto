import time
from threading import Thread
from modules import kodi_utils, settings

logger, path_exists, translate_path = kodi_utils.logger, kodi_utils.path_exists, kodi_utils.translate_path
monitor, is_playing, get_visibility = kodi_utils.monitor, kodi_utils.player.isPlaying, kodi_utils.get_visibility
get_property, set_property, clear_property = kodi_utils.get_property, kodi_utils.set_property, kodi_utils.clear_property
get_setting, set_setting, make_settings_dict = kodi_utils.get_setting, kodi_utils.set_setting, kodi_utils.make_settings_dict

def initializeDatabases():
	from modules.cache import check_databases
	logger('SALTS', 'InitializeDatabases Service Starting')
	check_databases()
	return logger('SALTS', 'InitializeDatabases Service Finished')

def checkSettingsFile():
	logger('SALTS', 'CheckSettingsFile Service Starting')
	clear_property('salts_settings')
	profile_dir = kodi_utils.get_addoninfo('profile')
	profile_xml = profile_dir + 'settings.xml'
	if not path_exists(profile_xml):
		kodi_utils.make_directorys(profile_dir)
		kodi_utils.addon().setSetting('kodi_menu_cache', 'true')
		kodi_utils.sleep(500)
	make_settings_dict()
	set_property('salts_kodi_menu_cache', get_setting('kodi_menu_cache'))
	set_property('salts_rli_fix', get_setting('rli_fix'))
	return logger('SALTS', 'CheckSettingsFile Service Finished')

def databaseMaintenance():
	from modules.cache import clean_databases
	current_time = int(time.time())
	next_clean = current_time + 259200 # 3 days
	due_clean = int(get_setting('database.maintenance.due', '0'))
	if current_time < due_clean: return
	logger('SALTS', 'Database Maintenance Service Starting')
	clean_databases(current_time, database_check=False, silent=True)
	set_setting('database.maintenance.due', str(next_clean))
	return logger('SALTS', 'Database Maintenance Service Finished')

def viewsSetWindowProperties():
	logger('SALTS', 'ViewsSetWindowProperties Service Starting')
	kodi_utils.set_view_properties()
	return logger('SALTS', 'ViewsSetWindowProperties Service Finished')

def reuseLanguageInvokerCheck():
	import xml.etree.ElementTree as ET
	logger('SALTS', 'ReuseLanguageInvokerCheck Service Starting')
	addon_xml = translate_path('special://home/addons/plugin.video.sallts/addon.xml')
	tree = ET.parse(addon_xml)
	root = tree.getroot()
	current_addon_setting = get_setting('reuse_language_invoker', 'true')
	text = '[B]Reuse Language Invoker[/B] SETTING/XML mismatch[CR]SALTS will reload your profile to refresh the addon.xml'
	item, refresh = next(root.iter('reuselanguageinvoker'), None), False
	if item is None: kodi_utils.notification(text.split('[CR]')[0])
	if not item is None and not item.text == current_addon_setting:
		item.text = current_addon_setting
		tree.write(addon_xml)
		refresh = True
	if refresh and kodi_utils.confirm_dialog(text=text):
		kodi_utils.execute_builtin('LoadProfile(%s)' % kodi_utils.get_infolabel('system.profilename'))
	return logger('SALTS', 'ReuseLanguageInvokerCheck Service Finished')

def autoRun():
	logger('SALTS', 'AutoRun Service Starting')
	if settings.auto_start_salts(): kodi_utils.execute_builtin('RunAddon(plugin.video.sallts)')
	return logger('SALTS', 'AutoRun Service Finished')

def clearSubs():
	logger('SALTS', 'Clear Subtitles Service Starting')
	sub_formats = ('.srt', '.ssa', '.smi', '.sub', '.idx')
	subtitle_path = 'special://temp/'
	for i in kodi_utils.list_dirs(subtitle_path)[1]:
		if i.startswith('SALTSSubs_') or i.endswith(sub_formats):
			kodi_utils.delete_file(subtitle_path + i)
	return logger('SALTS', 'Clear Subtitles Service Finished')

def traktMonitor():
	from caches.trakt_cache import clear_trakt_list_contents_data
	from indexers.trakt_api import trakt_sync_activities
	from indexers.mdblist_api import mdbl_sync_activities
	from indexers.flicklist_api import flicklist_sync_activities
	logger('SALTS', 'TraktMonitor Service Starting')
	trakt_service_string = 'TraktMonitor Service Update %s - %s'
	update_string = 'Next Update in %s minutes...'
	if not get_property('salts_traktmonitor_first_run') == 'true':
		for i in ('user_lists', 'liked_lists', 'my_lists'): clear_trakt_list_contents_data(i)
		set_property('salts_traktmonitor_first_run', 'true')
	while not monitor.abortRequested():
		while is_playing() or get_visibility('Container().isUpdating') or get_property('salts_pause_services') == 'true':
			monitor.waitForAbort(10)
		if not get_property('salts_traktmonitor_first_run') == 'true':
			monitor.waitForAbort(5)
		value, interval = settings.trakt_sync_interval()
		next_update_string = update_string % value
		try: status = trakt_sync_activities()
		except: status = 'failed'
		if status == 'success':
			logger('SALTS', trakt_service_string % ('SALTS TraktMonitor - Success', 'Trakt Update Performed'))
			if settings.trakt_sync_refresh_widgets():
				kodi_utils.widget_refresh()
				logger('SALTS', trakt_service_string % ('SALTS TraktMonitor - Widgets Refresh', 'Setting Activated. Widget Refresh Performed'))
			else: logger('SALTS', trakt_service_string % ('SALTS TraktMonitor - Widgets Refresh', 'Setting Disabled. Skipping Widget Refresh'))
		elif status == 'no account':
			logger('SALTS', trakt_service_string % ('SALTS TraktMonitor - Aborted. No Trakt Account Active', next_update_string))
		elif status == 'failed':
			logger('SALTS', trakt_service_string % ('SALTS TraktMonitor - Failed. Error from Trakt', next_update_string))
		else:# 'not needed'
			logger('SALTS', trakt_service_string % ('SALTS TraktMonitor - Success. No Changes Needed', next_update_string))
		try: status = mdbl_sync_activities()
		except: status = 'failed'
		if status == 'success':
			logger('SALTS', trakt_service_string % ('SALTS MDBListMonitor - Success', 'MDBList Update Performed'))
			if settings.trakt_sync_refresh_widgets():
				kodi_utils.widget_refresh()
				logger('SALTS', trakt_service_string % ('SALTS MDBListMonitor - Widgets Refresh', 'Setting Activated. Widget Refresh Performed'))
			else: logger('SALTS', trakt_service_string % ('SALTS MDBListMonitor - Widgets Refresh', 'Setting Disabled. Skipping Widget Refresh'))
		elif status == 'no account':
			logger('SALTS', trakt_service_string % ('SALTS MDBListMonitor - Aborted. No MDBList Account Active', next_update_string))
		elif status == 'failed':
			logger('SALTS', trakt_service_string % ('SALTS MDBListMonitor - Failed. Error from MDBList', next_update_string))
		else:# 'not needed'
			logger('SALTS', trakt_service_string % ('SALTS MDBListMonitor - Success. No Changes Needed', next_update_string))
		try: status = flicklist_sync_activities()
		except: status = 'failed'
		if status == 'success':
			logger('SALTS', trakt_service_string % ('SALTS FlickListMonitor - Success', 'FLickList Update Performed'))
			if settings.trakt_sync_refresh_widgets():
				kodi_utils.widget_refresh()
				logger('SALTS', trakt_service_string % ('SALTS FlickListMonitor - Widgets Refresh', 'Setting Activated. Widget Refresh Performed'))
			else: logger('SALTS', trakt_service_string % ('SALTS FlickListMonitor - Widgets Refresh', 'Setting Disabled. Skipping Widget Refresh'))
		elif status == 'no account':
			logger('SALTS', trakt_service_string % ('SALTS FlickListMonitor - Aborted. No FLickList Account Active', next_update_string))
		elif status == 'failed':
			logger('SALTS', trakt_service_string % ('SALTS FlickListMonitor - Failed. Error from FLickList', next_update_string))
		else:# 'not needed'
			logger('SALTS', trakt_service_string % ('SALTS FlickListMonitor - Success. No Changes Needed', next_update_string))
		monitor.waitForAbort(interval)
	return logger('SALTS', 'TraktMonitor Service Finished')

def premAccntNotification():
	logger('SALTS', 'Debrid Account Expiry Notification Service Starting')
	from importlib import import_module
	for user, expires, module, cls in (
		('pm.account_id', 'pm.expires', 'premiumize_api', 'PremiumizeAPI'),
		('rd.username', 'rd.expires', 'realdebrid_api', 'RealDebridAPI'),
		('tb.account_id', 'tb.expires', 'torbox_api', 'TorBoxAPI')
	):
		try:
			if not get_setting(user): continue
			if limit := int(get_setting(expires, '7')):
				module = 'debrids.%s' % module
				cls = getattr(import_module(module), cls)
				days_remaining = cls().days_remaining()
				if not days_remaining is None and days_remaining <= limit:
					kodi_utils.notification('%s expires in %s days' % (cls.__name__, days_remaining))
		except: pass
	return logger('SALTS', 'Debrid Account Expiry Notification Service Finished')

class SALTSMonitor(kodi_utils.xbmc_monitor):
	def __enter__(self):
		self.threads = (Thread(target=traktMonitor), Thread(target=premAccntNotification))
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		for i in self.threads: i.join()

	def startUpServices(self):
		try: initializeDatabases()
		except: pass
		try: checkSettingsFile()
		except: pass
		try: databaseMaintenance()
		except: pass
		try: viewsSetWindowProperties()
		except: pass
		try: reuseLanguageInvokerCheck()
		except: pass
		for i in self.threads: i.start()
		try: autoRun()
		except: pass
		try: clearSubs()
		except: pass

	def onScreensaverActivated(self):
		set_property('salts_pause_services', 'true')

	def onScreensaverDeactivated(self):
		clear_property('salts_pause_services')

	def onSettingsChanged(self):
		clear_property('salts_settings')
		kodi_utils.sleep(50)
		make_settings_dict()
		set_property('salts_kodi_menu_cache', get_setting('kodi_menu_cache'))
		set_property('salts_rli_fix', get_setting('rli_fix'))

	def onNotification(self, sender, method, data):
		if method == 'System.OnSleep': set_property('salts_pause_services', 'true')
		elif method == 'System.OnWake': clear_property('salts_pause_services')


logger('SALTS', 'Main Monitor Service Starting')
logger('SALTS', 'Settings Monitor Service Starting')

with SALTSMonitor() as salts:
	salts.startUpServices()
	salts.waitForAbort()

logger('SALTS', 'Settings Monitor Service Finished')
logger('SALTS', 'Main Monitor Service Finished')

