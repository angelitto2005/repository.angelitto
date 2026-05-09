from threading import Thread
from modules.kodi_utils import local_string as ls, notification, confirm_dialog, ok_dialog, show_busy_dialog, hide_busy_dialog
from modules.utils import manual_function_import

debrid_dict = {
	'realdebrid': 'RealDebridAPI', 'premiumize': 'PremiumizeAPI', 'torbox': 'TorBoxAPI'
}

class Debrid:
	def __init__(self, debrid=None):
		if not debrid or not debrid in debrid_dict: return
		function = manual_function_import('debrids.%s_api' % debrid, debrid_dict[debrid])
		self.debrid = getattr(function, 'name', debrid)
		self.api = function()

	def manual_add_magnet_to_cloud(self, hash, name):
		if not confirm_dialog(text=ls(32831) % self.debrid.upper(), top_space=True): return
		show_busy_dialog()
		self.api.clear_cache()
		if str(hash).startswith('magnet'): magnet = hash
		else: magnet = 'magnet:?xt=urn:btih:%s' % hash
		result = self.api.create_transfer(magnet)
		hide_busy_dialog()
		if not result: notification(32575)
		notification(32576)

	def unchecked_magnet_status(self, hash, name):
		show_busy_dialog()
		if str(hash).startswith('magnet'): magnet = hash
		else: magnet = 'magnet:?xt=urn:btih:%s' % hash
		result = self.api.parse_magnet_pack(magnet, hash)
		hide_busy_dialog()
		if not result: return ok_dialog(text='Not Cached at [B]%s[/B]' % self.debrid.upper(), top_space=True)
		torrent_id = next((i['torrent_id'] for i in result if 'torrent_id' in i), None)
		if torrent_id: Thread(target=self.api.delete_torrent, args=(torrent_id,)).start()
		ok_dialog(text='Cached at [B]%s[/B]' % self.debrid.upper(), top_space=True)

