import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import os
import shutil
import zipfile
import datetime
import time


# ===========================================================
#                     ADDON INFO
# ===========================================================

ADDON      = xbmcaddon.Addon()
ADDON_ID   = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
ADDON_VER  = ADDON.getAddonInfo('version')


# ===========================================================
#                     KODI PATHS
# ===========================================================

KODI_HOME      = xbmcvfs.translatePath('special://home/')
ADDONS_DIR     = os.path.join(KODI_HOME, 'addons')
USERDATA_DIR   = os.path.join(KODI_HOME, 'userdata')
DATABASE_DIR   = os.path.join(USERDATA_DIR, 'Database')
PACKAGES_DIR   = os.path.join(ADDONS_DIR, 'packages')
ADDONS_TEMP    = os.path.join(ADDONS_DIR, 'temp')
CACHE_DIR      = os.path.join(KODI_HOME, 'cache')
TEMP_DIR       = os.path.join(KODI_HOME, 'temp')
THUMBNAILS_DIR = os.path.join(USERDATA_DIR, 'Thumbnails')


# ===========================================================
#            BACKUP CONFIGURATION  (editable)
# ===========================================================


# Excluded from addons/ at root level
ADDONS_EXCLUDE = {
    'packages',
    'temp',
}

# Built dynamically from settings in get_backup_config()

GLOBAL_SKIP_DIRS = {
    '__pycache__',
    '.git',
    '.svn',
    'blur_v3',
    'crop_v2',
}

GLOBAL_SKIP_EXT = {
    '.pyc',
}


# ===========================================================
#                   HELPER FUNCTIONS
# ===========================================================

def log(msg, level=xbmc.LOGINFO):
    xbmc.log('[{0}] {1}'.format(ADDON_ID, msg), level)


def notify(msg, icon=xbmcgui.NOTIFICATION_INFO, ms=4000):
    xbmcgui.Dialog().notification(ADDON_NAME, msg, icon, ms)


def setting(key):
    return ADDON.getSetting(key)


def bool_setting(key):
    v = setting(key)
    return v.lower() == 'true' if v else False


def fmt_size(n):
    if n < 1024:
        return '{0} B'.format(n)
    if n < 1048576:
        return '{0:.1f} KB'.format(n / 1024.0)
    if n < 1073741824:
        return '{0:.1f} MB'.format(n / 1048576.0)
    return '{0:.2f} GB'.format(n / 1073741824.0)


def trunc(text, mx=52):
    if len(text) > mx:
        return '...' + text[-(mx - 3):]
    return text


def get_backup_path():
    p = setting('backup_path')
    if not p:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR gold]Locatia backup-ului nu este setata![/COLOR]\n\n'
            '[COLOR white]Apasa OK si alege folderul din Settings.[/COLOR]'
        )
        ADDON.openSettings()
        p = setting('backup_path')
    if p:
        p = xbmcvfs.translatePath(p)
    return p


def calc_folder_size(path):
    """Calculate total size of a folder recursively."""
    total = 0
    if not os.path.isdir(path):
        return 0
    try:
        for root, dirs, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def count_folder_files(path):
    """Count files in a folder recursively."""
    count = 0
    if not os.path.isdir(path):
        return 0
    try:
        for root, dirs, files in os.walk(path):
            count += len(files)
    except OSError:
        pass
    return count


def is_inside_kodi(path):
    """Safety check: path must be inside Kodi home."""
    p = os.path.normpath(os.path.realpath(path))
    k = os.path.normpath(os.path.realpath(KODI_HOME))
    if p == k:
        return False
    return p.startswith(k + os.sep)


def safe_delete_folder(path):
    """Safely delete a folder. Returns (success, message)."""
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        return True, 'nu exista'
    if not is_inside_kodi(path):
        return False, 'PATH NESIGUR - in afara Kodi!'
    try:
        shutil.rmtree(path)
        return True, 'sters'
    except Exception as e:
        return False, str(e)


def safe_delete_file(path):
    """Safely delete a file. Returns (success, message)."""
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        return True, 'nu exista'
    if not is_inside_kodi(path):
        return False, 'PATH NESIGUR - in afara Kodi!'
    try:
        os.remove(path)
        return True, 'sters'
    except Exception as e:
        return False, str(e)


# ===========================================================
#           VFS NETWORK TRANSFER HELPERS (SMB)
# ===========================================================

def vfs_join(base_path, file_name):
    """Joins a VFS path (like smb://) with a file safely."""
    base = base_path.replace('\\', '/')
    if not base.endswith('/'):
        base += '/'
    return base + file_name

def upload_to_vfs(src_local, dest_vfs, dialog, start_pct, end_pct):
    """Copiaza de pe Local pe SMB, bucata cu bucata."""
    try:
        total_size = os.path.getsize(src_local)
        copied = 0
        chunk_size = 4 * 1024 * 1024 # 4 MB chunks

        with open(src_local, 'rb') as f_in:
            f_out = xbmcvfs.File(dest_vfs, 'w')
            try:
                while True:
                    if dialog.iscanceled(): return False
                    chunk = f_in.read(chunk_size)
                    if not chunk: break
                    
                    if not f_out.write(bytearray(chunk)):
                        raise Exception("Scrierea prin retea a esuat. Verifica permisiunile!")
                    
                    copied += len(chunk)
                    if total_size > 0:
                        prog = start_pct + int((copied / float(total_size)) * (end_pct - start_pct))
                        dialog.update(prog, '[COLOR lime]Upload pe retea (SMB):[/COLOR]\n[COLOR white]{0} / {1}[/COLOR]'.format(fmt_size(copied), fmt_size(total_size)))
            finally:
                f_out.close()
        return True
    except Exception as e:
        log("Eroare Upload SMB: " + str(e), xbmc.LOGERROR)
        raise e

