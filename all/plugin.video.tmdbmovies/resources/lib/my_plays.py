# -*- coding: utf-8 -*-
"""My Plays - meniul "Play/Search with <player>" (context menu).

Mutat din tmdb_api.py ca sa nu creasca fisierul. Entry point:
entry.py -> mode=show_my_plays_menu.
Pentru un player nou: adauga un bloc in show_my_plays_menu + un
toggle use_<player> in resources/settings.xml.
"""

import json
import xbmc
import xbmcgui

from urllib.parse import quote_plus

def show_my_plays_menu(params):
    from resources.lib.config import ADDON, API_KEY, BASE_URL, LANG, IMG_BASE, BACKDROP_BASE
    from resources.lib.tmdb_api import get_tmdb_item_details, get_trakt_id
    
    tmdb_id = params.get('tmdb_id')
    c_type = params.get('type') # movie, tv, season, episode
    
    # Date brute
    title = params.get('title', '') 
    year = params.get('year', '')
    season = params.get('season', '')
    episode = params.get('episode', '')
    ep_name = params.get('ep_name', '')       
    premiered = params.get('premiered', '')   
    
    safe_title = quote_plus(title)
    
    # --- FETCH DATE COMPLETE PENTRU A SIMULA TMDB HELPER ---
    poster = ''
    fanart = ''
    plot = ''
    correct_imdb_id = params.get('imdb_id', '')
    correct_tvdb_id = ''
    rating = 0.0
    votes = 0
    studio = ''
    genre = ''
    mpaa = ''
    status = ''
    cast_list = []
    director = ''
    writer = ''

    try:
        main_details = get_tmdb_item_details(tmdb_id, 'movie' if c_type == 'movie' else 'tv') or {}
        
        if main_details:
            if main_details.get('poster_path'):
                poster = f"{IMG_BASE}{main_details['poster_path']}"
            if main_details.get('backdrop_path'):
                fanart = f"{BACKDROP_BASE}{main_details['backdrop_path']}"
            
            ext_ids = main_details.get('external_ids', {})
            if not correct_imdb_id: correct_imdb_id = ext_ids.get('imdb_id', '')
            correct_tvdb_id = str(ext_ids.get('tvdb_id', ''))
            
            status = main_details.get('status', '')
            if main_details.get('genres'):
                genre = ' / '.join([g['name'] for g in main_details['genres']])
            if main_details.get('networks'):
                studio = main_details['networks'][0].get('name', '')
            elif main_details.get('production_companies'):
                studio = main_details['production_companies'][0].get('name', '')
            
            if not year:
                date_ref = main_details.get('release_date') or main_details.get('first_air_date')
                if date_ref: year = date_ref[:4]

        if c_type == 'episode':
            ep_url = f"{BASE_URL}/tv/{tmdb_id}/season/{season}/episode/{episode}?api_key={API_KEY}&language={LANG}&append_to_response=credits"
            import requests
            r_ep = requests.get(ep_url, timeout=3)
            if r_ep.status_code == 200:
                ed = r_ep.json()
                plot = ed.get('overview', '')
                rating = float(ed.get('vote_average', 0.0))
                votes = int(ed.get('vote_count', 0))
                for actor in ed.get('credits', {}).get('guest_stars', [])[:10]:
                    cast_list.append({"name": actor['name'], "role": actor.get('character', '')})
        else:
            plot = main_details.get('overview', '')
            rating = float(main_details.get('vote_average', 0.0))
            votes = int(main_details.get('vote_count', 0))
            for actor in main_details.get('credits', {}).get('cast', [])[:10]:
                cast_list.append({"name": actor['name'], "role": actor.get('character', '')})

    except: pass

    if not year and premiered: year = premiered[:4]
    
    # === CITIRE SETARI PLAYERE ===
    # != 'false' asigura ca, daca setarea nu a fost inca salvata in settings.xml, va functiona ca TRUE implicit.
    show_pov = ADDON.getSetting('use_pov') != 'false'
    show_salts = ADDON.getSetting('use_salts') != 'false'
    show_fenlight = ADDON.getSetting('use_fenlight') != 'false'
    show_redlight = ADDON.getSetting('use_redlight') != 'false'
    show_fen = ADDON.getSetting('use_fen') != 'false'
    show_magneto = ADDON.getSetting('use_magneto') != 'false'
    show_luckodi = ADDON.getSetting('use_luckodi') != 'false'
    show_umbrella = ADDON.getSetting('use_umbrella') != 'false'
    show_elementum = ADDON.getSetting('use_elementum') != 'false'
    show_cinebox = ADDON.getSetting('use_cinebox') != 'false'
    show_seren = ADDON.getSetting('use_seren') != 'false'
    show_mrsplite = ADDON.getSetting('use_mrsplite') != 'false'
    show_tmdbhelper = ADDON.getSetting('use_tmdbhelper') != 'false'
    show_forge = ADDON.getSetting('use_forge') != 'false'

    options = []
    actions = []
    is_folder_list = [] 
    is_luc_kodi_action = [] 

    is_playable_context = (c_type in ['movie', 'episode'])
    prefix = "Play with" if is_playable_context else "Search with"

    # =========================================================================
    # 0. SERIALE (TV)
    # =========================================================================
    if c_type == 'tv':
        if show_tmdbhelper:
            url = f"plugin://plugin.video.themoviedb.helper/?info=search&type=tv&query={safe_title}"
            options.append(f"[B]Search with [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
            actions.append(url)
            is_folder_list.append(True) 
            is_luc_kodi_action.append(False)
        
        if not options:
            xbmcgui.Dialog().notification("My Plays", "Toate playerele sunt dezactivate!", xbmcgui.NOTIFICATION_WARNING)
            return
            
        ret = xbmcgui.Dialog().contextmenu(options)
        if ret >= 0:
            xbmc.executebuiltin(f'ActivateWindow(Videos,"{actions[ret]}",return)')
        return

    # =========================================================================
    # 1. PLAYERE DIRECTE
    # =========================================================================
    if c_type != 'season':
        # External addon integration (optional player)
        if show_pov:
            if c_type == 'movie':
                pov_url = f"plugin://plugin.video.pov/?mode=play_media&mediatype=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                pov_url = f"plugin://plugin.video.pov/?mode=play_media&mediatype=episode&query={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR FFB041FF]POV[/COLOR][/B]")
            actions.append(pov_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # SALTS
        if show_salts:
            if c_type == 'movie':
                salts_url = f"plugin://plugin.video.sallts/?mode=play_media&mediatype=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                salts_url = f"plugin://plugin.video.sallts/?mode=play_media&mediatype=episode&query={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR gold]SALTS[/COLOR][/B]")
            actions.append(salts_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # FEN LIGHT
        if show_fenlight:
            if c_type == 'movie':
                fen_url = f"plugin://plugin.video.fenlight/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                fen_url = f"plugin://plugin.video.fenlight/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR lightskyblue]Fen Light[/COLOR][/B]")
            actions.append(fen_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # RED LIGHT
        if show_redlight:
            if c_type == 'movie':
                red_url = f"plugin://plugin.video.redlight/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                red_url = f"plugin://plugin.video.redlight/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR FFFF2222]Red Light[/COLOR][/B]")
            actions.append(red_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # FEN
        if show_fen:
            if c_type == 'movie':
                fen_url = f"plugin://plugin.video.fen/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                fen_url = f"plugin://plugin.video.fen/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR lightskyblue]Fen[/COLOR][/B]")
            actions.append(fen_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # FORGE (Fen-based fork; keyless playback.media entry point)
        if show_forge:
            if c_type == 'movie':
                forge_url = f"plugin://plugin.video.forge/?mode=playback.media&media_type=movie&query={safe_title}&year={year}&poster={quote_plus(poster)}&title={safe_title}&tmdb_id={tmdb_id}&autoplay=false"
            else:
                forge_url = f"plugin://plugin.video.forge/?mode=playback.media&media_type=episode&query={safe_title}&year={year}&season={season}&episode={episode}&ep_name={quote_plus(ep_name)}&tmdb_id={tmdb_id}&premiered={premiered}&autoplay=false"
            options.append(f"[B]{prefix} [COLOR FFCD853F]Forge[/COLOR][/B]")
            actions.append(forge_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # MAGNETO
        if show_magneto:
            if c_type == 'movie':
                mag_url = f"plugin://script.module.magneto/?action=MediaPlay&mediatype=movie&imdb_id={correct_imdb_id}"
            else:
                mag_url = f"plugin://script.module.magneto/?action=MediaPlay&mediatype=episode&imdb_id={correct_imdb_id}&season={season}&episode={episode}"
            
            options.append(f"[B]{prefix} [COLOR red]Magneto[/COLOR][/B]")
            actions.append(mag_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)


        # =========================================================================
        # 2. luc_Kodi
        # =========================================================================
        meta_enc = "" # O definim aici sa fie accesibila si la Umbrella
        if show_luckodi or show_umbrella:
            meta_obj = {
                "premiered": premiered,
                "plot": plot,
                "tmdb": str(tmdb_id),
                "poster": poster,
                "thumb": poster,
                "fanart": fanart,
                "rating": rating,
                "votes": votes,
                "imdb": correct_imdb_id,
                "imdbnumber": correct_imdb_id,
                "code": correct_imdb_id,
                "year": str(year),
                "mediatype": c_type,
                "studio": studio,
                "genre": genre,
                "status": status,
                "castandart": cast_list
            }
            
            if c_type == 'episode':
                meta_obj.update({"title": ep_name, "tvshowtitle": title, "label": ep_name, "season": int(season), "episode": int(episode), "tvdb": correct_tvdb_id})
                meta_enc = quote_plus(json.dumps(meta_obj, ensure_ascii=False))
                lk_url = f"plugin://plugin.video.luc_kodi/?action=play&tmdb={tmdb_id}&tvdb={correct_tvdb_id}&title={quote_plus(ep_name)}&tvshowtitle={safe_title}&season={season}&episode={episode}&year={year}&premiered={premiered}&imdb={correct_imdb_id}&select=0&meta={meta_enc}"
            else:
                meta_obj.update({"title": title, "originaltitle": title})
                meta_enc = quote_plus(json.dumps(meta_obj, ensure_ascii=False))
                lk_url = f"plugin://plugin.video.luc_kodi/?action=play&tmdb={tmdb_id}&title={safe_title}&year={year}&premiered={premiered}&imdb={correct_imdb_id}&select=0&meta={meta_enc}"

            if show_luckodi:
                options.append(f"[B]{prefix} [COLOR ff00fa9a]luc_[/COLOR]Kodi[/B]")
                actions.append(lk_url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(True)

        # =========================================================================
        # 3. UMBRELLA
        # =========================================================================
        if show_umbrella:
            if c_type == 'movie':
                umb_url = f"plugin://plugin.video.umbrella/?action=play&title={safe_title}&year={year}&imdb={correct_imdb_id}&tmdb={tmdb_id}&meta={meta_enc}&select=0"
            else:
                umb_url = f"plugin://plugin.video.umbrella/?action=play&title={quote_plus(ep_name)}&year={year}&imdb={correct_imdb_id}&tmdb={tmdb_id}&tvdb={correct_tvdb_id}&season={season}&episode={episode}&tvshowtitle={safe_title}&premiered={premiered}&meta={meta_enc}&select=0"
            
            options.append(f"[B]{prefix} [COLOR FFE41B17]Umbrella[/COLOR][/B]")
            actions.append(umb_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(True)

        # =========================================================================
        # 4. ELEMENTUM
        # =========================================================================
        if show_elementum:
            if c_type == 'movie':
                elem_url = f"plugin://plugin.video.elementum/library/play/movie/{tmdb_id}"
            else:
                elem_url = f"plugin://plugin.video.elementum/library/play/show/{tmdb_id}/season/{season}/episode/{episode}"
            
            options.append(f"[B]{prefix} [COLOR FF786D5F]Elementum[/COLOR][/B]")
            actions.append(elem_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(True)

        # =========================================================================
        # 5. CINEBOX
        # =========================================================================
        if show_cinebox:
            if c_type == 'movie':
                cine_url = f"plugin://plugin.video.cinebox/?action=find_sources&media_type=movie&title={safe_title}&year={year}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&poster={quote_plus(poster)}&autoplay=false"
            else:
                cine_url = f"plugin://plugin.video.cinebox/?action=find_sources&media_type=tvshow&title={safe_title}&year={year}&season={season}&episode={episode}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&poster={quote_plus(poster)}&autoplay=false"
            
            options.append(f"[B]{prefix} [COLOR FFA70D2A]CINEBOX[/COLOR][/B]")
            actions.append(cine_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(True)
            
        # =========================================================================
        # 6. SEREN
        # =========================================================================
        if show_seren:
            trakt_media = 'movie' if c_type == 'movie' else 'show'
            trakt_id = get_trakt_id(correct_imdb_id, tmdb_id, trakt_media)
            
            if trakt_id:
                trakt_id_int = int(trakt_id)
                if c_type == 'movie':
                    action_args = quote_plus(json.dumps({"item_type": "movie", "trakt_id": trakt_id_int}))
                    seren_url = f"plugin://plugin.video.seren/?action=getSources&forceresumecheck=true&source_select=true&actionArgs={action_args}"
                else:
                    action_args = quote_plus(json.dumps({"episode": int(episode), "item_type": "episode", "season": int(season), "trakt_id": trakt_id_int}))
                    seren_url = f"plugin://plugin.video.seren/?action=getSources&smartPlay=false&source_select=true&forceresumecheck=true&actionArgs={action_args}"
                
                options.append(f"[B]{prefix} [COLOR FF00BFFF]Seren[/COLOR][/B]")
                actions.append(seren_url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(True)
            else:
                # Fallback: Search (nu necesita Trakt ID)
                seren_url = f"plugin://plugin.video.seren/?action=moviesSearchResults&actionArgs={safe_title}" if c_type == 'movie' else f"plugin://plugin.video.seren/?action=showsSearchResults&actionArgs={safe_title}"
                options.append(f"[B]Search with [COLOR FF00BFFF]Seren[/COLOR][/B]")
                actions.append(seren_url)
                is_folder_list.append(True)
                is_luc_kodi_action.append(False)
            
        # =========================================================================
        # 7. MRSP Lite
        # =========================================================================
        if show_mrsplite:
            if c_type == 'movie':
                mrsp_url = f"plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant={safe_title}+{year}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&mediatype=movie"
            else:
                try: s_str = f"s{int(season):02d}"
                except: s_str = f"s{season}"
                mrsp_url = f"plugin://plugin.video.romanianpack/?action=searchSites&searchSites=cuvant&cuvant={safe_title}+{s_str}&showname={safe_title}&season={season}&episode={episode}&tmdb_id={tmdb_id}&imdb_id={correct_imdb_id}&mediatype=episode"
            
            options.append(f"[B]{prefix} [COLOR orange]MRSP Lite[/COLOR][/B]")
            actions.append(mrsp_url)
            is_folder_list.append(False)
            is_luc_kodi_action.append(False)

        # =========================================================================
        # 8. TMDb Helper
        # =========================================================================
        if show_tmdbhelper:
            if c_type == 'movie':
                actions.append(f"plugin://plugin.video.themoviedb.helper/?info=search&type=movie&query={safe_title}")
                options.append(f"[B]Search with [COLOR gold]TMDB Helper[/COLOR][/B]")
                is_folder_list.append(True)
                is_luc_kodi_action.append(False)
                
                url = f"plugin://plugin.video.themoviedb.helper/?info=play&type=movie&tmdb_id={tmdb_id}"
                options.append(f"[B]{prefix} [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
                actions.append(url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(False)
            elif c_type == 'episode':
                url = f"plugin://plugin.video.themoviedb.helper/?info=play&type=episode&tmdb_id={tmdb_id}&season={season}&episode={episode}"
                options.append(f"[B]{prefix} [COLOR FF00CED1]TMDB Helper[/COLOR][/B]")
                actions.append(url)
                is_folder_list.append(False)
                is_luc_kodi_action.append(False)

    # --- EXECUTIE ---
    if not options:
        xbmcgui.Dialog().notification("My Plays", "Toate playerele sunt dezactivate!", xbmcgui.NOTIFICATION_WARNING)
        return

    ret = xbmcgui.Dialog().contextmenu(options)
    if ret >= 0:
        target = actions[ret]
        
        if is_luc_kodi_action[ret]:
            xbmc.executebuiltin('Dialog.Close(all,true)')
            xbmc.sleep(300)
            
            if "script.module.magneto" in target:
                xbmc.executebuiltin(f"RunPlugin({target})")
            else:
                xbmc.executebuiltin(f"PlayMedia({target})")
            
        elif is_folder_list[ret]:
            xbmc.executebuiltin(f'ActivateWindow(Videos,"{target}",return)')
        else:
            xbmc.executebuiltin(f"RunPlugin({target})")
