import xbmcgui
import xbmcplugin
import json
import urllib.request
import urllib.parse
import ssl
import api_config

def get_tmdb_json(url):
    context = ssl._create_unverified_context()
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=context) as response:
        return json.loads(response.read().decode('utf-8'))

def list_tvshows(handle, base_url, page, query=None):
    xbmcplugin.setContent(handle, 'tvshows')
    
    if query:
        encoded_query = urllib.parse.quote(query)
        url = f"{api_config.BASE_URL}/search/tv?api_key={api_config.API_KEY}&language=en-US&query={encoded_query}&page={page}"
    else:
        url = f"{api_config.BASE_URL}/tv/popular?api_key={api_config.API_KEY}&language=en-US&page={page}"
    
    try:
        data = get_tmdb_json(url)
        for item in data.get('results', []):
            name = item.get('name')
            tv_id = item.get('id')
            li = xbmcgui.ListItem(label=name)
            
            u = f"{base_url}?action=list_seasons&tv_id={tv_id}"
            
            p_path = item.get('poster_path')
            f_path = item.get('backdrop_path')
            art = {}
            if p_path:
                img = f"{api_config.IMG_BASE}{p_path}"
                art.update({'poster': img, 'thumb': img, 'icon': img})
            if f_path:
                art['fanart'] = f"{api_config.IMG_BASE}{f_path}"
            li.setArt(art)
            
            info = li.getVideoInfoTag()
            info.setTitle(name)
            info.setPlot(item.get('overview', ''))
            info.setMediaType('tvshow')
            
            xbmcplugin.addDirectoryItem(handle=handle, url=u, listitem=li, isFolder=True)
            
        if page < data.get('total_pages', 1):
            query_param = f"&query={urllib.parse.quote(query)}" if query else ""
            next_url = f"{base_url}?action=tvshows&page={page + 1}{query_param}"
            li_next = xbmcgui.ListItem(label=f"[COLOR yellow]>>> Pagina Următoare ({page + 1})[/COLOR]")
            xbmcplugin.addDirectoryItem(handle=handle, url=next_url, listitem=li_next, isFolder=True)
            
    except Exception as e:
        import xbmc
        xbmc.log(f"TMDB TV Search Error: {str(e)}", xbmc.LOGERROR)
        
    xbmcplugin.endOfDirectory(handle)

def list_seasons(handle, base_url, tv_id):
    xbmcplugin.setContent(handle, 'seasons')
    url = f"{api_config.BASE_URL}/tv/{tv_id}?api_key={api_config.API_KEY}&language=en-US"
    
    try:
        data = get_tmdb_json(url)
        main_fanart = f"{api_config.IMG_BASE}{data.get('backdrop_path')}" if data.get('backdrop_path') else ""
        
        for s in data.get('seasons', []):
            s_name = s.get('name')
            s_num = s.get('season_number')
            li = xbmcgui.ListItem(label=s_name)
            
            u = f"{base_url}?action=list_episodes&tv_id={tv_id}&season_num={s_num}"
            s_poster = f"{api_config.IMG_BASE}{s.get('poster_path')}" if s.get('poster_path') else main_fanart
            li.setArt({'poster': s_poster, 'thumb': s_poster, 'fanart': main_fanart})
            
            info = li.getVideoInfoTag()
            info.setTitle(s_name)
            info.setMediaType('season')
            
            xbmcplugin.addDirectoryItem(handle=handle, url=u, listitem=li, isFolder=True)
    except:
        pass
    xbmcplugin.endOfDirectory(handle)

def list_episodes(handle, base_url, tv_id, season_num):
    xbmcplugin.setContent(handle, 'episodes')
    url = f"{api_config.BASE_URL}/tv/{tv_id}/season/{season_num}?api_key={api_config.API_KEY}&language=en-US"
    
    try:
        data = get_tmdb_json(url)
        for ep in data.get('episodes', []):
            ep_name = f"{ep.get('episode_number')}. {ep.get('name')}"
            ep_num = ep.get('episode_number')
            plot = ep.get('overview', '')
            li = xbmcgui.ListItem(label=ep_name)
            
            s_path = ep.get('still_path')
            still = f"{api_config.IMG_BASE}{s_path}" if s_path else ""
            li.setArt({'thumb': still, 'icon': still, 'fanart': still})
            
            info = li.getVideoInfoTag()
            info.setTitle(ep_name)
            info.setPlot(plot)
            info.setMediaType('episode')
            
            u = f"{base_url}?action=play&tmdb_id={tv_id}&type=tv&season={season_num}&episode={ep_num}&title={urllib.parse.quote(ep_name)}"
            
            li.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(handle=handle, url=u, listitem=li, isFolder=False)
    except:
        pass
    xbmcplugin.endOfDirectory(handle)
