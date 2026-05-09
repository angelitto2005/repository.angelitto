root_list = [
	{'name': 32028, 'iconImage': 'movies.png', 'mode': 'navigator.main', 'action': 'MovieList'},
	{'name': 32029, 'iconImage': 'tv.png', 'mode': 'navigator.main', 'action': 'TVShowList'},
	{'name': 'Anime', 'iconImage': '', 'mode': 'navigator.main', 'action': 'AnimeList'},
	{'name': 32452, 'iconImage': 'people.png', 'mode': 'build_popular_people', 'isFolder': 'false'},
	{'name': 32451, 'iconImage': 'discover.png', 'mode': 'navigator.discover_main'},
	{'name': 32450, 'iconImage': 'search.png', 'mode': 'navigator.search'},
	{'name': 32453, 'iconImage': 'favorites.png', 'mode': 'navigator.favorites'},
	{'name': 32107, 'iconImage': 'downloads.png', 'mode': 'navigator.downloads'},
	{'name': 32454, 'iconImage': 'lists.png', 'mode': 'navigator.my_content'},
	{'name': 32455, 'iconImage': 'premium.png', 'mode': 'navigator.premium'},
#	{'name': 32456, 'iconImage': 'tools.png', 'mode': 'navigator.tools'},
	{'name': 32247, 'iconImage': 'settings.png', 'mode': 'navigator.settings'}
]

movie_list = [
	{'name': 32458, 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'trakt_movies_trending'},
	{'name': 32449, 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'trakt_movies_trending_recent'},
	{'name': 32043, 'iconImage': 'most_watched.png', 'mode': 'build_movie_list', 'action': 'trakt_movies_most_watched'},
	{'name': 32459, 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_popular'},
	{'name': 32460, 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_premieres'},
	{'name': 32461, 'iconImage': 'dvd.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_latest_releases'},
	{'name': 32469, 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_upcoming'},
	{'name': 32463, 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_blockbusters'},
	{'name': 32470, 'iconImage': 'genres.png', 'mode': 'navigator.genres', 'menu_type': 'movie'},
	{'name': 32472, 'iconImage': 'calender.png', 'mode': 'navigator.years', 'menu_type': 'movie'},
	{'name': 32474, 'iconImage': 'because_you_watched.png', 'mode': 'navigator.because_you_watched', 'menu_type': 'movie'},
	{'name': 32475, 'iconImage': 'watched.png', 'mode': 'build_movie_list', 'action': 'watched_movies'},
	{'name': 32476, 'iconImage': 'player.png', 'mode': 'build_movie_list', 'action': 'in_progress_movies'}
]

tvshow_list = [
	{'name': 32458, 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'trakt_tv_trending'},
	{'name': 32449, 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'trakt_tv_trending_recent'},
	{'name': 32043, 'iconImage': 'most_watched.png', 'mode': 'build_tvshow_list', 'action': 'trakt_tv_most_watched'},
	{'name': 32459, 'iconImage': 'popular.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_popular'},
	{'name': 32460, 'iconImage': 'fresh.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_premieres'},
	{'name': 32469, 'iconImage': 'lists.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_upcoming'},
	{'name': 32470, 'iconImage': 'genres.png', 'mode': 'navigator.genres', 'menu_type': 'tvshow'},
	{'name': 32480, 'iconImage': 'networks.png', 'mode': 'navigator.networks', 'menu_type': 'tvshow'},
	{'name': 32472, 'iconImage': 'calender.png', 'mode': 'navigator.years', 'menu_type': 'tvshow'},
	{'name': 32474, 'iconImage': 'because_you_watched.png', 'mode': 'navigator.because_you_watched', 'menu_type': 'tvshow'},
	{'name': 32475, 'iconImage': 'watched.png', 'mode': 'build_tvshow_list', 'action': 'watched_tvshows'},
	{'name': 32481, 'iconImage': 'in_progress_tvshow.png', 'mode': 'build_tvshow_list', 'action': 'in_progress_tvshows'},
	{'name': 32482, 'iconImage': 'player.png', 'mode': 'build_in_progress_episode'},
	{'name': 32483, 'iconImage': 'next_episodes.png', 'mode': 'build_next_episode'}
]

anime_list = [
	{'name': 'Series Calendar', 'iconImage': 'trakt.png', 'mode': 'build_anime_calendar'},
	{'name': 'Series Trending', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'trakt_tvanime_trending'},
	{'name': 'Series Most Watched', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'trakt_tvanime_most_watched'},
	{'name': 'Series Popular', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tvanime_popular'},
	{'name': 'Series Recent Released', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tvanime_premieres'},
	{'name': 'Series Genres', 'iconImage': 'genres.png', 'mode': 'navigator.anime_genres', 'menu_type': 'tvshow'},
	{'name': 'Series Years', 'iconImage': 'calender.png', 'mode': 'navigator.anime_years', 'menu_type': 'tvshow'},
	{'name': 'Movies Trending', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'trakt_moviesanime_trending'},
	{'name': 'Movies Most Watched', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'trakt_moviesanime_most_watched'},
	{'name': 'Movies Popular', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_moviesanime_popular'},
	{'name': 'Movies Recent Released', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_moviesanime_latest_releases'},
	{'name': 'Movies Genres', 'iconImage': 'genres.png', 'mode': 'navigator.anime_genres', 'menu_type': 'movie'},
	{'name': 'Movies Years', 'iconImage': 'calender.png', 'mode': 'navigator.anime_years', 'menu_type': 'movie'}
]

main_menu_items, main_menus, default_menu_items = {
	'RootList': {'name': 32457, 'iconImage': 'salts.png', 'mode': 'navigator.main', 'action': 'RootList'},
	'MovieList': root_list[0],
	'TVShowList': root_list[1],
	'AnimeList': root_list[2]
}, {
	'RootList': root_list,
	'MovieList': movie_list,
	'TVShowList': tvshow_list,
	'AnimeList': anime_list
}, (
	'RootList',
	'MovieList',
	'TVShowList',
	'AnimeList'
)