def download_from_vfs(src_vfs, dest_local, dialog, start_pct, end_pct):
    """Copiaza de pe SMB pe Local, bucata cu bucata."""
    try:
        try: total_size = xbmcvfs.Stat(src_vfs).st_size()
        except: total_size = 0

        copied = 0
        chunk_size = 4 * 1024 * 1024 # 4 MB chunks

        f_in = xbmcvfs.File(src_vfs)
        try:
            with open(dest_local, 'wb') as f_out:
                while True:
                    if dialog.iscanceled(): return False
                    
                    # ATENTIE: Folosim readBytes in loc de read pt fisiere ZIP (binare)
                    chunk = f_in.readBytes(chunk_size)
                    if not chunk: break
                    
                    f_out.write(bytearray(chunk))
                    copied += len(chunk)
                    if total_size > 0:
                        prog = start_pct + int((copied / float(total_size)) * (end_pct - start_pct))
                        dialog.update(prog, '[COLOR deepskyblue]Se descarca arhiva (SMB):[/COLOR]\n[COLOR white]{0} / {1}[/COLOR]'.format(fmt_size(copied), fmt_size(total_size)))
        finally:
            f_in.close()
        return True
    except Exception as e:
        log("Eroare Download SMB: " + str(e), xbmc.LOGERROR)
        raise e


# ===========================================================
#                COLLECT FILES FOR BACKUP
# ===========================================================

def get_backup_config():
    """Read backup settings and return files/dirs/db lists."""
    xml_map = [
        ('bkp_favourites',       'favourites.xml'),
        ('bkp_guisettings',      'guisettings.xml'),
        ('bkp_sources',          'sources.xml'),
        ('bkp_passwords',        'passwords.xml'),
        ('bkp_mediasources',     'mediasources.xml'),
        ('bkp_advancedsettings', 'advancedsettings.xml'),
        ('bkp_genxml',           'keymaps/gen.xml'),
    ]
    dir_map = [
        ('bkp_addon_data',  'addon_data'),
        ('bkp_playlists',   'playlists'),
    ]

    db_map = [
        ('bkp_myvideos_db',  'myvideos'),
        ('bkp_addons_db',    'addons'),
        ('bkp_viewmodes_db', 'viewmodes'),
    ]

    xml_files = [f for key, f in xml_map if bool_setting(key)]
    dirs      = [d for key, d in dir_map if bool_setting(key)]
    db_prefix = [p for key, p in db_map  if bool_setting(key)]

    return xml_files, dirs, db_prefix


def should_skip(filepath):
    """Check if a file should be skipped (junk)."""
    _, ext = os.path.splitext(filepath)
    if ext.lower() in GLOBAL_SKIP_EXT:
        return True
    return False


def collect_files():
    xml_files, user_dirs, db_prefixes = get_backup_config()
    files = []

    if os.path.isdir(ADDONS_DIR):
        for root, dirs, fnames in os.walk(ADDONS_DIR):
            dirs[:] = [d for d in dirs
                       if d not in GLOBAL_SKIP_DIRS]
            if os.path.normpath(root) == os.path.normpath(
                    ADDONS_DIR):
                dirs[:] = [d for d in dirs
                           if d not in ADDONS_EXCLUDE]
            for f in fnames:
                if should_skip(f):
                    continue
                fp = os.path.join(root, f)
                arc = 'addons/' + os.path.relpath(
                    fp, ADDONS_DIR).replace('\\', '/')
                files.append((fp, arc))

    if os.path.isdir(USERDATA_DIR):
        for fname in xml_files:
            fp = os.path.join(USERDATA_DIR, fname)
            if os.path.isfile(fp):
                files.append((fp, 'userdata/{0}'.format(fname)))

    for subdir in user_dirs:
        sd = os.path.join(USERDATA_DIR, subdir)
        if not os.path.isdir(sd):
            continue
        for root, dirs, fnames in os.walk(sd):
            dirs[:] = [d for d in dirs
                       if d not in GLOBAL_SKIP_DIRS]
            for f in fnames:
                if should_skip(f):
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(
                    fp, USERDATA_DIR).replace('\\', '/')
                files.append((fp, 'userdata/{0}'.format(rel)))

    if os.path.isdir(DATABASE_DIR) and db_prefixes:
        for f in sorted(os.listdir(DATABASE_DIR)):
            if not f.endswith('.db'):
                continue
            fl = f.lower()
            for prefix in db_prefixes:
                if fl.startswith(prefix):
                    fp = os.path.join(DATABASE_DIR, f)
                    if os.path.isfile(fp):
                        files.append((
                            fp,
                            'userdata/Database/{0}'.format(f)
                        ))
                    break

    return files

