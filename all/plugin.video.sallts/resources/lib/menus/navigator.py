import sys
from caches.navigator_cache import navigator_cache as nc
from modules import kodi_utils as ku, settings as ks
# logger = ku.logger

media_path, ls, build_url, notification, list_dirs = ku.media_path, ku.local_string, ku.build_url, ku.notification, ku.list_dirs
make_listitem, add_item, add_dir, end_directory, add_items = ku.make_listitem, ku.add_item, ku.add_dir, ku.end_directory, ku.add_items
set_content, set_view_mode, set_sort_method, set_category = ku.set_content, ku.set_view_mode, ku.set_sort_method, ku.set_category
_in_str, mov_str, tv_str, edit_str = ls(32484), ls(32028), ls(32029), ls(32705)
browse_str, add_menu_str, s_folder_str = ls(32706), ls(32730), ls(32731)

class Navigator:
	def __init__(self, params):
		params['handle'] = int(sys.argv[1])
		params['fanart'] = ks.addon_fanart()
		self.params = params
		self.params_get = self.params.get
		self.list_name = self.params_get('action', 'RootList')

	def downloads(self):
		dl_str, pr_str, im_str = ls(32107), ls(32485), ls(32798)
		mov_path, ep_path = ks.download_directory('movie'), ks.download_directory('episode')
		prem_path, im_path = ks.download_directory('premium'), ks.download_directory('image')
		n_ins = _in_str % (dl_str.upper(), '')
		self._add_item({'mode': 'navigator.folder_navigator', 'folder_path': mov_path , 'name': mov_str}, 'movies.png' , n_ins)
		self._add_item({'mode': 'navigator.folder_navigator', 'folder_path': ep_path  , 'name': tv_str }, 'tv.png'     , n_ins)
		self._add_item({'mode': 'navigator.folder_navigator', 'folder_path': prem_path, 'name': pr_str }, 'premium.png', n_ins)
		self._add_item({'mode': 'browser_image', 'folder_path': im_path,                'name': im_str }, 'people.png' , n_ins, False)
		self._end_directory()

	def discover_main(self):
		discover_str, his_str, help_str = ls(32451), ls(32486), ls(32487)
		movh_str, tvh_str = '%s %s' % (mov_str, his_str), '%s %s' % (tv_str, his_str)
		n_ins = _in_str % (discover_str.upper(), '')
		self._add_item({'mode': 'discover.movie', 'mediatype': 'movie',    'name': mov_str }, 'discover.png', n_ins)
		self._add_item({'mode': 'discover.tvshow', 'mediatype': 'tvshow',  'name': tv_str  }, 'discover.png', n_ins)
		self._add_item({'mode': 'discover.history', 'mediatype': 'movie',  'name': movh_str}, 'discover.png', n_ins)
		self._add_item({'mode': 'discover.history', 'mediatype': 'tvshow', 'name': tvh_str }, 'discover.png', n_ins)
		self._add_item({'mode': 'discover.help',                           'name': help_str}, 'discover.png', n_ins, False)
		self._end_directory()

	def premium(self):
		debrids = ks.debrid_enabled()
		if 'realdebrid' in debrids: self.realdebrid()
		if 'premiumize' in debrids: self.premiumize()
		if 'torbox' in debrids: self.torbox()
		self._end_directory()

	def realdebrid(self):
		rd_str, acc_str, his_str, cloud_str = ls(32054), ls(32494), ls(32486), ls(32496)
		clca_str, n_ins = ls(32497) % rd_str, _in_str % (rd_str.upper(), '')
		self._add_item({'mode': 'realdebrid.rd_torrent_cloud',      'name': cloud_str}, 'realdebrid.png', n_ins)
		self._add_item({'mode': 'realdebrid.rd_downloads',          'name': his_str  }, 'realdebrid.png', n_ins)
		self._add_item({'mode': 'realdebrid.show_account_info',     'name': acc_str  }, 'realdebrid.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'rd_cloud', 'name': clca_str }, 'realdebrid.png', n_ins, False)

	def premiumize(self):
		pm_str, acc_str, his_str, cloud_str = ls(32061), ls(32494), ls(32486), ls(32496)
		clca_str, n_ins = ls(32497) % pm_str, _in_str % (pm_str.upper(), '')
		self._add_item({'mode': 'premiumize.pm_torrent_cloud',      'name': cloud_str}, 'premiumize.png', n_ins)
		self._add_item({'mode': 'premiumize.pm_downloads',          'name': his_str  }, 'premiumize.png', n_ins)
		self._add_item({'mode': 'premiumize.show_account_info',     'name': acc_str  }, 'premiumize.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'pm_cloud', 'name': clca_str }, 'premiumize.png', n_ins, False)

	def torbox(self):
		tor_str, usenet_str, web_str = 'Torrent', 'Usenet', 'Web Download'
		tb_str, cloud_str, ai_str = 'TorBox', ls(32496), ls(32494)
		clca_str, n_ins = ls(32497) % tb_str, _in_str % (tb_str.upper(), '')
		self._add_item({'mode': 'torbox.tb_torrent_cloud', 'mediatype': 'torent', 'name': tor_str   }, 'torbox.png', n_ins)
		self._add_item({'mode': 'torbox.tb_torrent_cloud', 'mediatype': 'usenet', 'name': usenet_str}, 'torbox.png', n_ins)
		self._add_item({'mode': 'torbox.tb_torrent_cloud', 'mediatype': 'webdl',  'name': web_str   }, 'torbox.png', n_ins)
		self._add_item({'mode': 'torbox.show_account_info',                       'name': ai_str    }, 'torbox.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'tb_cloud',               'name': clca_str  }, 'torbox.png', n_ins, False)

	def favorites(self):
		fav_str = ls(32453)
		clear_fav_str = ls(32497) % fav_str
		n_ins, c_n_ins = _in_str % (fav_str.upper(), ''), _in_str % (ls(32524).upper(), '')
		self._add_item({'mode': 'build_movie_list', 'action': 'favorites_movies',   'name': mov_str      }, 'movies.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'favorites_tvshows', 'name': tv_str       }, 'tv.png'    , n_ins)
		self._add_item({'mode': 'favorites_choice', 'cache': 'clear_favorites',     'name': clear_fav_str}, 'tools.png' , c_n_ins, False)
		self._end_directory()

	def my_content(self):
		trakt_str, coll_str, wlist_str, fav_str, ls_str = ls(32037), ls(32499), ls(32500), ls(32453), ls(32501)
		t_n_ins, m_n_ins, f_n_ins = _in_str % (trakt_str.upper(), ''), _in_str % ('MDBList'.upper(), ''), _in_str % ('FlickList'.upper(), '')
		t_str, user_str, l_str, ai_str, ml_str, drp_str = ls(32037), ls(32065), ls(32501), ls(32494), ls(32454), 'Dropped TV Shows'
		tu_str, pu_str = '%s %s %s' % (ls(32458), user_str, l_str), '%s %s %s' % (ls(32459), user_str, l_str)
		sea_str, n_ins = '%s %s' % (ls(32477), l_str), _in_str % (t_str.upper(), '')
		mdb_mc_str, mdb_tc_str = 'My %s %s' % (coll_str, mov_str), 'My %s %s' % (coll_str, tv_str)
		mdb_mw_str, mdb_tw_str = 'My %s %s' % (wlist_str, mov_str), 'My %s %s' % (wlist_str, tv_str)
		fl_mf_str, fl_tf_str = 'My %s %s' % (fav_str[:-1], mov_str), 'My %s %s' % (fav_str[:-1], tv_str)
		trakt_status = ku.get_setting('trakt_user') not in ('', None)
		mdblist_status = ku.get_setting('mdblist.token') not in ('', None)
		flicklist_status = ku.get_setting('flicklist.token') not in ('', None)
		if trakt_status:
			self._add_item({'mode': 'navigator.trakt_lists',                                                  'name': ls_str   }, 'trakt.png', t_n_ins)
			self._add_item({'mode': 'navigator.trakt_watchlists',                                             'name': wlist_str}, 'trakt.png', t_n_ins)
			self._add_item({'mode': 'navigator.trakt_collections',                                            'name': coll_str }, 'trakt.png', t_n_ins)
			self._add_item({'mode': 'navigator.trakt_favorites',                                              'name': fav_str  }, 'trakt.png', t_n_ins)
			self._add_item({'mode': 'trakt.trakt_account_info',                                               'name': ai_str   }, 'trakt.png', t_n_ins, False)
		self._add_item({'mode': 'build_trakt_list.get_trakt_trending_popular_lists', 'list_type': 'trending', 'name': tu_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_trakt_list.get_trakt_trending_popular_lists', 'list_type': 'popular' , 'name': pu_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_trakt_list.search_trakt_lists',                                        'name': sea_str}, 'trakt.png', n_ins)
		if mdblist_status:
			self._add_item({'mode': 'build_mdbl_list.get_mdbl_lists', 'list_type': 'my_lists', 'name': ml_str    }, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'build_movie_list', 'action': 'mdblist_watchlist',         'name': mdb_mw_str}, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'build_tvshow_list', 'action': 'mdblist_watchlist',        'name': mdb_tw_str}, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'build_movie_list', 'action': 'mdblist_collection',        'name': mdb_mc_str}, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'build_tvshow_list', 'action': 'mdblist_collection',       'name': mdb_tc_str}, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'build_tvshow_list', 'action': 'mdblist_droplist',         'name': drp_str   }, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'mdblist.mdbl_account_info',                               'name': ai_str    }, 'mdblist.png', m_n_ins, False)
			self._add_item({'mode': 'build_mdbl_list.get_mdbl_top_lists',                      'name': pu_str    }, 'mdblist.png', m_n_ins)
			self._add_item({'mode': 'build_mdbl_list.search_mdbl_lists',                       'name': sea_str   }, 'mdblist.png', m_n_ins)
		if flicklist_status:
			self._add_item({'mode': 'build_flicklist_list.get_flicklist_lists',           'name': ml_str    }, 'DefaultPlaylist.png', f_n_ins)
			self._add_item({'mode': 'build_movie_list', 'action': 'flicklist_watchlist',  'name': mdb_mw_str}, 'DefaultPlaylist.png', f_n_ins)
			self._add_item({'mode': 'build_tvshow_list', 'action': 'flicklist_watchlist', 'name': mdb_tw_str}, 'DefaultPlaylist.png', f_n_ins)
			self._add_item({'mode': 'build_movie_list', 'action': 'flicklist_favorites',  'name': fl_mf_str }, 'DefaultPlaylist.png', f_n_ins)
			self._add_item({'mode': 'build_tvshow_list', 'action': 'flicklist_favorites', 'name': fl_tf_str }, 'DefaultPlaylist.png', f_n_ins)
			self._add_item({'mode': 'build_tvshow_list', 'action': 'flicklist_droplist',  'name': drp_str   }, 'DefaultPlaylist.png', f_n_ins)
			self._add_item({'mode': 'flicklist.flicklist_account_info',                   'name': ai_str    }, 'DefaultPlaylist.png', f_n_ins, False)
		self._end_directory()

	def trakt_collections(self):
		# use 'new_page' to pass the type of list to be processed when using 'trakt_collection_lists'...
		t_str, col_str = ls(32037), ls(32499)
		tcol_str = '%s %s' % (t_str, col_str)
		n_ins = _in_str % (tcol_str.upper(), '')
		mrec_str, mran_str = '%s %s' % (ls(32498), mov_str), '%s %s' % (ls(32504), mov_str)
		tvrec_str, tvran_str, ra_str = '%s %s' % (ls(32498), tv_str), '%s %s' % (ls(32504), tv_str), '%s %s' % (ls(32505), ls(32506))
		n_ins = _in_str % (col_str.upper(), '')
		self._add_item({'mode': 'build_movie_list', 'action': 'trakt_collection',                              'name': mov_str  }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_collection',                             'name': tv_str   }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_movie_list', 'action': 'trakt_collection_lists', 'new_page': 'recent',  'name': mrec_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_movie_list', 'action': 'trakt_collection_lists', 'new_page': 'random',  'name': mran_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_collection_lists', 'new_page': 'recent', 'name': tvrec_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_collection_lists', 'new_page': 'random', 'name': tvran_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_my_calendar', 'recently_aired': 'true',                                 'name': ra_str   }, 'trakt.png', n_ins)
		self._end_directory()

	def trakt_watchlists(self):
		t_str, watchlist_str = ls(32037), ls(32500)
		trakt_watchlist_str = '%s %s' % (t_str, watchlist_str)
		n_ins = _in_str % (trakt_watchlist_str.upper(), '')
		tmdb_status = ku.get_setting('tmdb.account_id') not in ('', None)
		self._add_item({'mode': 'build_movie_list', 'action': 'trakt_watchlist',  'name': mov_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_watchlist', 'name': tv_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'tmdb.import_trakt_watchlist',                    'name': 'Export to TMDB'}, 'trakt.png', n_ins, False) if tmdb_status else None
		self._end_directory()

	def trakt_favorites(self):
		t_str, fav_str = ls(32037), 'Favorites'
		trakt_fav_str = '%s %s' % (t_str, fav_str)
		n_ins = _in_str % (trakt_fav_str.upper(), '')
		self._add_item({'mode': 'build_movie_list', 'action': 'trakt_favorites',  'name': mov_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_favorites', 'name': tv_str }, 'trakt.png', n_ins)
		self._end_directory()

	def trakt_lists(self):
		t_str, ml_str, ll_str, rec_str = ls(32037), ls(32454), ls(32502), ls(32503)
		cal_str, ani_str, drp_str = ls(32081), 'Anime Calendar', 'Dropped TV Shows'
		n_ins = _in_str % (t_str.upper(), '')
		self._add_item({'mode': 'build_trakt_list.get_trakt_lists', 'list_type': 'my_lists',    'name': ml_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_trakt_list.get_trakt_lists', 'list_type': 'liked_lists', 'name': ll_str }, 'trakt.png', n_ins)
		self._add_item({'mode': 'navigator.trakt_recommendations',                              'name': rec_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_droplist',                'name': drp_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_my_calendar',                                            'name': cal_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_my_anime_calendar',                                      'name': ani_str}, 'trakt.png', n_ins)
		self._end_directory()

	def trakt_recommendations(self):
		rec_str = ls(32503)
		n_ins = _in_str % (rec_str.upper(), '')
		self._add_item({'mode': 'build_movie_list', 'action': 'trakt_recommendations',  'name': mov_str}, 'trakt.png', n_ins)
		self._add_item({'mode': 'build_tvshow_list', 'action': 'trakt_recommendations', 'name': tv_str }, 'trakt.png', n_ins)
		self._end_directory()

	def search(self):
		search_str, people_str = ls(32450), ls(32507)
		coll_str, s_n_ins = '%s %s (%s)' % (mov_str, ls(32499), ls(32068)), _in_str % (search_str.upper(), '')
		self._add_item({'mode': 'search_history', 'action': 'movie',               'name': mov_str         }, 'search_movie.png' , s_n_ins)
		self._add_item({'mode': 'search_history', 'action': 'tvshow',              'name': tv_str          }, 'search_tv.png'    , s_n_ins)
		self._add_item({'mode': 'search_history', 'action': 'people',              'name': people_str      }, 'search_people.png', s_n_ins)
		self._add_item({'mode': 'search_history', 'action': 'tmdb_collections',    'name': coll_str        }, 'search_tmdb.png'  , s_n_ins)
		self._end_directory()

	def settings(self):
		salts_str, manager_str, changelog_str, short_str = ls(32036), ls(32513), ls(32508), ls(32514)
		log_utils, views_str, clean_str, lang_inv_str, ms_str = ls(32777), ls(32510), ls(32512), ls(32978), ls(32455)
		settings_str, changelog_log_viewer_str = ls(32247), '%s & %s' % (changelog_str, log_utils)
		shortcut_manager_str = '%s %s' % (short_str, manager_str)
		n_ins, l_str = _in_str % (settings_str.upper(), ''), _in_str % ('LINKS', '')
		self._add_item({'mode': 'open_settings', 'query': '4.0', 'name': salts_str               }, 'salts.png', n_ins, False)
		self._add_item({'mode': 'myservices',                    'name': ms_str                  }, 'settings.png', n_ins, False)
		self._add_item({'mode': 'navigator.clear_info',          'name': clean_str               }, 'settings.png', n_ins)
#		self._add_item({'mode': 'navigator.log_utils',           'name': changelog_log_viewer_str}, 'settings.png', n_ins)
		self._add_item({'mode': 'navigator.set_view_modes',      'name': views_str               }, 'settings.png', n_ins)
		self._add_item({'mode': 'navigator.shortcut_folders',    'name': shortcut_manager_str    }, 'settings.png', n_ins)
		self._add_item({'mode': 'toggle_language_invoker',       'name': lang_inv_str            }, 'settings.png', n_ins, False)
		self.log_utils()
		self._add_item({'mode': 'refer_link', 'query': 'realdebrid',  'name': 'Real Debrid Referral Link'}, 'realdebrid.png', l_str, False)
		self._add_item({'mode': 'refer_link', 'query': 'torbox',      'name': 'TorBox Referral Link'     }, 'torbox.png',     l_str, False)
		self._end_directory()

	def clear_info(self):
		cache_str, clca_str, clean_str, all_str, settings_str = ls(32524), ls(32497), ls(32526), ls(32525), ls(32247)
		clean_set_cache_str = '%s %s %s' % (clean_str, ls(32247), ls(32524))
		clean_databases_str = '%s %s' % (clean_str, ls(32003))
		clean_all_str = '%s %s %s' % (clean_str, all_str, settings_str)
		clear_all_str, clear_meta_str = clca_str % all_str, clca_str % ls(32527)
		clear_list_str, clear_trakt_str = clca_str % ls(32501), clca_str % ls(32037)
		clear_mdbl_str, clear_flickl_str = clca_str % 'MDBList', clca_str % 'FlickList'
		clear_imdb_str, clint_str, clext_str = clca_str % ls(32064), clca_str % ls(32096), clca_str % ls(32118)
		clear_pm_str, clear_rd_str, clear_tb_str = clca_str % ls(32061), clca_str % ls(32054), clca_str % 'TorBox'
		clear_all_upper = '[B]%s[/B]' % clear_all_str.upper()
		n_ins, clean_ins = _in_str % (cache_str.upper(), ''), _in_str % (clean_str.upper(), '')
		self._add_item({'mode': 'clean_settings',                            'name': clean_all_str      }, 'tools.png', clean_ins, False)
		self._add_item({'mode': 'clean_settings_window_properties',          'name': clean_set_cache_str}, 'tools.png', clean_ins, False)
		self._add_item({'mode': 'clean_databases',                           'name': clean_databases_str}, 'tools.png', clean_ins, False)
		self._add_item({'mode': 'clear_all_cache',                           'name': clear_all_upper    }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'meta',              'name': clear_meta_str     }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'list',              'name': clear_list_str     }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'trakt',             'name': clear_trakt_str    }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'mdblist',           'name': clear_mdbl_str     }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'flicklist',         'name': clear_flickl_str   }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'imdb',              'name': clear_imdb_str     }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'internal_scrapers', 'name': clint_str          }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'pm_cloud',          'name': clear_pm_str       }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'rd_cloud',          'name': clear_rd_str       }, 'tools.png', n_ins, False)
		self._add_item({'mode': 'clear_cache', 'cache': 'tb_cloud',          'name': clear_tb_str       }, 'tools.png', n_ins, False)
		self._end_directory()

	def set_view_modes(self):
		set_views_str, lists_str, root_str, movies_str = ls(32510), ls(32501), ls(32457), ls(32028)
		tvshows_str, season_str, episode_str = ls(32029), ls(32537), ls(32506)
		premium_files_str, ep_lists_str = ls(32485), '%s %s' % (episode_str, lists_str)
		n_ins, reset_str = _in_str % (set_views_str.upper(), ''), 'Reset All Views'
		self._add_item({'mode': 'choose_view', 'view_type': 'view.main', 'content': '', 'exclude_external': 'true',                   'name': root_str         }, 'settings.png', n_ins)
		self._add_item({'mode': 'choose_view', 'view_type': 'view.movies', 'content': 'movies', 'exclude_external': 'true',           'name': movies_str       }, 'settings.png', n_ins)
		self._add_item({'mode': 'choose_view', 'view_type': 'view.tvshows', 'content': 'tvshows', 'exclude_external': 'true',         'name': tvshows_str      }, 'settings.png', n_ins)
		self._add_item({'mode': 'choose_view', 'view_type': 'view.seasons', 'content': 'seasons', 'exclude_external': 'true',         'name': season_str       }, 'settings.png', n_ins)
		self._add_item({'mode': 'choose_view', 'view_type': 'view.episodes', 'content': 'episodes', 'exclude_external': 'true',       'name': episode_str      }, 'settings.png', n_ins)
		self._add_item({'mode': 'choose_view', 'view_type': 'view.episodes_lists', 'content': 'episodes', 'exclude_external': 'true', 'name': ep_lists_str     }, 'settings.png', n_ins)
		self._add_item({'mode': 'choose_view', 'view_type': 'view.premium', 'content': 'files', 'exclude_external': 'true',           'name': premium_files_str}, 'settings.png', n_ins)
		self._add_item({'mode': 'clear_view', 'view_type': 'all',                                                                     'name': reset_str        }, 'settings.png', n_ins, False)
		self._end_directory()

	def log_utils(self):
		salts_vstr, log_path = ku.get_addoninfo('version'), 'special://home/addons/%s/changelog.txt'
		kl_loc, mt_str = 'special://logpath/kodi.log', log_path % 'plugin.video.sallts'
		salts_str, cl_str, lut_str, k_str, lv_str = ls(32036), ls(32508), ls(32777), ls(32538), ls(32509)
		mh_str, klv_h, klu_h = '%s  [I](v.%s)[/I]' % (salts_str, salts_vstr), '%s %s' % (k_str, lv_str), ls(32853)
		cl_n_ins, lu_n_ins, k_n_ins = _in_str % (cl_str.upper(), ''), _in_str % (lut_str.upper(), ''), _in_str % ('Kodi'.upper(), '')
		self._add_item({'mode': 'show_text', 'heading': mh_str, 'file': mt_str, 'exclude_external': 'true',                    'name': mh_str}, 'lists.png', cl_n_ins, False)
		self._add_item({'mode': 'show_text', 'heading': klv_h, 'file': kl_loc, 'kodi_log': 'true', 'exclude_external': 'true', 'name': klv_h }, 'lists.png', lu_n_ins, False)
		self._add_item({'mode': 'upload_logfile', 'exclude_external': 'true',                                                  'name': klu_h }, 'lists.png', lu_n_ins, False)

	def years(self):
		from modules.meta_lists import years
		menu_type = self.params_get('menu_type')
		mode = 'build_movie_list' if menu_type == 'movie' else 'build_tvshow_list'
		action = 'tmdb_movies_year' if menu_type == 'movie' else 'tmdb_tv_year'
		lst_ins = self.make_list_name(menu_type)
		for i in years():
			list_name = '%s: %s %s' % (lst_ins.upper(), str(i), ls(32460))
			self._add_item({'mode': mode, 'action': action, 'year': str(i), 'name': str(i)}, 'calender.png', list_name=list_name)
		self._end_directory()

	def anime_years(self):
		from modules.meta_lists import years
		menu_type = self.params_get('menu_type')
		mode = 'build_movie_list' if menu_type == 'movie' else 'build_tvshow_list'
		action = 'tmdb_moviesanime_year' if menu_type == 'movie' else 'tmdb_tvanime_year'
		lst_ins = self.make_list_name(menu_type)
		for i in years():
			list_name = 'ANIME %s: %s %s' % (lst_ins.upper(), str(i), ls(32460))
			self._add_item({'mode': mode, 'action': action, 'year': str(i), 'name': str(i)}, 'calender.png', list_name=list_name)
		self._end_directory()

	def genres(self):
		import json
		menu_type = self.params_get('menu_type')
		if menu_type == 'movie':
			from modules.meta_lists import movie_genres as genre_list
			mode, action = 'build_movie_list', 'tmdb_movies_genres'
		else:
			from modules.meta_lists import tvshow_genres as genre_list
			mode, action = 'build_tvshow_list', 'tmdb_tv_genres'
		lst_ins = self.make_list_name(menu_type)
		self._add_item({'mode': 'navigator.multiselect_genres', 'genre_list': json.dumps(genre_list), 'menu_type': menu_type, 'exclude_external': 'true', 'name': ls(32789)}, 'genres.png', isFolder=False)
		for genre, value in sorted(genre_list.items()):
			list_name = '%s: %s %s' % (lst_ins.upper(), genre, ls(32470))
			self._add_item({'mode': mode, 'action': action, 'genre_id': value[0], 'name': genre}, 'genres.png', list_name=list_name)
		self._end_directory()

	def anime_genres(self):
		menu_type = self.params_get('menu_type')
		if menu_type == 'movie':
			from modules.meta_lists import movie_genres as genre_list
			mode, action = 'build_movie_list', 'tmdb_moviesanime_genres'
		else:
			from modules.meta_lists import tvshow_genres as genre_list
			mode, action = 'build_tvshow_list', 'tmdb_tvanime_genres'
		lst_ins = self.make_list_name(menu_type)
		for genre, value in sorted(genre_list.items()):
			list_name = 'ANIME %s: %s %s' % (lst_ins.upper(), genre, ls(32470))
			self._add_item({'mode': mode, 'action': action, 'genre_id': value[0], 'name': genre}, 'genres.png', list_name=list_name)
		self._end_directory()

	def multiselect_genres(self):
		import json
		def _builder():
			for genre, value in genre_list.items():
				function_list_append(value[0])
				yield {'line1': genre, 'icon': '%s%s' % (icon_path, 'genres.png')}
		menu_type, genre_list, icon_path = self.params['menu_type'], self.params['genre_list'], media_path()
		function_list = []
		function_list_append = function_list.append
		genre_list = dict(sorted(json.loads(genre_list).items()))
		list_items = list(_builder())
		kwargs = {'items': json.dumps(list_items), 'heading': ls(32847), 'enumerate': 'false', 'multi_choice': 'true', 'multi_line': 'false'}
		genre_ids = ku.select_dialog(function_list, **kwargs)
		if genre_ids is None: return
		genre_id = ','.join(genre_ids)
		if menu_type == 'movie': url = {'mode': 'build_movie_list', 'action': 'tmdb_movies_genres', 'genre_id': genre_id}
		else: url = {'mode': 'build_tvshow_list', 'action': 'tmdb_tv_genres', 'genre_id': genre_id}
		return ku.execute_builtin('Container.Update(%s)' % build_url(url))

	def networks(self):
		from modules.meta_lists import networks
		lst_ins = self.make_list_name(self.params_get('menu_type'))
		for item in sorted(networks, key=lambda k: k['name']):
			list_name = '%s: %s %s' % (lst_ins.upper(), item['name'], ls(32480))
			self._add_item({'mode': 'build_tvshow_list', 'action': 'tmdb_tv_networks', 'network_id': item['id'], 'name': item['name']}, item['logo'], list_name=list_name)
		self._end_directory()

	def because_you_watched(self):
		from caches.watched_cache import get_watched_info_movie, get_watched_info_tv
		def _convert_salts_watched_episodes_info(watched_indicators):
			seen = set()
			_watched = get_watched_info_tv(watched_indicators)
			_watched.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
			return [(i[0], i[3], i[4], [(i[1], i[2])]) for i in _watched if not (i[0] in seen or seen.add(i[0]))]
		watched_indicators = ks.watched_indicators()
		mediatype = self.params_get('menu_type')
		function = get_watched_info_movie if mediatype == 'movie' else _convert_salts_watched_episodes_info
		mode = 'build_movie_list' if mediatype == 'movie' else 'build_tvshow_list'
		action = 'tmdb_movies_recommendations' if mediatype == 'movie' else 'tmdb_tv_recommendations'
		recently_watched = function(watched_indicators)
		recently_watched = sorted(recently_watched, key=lambda k: k[2], reverse=True)
		because_ins = '[I]%s[/I]  [B]%s[/B]' % (ls(32474), '%s')
		for item in recently_watched:
			tmdb_id = item[0]
			if mediatype == 'movie': name = because_ins % item[1]
			else:
				season, episode = item[3][-1]
				name = because_ins % '%s - %sx%s' % (item[1], season, episode)
			self._add_item({'mode': mode, 'action': action, 'tmdb_id': tmdb_id, 'exclude_external': 'true', 'name': name}, 'because_you_watched.png')
		self._end_directory()

	def folder_navigator(self):
		import os
		from modules.utils import clean_file_name, normalize
		def _process():
			for item, isFolder in items:
				try:
					url = os.path.join(folder_path, item)
					listitem = make_listitem()
					listitem.setLabel(clean_file_name(normalize(item)))
					listitem.setArt({'fanart': fanart})
					yield (url, listitem, isFolder)
				except: pass
		handle, fanart = self.params_get('handle'), self.params_get('fanart')
		folder_path = self.params_get('folder_path')
		sources_folders = self.params_get('sources_folders')
		dirs, files = list_dirs(folder_path)
		items = [(i, True) for i in dirs] + [(i, False) for i in files]
		add_items(handle, list(_process()))
		set_sort_method(handle, 'files')
		self._end_directory()

	def shortcut_folders(self):
		def _builder():
			for i in folders:
				try:
					cm = []
					cm_append = cm.append
					contents = eval(i[1])
					name, icon = i[0], '%s%s' % (icon_path, 'folder.png')
					display_name = '[B]%s : [/B] %s ' % (short_str.upper(), name)
					url_params = {'name': name, 'iconImage': 'folder.png', 'external_list_item': 'True'}
					url = build_url({'mode': 'navigator.build_shortcut_folder_list', 'shortcut_folder': 'True', **url_params})
					cm_append((delete_str, 'RunPlugin(%s)'% build_url({'mode': 'menu_editor.shortcut_folder_delete', 'list_name': name})))
					listitem = make_listitem()
					listitem.setLabel(display_name)
					listitem.addContextMenuItems(cm)
					listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
					yield (url, listitem, True)
				except: pass
		handle, fanart, icon_path = self.params_get('handle'), self.params_get('fanart'), media_path()
		short_str, delete_str, new_folder_str = ls(32514), ls(32703), '[B]%s...[/B]' % ls(32702)
		add_dir(handle, {'mode': 'menu_editor.shortcut_folder_make'}, new_folder_str, media_path('new.png'), isFolder=False)
		folders = nc.get_shortcut_folders()
		if folders: add_items(handle, list(_builder()))
		self._end_directory()

	def build_shortcut_folder_list(self):
		def _process():
			for item_position, item in enumerate(contents):
				try:
					cm = []
					cm_append = cm.append
					item_get = item.get
					name = item_get('name', 'Error: No Name')
					icon = item_get('iconImage') if item_get('network_id', '') != '' else '%s%s' % (icon_path, item_get('iconImage'))
					isFolder = False if item_get('isFolder', '') == 'false' else True
					url = build_url(item)
					edit_params = {'mode': 'menu_editor.edit_menu_shortcut_folder', 'active_list': list_name, 'position': item_position}
					cm_append((edit_str,'RunPlugin(%s)' % build_url(edit_params)))
					listitem = make_listitem()
					listitem.setLabel(name)
					listitem.addContextMenuItems(cm)
					listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
					yield (url, listitem, isFolder)
				except: pass
		handle, fanart, icon_path = self.params_get('handle'), self.params_get('fanart'), media_path()
		list_name = self.params_get('name')
		contents = nc.get_shortcut_folder_contents(list_name)
		add_items(handle, list(_process()))
		self._end_directory()

	def main(self):
		def build_main_lists():
			for item_position, item in enumerate(contents):
				try:
					cm = []
					cm_append = cm.append
					item_get = item.get
					if item_get('iconImage') in ('', 'None', None): icon = 'DefaultFolder.png'
					elif str(item_get('iconImage')).startswith('Default'): icon = item_get('iconImage')
					elif item_get('iconImage') == 'salts.png': icon = ku.get_addoninfo('icon')
					elif item_get('network_id', '') != '': icon = item_get('iconImage')
					else: icon = '%s%s' % (icon_path, item_get('iconImage'))
					isFolder = False if item_get('isFolder') == 'false' else True
					cm_append((edit_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.edit_menu', 'active_list': self.list_name, 'position': item_position})))
					cm_append((browse_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.browse', 'active_list': self.list_name})))
					listitem = make_listitem()
					listitem.setLabel(ls(item_get('name', '')))
					listitem.addContextMenuItems(cm)
					listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon})
					yield (build_url(item), listitem, isFolder)
				except: pass
		handle, fanart, icon_path = self.params_get('handle'), self.params_get('fanart'), media_path()
		contents = nc.currently_used_list(self.list_name)
		add_items(handle, list(build_main_lists()))
		self._end_directory()

	def make_list_name(self, menu_type):
		return menu_type.replace('tvshow', tv_str).replace('movie', mov_str)

	def _add_item(self, url_params, iconImage='', prefix='', isFolder=True, list_name=''):
		handle, fanart = self.params_get('handle'), self.params_get('fanart')
		if not isFolder: url_params['isFolder'] = 'false'
		if iconImage in ('', 'None', None): icon = 'DefaultFolder.png'
		elif iconImage.startswith('Default'): icon = iconImage
		elif iconImage == 'salts.png': icon = ku.get_addoninfo('icon')
		elif 'network_id' in url_params: icon = iconImage
		else: icon = media_path(iconImage)
		url_params['iconImage'] = icon
		url = build_url(url_params)
		listitem = make_listitem()
		listitem.setLabel(f"{prefix}{url_params['name']}")
		listitem.setArt({'icon': icon, 'poster': icon, 'thumb': icon, 'fanart': fanart, 'banner': icon, 'landscape': icon})
		if not 'exclude_external' in url_params:
			cm = []
			cm_append = cm.append
			if not list_name: list_name = f"{prefix}{url_params['name']}"
			cm_append((add_menu_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.add_external', 'name': list_name, 'iconImage': iconImage})))
			cm_append((s_folder_str, 'RunPlugin(%s)' % build_url({'mode': 'menu_editor.shortcut_folder_add_item', 'name': list_name, 'iconImage': iconImage})))
			listitem.addContextMenuItems(cm)
		add_item(handle, url, listitem, isFolder)

	def _end_directory(self):
		handle, fanart = self.params_get('handle'), self.params_get('fanart')
		set_category(handle, ls(self.params_get('name')))
		set_content(handle, '')
		end_directory(handle)
		set_view_mode('view.main', '')

