# -*- coding: utf-8 -*-

from resources.functions import *
from resources.lib.windows.base import BaseDialog
__settings__ = xbmcaddon.Addon()


class BrowseTorrentsXML(BaseDialog):
    def __init__(self, *args, **kwargs):
        super(BrowseTorrentsXML, self).__init__(self, args)
        self.window_id = 2003
        self.files = kwargs.get('files')
        self.total_results = str(len(self.files))
        self.meta = kwargs.get('meta')
        self.info = kwargs.get('info')
        self.addon_path = args[1]
        self.contentListNew = None
        self.link = kwargs.get('link')
        self.site = kwargs.get('site')
        if self.info:
            if py3:
                if isinstance(self.info, str):
                    self.info = eval(self.info)
            else:
                if isinstance(self.info, basestring):
                    self.info = eval(self.info)
        self.cm = None
        self.tdir = None
        self.item_dirs = []
        self.process_files()
        self.make_items()
        self.set_properties()

    def onInit(self):
        super(BrowseTorrentsXML, self).onInit()
        win = self.getControl(self.window_id)
        win.addItems(self.item_list)
        self.setFocusId(self.window_id)

    def run(self):
        self.doModal()
        try: del self.info
        except: pass
        try: del self.cm
        except: pass
        return self.selected

    def onAction(self, action):
        try:
            action_id = action.getId()
            if action_id in self.selection_actions:
                focus_id = self.getFocusId()
                position = self.get_position(self.window_id)
                chosen = self.item_list[position]
                if focus_id == 2003:
                    source = chosen.getProperty('mrsp.name')
                    folder = chosen.getProperty('mrsp.folder')
                    index = chosen.getProperty('mrsp.index')
                    noplay = chosen.getProperty('mrsp.play') == 'false'
                    if folder == 'true':
                        if self.tdir and position == 0:
                            self.tdir = None
                        elif (not self.tdir) and position == 0:
                            self.selected = ('', index)
                            self.close()
                        else:
                            self.tdir = source
                        self.process_files()
                        self.make_items()
                        self.set_properties()
                        win = self.getControl(self.window_id)
                        win.reset()
                        win.addItems(self.item_list)
                    else:
                        if not noplay:
                            self.selected = ('Play', index)
                            self.close()
            if action in self.closing_actions:
                self.selected = (None, '')
                self.close()
        except BaseException as e:
            log(e)
    
    def process_files(self):
        contentList = []
        for filedict in self.files:
            fileTitle = filedict.get('title')
            if self.tdir:
                if not self.tdir in fileTitle:
                    continue
            size = filedict.get('size')
            contentList.append([unescape(fileTitle).decode('utf-8'), str(filedict.get('ind')), size])
        self.item_dirs, self.contentListNew = cutFolder(contentList, self.tdir)
        self.item_dirs = sorted(self.item_dirs, key=lambda x: x[0].lower())
        self.contentListNew = sorted(self.contentListNew, key=lambda x: x[0].lower())
    def make_items(self):
        def builder():
            foldericon = os.path.join(self.addon_path, 'resources', 'skins', 'Default', 'media', 'common', 'folder.png')
            videoicon = os.path.join(self.addon_path, 'resources', 'skins', 'Default', 'media', 'common', 'video.png')
            genericicon = os.path.join(self.addon_path, 'resources', 'skins', 'Default', 'media', 'common', 'file.png')
            EXTS=['avi','mp4','mkv','flv','mov','vob','wmv','ogm','asx','mpg','mpeg','avc','vp3','fli','flc','m4v','iso','mp3','m2ts','3gp', 'ts']
            listitem = self.make_listitem()
            listitem.setProperty('mrsp.name', '..')
            listitem.setProperty('mrsp.folder', 'true')
            yield listitem
            j = 1
            for count, item in enumerate(self.item_dirs, 1):
                try:
                    listitem = self.make_listitem()
                    listitem.setProperty('mrsp.name', item)
                    listitem.setProperty('mrsp.folder', 'true')
                    listitem.setProperty('mrsp.size', 'Folder')
                    listitem.setProperty('mrsp.type', foldericon)
                    listitem.setProperty('mrsp.number', str(j))
                    j += 1
                    yield listitem
                except BaseException as e:
                    log(e)
            for name, index, size in self.contentListNew:
                try:
                    listitem = self.make_listitem()
                    if py3:
                        try: titleext = name.decode().split('.')[-1].lower()
                        except: titleext = name.split('.')[-1].lower()
                    else:
                        titleext = name.decode('utf-8').split('.')[-1].lower()
                    if titleext in EXTS:
                        listitem.setProperty('mrsp.type', videoicon)
                    else:
                        listitem.setProperty('mrsp.type', genericicon)
                        listitem.setProperty('mrsp.play', 'false')
                    listitem.setProperty('mrsp.name', name)
                    listitem.setProperty('mrsp.size', self.get_size(size))
                    listitem.setProperty('mrsp.index', str(index))
                    listitem.setProperty('mrsp.number', str(j))
                    j += 1
                    yield listitem
                except BaseException as e:
                    log(e)
        try:
            self.item_list = list(builder())
            self.total_results = str(len(self.item_list) - 1)
        except BaseException as e:
            log(e)

    def set_properties(self):
        if not self.info: return
        self.setProperty('mrsp.title', self.info.get('Title', ''))
        self.setProperty('mrsp.plot', self.info.get('Plot', ''))
        self.setProperty('mrsp.genre', self.info.get('Genre', ''))
        self.setProperty('mrsp.poster', self.info.get('Poster', ''))
        self.setProperty('mrsp.size', self.get_size(float(self.info.get('Size', ''))))
        self.setProperty('mrsp.total_items', self.total_results)
    
    def get_size(self, bytess):
        alternative = [
            (1024 ** 5, ' PB'),
            (1024 ** 4, ' TB'), 
            (1024 ** 3, ' GB'), 
            (1024 ** 2, ' MB'), 
            (1024 ** 1, ' KB'),
            (1024 ** 0, (' byte', ' bytes')),
            ]
        for factor, suffix in alternative:
            if bytess >= factor:
                break
        amount = int(bytess / factor)
        if isinstance(suffix, tuple):
            singular, multiple = suffix
            if amount == 1:
                suffix = singular
            else:
                suffix = multiple
        return str(amount) + suffix
    
    def natural_sort(self, l): 
        convert = lambda text: int(text) if text.isdigit() else text.lower()
        alphanum_key = lambda key: [convert(c) for c in re.split('([0-9]+)', key)]
        return sorted(l, key=alphanum_key)
