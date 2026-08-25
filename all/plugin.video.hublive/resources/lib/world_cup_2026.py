from urllib.parse import quote_plus

import xbmc
import xbmcgui
import xbmcplugin


_ROMANIAN_MONTHS = {
    6: "iunie",
    7: "iulie",
}

_DIGITAL_CHANNEL = "AntenaPLAY"
_BROADCASTERS = (
    (
        "România",
        (
            ("Antena 1", "Antena 1"),
            ("Antena 3 CNN", "Antena 3 CNN"),
        ),
    ),
    (
        "SUA",
        (
            ("FOX", "FOX"),
            ("FS1", "FS1"),
            ("Telemundo", "Telemundo"),
            ("Universo", "Universo"),
        ),
    ),
    (
        "Canada",
        (
            ("CTV", "CTV"),
            ("TSN", "TSN"),
            ("RDS", "RDS"),
        ),
    ),
    (
        "Germania",
        (
            ("ARD / Das Erste", "Das Erste"),
            ("ZDF", "ZDF"),
            ("Magenta Sport", "Magenta Sport"),
        ),
    ),
    (
        "Franța",
        (
            ("M6", "M6"),
            ("beIN Sports France", "beIN Sports"),
        ),
    ),
    (
        "Anglia / Regatul Unit",
        (
            ("BBC One", "BBC One"),
            ("BBC Two", "BBC Two"),
            ("ITV1", "ITV 1"),
            ("ITV4", "ITV 4"),
        ),
    ),
    (
        "Spania",
        (
            ("La 1 / RTVE", "La 1"),
            ("Teledeporte", "Teledeporte"),
            ("Gol Mundial / Mediapro", "Gol Mundial"),
            ("DAZN", "DAZN"),
        ),
    ),
    (
        "Italia",
        (
            ("RAI 1", "RAI 1"),
            ("RAI 2", "RAI 2"),
            ("Rai Sport", "Rai Sport"),
            ("DAZN", "DAZN"),
        ),
    ),
)


def _set_video_info(item, title, plot):
    """Set video metadata without relying on Kodi's deprecated setInfo path."""
    get_tag = getattr(item, "getVideoInfoTag", None)
    if callable(get_tag):
        tag = get_tag()
        set_title = getattr(tag, "setTitle", None)
        set_plot = getattr(tag, "setPlot", None)
        if callable(set_title) and callable(set_plot):
            set_title(title)
            set_plot(plot)
            return

    set_info = getattr(item, "setInfo", None)
    if callable(set_info):
        set_info("video", {"title": title, "plot": plot})


# Schedule source:
# https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/match-schedule-fixtures-results-teams-stadiums
# Romanian broadcast source:
# https://a1.ro/campionatul-mondial-de-fotbal-2026/stiri/din-11-iunie-toata-lumea-la-antena-fifa-world-cup-2026-incepe-exclusiv-in-universul-antena-id1157597.html
# International broadcaster reference:
# https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026


def _match(date, time, home, away, stage, venue="", confirmed_channels=()):
    return {
        "id": f"{date}-{time.replace(':', '')}-{home.lower().replace(' ', '-')}",
        "date": date,
        "time": time,
        "home": home,
        "away": away,
        "stage": stage,
        "venue": venue,
        "confirmed_channels": tuple(confirmed_channels),
    }