# ===========================================================
#                       BACKUP
# ===========================================================

def do_backup():
    bpath = get_backup_path()
    if not bpath:
        return

    # Creati folderul folosind VFS, ca sa mearga si cu smb://
    if not xbmcvfs.exists(bpath):
        try:
            xbmcvfs.mkdirs(bpath)
        except Exception as e:
            xbmcgui.Dialog().ok(
                ADDON_NAME,
                '[COLOR red]Nu pot crea folderul:[/COLOR]\n'
                '[COLOR cyan]{0}[/COLOR]\n\n'
                '[COLOR white]{1}[/COLOR]'.format(bpath, e)
            )
            return

    pdia = xbmcgui.DialogProgress()
    pdia.create(ADDON_NAME, '[COLOR deepskyblue]Se scaneaza fisierele...[/COLOR]')
    pdia.update(0)

    file_list = collect_files()
    total = len(file_list)
    pdia.close()

    if total == 0:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR red]Nu s-au gasit fisiere de salvat![/COLOR]'
        )
        return

    cnt_addons   = sum(1 for _, a in file_list if a.startswith('addons/'))
    cnt_userdata = sum(1 for _, a in file_list if a.startswith('userdata/'))

    db_names = sorted(set(
        a.split('/')[-1] for _, a in file_list
        if a.startswith('userdata/Database/')
    ))
    db_display = ', '.join(db_names) if db_names else 'niciunul'

    summary = (
        '[COLOR lime]Fisiere gasite:[/COLOR]  '
        '[COLOR springgreen]{0}[/COLOR]\n\n'
        '[COLOR deepskyblue]addons    :[/COLOR]  [COLOR white]{1}[/COLOR]\n'
        '[COLOR deepskyblue]userdata  :[/COLOR]  [COLOR white]{2}[/COLOR]\n'
        '[COLOR deepskyblue]databases :[/COLOR]  [COLOR khaki]{3}[/COLOR]\n\n'
        '[COLOR gold]Destinatie:[/COLOR]\n'
        '[COLOR cyan]{4}[/COLOR]\n\n'
        '[COLOR orange]Continui cu backup-ul?[/COLOR]'
    ).format(total, cnt_addons, cnt_userdata, db_display, bpath)

    if not xbmcgui.Dialog().yesno(
        ADDON_NAME + '  -  Backup',
        summary,
        yeslabel='[COLOR lime]Da, salveaza[/COLOR]',
        nolabel='[COLOR red]Anuleaza[/COLOR]'
    ):
        return

    ts         = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    zip_name   = 'B&R_Kodi_{0}.zip'.format(ts)
    
    # Fisierul il cream LOCAL pe temp, apoi il urcam!
    local_temp = os.path.join(TEMP_DIR, zip_name)
    final_dest = vfs_join(bpath, zip_name)

    pdia = xbmcgui.DialogProgress()
    pdia.create(ADDON_NAME, '[COLOR lime]Se creeaza arhiva local...[/COLOR]\n ')

    errors  = 0
    written = 0
    t0      = time.time()

    try:
        # PARTEA 1: ARHIVARE LOCALA (0% -> 80%)
        with zipfile.ZipFile(local_temp, 'w', zipfile.ZIP_DEFLATED,
                             allowZip64=True, compresslevel=5) as zf:
            for i, (fpath, arcname) in enumerate(file_list):
                if pdia.iscanceled():
                    pdia.close()
                    if os.path.exists(local_temp):
                        try: os.remove(local_temp)
                        except: pass
                    notify('Backup anulat!', xbmcgui.NOTIFICATION_WARNING)
                    return

                pct = int(((i + 1) / float(total)) * 80)
                pdia.update(
                    pct,
                    '[COLOR lime]Arhivare locala:[/COLOR] '
                    '[COLOR white]{0}/{1}[/COLOR]\n'
                    '[COLOR silver]{2}[/COLOR]'.format(
                        i + 1, total, trunc(arcname))
                )

                try:
                    zf.write(fpath, arcname)
                    written += 1
                except (PermissionError, OSError) as e:
                    log('SKIP {0} -> {1}'.format(fpath, e), xbmc.LOGWARNING)
                    errors += 1

        # PARTEA 2: UPLOAD PRIN RETEA (80% -> 100%)
        upload_success = upload_to_vfs(local_temp, final_dest, pdia, 80, 100)
        
        if not upload_success:
            raise Exception("Transferul spre retea a fost anulat de utilizator.")

    except Exception as e:
        pdia.close()
        log('Backup FAILED: {0}'.format(e), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR red]Eroare critica la backup![/COLOR]\n\n'
            '[COLOR white]{0}[/COLOR]'.format(e)
        )
        return
    finally:
        # Curatam fisierul temp
        if os.path.exists(local_temp):
            try: os.remove(local_temp)
            except: pass

    pdia.close()
    elapsed = time.time() - t0

    try:
        sz_bytes = xbmcvfs.Stat(final_dest).st_size()
        zsize = fmt_size(sz_bytes)
    except Exception:
        zsize = '?'

    result = (
        '[COLOR lime]========================================[/COLOR]\n'
        '[COLOR lime]         BACKUP COMPLET ![/COLOR]\n'
        '[COLOR lime]========================================[/COLOR]\n\n'
        '[COLOR deepskyblue]Fisiere salvate :[/COLOR]  '
        '[COLOR springgreen]{0}[/COLOR]\n'
        '[COLOR deepskyblue]Dimensiune ZIP  :[/COLOR]  '
        '[COLOR springgreen]{1}[/COLOR]\n'
        '[COLOR deepskyblue]Timp            :[/COLOR]  '
        '[COLOR white]{2:.1f} secunde[/COLOR]\n'
    ).format(written, zsize, elapsed)

    if errors:
        result += (
            '[COLOR orange]Fisiere sarite  :[/COLOR]  '
            '[COLOR red]{0}[/COLOR]\n'
        ).format(errors)

    result += (
        '\n[COLOR gold]Fisier salvat:[/COLOR]\n'
        '[COLOR cyan]{0}[/COLOR]'
    ).format(zip_name)

    xbmcgui.Dialog().ok(ADDON_NAME, result)
    log('Backup OK -> {0} | {1} files | {2}'.format(final_dest, written, zsize))


