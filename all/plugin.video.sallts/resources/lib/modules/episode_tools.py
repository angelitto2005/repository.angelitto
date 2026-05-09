import json
from datetime import date
from random import choice
from threading import Thread
import _strptime  # fix bug in python import
from windows import open_window
from indexers.metadata import tvshow_meta, season_episodes_meta, all_episodes_meta
from modules import kodi_utils, settings
from modules.utils import get_datetime, adjust_premiered_date
from sources import Sources
# from modules.kodi_utils import logger

ls, build_url = kodi_utils.local_string, kodi_utils.build_url

def get_random_episode(tmdb_id, continual=False):
	meta_user_info, adjust_hours, current_date = settings.metadata_user_info(), settings.date_offset(), get_datetime()
	tmdb_key = str(tmdb_id)
	meta = tvshow_meta('tmdb_id', tmdb_id, meta_user_info, current_date)
	try:
		episodes_data = [i for i in all_episodes_meta(meta, meta_user_info, Thread) if i['premiered']]
		episodes_data = [i for i in episodes_data if not i['season'] == 0 and adjust_premiered_date(i['premiered'], adjust_hours)[0] <= current_date]
	except: episodes_data = []
	if not episodes_data: return None
	if continual:
		episode_history = {}
		episode_list = []
		try:
			episode_history = json.loads(kodi_utils.get_property('salts_random_episode_history'))
			if tmdb_key in episode_history: episode_list = episode_history[tmdb_key]
		except: pass
		episodes_data = [i for i in episodes_data if not i in episode_list] or episodes_data
	chosen_episode = choice(episodes_data)
	if continual:
		episode_list.append(chosen_episode)
		episode_history[tmdb_key] = episode_list
		kodi_utils.set_property('salts_random_episode_history', json.dumps(episode_history))
	title, season, episode = meta['title'], int(chosen_episode['season']), int(chosen_episode['episode'])
	query = title + ' S%.2dE%.2d' % (season, episode)
	display_name = '%s - %dx%.2d' % (title, season, episode)
	ep_name, plot = chosen_episode['title'], chosen_episode['plot']
	try: premiered = adjust_premiered_date(chosen_episode['premiered'], adjust_hours)[1]
	except: premiered = chosen_episode['premiered']
	meta.update({
		'mediatype': 'episode', 'rootname': display_name, 'season': season, 'episode': episode,
		'premiered': premiered, 'ep_name': ep_name, 'plot': plot
	})
	if continual: meta['random_continual'] = 'true'
	else: meta['random'] = 'true'
	url_params = {
		'mode': 'play_media', 'mediatype': 'episode', 'tvshowtitle': meta['rootname'],
		'tmdb_id': meta['tmdb_id'], 'imdb_id': meta.get('imdb_id'), 'season': season, 'episode': episode,
		'query': query, 'meta': json.dumps(meta)
	}
	return meta, url_params

def nextep_playback_info(meta):
	def _build_next_episode_play():
		ep_data = season_episodes_meta(season, meta, settings.metadata_user_info())
		if not ep_data: return 'no_next_episode'
		ep_data = [i for i in ep_data if i['episode'] == episode][0]
		airdate = ep_data['premiered']
		d = airdate.split('-')
		episode_date = date(int(d[0]), int(d[1]), int(d[2]))
		if current_date < episode_date: return 'no_next_episode'
		custom_title = meta_get('custom_title')
		title = custom_title or meta_get('title')
		display_name = '%s - %dx%.2d' % (title, int(season), int(episode))
		meta.update({
			'mediatype': 'episode', 'rootname': display_name, 'season': season, 'episode': episode,
			'premiered': airdate, 'ep_name': ep_data['title'], 'plot': ep_data['plot']
		})
		url_params = {
			'mode': 'play_media', 'mediatype': 'episode', 'tvshowtitle': meta_get('rootname'),
			'tmdb_id': tmdb_id, 'imdb_id': meta.get('imdb_id'), 'season': season, 'episode': episode
		}
		if custom_title: url_params['custom_title'] = custom_title
		return url_params
	meta_get = meta.get
	tmdb_id, current_season, current_episode = meta_get('tmdb_id'), int(meta_get('season')), int(meta_get('episode'))
	try:
		current_date = get_datetime()
		season_data = meta_get('season_data')
		curr_season_data = [i for i in season_data if i['season_number'] == current_season][0]
		season = current_season if current_episode < curr_season_data['episode_count'] else current_season + 1
		episode = current_episode + 1 if current_episode < curr_season_data['episode_count'] else 1
		nextep_info = _build_next_episode_play()
	except: nextep_info = 'error'
	return meta, nextep_info

