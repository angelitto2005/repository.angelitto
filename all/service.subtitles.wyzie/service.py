import xbmcaddon, sys
__addon__ = xbmcaddon.Addon()
sursa = __addon__.getSettingInt('sursa_activa')
if sursa == 1:
    import service_subhero as provider
else:
    import service_wyzie as provider
if __name__ == '__main__':
    provider.run()