# ===========================================================
#                       RESTORE
# ===========================================================

def do_restore():
    bpath = get_backup_path()
    if not bpath:
        return

    if not xbmcvfs.exists(bpath):
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR red]Folderul nu exista sau este inaccesibil:[/COLOR]\n'
            '[COLOR cyan]{0}[/COLOR]'.format(bpath)
        )
        return

    backups = []
    try:
        # Folosim listdir prin VFS
        dirs, files = xbmcvfs.listdir(bpath)
        
        for f in sorted(files, reverse=True):
            fl = f.lower()
            if (fl.startswith('b&r_kodi_') or fl.startswith('kodi_backup_')) and fl.endswith('.zip'):
                fp = vfs_join(bpath, f)
                
                try: sz_bytes = xbmcvfs.Stat(fp).st_size()
                except: sz_bytes = 0
                fsize = fmt_size(sz_bytes)
                
                if fl.startswith('b&r_kodi_'): stem = f[len('B&R_Kodi_'):-len('.zip')]
                else: stem = f[len('kodi_backup_'):-len('.zip')]
                
                nice = stem
                if len(stem) == 19 and '_' in stem:
                    try:
                        date_part, time_part = stem.split('_')
                        yyyy, mm, dd = date_part.split('-')
                        HH, MM, SS = time_part.split('-')
                        
                        luni = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                        luna_str = luni[int(mm)]
                        nice = '{0} {1} {2}  -  {3}:{4}:{5}'.format(dd, luna_str, yyyy, HH, MM, SS)
                    except Exception: pass
                
                backups.append({
                    'file': f, 'path': fp,
                    'size': fsize, 'date': nice,
                })
    except Exception as e:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR red]Nu pot citi folderul:[/COLOR]\n'
            '[COLOR white]{0}[/COLOR]'.format(e)
        )
        return

    if not backups:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR red]Nu exista backup-uri in:[/COLOR]\n'
            '[COLOR cyan]{0}[/COLOR]'.format(bpath)
        )
        return

    items = []
    for b in backups:
        items.append(
            '[COLOR deepskyblue]{0}[/COLOR]'
            '    [COLOR springgreen][{1}][/COLOR]'.format(
                b['date'], b['size'])
        )

    sel = xbmcgui.Dialog().select(
        ADDON_NAME + '  -  Alege backup-ul', items
    )
    if sel < 0:
        return

    chosen   = backups[sel]
    smb_zip_filepath = chosen['path']

    # Aratam detaliile *inainte* sa descarcam, e mult mai rapid asa pe SMB
    info = (
        '[COLOR deepskyblue]{0}[/COLOR]   '
        '[COLOR springgreen]({1})[/COLOR]\n\n'
        '[COLOR gold]Restaurare in:[/COLOR]\n'
        '[COLOR cyan]{2}[/COLOR]\n\n'
        '[COLOR red]ATENTIE: Fisierele existente vor fi SUPRASCRISE![/COLOR]\n'
        '[COLOR orange]Dupa restaurare Kodi se va INCHIDE FORTAT![/COLOR]\n'
        '[COLOR silver]Va trebui sa pornesti Kodi manual.[/COLOR]'
    ).format(
        chosen['date'], chosen['size'], KODI_HOME
    )

    if not xbmcgui.Dialog().yesno(
        ADDON_NAME + '  -  Restore',
        info,
        yeslabel='[COLOR lime]Da, restaureaza[/COLOR]',
        nolabel='[COLOR red]Anuleaza[/COLOR]'
    ):
        return

    os.makedirs(KODI_HOME, exist_ok=True)
    
    local_temp_zip = os.path.join(TEMP_DIR, "temp_restore.zip")
    pdia = xbmcgui.DialogProgress()
    pdia.create(ADDON_NAME, '[COLOR deepskyblue]Se pregateste descarcarea...[/COLOR]\n ')

    restored = 0
    errors   = 0
    t0       = time.time()

    try:
        # PARTEA 1: DOWNLOAD DE PE SMB (0% -> 40%)
        download_success = download_from_vfs(smb_zip_filepath, local_temp_zip, pdia, 0, 40)
        
        if not download_success:
            raise Exception("Descarcarea a fost oprita.")

        # PARTEA 2: EXTRAGERE LOCALA (40% -> 100%)
        with zipfile.ZipFile(local_temp_zip, 'r') as zf:
            members = [m for m in zf.namelist() if not m.endswith('/')]
            total   = len(members)
            
            for i, member in enumerate(members):
                if pdia.iscanceled():
                    pdia.close()
                    notify('Restaurare anulata!', xbmcgui.NOTIFICATION_WARNING)
                    return

                if '..' in member or member.startswith('/'):
                    log('SKIP unsafe: {0}'.format(member), xbmc.LOGWARNING)
                    continue

                pct = 40 + int(((i + 1) / float(total)) * 60)
                pdia.update(
                    pct,
                    '[COLOR deepskyblue]Se extrage:[/COLOR] '
                    '[COLOR white]{0}/{1}[/COLOR]\n'
                    '[COLOR silver]{2}[/COLOR]'.format(
                        i + 1, total, trunc(member))
                )

                dest = os.path.join(KODI_HOME, member.replace('/', os.sep))
                ddir = os.path.dirname(dest)

                try:
                    os.makedirs(ddir, exist_ok=True)
                    with zf.open(member) as src:
                        data = src.read()
                    with open(dest, 'wb') as dst:
                        dst.write(data)
                    restored += 1
                except (PermissionError, OSError) as e:
                    log('SKIP {0} -> {1}'.format(member, e), xbmc.LOGWARNING)
                    errors += 1

    except zipfile.BadZipFile:
        pdia.close()
        xbmcgui.Dialog().ok(ADDON_NAME, '[COLOR red]Fisierul ZIP este corupt![/COLOR]')
        return
    except Exception as e:
        pdia.close()
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR red]Eroare critica:[/COLOR]\n'
            '[COLOR white]{0}[/COLOR]'.format(e)
        )
        return
    finally:
        if os.path.exists(local_temp_zip):
            try: os.remove(local_temp_zip)
            except: pass

    pdia.close()
    elapsed = time.time() - t0

    result = (
        '[COLOR lime]========================================[/COLOR]\n'
        '[COLOR lime]       RESTAURARE COMPLETA ![/COLOR]\n'
        '[COLOR lime]========================================[/COLOR]\n\n'
        '[COLOR deepskyblue]Fisiere restaurate :[/COLOR]  '
        '[COLOR springgreen]{0}[/COLOR]\n'
        '[COLOR deepskyblue]Timp               :[/COLOR]  '
        '[COLOR white]{1:.1f} secunde[/COLOR]\n'
    ).format(restored, elapsed)

    if errors:
        result += (
            '[COLOR orange]Fisiere sarite     :[/COLOR]  '
            '[COLOR red]{0}[/COLOR]\n'
        ).format(errors)

    result += (
        '\n[COLOR red]========================================[/COLOR]\n'
        '[COLOR orange]Kodi se va INCHIDE FORTAT dupa ce[/COLOR]\n'
        '[COLOR orange]apesi OK.  Porneste Kodi manual![/COLOR]\n'
        '[COLOR red]========================================[/COLOR]'
    )

    xbmcgui.Dialog().ok(ADDON_NAME, result)

    log('Restore OK | {0} files | {1:.1f}s | FORCE KILL'.format(
        restored, elapsed))

    # ============================================================
    #   FORCE KILL  -  prevents Kodi from overwriting
    #   guisettings.xml during normal shutdown
    # ============================================================
    time.sleep(1)
    os._exit(1)


