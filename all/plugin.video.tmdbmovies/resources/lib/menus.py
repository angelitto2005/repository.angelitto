# Meniul Principal
root_list = [
    {'name': '[B][COLOR FF00CED1]Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'movies_menu'},
    {'name': '[B][COLOR FF00CED1]TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'tv_menu'},
    {'name': '[B][COLOR pink]Trakt[/COLOR][/B]', 'iconImage': 'trakt.png', 'mode': 'trakt_main_menu'},
    {'name': '[B][COLOR lightskyblue]Bollywood[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'hindi_movies_menu'},
    {'name': '[B][COLOR yellow]Romania[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'romania_menu'},
    {'name': '[B][COLOR orange]Actors[/COLOR][/B]', 'iconImage': 'people.png', 'mode': 'actors_menu'},
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
    {'name': 'Netflix Movies', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_netflix'},
    {'name': 'Amazon Prime Movies', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_amazon'},
    {'name': 'Disney+ Movies', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_disney'},
    {'name': 'Apple TV+ Movies', 'iconImage': 'movies.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_apple'},
    {'name': 'Top Box Office', 'iconImage': 'box_office.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_box_office'},
    {'name': 'In Theaters', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_now_playing'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_upcoming'},
    {'name': 'Anticipated', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_anticipated'},
    {'name': 'Blockbusters', 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_blockbusters'},
    {'name': 'Providers', 'iconImage': 'movies.png', 'mode': 'navigator_providers', 'menu_type': 'movie'},
    {'name': 'Highest Revenue', 'iconImage': 'box_office.png', 'mode': 'list_highest_revenue', 'media_type': 'movie'},
    {'name': 'Most Voted', 'iconImage': 'most_voted.png', 'mode': 'list_most_voted', 'media_type': 'movie'},
    {'name': 'Genres', 'iconImage': 'genres.png', 'mode': 'navigator_genres', 'menu_type': 'movie'},
    {'name': 'Release Years', 'iconImage': 'calender.png', 'mode': 'navigator_years', 'menu_type': 'movie'},
    {'name': 'In Progress', 'iconImage': 'player.png', 'mode': 'in_progress_movies', 'action': 'noop'}
]

# Meniul TV Shows
tvshow_list = [
    {'name': 'Trending Today', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_day'},
    {'name': 'Trending This Week', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_week'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_popular'},
    {'name': 'Most Favorited', 'iconImage': 'favorites.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_top_rated'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_premieres'},
    {'name': 'Latest Releases', 'iconImage': 'dvd.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_latest_releases'},
    {'name': 'Netflix TV Shows', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_netflix'},
    {'name': 'Amazon Prime TV Shows', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_amazon'},
    {'name': 'Disney+ TV Shows', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_disney'},
    {'name': 'Apple TV+ TV Shows', 'iconImage': 'tv.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_apple'},
    {'name': 'Airing Today', 'iconImage': 'live.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_airing_today'},
    {'name': 'On The Air', 'iconImage': 'on_the_air.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_on_the_air'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_upcoming'},
    {'name': 'Providers', 'iconImage': 'tv.png', 'mode': 'navigator_providers', 'menu_type': 'tv'},
    {'name': 'Networks', 'iconImage': 'networks.png', 'mode': 'navigator_networks', 'menu_type': 'tv'},
    {'name': 'Most Voted', 'iconImage': 'most_voted.png', 'mode': 'list_most_voted', 'media_type': 'tv'},
    {'name': 'Genres', 'iconImage': 'genres.png', 'mode': 'navigator_genres', 'menu_type': 'tv'},
    {'name': 'Release Years', 'iconImage': 'calender.png', 'mode': 'navigator_years', 'menu_type': 'tv'},
    {'name': 'In Progress TV Shows', 'iconImage': 'in_progress_tvshow.png', 'mode': 'in_progress_tvshows', 'action': 'noop'},
    {'name': 'In Progress Episodes', 'iconImage': 'player.png', 'mode': 'in_progress_episodes', 'action': 'noop'},
    {'name': '[B][COLOR FF33CCFF]Next Episodes[/COLOR][/B]', 'iconImage': 'next_episodes.png', 'mode': 'next_episodes', 'action': 'noop'}
]

TV_NETWORKS = sorted([
    {'id': 129, 'name': 'A&E'},
    {'id': 2, 'name': 'ABC'},
    {'id': 2697, 'name': 'Acorn TV'},
    {'id': 80, 'name': 'Adult Swim'},
    {'id': 1024, 'name': 'Amazon'},
    {'id': 174, 'name': 'AMC'},
    {'id': 91, 'name': 'Animal Planet'},
    {'id': 2552, 'name': 'Apple TV+'},
    {'id': 173, 'name': 'AT-X'},
    {'id': 251, 'name': 'Audience'},
    {'id': 493, 'name': 'BBC America'},
    {'id': 4, 'name': 'BBC One'},
    {'id': 332, 'name': 'BBC Two'},
    {'id': 3, 'name': 'BBC Three'},
    {'id': 100, 'name': 'BBC Four'},
    {'id': 24, 'name': 'BET'},
    {'id': 74, 'name': 'Bravo'},
    {'id': 56, 'name': 'Cartoon Network'},
    {'id': 32, 'name': 'CBC'},
    {'id': 1709, 'name': 'CBS All Access'},
    {'id': 16, 'name': 'CBS'},
    {'id': 26, 'name': 'Channel 4'},
    {'id': 99, 'name': 'Channel 5'},
    {'id': 359, 'name': 'Cinemax'},
    {'id': 47, 'name': 'Comedy Central'},
    {'id': 928, 'name': 'Crackle'},
    {'id': 110, 'name': 'CTV'},
    {'id': 2243, 'name': 'DC Universe'},
    {'id': 64, 'name': 'Discovery Channel'},
    {'id': 54, 'name': 'Disney Channel'},
    {'id': 44, 'name': 'Disney XD'},
    {'id': 2739, 'name': 'Disney+'},
    {'id': 76, 'name': 'E!'},
    {'id': 136, 'name': 'E4'},
    {'id': 19, 'name': 'FOX'},
    {'id': 1267, 'name': 'Freeform'},
    {'id': 384, 'name': 'Hallmark Channel'},
    {'id': 3186, 'name': 'HBO Max'},
    {'id': 49, 'name': 'HBO'},
    {'id': 210, 'name': 'HGTV'},
    {'id': 65, 'name': 'History Channel'},
    {'id': 453, 'name': 'Hulu'},
    {'id': 9, 'name': 'ITV'},
    {'id': 34, 'name': 'Lifetime'},
    {'id': 33, 'name': 'MTV'},
    {'id': 43, 'name': 'National Geographic'},
    {'id': 6, 'name': 'NBC'},
    {'id': 213, 'name': 'Netflix'},
    {'id': 35, 'name': 'Nick Jr.'},
    {'id': 13, 'name': 'Nickelodeon'},
    {'id': 2076, 'name': 'Paramount Network'},
    {'id': 4330, 'name': 'Paramount+'},
    {'id': 14, 'name': 'PBS'},
    {'id': 3353, 'name': 'Peacock'},
    {'id': 67, 'name': 'Showtime'},
    {'id': 214, 'name': 'Sky One'},
    {'id': 55, 'name': 'Spike'},
    {'id': 318, 'name': 'Starz'},
    {'id': 270, 'name': 'SundanceTV'},
    {'id': 77, 'name': 'Syfy'},
    {'id': 68, 'name': 'TBS'},
    {'id': 71, 'name': 'The CW'},
    {'id': 21, 'name': 'The WB'},
    {'id': 84, 'name': 'TLC'},
    {'id': 41, 'name': 'TNT'},
    {'id': 209, 'name': 'Travel Channel'},
    {'id': 364, 'name': 'truTV'},
    {'id': 397, 'name': 'TV Land'},
    {'id': 30, 'name': 'USA Network'},
    {'id': 158, 'name': 'VH1'},
    {'id': 202, 'name': 'WGN America'},
    {'id': 1436, 'name': 'YouTube Red'},
], key=lambda x: x['name'])

# Genres remain unchanged
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
    {'id': 10765, 'name': 'Sci-Fi & Fantasy'},
    {'id': 10766, 'name': 'Soap'},
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
    {'name': '[B][COLOR FF33CCFF]Next Episodes[/COLOR][/B]', 'iconImage': 'next_episodes.png', 'mode': 'next_episodes'},
    {'name': 'Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_movies_menu'},
    {'name': 'TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_tv_menu'},
    {'name': 'Calendar', 'iconImage': 'trakt.png', 'mode': 'trakt_calendar_menu'},
    {'name': 'Trending User Lists', 'iconImage': 'trakt.png', 'mode': 'trakt_public_lists', 'list_type': 'trending'},
    {'name': 'Popular User Lists', 'iconImage': 'trakt.png', 'mode': 'trakt_public_lists', 'list_type': 'popular'},
    {'name': 'Search List', 'iconImage': 'trakt.png', 'mode': 'trakt_search_list'}
]

# Meniul Trakt Movies (NOU)
trakt_movies_list = [
    {'name': 'Trending Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'movies'},
    {'name': 'Popular Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'movies'},
    {'name': 'Most Collected', 'iconImage': 'trakt.png', 'mode': 'trakt_period_dialog', 'list_type': 'collected', 'media_type': 'movies'},
    {'name': 'Most Watched', 'iconImage': 'trakt.png', 'mode': 'trakt_period_dialog', 'list_type': 'watched', 'media_type': 'movies'},
    {'name': 'Anticipated Movies', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'movies'},
    {'name': 'Top 10 Box Office', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'boxoffice', 'media_type': 'movies'},
    {'name': 'In Progress', 'iconImage': 'player.png', 'mode': 'in_progress_movies', 'action': 'noop'}
]

# Meniul Trakt TV Shows (NOU)
trakt_tv_list = [
    {'name': 'Trending TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'trending', 'media_type': 'shows'},
    {'name': 'Popular TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'popular', 'media_type': 'shows'},
    {'name': 'Most Collected', 'iconImage': 'trakt.png', 'mode': 'trakt_period_dialog', 'list_type': 'collected', 'media_type': 'shows'},
    {'name': 'Most Watched', 'iconImage': 'trakt.png', 'mode': 'trakt_period_dialog', 'list_type': 'watched', 'media_type': 'shows'},
    {'name': 'Anticipated TV Shows', 'iconImage': 'trakt.png', 'mode': 'trakt_discovery_list', 'list_type': 'anticipated', 'media_type': 'shows'},
    {'name': 'In Progress TV Shows', 'iconImage': 'in_progress_tvshow.png', 'mode': 'in_progress_tvshows', 'action': 'noop'},
    {'name': 'In Progress Episodes', 'iconImage': 'player.png', 'mode': 'in_progress_episodes', 'action': 'noop'}
]


# --- TRAKT PERSONAL SUB-MENUS (NEW) ---
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

# --- TMDB PERSONAL SUB-MENUS (NEW) ---
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


# --- ROMANIA MENUS (NEW) ---
romania_menu = [
    {'name': '[B][COLOR yellow]Romanian Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'romania_movies_menu'},
    {'name': '[B][COLOR yellow]Romanian TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'romania_tvshows_menu'}
]

romania_movies_list = [
    {'name': 'Trending', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'romania_movies_trending'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'romania_movies_popular'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'romania_movies_premieres'},
    {'name': 'In Theaters', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'romania_movies_in_theaters'},
    {'name': 'Release Date (New)', 'iconImage': 'dvd.png', 'mode': 'build_movie_list', 'action': 'romania_movies_latest'}
]

romania_tvshows_list = [
    {'name': 'Trending', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'romania_tv_trending'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_tvshow_list', 'action': 'romania_tv_popular'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_tvshow_list', 'action': 'romania_tv_premieres'},
    {'name': 'Release Date (New)', 'iconImage': 'dvd.png', 'mode': 'build_tvshow_list', 'action': 'romania_tv_latest'}
]

