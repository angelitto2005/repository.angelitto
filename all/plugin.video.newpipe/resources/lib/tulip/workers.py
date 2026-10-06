# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import threading


class Thread(threading.Thread):

    def __init__(self, target, *args):
        self.__target = target
        self.__args = args
        threading.Thread.__init__(self)

    def run(self):

        try:
            self.__target(*self.__args)
        except TypeError:
            return