# ===========================================================
#                       CLEANING
# ===========================================================

def do_cleaning():
    """Clean selected Kodi cache/temp/junk folders and files."""

    # ---- Build list of items to clean ----
    targets = []

    if bool_setting('clean_packages'):
        targets.append({
            'type': 'folder',
            'path': PACKAGES_DIR,
            'label': 'addons/packages/',
            'desc': 'ZIP-uri descarcate addon-uri',
        })

    if bool_setting('clean_addons_temp'):
        targets.append({
            'type': 'folder',
            'path': ADDONS_TEMP,
            'label': 'addons/temp/',
            'desc': 'Fisiere temporare addon-uri',
        })

    if bool_setting('clean_cache'):
        targets.append({
            'type': 'folder',
            'path': CACHE_DIR,
            'label': 'cache/',
            'desc': 'Cache general Kodi',
        })

    if bool_setting('clean_temp'):
        targets.append({
            'type': 'folder',
            'path': TEMP_DIR,
            'label': 'temp/',
        })

    if bool_setting('clean_thumbnails'):
        targets.append({
            'type': 'folder',
            'path': THUMBNAILS_DIR,
            'label': 'userdata/Thumbnails/',
            'desc': 'Cache imagini si thumbnails',
        })
        
        # Caches aditionale pentru TMDb Helper
        targets.append({
            'type': 'folder',
            'path': os.path.join(USERDATA_DIR, 'addon_data', 'plugin.video.themoviedb.helper', 'blur_v3'),
            'label': 'TMDb blur_v3/',
            'desc': 'Cache imagini blurate',
        })
        targets.append({
            'type': 'folder',
            'path': os.path.join(USERDATA_DIR, 'addon_data', 'plugin.video.themoviedb.helper', 'crop_v2'),
            'label': 'TMDb crop_v2/',
            'desc': 'Cache imagini taiate',
        })

    if bool_setting('clean_textures_db'):
        if os.path.isdir(DATABASE_DIR):
            for f in sorted(os.listdir(DATABASE_DIR)):
                fl = f.lower()
                if fl.startswith('textures') and (
                    fl.endswith('.db') or
                    fl.endswith('.db-shm') or
                    fl.endswith('.db-wal')
                ):
                    targets.append({
                        'type': 'file',
                        'path': os.path.join(DATABASE_DIR, f),
                        'label': 'Database/{0}'.format(f),
                        'desc': 'Baza de date thumbnails',
                    })

    # ---- Nothing selected? ----
    if not targets:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR gold]Nicio optiune de cleaning nu este activata![/COLOR]\n\n'
            '[COLOR white]Du-te in Settings -> Cleaning Options[/COLOR]\n'
            '[COLOR white]si bifeaza ce vrei sa stergi.[/COLOR]'
        )
        ADDON.openSettings()
        return

    # ---- Scan sizes ----
    pdia = xbmcgui.DialogProgress()
    pdia.create(ADDON_NAME,
                '[COLOR deepskyblue]Se scaneaza dimensiunile...[/COLOR]')
    pdia.update(0)

    total_size  = 0
    total_files = 0
    details     = []

    for idx, t in enumerate(targets):
        pct = int(((idx + 1) / float(len(targets))) * 100)
        pdia.update(pct,
                    '[COLOR silver]Scanare: {0}[/COLOR]'.format(t['label']))

        if t['type'] == 'folder':
            if os.path.isdir(t['path']):
                sz = calc_folder_size(t['path'])
                fc = count_folder_files(t['path'])
                t['size']  = sz
                t['count'] = fc
                t['exists'] = True
                total_size  += sz
                total_files += fc
                details.append(
                    '[COLOR lime]  [+][/COLOR]  '
                    '[COLOR deepskyblue]{label}[/COLOR]\n'
                    '         [COLOR white]{cnt} fisiere[/COLOR]  -  '
                    '[COLOR springgreen]{sz}[/COLOR]'.format(
                        label=t['label'],
                        cnt=fc,
                        sz=fmt_size(sz))
                )
            else:
                t['exists'] = False
                details.append(
                    '[COLOR gray]  [-][/COLOR]  '
                    '[COLOR gray]{0}[/COLOR]  '
                    '[COLOR silver](nu exista)[/COLOR]'.format(t['label'])
                )

        elif t['type'] == 'file':
            if os.path.isfile(t['path']):
                try:
                    sz = os.path.getsize(t['path'])
                except OSError:
                    sz = 0
                t['size']   = sz
                t['exists'] = True
                total_size  += sz
                total_files += 1
                details.append(
                    '[COLOR lime]  [+][/COLOR]  '
                    '[COLOR deepskyblue]{label}[/COLOR]  -  '
                    '[COLOR springgreen]{sz}[/COLOR]'.format(
                        label=t['label'],
                        sz=fmt_size(sz))
                )
            else:
                t['exists'] = False
                details.append(
                    '[COLOR gray]  [-][/COLOR]  '
                    '[COLOR gray]{0}[/COLOR]  '
                    '[COLOR silver](nu exista)[/COLOR]'.format(t['label'])
                )

    pdia.close()

    # ---- Check if anything exists ----
    existing = [t for t in targets if t.get('exists', False)]
    if not existing:
        xbmcgui.Dialog().ok(
            ADDON_NAME,
            '[COLOR gold]Nimic de sters![/COLOR]\n\n'
            '[COLOR silver]Toate folderele/fisierele selectate\n'
            'nu exista sau sunt deja goale.[/COLOR]'
        )
        return

    # ---- Show confirmation ----
    detail_text = '\n'.join(details)

    confirm_msg = (
        '[COLOR orangered]========================================[/COLOR]\n'
        '[COLOR orangered]            CLEANING[/COLOR]\n'
        '[COLOR orangered]========================================[/COLOR]\n\n'
        '{details}\n\n'
        '[COLOR gold]==========================================[/COLOR]\n'
        '[COLOR gold]Total de sters:[/COLOR]  '
        '[COLOR orangered]{files} fisiere[/COLOR]  -  '
        '[COLOR orangered]{size}[/COLOR]\n'
        '[COLOR gold]==========================================[/COLOR]\n\n'
        '[COLOR red]ATENTIE: Aceasta actiune este IREVERSIBILA![/COLOR]\n'
        '[COLOR orange]Se recomanda restart Kodi dupa cleaning.[/COLOR]'
    ).format(
        details=detail_text,
        files=total_files,
        size=fmt_size(total_size)
    )

    if not xbmcgui.Dialog().yesno(
        ADDON_NAME + '  -  Cleaning',
        confirm_msg,
        yeslabel='[COLOR orangered]Da, sterge tot![/COLOR]',
        nolabel='[COLOR lime]Anuleaza[/COLOR]'
    ):
        return

    # ---- Perform cleaning ----
    pdia = xbmcgui.DialogProgress()
    pdia.create(ADDON_NAME,
                '[COLOR orangered]Se sterg fisierele...[/COLOR]\n ')

    deleted_ok   = 0
    deleted_fail = 0
    freed_size   = 0
    results      = []

    for idx, t in enumerate(existing):
        pct = int(((idx + 1) / float(len(existing))) * 100)
        pdia.update(
            pct,
            '[COLOR orangered]Se sterge:[/COLOR]\n'
            '[COLOR white]{0}[/COLOR]'.format(t['label'])
        )

        if t['type'] == 'folder':
            ok, msg = safe_delete_folder(t['path'])
            if ok:
                freed_size   += t.get('size', 0)
                deleted_ok   += 1
                results.append(
                    '[COLOR lime]  [OK][/COLOR]  '
                    '[COLOR white]{0}[/COLOR]  '
                    '[COLOR springgreen]({1})[/COLOR]'.format(
                        t['label'], fmt_size(t.get('size', 0)))
                )
                log('CLEAN OK: {0}'.format(t['path']))
            else:
                deleted_fail += 1
                results.append(
                    '[COLOR red]  [FAIL][/COLOR]  '
                    '[COLOR white]{0}[/COLOR]\n'
                    '         [COLOR red]{1}[/COLOR]'.format(
                        t['label'], msg)
                )
                log('CLEAN FAIL: {0} -> {1}'.format(t['path'], msg),
                    xbmc.LOGWARNING)

        elif t['type'] == 'file':
            ok, msg = safe_delete_file(t['path'])
            if ok:
                freed_size   += t.get('size', 0)
                deleted_ok   += 1
                results.append(
                    '[COLOR lime]  [OK][/COLOR]  '
                    '[COLOR white]{0}[/COLOR]  '
                    '[COLOR springgreen]({1})[/COLOR]'.format(
                        t['label'], fmt_size(t.get('size', 0)))
                )
                log('CLEAN OK: {0}'.format(t['path']))
            else:
                deleted_fail += 1
                results.append(
                    '[COLOR red]  [FAIL][/COLOR]  '
                    '[COLOR white]{0}[/COLOR]\n'
                    '         [COLOR red]{1}[/COLOR]'.format(
                        t['label'], msg)
                )
                log('CLEAN FAIL: {0} -> {1}'.format(t['path'], msg),
                    xbmc.LOGWARNING)

        time.sleep(0.3)

    pdia.close()

    # ---- Results ----
    results_text = '\n'.join(results)

    result_msg = (
        '[COLOR lime]========================================[/COLOR]\n'
        '[COLOR lime]        CLEANING COMPLET ![/COLOR]\n'
        '[COLOR lime]========================================[/COLOR]\n\n'
        '{results}\n\n'
        '[COLOR gold]==========================================[/COLOR]\n'
        '[COLOR deepskyblue]Sterse cu succes :[/COLOR]  '
        '[COLOR springgreen]{ok}[/COLOR]\n'
        '[COLOR deepskyblue]Spatiu eliberat  :[/COLOR]  '
        '[COLOR springgreen]{freed}[/COLOR]\n'
    ).format(
        results=results_text,
        ok=deleted_ok,
        freed=fmt_size(freed_size)
    )

    if deleted_fail > 0:
        result_msg += (
            '[COLOR orange]Esecuri          :[/COLOR]  '
            '[COLOR red]{0}[/COLOR]\n'
        ).format(deleted_fail)

    result_msg += (
        '[COLOR gold]==========================================[/COLOR]\n\n'
        '[COLOR silver]Se recomanda repornirea Kodi.[/COLOR]'
    )

    xbmcgui.Dialog().ok(ADDON_NAME, result_msg)

    log('Cleaning done: {0} OK, {1} FAIL, freed {2}'.format(
        deleted_ok, deleted_fail, fmt_size(freed_size)))


