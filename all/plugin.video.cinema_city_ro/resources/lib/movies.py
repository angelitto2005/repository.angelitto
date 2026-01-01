import xbmcgui
import xbmcplugin
import json
import urllib.request
import urllib.parse
import ssl
import api_config

def list_movies(handle, base_url, page, query=None, multi=False):
    xbmcplugin.setContent(handle, 'movies')
    
    if query:
        encoded_query = urllib.parse.quote(query)
        if multi:
            url = f"{api_config.BASE_URL}/search/multi?api_key={api_config.API_KEY}&language=en-US&query={encoded_query}&page={page}"
        else:
            url = f"{api_config.BASE_URL}/search/movie?api_key={api_config.API_KEY}&language=en-US&query={encoded_query}&page={page}"
    else:
        url = f"{api_config.BASE_URL}/movie/now_playing?api_key={api_config.API_KEY}&language=en-US&page={page}"
    
    try:
        context = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            for item in data.get('results', []):
                media_type = item.get('media_type', 'movie')
                
                title = item.get('title') if media_type == 'movie' else item.get('name')
                if not title: continue

                tmdb_id = item.get('id')
                p_path = item.get('poster_path')
                f_path = item.get('backdrop_path')
                
                li = xbmcgui.ListItem(label=title)
                img = f"{api_config.IMG_BASE}{p_path}" if p_path else ""
                fan = f"{api_config.IMG_BASE}{f_path}" if f_path else ""
                li.setArt({'poster': img, 'fanart': fan, 'thumb': img})
                
                info = li.getVideoInfoTag()
                info.setTitle(title)
                info.setPlot(item.get('overview', ''))
                
                if media_type == 'tv':
                    u = f"{base_url}?action=list_seasons&tv_id={tmdb_id}"
                    is_folder = True
                    info.setMediaType('tvshow')
                else:
                    u = f"{base_url}?action=play&tmdb_id={tmdb_id}&type=movie&title={urllib.parse.quote(title)}"
                    li.setProperty('IsPlayable', 'true')
                    is_folder = False
                    info.setMediaType('movie')
                    if item.get('release_date'):
                        info.setYear(int(item.get('release_date').split('-')[0]))

                xbmcplugin.addDirectoryItem(handle=handle, url=u, listitem=li, isFolder=is_folder)
            
            if page < data.get('total_pages', 1):
                query_param = f"&query={urllib.parse.quote(query)}" if query else ""
                multi_param = "&multi=True" if multi else ""
                act = "search_all" if multi else "movies"
                
                u_next = f"{base_url}?action={act}&page={page + 1}{query_param}{multi_param}"
                xbmcplugin.addDirectoryItem(handle=handle, url=u_next, listitem=xbmcgui.ListItem(label="[COLOR yellow]>>> Pagina Următoare[/COLOR]"), isFolder=True)
                
    except Exception as e:
        import xbmc
        xbmc.log(f"TMDB Search Error: {str(e)}", xbmc.LOGERROR)
        
    xbmcplugin.endOfDirectory(handle)
