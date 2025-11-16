from tmdbhelper.lib.addon.permissions import __access__
from tmdbhelper.lib.api.api_keys.tokenhandler import TokenHandler

if __access__.has_access('internal'):
    API_KEY = 'a07324c669cac4d96789197134ce272b'
    API_READ_ACCESS_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJhMDczMjRjNjY5Y2FjNGQ5Njc4OTE5NzEzNGNlMjcyYiIsIm5iZiI6MTUxOTkzOTM2NC42MDYwMDAyLCJzdWIiOiI1YTk4NmYyNGMzYTM2ODA3M2EwMDZiYzAiLCJzY29wZXMiOlsiYXBpX3JlYWQiXSwidmVyc2lvbiI6MX0.YMASJX_w-l8tDnqGHl_6EZljra3TOp-hnkgKjyFM4Y8'
    USER_TOKEN = TokenHandler('tmdb_user_token', store_as='setting')
else:
    API_KEY = ''
    API_READ_ACCESS_TOKEN = ''
    USER_TOKEN = TokenHandler()
