import sys
import urllib.parse
import urllib.request
import re
import xbmcgui
import xbmcplugin
import xbmc

# Plugin constants
URL = sys.argv[0]
HANDLE = int(sys.argv[1])
BASE_URL = 'https://rotv123.com'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'

def get_html(url):
    req = urllib.request.Request(url)
    req.add_header('User-Agent', USER_AGENT)
    req.add_header('Referer', BASE_URL)
    req.add_header('Origin', BASE_URL)

    try:
        response = urllib.request.urlopen(req)
        content = response.read().decode('utf-8')
        return content
    except Exception as e:
        xbmcgui.Dialog().notification('Rotv123', f'Error: {str(e)}', xbmcgui.NOTIFICATION_ERROR)
        return None

def build_url(query):
    return URL + '?' + urllib.parse.urlencode(query)

def main_menu():
    html = get_html(BASE_URL)
    if not html:
        return

    xbmcplugin.setContent(HANDLE, 'genres')  # Set content type for main menu

    pattern = re.compile(r'href="([^"]*categoria\.php\?cat=[^"]*)"[^>]*class="[^"]*main-category[^"]*"[^>]*>.*?category-title">([^<]+)</div>', re.DOTALL)
    matches = pattern.findall(html)

    for link, title in matches:
        if not link.startswith('http'):
            link = urllib.parse.urljoin(BASE_URL, link)

        url = build_url({'mode': 'category', 'url': link})
        list_item = xbmcgui.ListItem(label=title.strip())

        # Set more specific info type based on category
        category_lower = title.lower().strip()
        if 'sport' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'Sports channels in {title}',
                'genre': 'Sports',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultVideoPlaylists.png', 'icon': 'DefaultVideoPlaylists.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'filme' in category_lower or 'cinema' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'Movies and cinema in {title}',
                'genre': 'Movies',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultMovies.png', 'icon': 'DefaultMovies.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'muzica' in category_lower or 'music' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'Music channels in {title}',
                'genre': 'Music',
                'mediatype': 'musicvideo'
            })
            list_item.setArt({'thumb': 'DefaultMusicVideos.png', 'icon': 'DefaultMusicVideos.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'stiri' in category_lower or 'news' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'News channels in {title}',
                'genre': 'News',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultTVShows.png', 'icon': 'DefaultTVShows.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'copii' in category_lower or 'kids' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'Kids channels in {title}',
                'genre': 'Kids',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultVideoPlaylists.png', 'icon': 'DefaultVideoPlaylists.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'documentare' in category_lower or 'doc' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'Documentary channels in {title}',
                'genre': 'Documentary',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultVideo.png', 'icon': 'DefaultVideo.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'religioase' in category_lower or 'religion' in category_lower:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'Religious channels in {title}',
                'genre': 'Religious',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultVideo.png', 'icon': 'DefaultVideo.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        else:
            list_item.setInfo('video', {
                'title': title.strip(),
                'plot': f'{title} channels',
                'genre': 'General',
                'mediatype': 'video'
            })
            list_item.setArt({'thumb': 'DefaultVideo.png', 'icon': 'DefaultVideo.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})

        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=True)

    # Add a search option if available
    search_url = build_url({'mode': 'search'})
    search_item = xbmcgui.ListItem(label='Search Channels')
    search_item.setInfo('video', {
        'title': 'Search Channels',
        'plot': 'Search for specific channels',
        'mediatype': 'video'
    })
    search_item.setArt({'thumb': 'DefaultAddonSearch.png', 'icon': 'DefaultAddonSearch.png', 'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=search_url, listitem=search_item, isFolder=True)

    xbmcplugin.setContent(HANDLE, 'genres')
    xbmcplugin.endOfDirectory(HANDLE)

def list_category(category_url):
    html = get_html(category_url)
    if not html:
        return

    # Determine content type based on category URL
    category_lower = category_url.lower()
    if 'sport' in category_lower:
        xbmcplugin.setContent(HANDLE, 'tvshows')  # Using tvshows for sports channels
    elif 'filme' in category_lower or 'movie' in category_lower:
        xbmcplugin.setContent(HANDLE, 'movies')
    elif 'muzica' in category_lower or 'music' in category_lower:
        xbmcplugin.setContent(HANDLE, 'musicvideos')
    elif 'stiri' in category_lower or 'news' in category_lower:
        xbmcplugin.setContent(HANDLE, 'episodes')  # Using episodes for news
    else:
        xbmcplugin.setContent(HANDLE, 'videos')  # Default content type

    pattern = re.compile(r'<a href=[\'"]([^\'"]+)[\'"][^>]*class="channel-card"[^>]*>.*?onerror="this\.src=[\'"]([^\'"]+)[\'"][^>]*>.*?<span class="channel-name">([^<]+)</span>', re.DOTALL)
    matches = pattern.findall(html)

    for link, placeholder_img, channel_name in matches:
        title = channel_name.strip()

        if not link.startswith('http'):
            link = urllib.parse.urljoin(BASE_URL, link)

        url = build_url({'mode': 'play', 'url': link})
        list_item = xbmcgui.ListItem(label=title)

        # Determine channel type for better icon selection
        title_lower = title.lower()
        if 'sport' in title_lower or 'football' in title_lower or 'tennis' in title_lower or 'basket' in title_lower:
            list_item.setInfo('video', {
                'title': title,
                'originaltitle': title,
                'genre': 'Sports',
                'mediatype': 'video',
                'studio': 'ROTV123'
            })
            list_item.setArt({'thumb': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultVideoPlaylists.png',
                             'icon': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultVideoPlaylists.png',
                             'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'film' in title_lower or 'movie' in title_lower or 'cinema' in title_lower:
            list_item.setInfo('video', {
                'title': title,
                'originaltitle': title,
                'genre': 'Movies',
                'mediatype': 'video',
                'studio': 'ROTV123'
            })
            list_item.setArt({'thumb': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultMovies.png',
                             'icon': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultMovies.png',
                             'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'music' in title_lower or 'muzica' in title_lower or 'radio' in title_lower:
            list_item.setInfo('video', {
                'title': title,
                'originaltitle': title,
                'genre': 'Music',
                'mediatype': 'musicvideo',
                'studio': 'ROTV123'
            })
            list_item.setArt({'thumb': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultMusicVideos.png',
                             'icon': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultMusicVideos.png',
                             'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'news' in title_lower or 'stiri' in title_lower or 'info' in title_lower:
            list_item.setInfo('video', {
                'title': title,
                'originaltitle': title,
                'genre': 'News',
                'mediatype': 'video',
                'studio': 'ROTV123'
            })
            list_item.setArt({'thumb': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultTVShows.png',
                             'icon': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultTVShows.png',
                             'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        elif 'kids' in title_lower or 'copii' in title_lower or 'cartoon' in title_lower:
            list_item.setInfo('video', {
                'title': title,
                'originaltitle': title,
                'genre': 'Kids',
                'mediatype': 'video',
                'studio': 'ROTV123'
            })
            list_item.setArt({'thumb': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultVideoPlaylists.png',
                             'icon': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultVideoPlaylists.png',
                             'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})
        else:
            list_item.setInfo('video', {
                'title': title,
                'originaltitle': title,
                'mediatype': 'video',
                'studio': 'ROTV123'
            })
            list_item.setArt({'thumb': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultVideo.png',
                             'icon': placeholder_img if placeholder_img and placeholder_img.strip() else 'DefaultVideo.png',
                             'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'})

        list_item.setProperty('IsPlayable', 'true')

        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)


def play_video(video_url):
    if not video_url.startswith('http'):
        video_url = urllib.parse.urljoin(BASE_URL, video_url)

    # Extract channel name from URL or get it from previous context
    channel_name = extract_channel_name_from_url(video_url)

    html = get_html(video_url)
    if not html:
        xbmcgui.Dialog().notification('Rotv123', 'Could not retrieve page', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())
        return

    streams_pattern = re.compile(r'const streams\s*=\s*\{([^}]+)\}', re.DOTALL)
    streams_match = streams_pattern.search(html)

    if streams_match:
        streams_content = streams_match.group(1)
        url_pattern = re.compile(r'(\w+)\s*:\s*[\'"]\s*([^\'"\s,]+)')
        url_matches = url_pattern.findall(streams_content)

        streams = {}
        for label, url in url_matches:
            streams[label] = url.strip()

        if streams:
            if len(streams) > 1:
                stream_labels = []
                stream_urls = []

                for idx, label in enumerate(['primary', 'backup1', 'backup2'], start=1):
                    if label in streams:
                        stream_labels.append(f"Stream {idx}")
                        stream_urls.append(streams[label])

                dialog = xbmcgui.Dialog()
                selected_index = dialog.select('Select Stream Source', stream_labels)

                if selected_index >= 0:
                    stream_url = stream_urls[selected_index]
                else:
                    stream_url = streams.get('primary', next(iter(streams.values())) if streams else None)
            else:
                stream_url = next(iter(streams.values()))

            if stream_url:
                header_string = f'User-Agent={USER_AGENT}&Referer={BASE_URL}&Origin={BASE_URL}'

                # Create a list item with proper metadata for the playing video
                play_item = xbmcgui.ListItem(label=channel_name or "Unknown Channel")

                # Determine genre based on channel name
                genre = 'General'
                title_lower = (channel_name or "").lower()
                if 'sport' in title_lower or 'football' in title_lower or 'tennis' in title_lower or 'basket' in title_lower:
                    genre = 'Sports'
                elif 'film' in title_lower or 'movie' in title_lower or 'cinema' in title_lower:
                    genre = 'Movies'
                elif 'music' in title_lower or 'muzica' in title_lower or 'radio' in title_lower:
                    genre = 'Music'
                elif 'news' in title_lower or 'stiri' in title_lower or 'info' in title_lower:
                    genre = 'News'
                elif 'kids' in title_lower or 'copii' in title_lower or 'cartoon' in title_lower:
                    genre = 'Kids'

                play_item.setInfo('video', {
                    'title': channel_name or "Unknown Channel",
                    'originaltitle': channel_name or "Unknown Channel",
                    'plot': f'Playing {channel_name or "channel"} from Rotv123',
                    'genre': genre,
                    'mediatype': 'video',
                    'studio': 'ROTV123',
                    'country': 'Romania'
                })

                # Set art for the playing item
                play_item.setArt({
                    'thumb': 'special://home/addons/plugin.video.rotv123/icon.png',
                    'icon': 'special://home/addons/plugin.video.rotv123/icon.png',
                    'fanart': 'special://home/addons/plugin.video.rotv123/fanart.jpg'
                })

                play_item.setPath(stream_url + '|' + header_string)
                xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_item)
            else:
                xbmcgui.Dialog().notification('Rotv123', 'No stream URLs found', xbmcgui.NOTIFICATION_ERROR)
                xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())
        else:
            xbmcgui.Dialog().notification('Rotv123', 'No stream URLs found', xbmcgui.NOTIFICATION_ERROR)
            xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())
    else:
        xbmcgui.Dialog().notification('Rotv123', 'Stream not found', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())

def extract_channel_name_from_url(url):
    """
    Extract channel name from the URL by parsing the path
    """
    try:
        parsed_url = urllib.parse.urlparse(url)
        path_parts = parsed_url.path.split('/')
        # Look for the channel name in the URL path
        for part in reversed(path_parts):
            if part and not part.endswith('.php') and not part.endswith('.html'):
                return part.replace('-', ' ').replace('_', ' ').title()
        return None
    except:
        return None

def router(param_string):
    params = dict(urllib.parse.parse_qsl(param_string))
    mode = params.get('mode')

    if mode is None:
        main_menu()
    elif mode == 'category':
        list_category(params.get('url'))
    elif mode == 'play':
        play_video(params.get('url'))
    elif mode == 'search':
        search_channels()
    else:
        main_menu()

def search_channels():
    """Placeholder for search functionality"""
    dialog = xbmcgui.Dialog()
    search_term = dialog.input('Enter search term', type=xbmcgui.INPUT_ALPHANUM)

    if search_term:
        # For now, just show a notification since actual search implementation would require
        # checking the website's search functionality
        dialog.notification('Rotv123', f'Search for "{search_term}" not yet implemented', xbmcgui.NOTIFICATION_INFO)
        main_menu()
    else:
        main_menu()

if __name__ == '__main__':
    router(sys.argv[2][1:])
