"""
	Fenomscrapers Module
"""

from threading import Thread
import traceback
from urllib.parse import parse_qsl
import xbmc
from magneto.modules import control, log_utils

window = control.homeWindow
LOGINFO = 1  # (LOGNOTICE(2) deprecated in 19, use LOGINFO(1))


def routing(sys):
	params = dict(parse_qsl(sys.argv[2].replace('?', '')))
	action = params.get('action')
	name = params.get('name')

	if action is None:
		from magneto.player.navigator import Navigator
		Navigator(params).main()

	elif action == 'MediaPlay':
		from magneto import player
		player.MagnetoPlayer().source_select(params)

	elif action in ('Movies', 'Series', 'Episodes'):
		from magneto.player import navigator
		if action == 'Episodes': cls = navigator.Episodes()
		elif action == 'Series': cls = navigator.Series()
		else: cls = navigator.Movies()
		cls.run(params)

	elif action == 'ShowReadme':
		from magneto.modules import help
		help.get('aioStreams')

	elif action == 'InstallJson':
		from magneto.player import settings
		settings.install_json()

	elif action == 'ColorPick':
		from magneto.player import settings
		settings.color_pick(params)

	elif action == 'MagnetoSettings':
		control.openSettings('0.0', 'script.module.magneto')

	elif action == 'ShowChangelog':
		from magneto.modules import changelog
		changelog.get()

	elif action == 'ShowHelp':
		from magneto.modules import help
		help.get(name)

	elif action == 'Defaults':
		from magneto import sources
		try:
			provider_defaults = control.getProviderDefaults()
			sourceList = []
			sourceList = sources(ret_all=True)
			for name, source in sourceList:
				source_setting = 'provider.' + name
				default_setting = provider_defaults.get(source_setting) or 'false'
				control.setSetting(source_setting, default_setting)
			control.notification(message='Success')
		except: control.notification(message='Error')

	elif action == 'toggleAll':
		from magneto import providers
		sourceList = []
		sourceList = providers.all_providers
		for i in sourceList:
			source_setting = 'provider.' + i
			control.setSetting(source_setting, params['setting'])

	elif action == 'toggleAllHosters':
		from magneto import providers
		sourceList = []
		sourceList = providers.hoster_providers
		for i in sourceList:
			source_setting = 'provider.' + i
			control.setSetting(source_setting, params['setting'])

	elif action == 'toggleAllTorrent':
		from magneto import providers
		sourceList = []
		sourceList = providers.torrent_providers
		for i in sourceList:
			source_setting = 'provider.' + i
			control.setSetting(source_setting, params['setting'])

	elif action == 'toggleAllPackTorrent':
		from magneto import sources
		sourceList = []
		sourceList = sources(ret_all=True)
		for name, source in sourceList:
			setting = 'true' if source.pack_capable else 'false'
			source_setting = 'provider.' + name
			control.setSetting(source_setting, setting)

	elif action == 'cleanSettings':
		control.clean_settings()

	elif action == 'undesirablesSelect':
		from magneto.modules.undesirables import undesirablesSelect
		undesirablesSelect()

	elif action == 'undesirablesInput':
		from magneto.modules.undesirables import undesirablesInput
		undesirablesInput()

	elif action == 'undesirablesUserRemove':
		from magneto.modules.undesirables import undesirablesUserRemove
		undesirablesUserRemove()

	elif action == 'undesirablesUserRemoveAll':
		from magneto.modules.undesirables import undesirablesUserRemoveAll
		undesirablesUserRemoveAll()

	elif action == 'tools_clearLogFile':
		from magneto.modules import log_utils
		cleared = log_utils.clear_logFile()
		if cleared == 'canceled': pass
		elif cleared: control.notification(message='Magneto Log File Successfully Cleared')
		else: control.notification(message='Error clearing Magneto Log File, see kodi.log for more info')

	elif action == 'tools_viewLogFile':
		from magneto.modules import log_utils
		log_utils.view_LogFile(name)

	elif action == 'tools_uploadLogFile':
		from magneto.modules import log_utils
		log_utils.upload_LogFile()

	elif action == 'healthCheck':
		from magneto.modules.health import magneto
		magneto()


class SettingsServiceMonitor(control.monitor_class):
	def __enter__(self):
		xbmc.log('[ script.module.magneto ]  Service Started', LOGINFO)
		self._check_settings_file()
		window.setProperty('magneto.debug.reversed', control.setting('debug.reversed'))
		xbmc.log('[ script.module.magneto ]  Settings Monitor Service Starting...', LOGINFO)
		return self

	def __exit__(self, exc_type, exc_value, tb):
		if exc_type: traceback.print_exception(exc_type, exc_value, tb)
		xbmc.log('[ script.module.magneto ]  Service Stopped', LOGINFO)
		return True # Suppress exceptions during teardown to prevent crashes

	def run(self):
		with self:
			self._check_version_update()
			Thread(target=self._check_undesirables_database).start()
			self.waitForAbort()

	def onSettingsChanged(self):
		window.clearProperty('magneto_settings')
		control.sleep(50)
		control.make_settings_dict()
		control.refresh_debugReversed()

	def _check_settings_file(self):
		xbmc.log('[ script.module.magneto ]  CheckSettingsFile Service Starting...', LOGINFO)
		try:
			profile_dir = control.dataPath
			if not control.existsPath(profile_dir):
				if control.makeDirs(profile_dir):
					log_utils.log(f"{profile_dir} : created successfully", LOGINFO)
			else: log_utils.log(f"{profile_dir} : already exists", LOGINFO)
			settings_xml = control.joinPath(profile_dir, 'settings.xml')
			if not control.existsPath(settings_xml):
				control.setSetting('module.provider', 'Magneto')
				log_utils.log(f"{settings_xml} : created successfully", LOGINFO)
			else: log_utils.log(f"{settings_xml} : already exists", LOGINFO)
			window.clearProperty('magneto_settings')
			control.make_settings_dict()
			xbmc.log('[ script.module.magneto ]  CheckSettingsFile Service Finished', LOGINFO)
		except Exception:
			traceback.print_exc()

	def _check_undesirables_database(self):
		xbmc.log('[ script.module.magneto ]  CheckUndesirablesDatabase Service Starting...', LOGINFO)
		try:
			from magneto.modules import undesirables
			old_database = undesirables.Undesirables().check_database()
			if old_database: undesirables.add_new_default_keywords()
			xbmc.log('[ script.module.magneto ]  CheckUndesirablesDatabase Service Finished', LOGINFO)
		except Exception:
			traceback.print_exc()

	def _check_version_update(self):
		if not control.isVersionUpdate(): return
		control.clean_settings()
		xbmc.log('[ script.module.magneto ]  Settings file cleaned complete', LOGINFO)