# ===========================================================
#                       INFO SCREEN
# ===========================================================

def show_info():
    # --- 1. SETARI LOCATII ---
    bp = setting('backup_path')
    bp_show = '[COLOR cyan]{0}[/COLOR]'.format(xbmcvfs.translatePath(bp)) if bp else '[COLOR red](nesetat!)[/COLOR]'

    # --- 2. SETARI BACKUP ---
    all_xml = [
        ('bkp_favourites', 'favourites'), ('bkp_guisettings', 'guisettings'),
        ('bkp_sources', 'sources'), ('bkp_passwords', 'passwords'),
        ('bkp_mediasources', 'mediasources'), ('bkp_advancedsettings', 'advancedsettings'),
        ('bkp_genxml', 'keymaps/gen')
    ]
    active_xml = [name for key, name in all_xml if bool_setting(key)]
    xml_txt = '[COLOR white]' + ', '.join(active_xml) + '[/COLOR]' if active_xml else '[COLOR gray]niciunul[/COLOR]'

    active_dirs = ['addons']
    if bool_setting('bkp_addon_data'): active_dirs.append('addon_data')
    if bool_setting('bkp_playlists'): active_dirs.append('playlists')
    dir_txt = '[COLOR white]' + ', '.join(active_dirs) + '[/COLOR]'

    active_db = []
    if bool_setting('bkp_myvideos_db'): active_db.append('MyVideos')
    if bool_setting('bkp_addons_db'): active_db.append('Addons')
    if bool_setting('bkp_viewmodes_db'): active_db.append('ViewModes')
    db_txt = '[COLOR white]' + ', '.join(active_db) + '[/COLOR]' if active_db else '[COLOR gray]niciunul[/COLOR]'

    # --- 3. DIMENSIUNI CLEANING ---
    clean_lines = []
    
    def get_sz_str(path):
        sz = calc_folder_size(path) if os.path.isdir(path) else 0
        return '[COLOR springgreen]({0})[/COLOR]'.format(fmt_size(sz))

    # Packages & Temp
    clean_lines.append(" • [COLOR silver]addons/packages[/COLOR]  {0}".format(get_sz_str(PACKAGES_DIR)))
    clean_lines.append(" • [COLOR silver]addons/temp[/COLOR]  {0}".format(get_sz_str(ADDONS_TEMP)))
    
    # Cache & Temp Radacina
    cache_sz = calc_folder_size(CACHE_DIR) + calc_folder_size(TEMP_DIR)
    clean_lines.append(" • [COLOR silver]Cache & Temp (Kodi)[/COLOR]  [COLOR springgreen]({0})[/COLOR]".format(fmt_size(cache_sz)))

    # Thumbnails + TMDb (le grupam vizual)
    tb_sz = calc_folder_size(THUMBNAILS_DIR)
    tb_sz += calc_folder_size(os.path.join(USERDATA_DIR, 'addon_data', 'plugin.video.themoviedb.helper', 'blur_v3'))
    tb_sz += calc_folder_size(os.path.join(USERDATA_DIR, 'addon_data', 'plugin.video.themoviedb.helper', 'crop_v2'))
    clean_lines.append(" • [COLOR silver]Thumbnails & Image Cache[/COLOR]  [COLOR springgreen]({0})[/COLOR]".format(fmt_size(tb_sz)))
    
    # Textures DB
    tex_sz = 0
    if os.path.isdir(DATABASE_DIR):
        for f in os.listdir(DATABASE_DIR):
            if f.lower().startswith('textures') and f.lower().endswith('.db'):
                try: tex_sz += os.path.getsize(os.path.join(DATABASE_DIR, f))
                except OSError: pass
    clean_lines.append(" • [COLOR silver]Textures DB[/COLOR]  [COLOR springgreen]({0})[/COLOR]".format(fmt_size(tex_sz)))

    clean_txt = '\n'.join(clean_lines)

    # --- 4. ASAMBLARE MESAJ FINAL ---
    msg = (
        '[COLOR deepskyblue][B]=== LOCATII ===[/B][/COLOR]\n'
        '[COLOR gold]Kodi:[/COLOR] [COLOR cyan]{kodi}[/COLOR]\n'
        '[COLOR gold]Backup:[/COLOR] {bkp}\n\n'
        
        '[COLOR lime][B]=== DE SALVAT (BACKUP) ===[/B][/COLOR]\n'
        '[COLOR gray]XML:[/COLOR]  {xml}\n'
        '[COLOR gray]Foldere:[/COLOR]  {dirs}\n'
        '[COLOR gray]Baze date:[/COLOR]  {db}\n\n'

        '[COLOR orangered][B]=== SPATIU OCUPAT (CLEANING) ===[/B][/COLOR]\n'
        '{clean}\n\n'

        '[COLOR gray][B]=== IGNORATE (JUNK SKIP) ===[/B][/COLOR]\n'
        '[COLOR silver]__pycache__, .git, .svn, *.pyc, blur_v3, crop_v2, temp, packages[/COLOR]'
    ).format(
        kodi=KODI_HOME, bkp=bp_show,
        xml=xml_txt, dirs=dir_txt, db=db_txt,
        clean=clean_txt
    )

    xbmcgui.Dialog().textviewer(ADDON_NAME + '  -  Sumar Configuratie', msg)

