# -*- coding: utf-8 -*-

'''
    Tulip library
    Author Twilight0

    SPDX-License-Identifier: GPL-3.0-only
    See LICENSES/GPL-3.0-only for more information.
'''

import hashlib
import json
from ast import literal_eval as evaluate
from sqlite3 import dbapi2 as database
from tulip import kodi
from tulip.utils import iteritems


def add(url, path=kodi.bookmarksFile):

    try:

        data = json.loads(url)

        dbid = hashlib.md5()

        for i in data['bookmark']:
            try:
                dbid.update(i)
            except TypeError:
                dbid.update(i.encode('utf-8'))
        for i in data['action']:
            try:
                dbid.update(i)
            except TypeError:
                dbid.update(i.encode('utf-8'))

        dbid = str(dbid.hexdigest())

        item = dict((k, v) for k, v in iteritems(data) if not k == 'bookmark')
        item = repr(item)

        kodi.makeFile(kodi.dataPath)
        dbcon = database.connect(path)
        dbcur = dbcon.cursor()
        dbcur.execute("CREATE TABLE IF NOT EXISTS bookmark (""dbid TEXT, ""item TEXT, ""UNIQUE(dbid)"");")
        dbcur.execute("DELETE FROM bookmark WHERE dbid = '{}'".format(dbid))
        dbcur.execute("INSERT INTO bookmark Values (?, ?)", (dbid, item))
        dbcon.commit()

    except Exception:

        pass


def delete(url, path=kodi.bookmarksFile):

    try:

        data = json.loads(url)

        dbid = hashlib.md5()

        for i in data['delbookmark']:
            try:
                dbid.update(i)
            except TypeError:
                dbid.update(i.encode('utf-8'))

        for i in data['action']:
            try:
                dbid.update(i)
            except TypeError:
                dbid.update(i.encode('utf-8'))

        dbid = str(dbid.hexdigest())

        kodi.makeFile(kodi.dataPath)
        dbcon = database.connect(path)
        dbcur = dbcon.cursor()
        dbcur.execute("CREATE TABLE IF NOT EXISTS bookmark (""dbid TEXT, ""item TEXT, ""UNIQUE(dbid)"");")
        dbcur.execute("DELETE FROM bookmark WHERE dbid = '{}'".format(dbid))
        dbcon.commit()

        kodi.refresh()

    except Exception:

        pass


def get(path=kodi.bookmarksFile):

    try:

        kodi.makeFile(kodi.dataPath)
        dbcon = database.connect(path)
        dbcur = dbcon.cursor()
        dbcur.execute("SELECT * FROM bookmark")
        items = dbcur.fetchall()

        try:
            items = [evaluate(i[1].encode('utf-8')) for i in items]
        except Exception:
            items = [evaluate(i[1]) for i in items]

        return items

    except Exception:

        return


def clear(table=None, path=kodi.bookmarksFile):

    try:

        dbcon = database.connect(path)
        dbcur = dbcon.cursor()

        for t in table:
            try:
                dbcur.execute("DROP TABLE IF EXISTS {0}".format(t))
                dbcur.execute("VACUUM")
                dbcon.commit()
            except Exception:
                pass

    except Exception:
        pass


__all__ = ['add', 'delete', 'get', 'clear']