# Times are local Romanian times (Europe/Bucharest).
MATCHES = [
    _match("2026-06-11", "22:00", "Mexic", "Africa de Sud", "Grupa A", "Mexico City", ("Antena 1",)),
    _match("2026-06-12", "05:00", "Coreea de Sud", "Cehia", "Grupa A", "Guadalajara", ("Antena 1",)),
    _match("2026-06-12", "22:00", "Canada", "Bosnia și Herțegovina", "Grupa B", "Toronto", ("Antena 1",)),
    _match("2026-06-13", "04:00", "SUA", "Paraguay", "Grupa D", "Los Angeles", ("Antena 1",)),
    _match("2026-06-13", "22:00", "Qatar", "Elveția", "Grupa B", "San Francisco Bay Area"),
    _match("2026-06-14", "01:00", "Brazilia", "Maroc", "Grupa C", "New York / New Jersey"),
    _match("2026-06-14", "04:00", "Haiti", "Scoția", "Grupa C", "Boston"),
    _match("2026-06-14", "07:00", "Australia", "Turcia", "Grupa D", "Vancouver"),
    _match("2026-06-14", "20:00", "Germania", "Curaçao", "Grupa E", "Houston"),
    _match("2026-06-14", "23:00", "Țările de Jos", "Japonia", "Grupa F", "Dallas"),
    _match("2026-06-15", "02:00", "Coasta de Fildeș", "Ecuador", "Grupa E", "Philadelphia"),
    _match("2026-06-15", "05:00", "Suedia", "Tunisia", "Grupa F", "Monterrey"),
    _match("2026-06-15", "19:00", "Spania", "Cabo Verde", "Grupa H", "Atlanta"),
    _match("2026-06-15", "22:00", "Belgia", "Egipt", "Grupa G", "Seattle"),
    _match("2026-06-16", "01:00", "Arabia Saudită", "Uruguay", "Grupa H", "Miami"),
    _match("2026-06-16", "04:00", "Iran", "Noua Zeelandă", "Grupa G", "Los Angeles"),
    _match("2026-06-16", "22:00", "Franța", "Senegal", "Grupa I", "New York / New Jersey"),
    _match("2026-06-17", "01:00", "Irak", "Norvegia", "Grupa I", "Boston"),
    _match("2026-06-17", "04:00", "Argentina", "Algeria", "Grupa J", "Kansas City"),
    _match("2026-06-17", "07:00", "Austria", "Iordania", "Grupa J", "San Francisco Bay Area"),
    _match("2026-06-17", "20:00", "Portugalia", "RD Congo", "Grupa K", "Houston"),
    _match("2026-06-17", "23:00", "Anglia", "Croația", "Grupa L", "Dallas"),
    _match("2026-06-18", "02:00", "Ghana", "Panama", "Grupa L", "Toronto"),
    _match("2026-06-18", "05:00", "Uzbekistan", "Columbia", "Grupa K", "Mexico City"),
    _match("2026-06-18", "19:00", "Cehia", "Africa de Sud", "Grupa A", "Atlanta"),
    _match("2026-06-18", "22:00", "Elveția", "Bosnia și Herțegovina", "Grupa B", "Los Angeles"),
    _match("2026-06-19", "01:00", "Canada", "Qatar", "Grupa B", "Vancouver"),
    _match("2026-06-19", "04:00", "Mexic", "Coreea de Sud", "Grupa A", "Guadalajara"),
    _match("2026-06-19", "22:00", "SUA", "Australia", "Grupa D", "Seattle"),
    _match("2026-06-20", "01:00", "Scoția", "Maroc", "Grupa C", "Boston"),
    _match("2026-06-20", "04:00", "Brazilia", "Haiti", "Grupa C", "Philadelphia"),
    _match("2026-06-20", "07:00", "Turcia", "Paraguay", "Grupa D", "San Francisco Bay Area"),
    _match("2026-06-20", "20:00", "Țările de Jos", "Suedia", "Grupa F", "Houston"),
    _match("2026-06-20", "23:00", "Germania", "Coasta de Fildeș", "Grupa E", "Toronto"),
    _match("2026-06-21", "03:00", "Ecuador", "Curaçao", "Grupa E", "Kansas City"),
    _match("2026-06-21", "07:00", "Tunisia", "Japonia", "Grupa F", "Monterrey"),
    _match("2026-06-21", "19:00", "Spania", "Arabia Saudită", "Grupa H", "Atlanta"),
    _match("2026-06-21", "22:00", "Belgia", "Iran", "Grupa G", "Los Angeles"),
    _match("2026-06-22", "01:00", "Uruguay", "Cabo Verde", "Grupa H", "Miami"),
    _match("2026-06-22", "04:00", "Noua Zeelandă", "Egipt", "Grupa G", "Vancouver"),
    _match("2026-06-22", "20:00", "Argentina", "Austria", "Grupa J", "Dallas"),
    _match("2026-06-23", "00:00", "Franța", "Irak", "Grupa I", "Philadelphia"),
    _match("2026-06-23", "03:00", "Norvegia", "Senegal", "Grupa I", "Toronto"),
    _match("2026-06-23", "06:00", "Iordania", "Algeria", "Grupa J", "San Francisco Bay Area"),
    _match("2026-06-23", "20:00", "Portugalia", "Uzbekistan", "Grupa K", "Houston"),
    _match("2026-06-23", "23:00", "Anglia", "Ghana", "Grupa L", "Boston"),
    _match("2026-06-24", "02:00", "Panama", "Croația", "Grupa L", "Toronto"),
    _match("2026-06-24", "05:00", "Columbia", "RD Congo", "Grupa K", "Guadalajara"),
    _match("2026-06-24", "22:00", "Elveția", "Canada", "Grupa B", "Vancouver"),
    _match("2026-06-24", "22:00", "Bosnia și Herțegovina", "Qatar", "Grupa B", "Seattle"),
    _match("2026-06-25", "01:00", "Maroc", "Haiti", "Grupa C", "Atlanta"),
    _match("2026-06-25", "01:00", "Scoția", "Brazilia", "Grupa C", "Miami"),
    _match("2026-06-25", "04:00", "Cehia", "Mexic", "Grupa A", "Mexico City"),
    _match("2026-06-25", "04:00", "Africa de Sud", "Coreea de Sud", "Grupa A", "Monterrey"),
    _match("2026-06-25", "23:00", "Curaçao", "Coasta de Fildeș", "Grupa E", "Philadelphia"),
    _match("2026-06-25", "23:00", "Ecuador", "Germania", "Grupa E", "New York / New Jersey"),
    _match("2026-06-26", "01:00", "Japonia", "Suedia", "Grupa F", "Dallas"),
    _match("2026-06-26", "02:00", "Tunisia", "Țările de Jos", "Grupa F", "Kansas City"),
    _match("2026-06-26", "05:00", "Turcia", "SUA", "Grupa D", "Los Angeles"),
    _match("2026-06-26", "05:00", "Paraguay", "Australia", "Grupa D", "San Francisco Bay Area"),
    _match("2026-06-26", "22:00", "Norvegia", "Franța", "Grupa I", "Boston"),
    _match("2026-06-26", "22:00", "Senegal", "Irak", "Grupa I", "Toronto"),
    _match("2026-06-27", "00:00", "Panama", "Anglia", "Grupa L", "New York / New Jersey"),
    _match("2026-06-27", "00:00", "Croația", "Ghana", "Grupa L", "Philadelphia"),
    _match("2026-06-27", "03:00", "Cabo Verde", "Arabia Saudită", "Grupa H", "Houston"),
    _match("2026-06-27", "03:00", "Uruguay", "Spania", "Grupa H", "Guadalajara"),
    _match("2026-06-27", "06:00", "Noua Zeelandă", "Belgia", "Grupa G", "Vancouver"),
    _match("2026-06-27", "06:00", "Egipt", "Iran", "Grupa G", "Seattle"),
    _match("2026-06-28", "02:30", "Columbia", "Portugalia", "Grupa K", "Miami"),
    _match("2026-06-28", "02:30", "RD Congo", "Uzbekistan", "Grupa K", "Atlanta"),
    _match("2026-06-28", "05:00", "Algeria", "Austria", "Grupa J", "Kansas City"),
    _match("2026-06-28", "05:00", "Iordania", "Argentina", "Grupa J", "Dallas"),
    _match("2026-06-28", "22:00", "Locul 2 Grupa A", "Locul 2 Grupa B", "Șaisprezecimi", "Los Angeles"),
    _match("2026-06-29", "20:00", "Câștigătoare Grupa C", "Locul 2 Grupa F", "Șaisprezecimi", "Houston"),
    _match("2026-06-29", "23:30", "Câștigătoare Grupa E", "Cel mai bun loc 3", "Șaisprezecimi", "Boston"),
    _match("2026-06-30", "04:00", "Câștigătoare Grupa F", "Locul 2 Grupa C", "Șaisprezecimi", "Monterrey"),
    _match("2026-06-30", "20:00", "Locul 2 Grupa E", "Locul 2 Grupa I", "Șaisprezecimi", "Dallas"),
    _match("2026-07-01", "00:00", "Câștigătoare Grupa I", "Cel mai bun loc 3", "Șaisprezecimi", "New York / New Jersey"),
    _match("2026-07-01", "04:00", "Câștigătoare Grupa A", "Cel mai bun loc 3", "Șaisprezecimi", "Mexico City"),
    _match("2026-07-01", "19:00", "Câștigătoare Grupa L", "Cel mai bun loc 3", "Șaisprezecimi", "Atlanta"),
    _match("2026-07-01", "23:00", "Câștigătoare Grupa G", "Cel mai bun loc 3", "Șaisprezecimi", "Seattle"),
    _match("2026-07-02", "03:00", "Câștigătoare Grupa D", "Cel mai bun loc 3", "Șaisprezecimi", "San Francisco Bay Area"),
    _match("2026-07-02", "22:00", "Câștigătoare Grupa H", "Locul 2 Grupa J", "Șaisprezecimi", "Los Angeles"),
    _match("2026-07-03", "02:00", "Locul 2 Grupa K", "Locul 2 Grupa L", "Șaisprezecimi", "Toronto"),
    _match("2026-07-03", "06:00", "Câștigătoare Grupa B", "Cel mai bun loc 3", "Șaisprezecimi", "Vancouver"),
    _match("2026-07-03", "21:00", "Câștigătoare Grupa J", "Locul 2 Grupa H", "Șaisprezecimi", "Dallas"),
    _match("2026-07-04", "01:00", "Locul 2 Grupa D", "Locul 2 Grupa G", "Șaisprezecimi", "Miami"),
    _match("2026-07-04", "03:30", "Câștigătoare Grupa K", "Cel mai bun loc 3", "Șaisprezecimi", "Vancouver"),
    _match("2026-07-04", "21:00", "Câștigătoare M73", "Câștigătoare M75", "Optimi", "Houston"),
    _match("2026-07-05", "00:00", "Câștigătoare M74", "Câștigătoare M77", "Optimi", "Philadelphia"),
    _match("2026-07-05", "23:00", "Câștigătoare M76", "Câștigătoare M78", "Optimi", "New York / New Jersey"),
    _match("2026-07-06", "03:00", "Câștigătoare M79", "Câștigătoare M80", "Optimi", "Mexico City"),
    _match("2026-07-06", "22:00", "Câștigătoare M83", "Câștigătoare M84", "Optimi", "Dallas"),
    _match("2026-07-07", "03:00", "Câștigătoare M81", "Câștigătoare M82", "Optimi", "Seattle"),
    _match("2026-07-07", "19:00", "Câștigătoare M86", "Câștigătoare M88", "Optimi", "Atlanta"),
    _match("2026-07-07", "23:00", "Câștigătoare M85", "Câștigătoare M87", "Optimi", "Vancouver"),
    _match("2026-07-09", "23:00", "Câștigătoare M89", "Câștigătoare M90", "Sferturi", "Boston"),
    _match("2026-07-10", "22:00", "Câștigătoare M93", "Câștigătoare M94", "Sferturi", "Los Angeles"),
    _match("2026-07-11", "00:00", "Câștigătoare M95", "Câștigătoare M96", "Sferturi", "Miami"),
    _match("2026-07-12", "04:00", "Câștigătoare M91", "Câștigătoare M92", "Sferturi", "Kansas City"),
    _match("2026-07-14", "22:00", "Câștigătoare M97", "Câștigătoare M98", "Semifinală", "Dallas"),
    _match("2026-07-15", "22:00", "Câștigătoare M99", "Câștigătoare M100", "Semifinală", "Atlanta"),
    _match("2026-07-18", "00:00", "Pierzătoare M101", "Pierzătoare M102", "Locul 3", "Miami"),
    _match("2026-07-19", "22:00", "Câștigătoare M101", "Câștigătoare M102", "Finală", "New York / New Jersey"),
]


