# -*- coding: utf-8 -*-
import xbmcaddon, sys

__addon__ = xbmcaddon.Addon()
# 0 = Wyzie, 1 = SubHero (Verifică să fie 'sursa_activa' ca în XML)
sursa = __addon__.getSettingInt('sursa_activa')

if sursa == 1:
    import service_subhero as provider
else:
    import service_wyzie as provider

if __name__ == '__main__':
    provider.run()