# ===========================================================
#                     MAIN MENU
# ===========================================================

def main():
    dialog = xbmcgui.Dialog()

    options = [
        '[B][COLOR lime]>>  BACKUP[/COLOR][/B]'
        '           [COLOR silver]Salveaza configuratia Kodi[/COLOR]',

        '[B][COLOR deepskyblue]>>  RESTORE[/COLOR][/B]'
        '          [COLOR silver]Restaureaza din backup[/COLOR]',

        '[B][COLOR orangered]>>  CLEANING[/COLOR][/B]'
        '         [COLOR silver]Sterge cache si junk[/COLOR]',

        '[B][COLOR gold]>>  SETTINGS[/COLOR][/B]'
        '         [COLOR silver]Configureaza addon-ul[/COLOR]',

        '[B][COLOR hotpink]>>  INFO[/COLOR][/B]'
        '             [COLOR silver]Ce salveaza / sterge[/COLOR]',
    ]

    choice = dialog.select(
        '{0}  v{1}'.format(ADDON_NAME, ADDON_VER),
        options
    )

    if choice == 0:
        do_backup()
    elif choice == 1:
        do_restore()
    elif choice == 2:
        do_cleaning()
    elif choice == 3:
        ADDON.openSettings()
    elif choice == 4:
        show_info()


# ===========================================================
#                     ENTRY POINT
# ===========================================================

if __name__ == '__main__':
    main()