def _date_label(date_value):
    try:
        year_text, month_text, day_text = date_value.split("-", 2)
        year = int(year_text)
        month = int(month_text)
        day = int(day_text)
        month_name = _ROMANIAN_MONTHS[month]
    except (AttributeError, KeyError, TypeError, ValueError):
        return date_value or ""
    return f"{day} {month_name} {year}"


def _find_match(match_id):
    return next((match for match in MATCHES if match["id"] == match_id), None)


def list_world_cup_matches(base_url, handle):
    xbmc.log("[WorldCup] Rendering match schedule", level=xbmc.LOGINFO)
    xbmcplugin.setPluginCategory(handle, "World Cup 2026")
    previous_date = None

    for match in MATCHES:
        if match["date"] != previous_date:
            previous_date = match["date"]
            header = xbmcgui.ListItem(
                label=f"[COLOR gold]--- {_date_label(previous_date)} ---[/COLOR]"
            )
            xbmcplugin.addDirectoryItem(
                handle=handle, url="", listitem=header, isFolder=False
            )

        confirmed = match["confirmed_channels"]
        channel_status = (
            f"[COLOR green]{', '.join(confirmed)}[/COLOR]"
            if confirmed
            else "[COLOR gray]post TV în curs de confirmare[/COLOR]"
        )
        label = (
            f"[B]{match['time']}[/B]  {match['home']} - {match['away']} "
            f"[COLOR gray]({match['stage']})[/COLOR]"
        )
        item = xbmcgui.ListItem(label=label)
        item.setArt(
            {"icon": "DefaultAddonGame.png", "thumb": "DefaultAddonGame.png"}
        )
        _set_video_info(
            item,
            f"{match['home']} - {match['away']}",
            (
                f"{_date_label(match['date'])}, ora {match['time']}\n"
                f"{match['stage']} - {match['venue']}\n"
                f"Canal liniar: {channel_status}\n"
                f"Online oficial: {_DIGITAL_CHANNEL}"
            ),
        )
        url = f"{base_url}?mode=world_cup_match&match_id={quote_plus(match['id'])}"
        xbmcplugin.addDirectoryItem(
            handle=handle, url=url, listitem=item, isFolder=True
        )

    xbmcplugin.endOfDirectory(handle, cacheToDisc=True)
    xbmc.log(
        f"[WorldCup] Match schedule rendered: {len(MATCHES)} matches",
        level=xbmc.LOGINFO,
    )


