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
    {'name': '[B][COLOR FFCCCCFF]Trending Today[/COLOR][/B]', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_trending_day'},
    {'name': '[B][COLOR FFCCCCFF]Trending This Week[/COLOR][/B]', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_trending_week'},
    {'name': '[B][COLOR FFCCCCFF]Popular[/COLOR][/B]', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_popular'},
    {'name': '[B][COLOR FFCCCCFF]Most Favorited[/COLOR][/B]', 'iconImage': 'favorites.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_top_rated'},
    {'name': '[B][COLOR FFCCCCFF]Premieres[/COLOR][/B]', 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_premieres'},
    {'name': '[B][COLOR FFCCCCFF]Latest Releases[/COLOR][/B]', 'iconImage': 'dvd.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_latest_releases'},
    {'name': '[B][COLOR FFCCCCFF]Netflix Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_netflix'},
    {'name': '[B][COLOR FFCCCCFF]Amazon Prime Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_amazon'},
    {'name': '[B][COLOR FFCCCCFF]Disney+ Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_disney'},
    {'name': '[B][COLOR FFCCCCFF]Apple TV+ Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_apple'},
    {'name': '[B][COLOR FFCCCCFF]Top Box Office[/COLOR][/B]', 'iconImage': 'box_office.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_box_office'},
    {'name': '[B][COLOR FFCCCCFF]In Theaters[/COLOR][/B]', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_now_playing'},
    {'name': '[B][COLOR FFCCCCFF]Upcoming[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_upcoming'},
    {'name': '[B][COLOR FFCCCCFF]Anticipated[/COLOR][/B]', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_anticipated'},
    {'name': '[B][COLOR FFCCCCFF]Blockbusters[/COLOR][/B]', 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_blockbusters'},
    {'name': '[B][COLOR FFCCCCFF]In Progress[/COLOR][/B]', 'iconImage': 'player.png', 'mode': 'in_progress_movies', 'action': 'noop'}
]

# Meniul TV Shows
tvshow_list = [
    {'name': '[B][COLOR FFCCCCFF]Trending Today[/COLOR][/B]', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_day'},
    {'name': '[B][COLOR FFCCCCFF]Trending This Week[/COLOR][/B]', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_week'},
    {'name': '[B][COLOR FFCCCCFF]Popular[/COLOR][/B]', 'iconImage': 'popular.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_popular'},
    {'name': '[B][COLOR FFCCCCFF]Most Favorited[/COLOR][/B]', 'iconImage': 'favorites.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_top_rated'},
    {'name': '[B][COLOR FFCCCCFF]Premieres[/COLOR][/B]', 'iconImage': 'fresh.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_premieres'},
    {'name': '[B][COLOR FFCCCCFF]Latest Releases[/COLOR][/B]', 'iconImage': 'live.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_latest_releases'},
    {'name': '[B][COLOR FFCCCCFF]Netflix TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_netflix'},
    {'name': '[B][COLOR FFCCCCFF]Amazon Prime TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_amazon'},
    {'name': '[B][COLOR FFCCCCFF]Disney+ TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_disney'},
    {'name': '[B][COLOR FFCCCCFF]Apple TV+ TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_apple'},
    {'name': '[B][COLOR FFCCCCFF]Airing Today[/COLOR][/B]', 'iconImage': 'live.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_airing_today'},
    {'name': '[B][COLOR FFCCCCFF]On The Air[/COLOR][/B]', 'iconImage': 'on_the_air.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_on_the_air'},
    {'name': '[B][COLOR FFCCCCFF]Upcoming[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_upcoming'},
    {'name': '[B][COLOR FFCCCCFF]In Progress TV Shows[/COLOR][/B]', 'iconImage': 'in_progress_tvshow.png', 'mode': 'in_progress_tvshows', 'action': 'noop'},
    {'name': '[B][COLOR FFCCCCFF]In Progress Episodes[/COLOR][/B]', 'iconImage': 'player.png', 'mode': 'in_progress_episodes', 'action': 'noop'},
    {'name': '[B][COLOR FF33CCFF]Next Episodes[/COLOR][/B]', 'iconImage': 'next_episodes.png', 'mode': 'next_episodes', 'action': 'noop'}
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
    {'name': '[B][COLOR FFCCCCFF]Trending[/COLOR][/B]', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_trending'},
    {'name': '[B][COLOR FFCCCCFF]Popular[/COLOR][/B]', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_popular'},
    {'name': '[B][COLOR FFCCCCFF]Premieres[/COLOR][/B]', 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_premieres'},
    {'name': '[B][COLOR FFCCCCFF]In Theaters[/COLOR][/B]', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_in_theaters'},
    {'name': '[B][COLOR FFCCCCFF]Upcoming[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_upcoming'},
    {'name': '[B][COLOR FFCCCCFF]Anticipated[/COLOR][/B]', 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'hindi_movies_anticipated'},
]


# Meniul Trakt Principal (NOU)
trakt_main_list = [
    {'name': '[B][COLOR FFCCCCFF]Movies[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_movies_menu'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_tv_menu'},
    {'name': '[B][COLOR FFCCCCFF]Trending User Lists[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_public_lists', 'list_type': 'trending'},
    {'name': '[B][COLOR FFCCCCFF]Popular User Lists[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_public_lists', 'list_type': 'popular'},
    {'name': '[B][COLOR FFCCCCFF]Search List[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_search_list'}
]

# Meniul Trakt Movies (NOU)
trakt_movies_list = [
    {'name': '[B][COLOR FFCCCCFF]Trending Movies[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'movies'},
    {'name': '[B][COLOR FFCCCCFF]Popular Movies[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'movies'},
    {'name': '[B][COLOR FFCCCCFF]Anticipated Movies[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'movies'},
    {'name': '[B][COLOR FFCCCCFF]Top 10 Box Office[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'boxoffice', 'media_type': 'movies'}
]

# Meniul Trakt TV Shows (NOU)
trakt_tv_list = [
    {'name': '[B][COLOR FFCCCCFF]Trending TV Shows[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'shows'},
    {'name': '[B][COLOR FFCCCCFF]Popular TV Shows[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'shows'},
    {'name': '[B][COLOR FFCCCCFF]Anticipated TV Shows[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'shows'}
]


# --- SUB-MENIURI PERSONALE TRAKT (NOU) ---
trakt_favorites_list_menu = [
    {'name': '[B][COLOR FFCCCCFF]Movies Favorites[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_list', 'type': 'movies'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows Favorites[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_favorites_list', 'type': 'shows'}
]

trakt_watchlist_list_menu = [
    {'name': '[B][COLOR FFCCCCFF]Movies Watchlist[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'watchlist', 'media_filter': 'movies'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows Watchlist[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'watchlist', 'media_filter': 'shows'}
]

trakt_history_list_menu = [
    {'name': '[B][COLOR FFCCCCFF]Movies History[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'history', 'media_filter': 'movies'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows History[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_list_items', 'list_type': 'history', 'media_filter': 'shows'}
]

# --- SUB-MENIURI PERSONALE TMDB (NOU) ---
tmdb_watchlist_list_menu = [
    {'name': '[B][COLOR FFCCCCFF]Movies Watchlist[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_watchlist', 'type': 'movie'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows Watchlist[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_watchlist', 'type': 'tv'}
]

tmdb_favorites_list_menu = [
    {'name': '[B][COLOR FFCCCCFF]Movies Favorites[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_favorites', 'type': 'movie'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows Favorites[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_favorites', 'type': 'tv'}
]

tmdb_recommendations_list_menu = [
    {'name': '[B][COLOR FFCCCCFF]Movies Recommendations[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_account_recommendations', 'type': 'movie'},
    {'name': '[B][COLOR FFCCCCFF]TV Shows Recommendations[/COLOR][/B]', 'iconImage': 'tmdb.png', 'mode': 'tmdb_account_recommendations', 'type': 'tv'}
]

