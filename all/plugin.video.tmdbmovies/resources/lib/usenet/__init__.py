"""Usenet (NZB) support: our own indexers (Newznab) played over our own
NNTP provider, without debrid.

Layout:
    nntp.py     NNTP transport (RFC 3977): TLS, AUTHINFO, STAT, BODY
    yenc.py     yEnc decoding
    nzb.py      NZB parsing, media picking, stored RAR volumes
    config.py   the settings from Settings > Usenet
    indexer.py  Newznab search (several indexers, quotas, cache)
    health.py   availability check with STAT (no article download)
    engine.py   an NZB turned into a byte stream
    server.py   local HTTP server with Range, what Kodi plays
    service_host.py  starts the server inside the add-on service
"""
