# Meniul Principal
root_list = [
    {'name': '[B][COLOR FF00CED1]Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'movies_menu'},
    {'name': '[B][COLOR FF00CED1]TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'tv_menu'},
    {'name': '[B][COLOR pink]Trakt[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_main_menu'},
    {'name': '[B][COLOR blue]Bollywood[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'hindi_movies_menu'},
    {'name': '[B][COLOR FF6AFB92]My Lists[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'my_lists_menu'},
    {'name': '[B][COLOR FFFF69B4]My Favorites[/COLOR][/B]', 'iconImage': 'favorites.png', 'mode': 'favorites_menu'},
    {'name': '[B][COLOR gray]Downloads[/COLOR][/B]', 'iconImage': 'download.png', 'mode': 'downloads_menu'}, 
    {'name': '[B][COLOR FFFDBD01]Search[/COLOR][/B]', 'iconImage': 'search.png', 'mode': 'search_menu'},
    {'name': '[B][COLOR gray]Settings[/COLOR][/B]', 'iconImage': 'settings.png', 'mode': 'settings_menu'}
]

# Meniul Movies
movie_list = [
    {'name': 'Trending Today', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_trending_day'},
    {'name': 'Trending This Week', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_trending_week'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_popular'},
    {'name': 'Most Favorited', 'iconImage': 'favorites.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_top_rated'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_premieres'},
    {'name': 'Latest Releases', 'iconImage': 'dvd.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_latest_releases'},
    {'name': 'Top Box Office', 'iconImage': 'box_office.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_box_office'},
    {'name': 'In Theaters', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_now_playing'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_upcoming'},
    {'name': 'Anticipated', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_anticipated'},
    {'name': 'Blockbusters', 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_blockbusters'},
    {'name': 'In Progress', 'iconImage': 'player.png', 'mode': 'in_progress_movies', 'action': 'noop'}
]

# Meniul TV Shows
tvshow_list = [
    {'name': 'Trending Today', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_day'},
    {'name': 'Trending This Week', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_week'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_popular'},
    {'name': 'Most Favorited', 'iconImage': 'favorites.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_top_rated'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_premieres'},
    {'name': 'Airing Today', 'iconImage': 'live.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_airing_today'},
    {'name': 'On The Air', 'iconImage': 'on_the_air.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_on_the_air'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_upcoming'},
    {'name': 'In Progress TV Shows', 'iconImage': 'in_progress_tvshow.png', 'mode': 'in_progress_tvshows', 'action': 'noop'},
    {'name': 'In Progress Episodes', 'iconImage': 'player.png', 'mode': 'in_progress_episodes', 'action': 'noop'},
    {'name': 'Next Episodes (Up Next)', 'iconImage': 'next_episodes.png', 'mode': 'next_episodes', 'action': 'noop'}
]

# Genurile raman neschimbate
MOVIE_GENRES = [
    {'id': 28, 'name': 'Action'},
    {'id': 12, 'name': 'Adventure'},
    {'id': 16, 'name': 'Animation'},
    {'id': 35, 'name': 'Comedy'},
    {'id': 80, 'name': 'Crime'},
    {'id': 99, 'name': 'Documentary'},
    {'id': 18, 'name': 'Drama'},
    {'id': 10751, 'name': 'Family'},
    {'id': 14, 'name': 'Fantasy'},
    {'id': 36, 'name': 'History'},
    {'id': 27, 'name': 'Horror'},
    {'id': 10402, 'name': 'Music'},
    {'id': 9648, 'name': 'Mystery'},
    {'id': 10749, 'name': 'Romance'},
    {'id': 878, 'name': 'Science Fiction'},
    {'id': 10770, 'name': 'TV Movie'},
    {'id': 53, 'name': 'Thriller'},
    {'id': 10752, 'name': 'War'},
    {'id': 37, 'name': 'Western'}
]

TV_GENRES = [
    {'id': 10759, 'name': 'Action & Adventure'},
    {'id': 16, 'name': 'Animation'},
    {'id': 35, 'name': 'Comedy'},
    {'id': 80, 'name': 'Crime'},
    {'id': 99, 'name': 'Documentary'},
    {'id': 18, 'name': 'Drama'},
    {'id': 10751, 'name': 'Family'},
    {'id': 10762, 'name': 'Kids'},
    {'id': 9648, 'name': 'Mystery'},
    {'id': 10763, 'name': 'News'},
    {'id': 10764, 'name': 'Reality'},
    {'id': 10765, 'name': 'Sci-Fi & Fantasy'},
    {'id': 10766, 'name': 'Soap'},
    {'id': 10767, 'name': 'Talk'},
    {'id': 10768, 'name': 'War & Politics'},
    {'id': 37, 'name': 'Western'}
]

# Meniul Hindi Movies (NOU)
hindi_movies_list = [
    {'name': 'Trending', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_trending'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_popular'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_premieres'},
    {'name': 'In Theaters', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_in_theaters'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_upcoming'},
    {'name': 'Anticipated', 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_anticipated'},
]


# Meniul Trakt Principal (NOU)
trakt_main_list = [
    {'name': 'Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_movies_menu'},
    {'name': 'TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_tv_menu'},
    {'name': 'Trending User Lists', 'iconImage': 'trakt.png', 'mode': 'trakt_public_lists', 'list_type': 'trending'},
    {'name': 'Popular User Lists', 'iconImage': 'trakt.png', 'mode': 'trakt_public_lists', 'list_type': 'popular'},
    {'name': 'Search List', 'iconImage': 'trakt.png', 'mode': 'trakt_search_list'}
]

# Meniul Trakt Movies (NOU)
trakt_movies_list = [
    {'name': 'Trending Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'movies'},
    {'name': 'Popular Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'movies'},
    {'name': 'Anticipated Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'movies'},
    {'name': 'Top 10 Box Office', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'boxoffice', 'media_type': 'movies'}
]

# Meniul Trakt TV Shows (NOU)
trakt_tv_list = [
    {'name': 'Trending TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'shows'},
    {'name': 'Popular TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'shows'},
    {'name': 'Anticipated TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'shows'}
]


# --- SUB-MENIURI PERSONALE TRAKT (NOU) ---
trakt_favorites_list_menu = [
    {'name': 'Movies Favorites', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_list', 'type': 'movies'},
    {'name': 'TV Shows Favorites', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_list', 'type': 'shows'}
]

trakt_watchlist_list_menu = [
    {'name': 'Movies Watchlist', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'watchlist', 'media_filter': 'movies'},
    {'name': 'TV Shows Watchlist', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'watchlist', 'media_filter': 'shows'}
]

trakt_history_list_menu = [
    {'name': 'Movies History', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'history', 'media_filter': 'movies'},
    {'name': 'TV Shows History', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'history', 'media_filter': 'shows'}
]

# --- SUB-MENIURI PERSONALE TMDB (NOU) ---
tmdb_watchlist_list_menu = [
    {'name': 'Movies Watchlist', 'iconImage': 'tmdb.png', 'mode': 'tmdb_watchlist', 'type': 'movie'},
    {'name': 'TV Shows Watchlist', 'iconImage': 'tmdb.png', 'mode': 'tmdb_watchlist', 'type': 'tv'}
]

tmdb_favorites_list_menu = [
    {'name': 'Movies Favorites', 'iconImage': 'tmdb.png', 'mode': 'tmdb_favorites', 'type': 'movie'},
    {'name': 'TV Shows Favorites', 'iconImage': 'tmdb.png', 'mode': 'tmdb_favorites', 'type': 'tv'}
]

tmdb_recommendations_list_menu = [
    {'name': 'Movies Recommendations', 'iconImage': 'tmdb.png', 'mode': 'tmdb_account_recommendations', 'type': 'movie'},
    {'name': 'TV Shows Recommendations', 'iconImage': 'tmdb.png', 'mode': 'tmdb_account_recommendations', 'type': 'tv'}
]

