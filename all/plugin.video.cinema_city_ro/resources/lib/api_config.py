import xbmcaddon
addon = xbmcaddon.Addon()

BASE_URL = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w500"
API_KEY = addon.getSetting("tmdb_api_key")


