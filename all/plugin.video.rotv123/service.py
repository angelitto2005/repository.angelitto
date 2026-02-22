# -*- coding: utf-8 -*-
#service.py

import time
import xbmc

from common import (
    log,
    load_catalog,
    get_active_channels,
    get_epg_id,
    get_settings,
    prefetch_epg,
)

EPG_REFRESH_INTERVAL = 3600


def do_prefetch():
    settings = get_settings()
    source   = settings['epg_source']

    if not source:
        log('EPG sursă = Niciunul, skip prefetch')
        return

    channels    = get_active_channels()
    station_ids = [get_epg_id(ch, source) for ch in channels]
    station_ids = [s for s in station_ids if s]

    log(f'EPG prefetch pentru {len(station_ids)} stații (sursă: {source})')
    prefetch_epg(station_ids)
    log('EPG prefetch complet')


def run():
    log('Service pornit')
    monitor = xbmc.Monitor()

    log('Verificare catalog...')
    load_catalog()

    do_prefetch()

    last_epg_refresh = time.time()

    while not monitor.abortRequested():
        if monitor.waitForAbort(60):
            break

        elapsed = time.time() - last_epg_refresh
        if elapsed >= EPG_REFRESH_INTERVAL:
            log('EPG refresh periodic...')
            do_prefetch()
            last_epg_refresh = time.time()

    log('Service oprit')


if __name__ == '__main__':
    run()