def list_world_cup_match_channels(base_url, handle, match_id):
    xbmc.log(
        f"[WorldCup] Rendering broadcaster list for {match_id}",
        level=xbmc.LOGINFO,
    )
    match = _find_match(match_id)
    if not match:
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return

    title = f"{match['home']} - {match['away']}"
    xbmcplugin.setPluginCategory(handle, title)

    info = xbmcgui.ListItem(
        label=(
            f"[COLOR gold]{_date_label(match['date'])}, "
            f"{match['time']} - {match['stage']}[/COLOR]"
        )
    )
    _set_video_info(
        info,
        title,
        (
            f"{match['venue']}\n"
            f"Drepturi România: Antena Group\n"
            f"Online oficial: {_DIGITAL_CHANNEL}"
        ),
    )
    xbmcplugin.addDirectoryItem(
        handle=handle, url="", listitem=info, isFolder=False
    )

    confirmed = set(match["confirmed_channels"])
    for country, broadcasters in _BROADCASTERS:
        country_header = xbmcgui.ListItem(
            label=f"[COLOR gold]--- {country} ---[/COLOR]"
        )
        xbmcplugin.addDirectoryItem(
            handle=handle, url="", listitem=country_header, isFolder=False
        )

        for broadcaster, search_query in broadcasters:
            if country == "România":
                status = (
                    "[COLOR green]confirmat pentru acest meci[/COLOR]"
                    if broadcaster in confirmed
                    else "[COLOR gray]grila exactă nu este confirmată[/COLOR]"
                )
            else:
                status = "[COLOR cyan]broadcaster oficial în această țară[/COLOR]"

            item = xbmcgui.ListItem(label=f"{broadcaster} - {status}")
            item.setArt(
                {
                    "icon": "DefaultAddonPVRClient.png",
                    "thumb": "DefaultAddonPVRClient.png",
                }
            )
            _set_video_info(
                item,
                broadcaster,
                (
                    f"Țară: {country}\n"
                    "Deținător de drepturi pentru World Cup 2026.\n"
                    "Canalul exact al acestui meci poate varia în grila locală.\n"
                    f'Caută în HubLive după: "{search_query}".'
                ),
            )
            search_url = (
                f"{base_url}?mode=mega_search_results"
                f"&query={quote_plus(search_query)}&search_type=live"
            )
            xbmcplugin.addDirectoryItem(
                handle=handle, url=search_url, listitem=item, isFolder=True
            )

    digital = xbmcgui.ListItem(
        label=f"{_DIGITAL_CHANNEL} - [COLOR cyan]platformă online oficială[/COLOR]"
    )
    _set_video_info(
        digital,
        _DIGITAL_CHANNEL,
        (
            "AntenaPLAY este platforma online oficială. "
            "HubLive nu încearcă să o redea ca flux IPTV."
        ),
    )
    xbmcplugin.addDirectoryItem(
        handle=handle, url="", listitem=digital, isFolder=False
    )
    xbmcplugin.endOfDirectory(handle, cacheToDisc=True)
    xbmc.log(
        f"[WorldCup] Broadcaster list rendered for {match_id}",
        level=xbmc.LOGINFO,
    )