def execute_scrape_nextep(meta):
	nextep_meta, nextep_params = nextep_playback_info(meta)
	if nextep_params == 'error': return kodi_utils.notification(32574)
	elif nextep_params == 'no_next_episode': return
	if not Sources.background_prep(nextep_params): return kodi_utils.notification(32760)
	Sources.nextep_callback(nextep_params)
	action = open_window(('windows.next_episode', 'NextEpisode'), 'next_episode.xml', meta=nextep_meta, function='next_ep')
	if action == 'cancel':
		Sources.nextep_params.clear()
		return kodi_utils.notification(32736)
	if action == 'play': kodi_utils.player.stop()

def execute_nextep(meta, nextep_settings):
	def _get_nextep_params():
		if 'random_continual' in meta: nextep_params = get_random_episode(meta['tmdb_id'], True)
		else: nextep_params = nextep_playback_info(meta)
		return nextep_params
	def _confirm_threshold():
		nextep_threshold = nextep_settings['threshold']
		if nextep_threshold == 0: return True
		try: current_number = int(kodi_utils.get_property('salts_total_autoplays'))
		except: current_number = 1
		if current_number < nextep_threshold:
			current_number += 1
			kodi_utils.set_property('salts_total_autoplays', str(current_number))
			return True
		if open_window(('windows.next_episode', 'NextEpisode'), 'next_episode.xml', meta=nextep_meta, function='confirm'):
			current_number = 1
			kodi_utils.set_property('salts_total_autoplays', str(current_number))
			return True
		return False
	def _continue_action():
		if run_popup: action = open_window(('windows.next_episode', 'NextEpisode'), 'next_episode.xml', meta=nextep_meta, function='next_ep')
		else: action = 'close'
		return action
	def _control():
		confirm_threshold = False
		final_action = 'cancel'
		while player.isPlayingVideo():
			try:
				total_time = player.getTotalTime()
				curr_time = player.getTime()
				remaining_time = round(total_time - curr_time)
				if remaining_time <= nextep_threshold_check:
					if not confirm_threshold:
						confirm_threshold = _confirm_threshold()
						if not confirm_threshold:
							final_action = 'cancel'
							break
				if remaining_time <= display_nextep_popup:
					final_action = _continue_action()
					break
				kodi_utils.sleep(200)
			except: pass
		return final_action
	player = kodi_utils.player
	run_popup, display_nextep_popup = nextep_settings['run_popup'], nextep_settings['window_time']
	nextep_prep, nextep_threshold_check = nextep_settings['start_prep'], nextep_settings['threshold_check']
	nextep_meta, nextep_params = _get_nextep_params()
	if nextep_params == 'error': return kodi_utils.notification(32574)
	elif nextep_params == 'no_next_episode': return
	if not Sources.background_prep(nextep_params): return kodi_utils.notification(32760)
	Sources.nextep_callback(nextep_params)
	action = _control()
	if action == 'cancel':
		Sources.nextep_params.clear()
		kodi_utils.clear_property('salts_total_autoplays')
		return kodi_utils.notification(32736)
	if action == 'close':
		if run_popup: return
		text = '%s %s S%02dE%02d' % (ls(32801), nextep_meta['title'], nextep_meta['season'], nextep_meta['episode'])
		kodi_utils.notification(text, 6500, nextep_meta['poster'])
	if action == 'play': player.stop()

