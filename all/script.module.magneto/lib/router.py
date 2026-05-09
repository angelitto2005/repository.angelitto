"""
	Fenomscrapers Module
"""

from sys import argv
from urllib.parse import parse_qsl
from magneto import providers
from magneto.modules import control

params = dict(parse_qsl(argv[2].replace('?', '')))
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
	sourceList = []
	sourceList = providers.all_providers
	for i in sourceList:
		source_setting = 'provider.' + i
		control.setSetting(source_setting, params['setting'])

elif action == 'toggleAllHosters':
	sourceList = []
	sourceList = providers.hoster_providers
	for i in sourceList:
		source_setting = 'provider.' + i
		control.setSetting(source_setting, params['setting'])

elif action == 'toggleAllTorrent':
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
