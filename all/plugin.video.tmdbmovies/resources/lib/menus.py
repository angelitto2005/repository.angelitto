# Meniul Principal
root_list = [
    {'name': '[B][COLOR FF00CED1]Movies[/COLOR][/B]', 'iconImage': 'movies.png', 'mode': 'movies_menu'},
    {'name': '[B][COLOR FF00CED1]TV Shows[/COLOR][/B]', 'iconImage': 'tv.png', 'mode': 'tv_menu'},
    {'name': '[B][COLOR FFFDBD01]Search[/COLOR][/B]', 'iconImage': 'search.png', 'mode': 'search_menu'},
    {'name': '[B][COLOR FF6AFB92]My Lists[/COLOR][/B]', 'iconImage': 'lists.png', 'mode': 'my_lists_menu'},
    {'name': '[B][COLOR FFFF69B4]Favorites[/COLOR][/B]', 'iconImage': 'favorites.png', 'mode': 'favorites_menu'},
    {'name': '[B][COLOR gray]Settings[/COLOR][/B]', 'iconImage': 'settings.png', 'mode': 'settings_menu'}
]

# Meniul Movies
movie_list = [
    {'name': 'Trending', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_trending_day'},
    {'name': 'Trending Recent', 'iconImage': 'trending.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_trending_week'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_popular'},
    {'name': 'Most Favorited', 'iconImage': 'favorites.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_top_rated'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_premieres'},
    {'name': 'Latest Releases', 'iconImage': 'dvd.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_latest_releases'},
    {'name': 'Top Box Office', 'iconImage': 'box_office.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_box_office'},
    {'name': 'In Theaters', 'iconImage': 'in_theatres.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_now_playing'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_upcoming'},
    {'name': 'Blockbusters', 'iconImage': 'most_voted.png', 'mode': 'build_movie_list', 'action': 'tmdb_movies_blockbusters'},
    {'name': 'In Progress', 'iconImage': 'player.png', 'mode': 'in_progress_movies', 'action': 'noop'}
]

# Meniul TV Shows
tvshow_list = [
    {'name': 'Trending', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_day'},
    {'name': 'Trending Recent', 'iconImage': 'trending.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_trending_week'},
    {'name': 'Popular', 'iconImage': 'popular.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_popular'},
    {'name': 'Most Favorited', 'iconImage': 'favorites.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_top_rated'},
    {'name': 'Premieres', 'iconImage': 'fresh.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_premieres'},
    {'name': 'Airing Today', 'iconImage': 'live.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_airing_today'},
    {'name': 'On The Air', 'iconImage': 'on_the_air.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_on_the_air'},
    {'name': 'Upcoming', 'iconImage': 'lists.png', 'mode': 'build_tvshow_list', 'action': 'tmdb_tv_upcoming'},
    {'name': 'In Progress TV Shows', 'iconImage': 'in_progress_tvshow.png', 'mode': 'in_progress_tvshows', 'action': 'noop'},
    {'name': 'In Progress Episodes', 'iconImage': 'player.png', 'mode': 'in_progress_episodes', 'action': 'noop'}
]

# (Genurile pot rămâne aici dacă sunt folosite intern la afișarea metadata, chiar dacă meniul de navigare e șters)
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