import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import os
import zipfile
import datetime
import shutil

ADDON = xbmcaddon.Addon()
ADDON_NAME = "[B][COLOR cyan]My Custom [B][COLOR gray]Backup[/COLOR][/B]"
BACKUP_FOLDER = ADDON.getSetting('backup_folder')

KODI_HOME = os.path.normpath(xbmcvfs.translatePath('special://home/'))
TEMP_DIR = os.path.normpath(xbmcvfs.translatePath('special://temp/'))

def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[MCB_Backup] {message}", level)

def show_notification(message, is_error=False):
    icon = xbmcgui.NOTIFICATION_ERROR if is_error else xbmcgui.NOTIFICATION_INFO
    color = "red" if is_error else "green"
    xbmcgui.Dialog().notification("[B][COLOR cyan]My Custom [B][COLOR gray]Backup[/COLOR][/B]", f"[COLOR {color}]{message}[/COLOR]", icon, 4000)

def vfs_join(base_path, file_name):
    base = base_path.replace('\\', '/')
    if not base.endswith('/'): base += '/'
    return base + file_name

def fmt_size(n):
    if n < 1024: return f"{n} B"
    if n < 1048576: return f"{n / 1024.0:.1f} KB"
    if n < 1073741824: return f"{n / 1048576.0:.1f} MB"
    return f"{n / 1073741824.0:.2f} GB"

def calc_folder_size(path):
    total = 0
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            for f in files:
                try: total += os.path.getsize(os.path.join(root, f))
                except OSError: pass
    return total

# --- NEW FUNCTIONS FOR NETWORK TRANSFER (SMB) WITH PROGRESS ---

def upload_to_vfs(src_local, dest_vfs, dialog, start_pct, end_pct):
    """Copies from Android to SMB/Local, chunk by chunk, showing progress."""
    try:
        total_size = os.path.getsize(src_local)
        copied = 0
        chunk_size = 4 * 1024 * 1024 # 4 MB chunks
        
        # Check if it's an SMB path or a local path to display the correct text
        if dest_vfs.lower().startswith('smb://'):
            action_text = "SMB Network Upload:"
        else:
            action_text = "Saving Backup File:"

        with open(src_local, 'rb') as f_in:
            f_out = xbmcvfs.File(dest_vfs, 'w')
            try:
                while True:
                    if dialog.iscanceled():
                        return False
                    
                    chunk = f_in.read(chunk_size)
                    if not chunk:
                        break
                    
                    success = f_out.write(bytearray(chunk))
                    if not success:
                        raise Exception("Write failed abruptly. Connection lost or insufficient space?")
                    
                    copied += len(chunk)
                    if total_size > 0:
                        prog = start_pct + int((copied / float(total_size)) * (end_pct - start_pct))
                        dialog.update(prog, f"[B][COLOR yellow]{action_text}[/COLOR][/B]\n[COLOR white]{fmt_size(copied)} / {fmt_size(total_size)}[/COLOR]")
            finally:
                f_out.close()
        return True
    except Exception as e:
        log(f"Stream upload error: {e}", xbmc.LOGERROR)
        if "No such file" in str(e) or "failed" in str(e).lower() or "'w'" in str(e):
            raise Exception("ACCESS DENIED! Windows/System is blocking the write.\nCheck permissions.")
        raise e

def download_from_vfs(src_vfs, dest_local, dialog, start_pct, end_pct):
    """Copies from SMB/Local to Android, chunk by chunk, showing progress."""
    try:
        try: total_size = xbmcvfs.Stat(src_vfs).st_size()
        except: total_size = 0

        copied = 0
        chunk_size = 4 * 1024 * 1024 # 4 MB chunks
        
        # Check if it's an SMB path or a local path
        if src_vfs.lower().startswith('smb://'):
            action_text = "SMB Network Download:"
        else:
            action_text = "Loading Archive:"

        f_in = xbmcvfs.File(src_vfs)
        try:
            with open(dest_local, 'wb') as f_out:
                while True:
                    if dialog.iscanceled():
                        return False
                    
                    chunk = f_in.readBytes(chunk_size)
                    if not chunk:
                        break
                    
                    f_out.write(bytearray(chunk))
                    copied += len(chunk)
                    
                    if total_size > 0:
                        prog = start_pct + int((copied / float(total_size)) * (end_pct - start_pct))
                        dialog.update(prog, f"[B][COLOR yellow]{action_text}[/COLOR][/B]\n[COLOR white]{fmt_size(copied)} / {fmt_size(total_size)}[/COLOR]")
        finally:
            f_in.close()
        return True
    except Exception as e:
        log(f"Stream download error: {e}", xbmc.LOGERROR)
        raise e

# -------------------------------------------------------------

def gather_files_for_backup():
    files_to_zip = []

    b_fav = (ADDON.getSetting('backup_fav') == 'true')
    b_gui = (ADDON.getSetting('backup_gui') == 'true')
    b_src = (ADDON.getSetting('backup_src') == 'true')
    b_pass = (ADDON.getSetting('backup_pass') == 'true')
    b_media = (ADDON.getSetting('backup_media') == 'true')
    b_adv = (ADDON.getSetting('backup_adv') == 'true')
    b_gen = (ADDON.getSetting('backup_gen') == 'true')
    b_db_add = (ADDON.getSetting('backup_db_add') == 'true')
    b_db_vid = (ADDON.getSetting('backup_db_vid') == 'true')
    b_db_view = (ADDON.getSetting('backup_db_view') == 'true')
    b_adata = (ADDON.getSetting('backup_adata') == 'true')
    b_play = (ADDON.getSetting('backup_play') == 'true')

    xml_files = []
    if b_fav: xml_files.append('userdata/favourites.xml')
    if b_gui: xml_files.append('userdata/guisettings.xml')
    if b_src: xml_files.append('userdata/sources.xml')
    if b_pass: xml_files.append('userdata/passwords.xml')
    if b_media: xml_files.append('userdata/mediasources.xml')
    if b_adv: xml_files.append('userdata/advancedsettings.xml')
    if b_gen: xml_files.append('userdata/keymaps/gen.xml')

    for x in xml_files:
        full_path = os.path.join(KODI_HOME, os.path.normpath(x))
        if os.path.exists(full_path):
            files_to_zip.append((full_path, x))

    dirs_to_add = []
    if b_adata: dirs_to_add.append('userdata/addon_data')
    if b_play: dirs_to_add.append('userdata/playlists')

    # EXCLUDED FOLDERS AND EXTENSIONS
    skip_folders = ['__pycache__', '.git', '.svn', 'blur_v3', 'crop_v2', 'Downloads', 'Movies Downloads', 'TV Show Downloads']
    skip_exts = ('.pyc', '.mp4', '.mkv', '.avi', '.ts', '.m2ts', '.bak')

    for d in dirs_to_add:
        full_path = os.path.join(KODI_HOME, os.path.normpath(d))
        if os.path.exists(full_path):
            for root, dirs, files in os.walk(full_path):
                for junk in skip_folders:
                    if junk in dirs: dirs.remove(junk)
                for file in files:
                    if file.endswith(skip_exts): continue
                    fp = os.path.join(root, file)
                    rel = os.path.relpath(fp, KODI_HOME)
                    files_to_zip.append((fp, rel))

    addons_path = os.path.join(KODI_HOME, 'addons')
    if os.path.exists(addons_path):
        for root, dirs, files in os.walk(addons_path):
            if root == addons_path:
                if 'packages' in dirs: dirs.remove('packages')
                if 'temp' in dirs: dirs.remove('temp')
            for junk in skip_folders:
                if junk in dirs: dirs.remove(junk)
            for file in files:
                if file.endswith(skip_exts): continue
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, KODI_HOME)
                files_to_zip.append((fp, rel))

    db_path = os.path.join(KODI_HOME, 'userdata', 'Database')
    if os.path.exists(db_path):
        for file in os.listdir(db_path):
            if file.endswith('.db'):
                if b_db_vid and file.startswith('MyVideos'):
                    fp = os.path.join(db_path, file)
                    rel = os.path.relpath(fp, KODI_HOME)
                    files_to_zip.append((fp, rel))
                elif b_db_add and file.startswith('Addons'):
                    fp = os.path.join(db_path, file)
                    rel = os.path.relpath(fp, KODI_HOME)
                    files_to_zip.append((fp, rel))
                elif b_db_view and file.startswith('ViewModes'):
                    fp = os.path.join(db_path, file)
                    rel = os.path.relpath(fp, KODI_HOME)
                    files_to_zip.append((fp, rel))

    final_files = []
    for fp, rel in files_to_zip:
        if not rel.endswith('profiles.xml'):
            final_files.append((fp, rel))

    return final_files

def do_backup():
    if not BACKUP_FOLDER:
        show_notification("Set the backup folder first!", True)
        ADDON.openSettings()
        return

    log(f"Starting do_backup. Target location: {BACKUP_FOLDER}")
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_filename = f"MCB_Kodi_{timestamp}.zip"
    
    local_temp_zip = os.path.join(TEMP_DIR, zip_filename)
    final_dest_zip = vfs_join(BACKUP_FOLDER, zip_filename)

    # FIX: Ensure TEMP_DIR exists physically
    os.makedirs(os.path.dirname(local_temp_zip), exist_ok=True)

    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, "[B][COLOR orange]Analyzing files...[/COLOR][/B]")

    try:
        files_to_zip = gather_files_for_backup()
        total_files = len(files_to_zip)

        if total_files == 0:
            dialog.close()
            xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR red]No valid files found![/COLOR]")
            return

        dialog.update(0, f"[COLOR cyan]Creating local archive... ({total_files} files)[/COLOR]")

        # 1. CREATE LOCAL ARCHIVE (0% -> 80%)
        with zipfile.ZipFile(local_temp_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for index, (full_path, rel_path) in enumerate(files_to_zip):
                if dialog.iscanceled(): return
                
                percent = int((index / float(total_files)) * 80)
                dialog.update(percent, f"[B][COLOR cyan]Archiving ({percent}%):[/COLOR][/B]\n[COLOR white]{os.path.basename(rel_path)}[/COLOR]")
                zipf.write(full_path, rel_path.replace('\\', '/'))
        
        # 2. NETWORK UPLOAD (80% -> 100%)
        if not xbmcvfs.exists(BACKUP_FOLDER):
            try: xbmcvfs.mkdirs(BACKUP_FOLDER)
            except: pass

        log(f"Starting SMB transfer. Local: {local_temp_zip} -> Network: {final_dest_zip}")
        
        # USING THE NEW FUNCTION HERE
        upload_success = upload_to_vfs(local_temp_zip, final_dest_zip, dialog, 80, 100)
        
        if upload_success:
            os.remove(local_temp_zip)
            dialog.update(100, "[COLOR green]Transfer complete![/COLOR]")
            dialog.close()
            xbmcgui.Dialog().ok(
                ADDON_NAME, 
                f"[B][COLOR lime]Backup finished![/COLOR][/B]\n"
                f"[B][COLOR yellow]Saved files: {total_files}[/COLOR][/B]\n"
                f"[B][COLOR cyan]Name: {zip_filename}[/COLOR][/B]"
            )
        else:
            raise Exception("Transfer was interrupted.")
    
    except Exception as e:
        log(f"BACKUP ERROR: {str(e)}", xbmc.LOGERROR)
        dialog.close()
        xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR red]Backup error:[/COLOR]\n{str(e)}")
    finally:
        if os.path.exists(local_temp_zip):
            try: os.remove(local_temp_zip)
            except: pass

def do_restore():
    if not BACKUP_FOLDER:
        show_notification("Set the backup folder first!", True)
        ADDON.openSettings()
        return

    log(f"Starting do_restore. Searching in: {BACKUP_FOLDER}")
    zip_files = []
    display_list = []
    
    try:
        dirs, files = xbmcvfs.listdir(BACKUP_FOLDER)
    except Exception as e:
        xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR red]Cannot read folder![/COLOR]\nCheck if SMB is accessible.")
        return

    for f in sorted(files, reverse=True):
        fl = f.lower()
        if (fl.startswith('mcb_kodi_') or fl.startswith('kodi_backup_')) and fl.endswith('.zip'):
            zip_files.append(f)
            stem = f[len('MCB_Kodi_'):-len('.zip')] if fl.startswith('mcb_kodi_') else f[len('Kodi_Backup_'):-len('.zip')]
            nice = f
            try:
                if len(stem) == 19 and '_' in stem:
                    date_part, time_part = stem.split('_')
                    yyyy, mm, dd = date_part.split('-')
                    HH, MM, SS = time_part.split('-')
                elif len(stem) == 15 and '_' in stem:
                    date_part, time_part = stem.split('_')
                    yyyy, mm, dd = date_part[0:4], date_part[4:6], date_part[6:8]
                    HH, MM, SS = time_part[0:2], time_part[2:4], time_part[4:6]
                else: raise ValueError
                
                months = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                nice = f"{dd} {months[int(mm)]} {yyyy}  -  {HH}:{MM}:{SS}"
            except Exception: pass
            display_list.append(f"[COLOR cyan]{nice}[/COLOR]")

    if not zip_files:
        xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR red]No backup archive found in the folder![/COLOR]")
        return

    selected_index = xbmcgui.Dialog().select("[COLOR cyan]Choose file to RESTORE[/COLOR]", display_list)
    if selected_index == -1: return

    selected_zip = zip_files[selected_index]
    smb_zip_filepath = vfs_join(BACKUP_FOLDER, selected_zip)
    local_temp_zip = os.path.join(TEMP_DIR, "temp_restore.zip")

    # FIX: Ensure TEMP_DIR exists physically
    os.makedirs(os.path.dirname(local_temp_zip), exist_ok=True)

    confirm = xbmcgui.Dialog().yesno(
        "[COLOR red][B]RESTORE WARNING[/B][/COLOR]",
        "[COLOR white]This action will overwrite your current settings![/COLOR]\n"
        "[COLOR yellow]Kodi will FORCE CLOSE at the end.[/COLOR]\n\n"
        "[COLOR green]Are you sure you want to continue?[/COLOR]"
    )
    if not confirm: return

    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, f"[COLOR yellow]Preparing download...[/COLOR]")
    
    try:
        log(f"Download SMB: {smb_zip_filepath} -> {local_temp_zip}")
        
        # USING THE NEW FUNCTION FOR PROGRESS DOWNLOAD HERE
        download_success = download_from_vfs(smb_zip_filepath, local_temp_zip, dialog, 0, 70)
        
        if not download_success:
            raise Exception("Archive download was interrupted or failed.")

        dialog.update(70, "[COLOR magenta]Extracting files to system...[/COLOR]")
        log("Starting file extraction from temp archive.")

        with zipfile.ZipFile(local_temp_zip, 'r') as zipf:
            zipf.extractall(KODI_HOME)
        
        if os.path.exists(local_temp_zip):
            os.remove(local_temp_zip)

        dialog.update(100, "[COLOR green]Finished![/COLOR]")
        dialog.close()
        
        xbmcgui.Dialog().ok(
            "[COLOR green][B]RESTORE COMPLETE[/B][/COLOR]", 
            "[COLOR white]Files were restored successfully![/COLOR]\n\n"
            "[COLOR yellow]Kodi will force close NOW.[/COLOR]\n"
            "[COLOR cyan]After closing, start it normally.[/COLOR]"
        )
        os._exit(1)

    except Exception as e:
        log(f"RESTORE ERROR: {str(e)}", xbmc.LOGERROR)
        dialog.close()
        xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR red]Restore Error:[/COLOR]\n\n{str(e)}")
    finally:
        if os.path.exists(local_temp_zip):
            try: os.remove(local_temp_zip)
            except: pass

def do_clean():
    clean_packages = (ADDON.getSetting('clean_packages') == 'true')
    clean_temp = (ADDON.getSetting('clean_temp') == 'true')
    clean_cache = (ADDON.getSetting('clean_cache') == 'true')
    clean_thumbs = (ADDON.getSetting('clean_thumbnails') == 'true')
    clean_textures = (ADDON.getSetting('clean_textures') == 'true')

    if not any([clean_packages, clean_temp, clean_cache, clean_thumbs, clean_textures]):
        xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR yellow]You haven't checked any cleaning options in Settings![/COLOR]")
        ADDON.openSettings()
        return

    requires_restart = clean_thumbs or clean_textures

    msg = "[COLOR white]Unnecessary files checked in Settings will be deleted.[/COLOR]\n"
    if requires_restart:
        msg += "\n[COLOR red][B]WARNING:[/B] Because you chose to delete Thumbnails / Textures, Kodi will FORCE CLOSE at the end![/COLOR]\n"
    msg += "\n[COLOR green]Are you sure you want to continue?[/COLOR]"

    confirm = xbmcgui.Dialog().yesno("[COLOR cyan][B]Confirm Cleaning[/B][/COLOR]", msg)
    if not confirm:
        return

    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, "[COLOR yellow]Cleaning files...[/COLOR]")
    deleted_count = 0

    def safe_remove_dir(path):
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path, exist_ok=True)

    try:
        if clean_packages:
            safe_remove_dir(os.path.join(KODI_HOME, 'addons', 'packages'))
            deleted_count += 1
        if clean_temp:
            safe_remove_dir(os.path.join(KODI_HOME, 'addons', 'temp'))
            deleted_count += 1
        if clean_cache:
            safe_remove_dir(os.path.join(KODI_HOME, 'cache'))
            safe_remove_dir(os.path.join(KODI_HOME, 'temp'))
            temp_root = os.path.normpath(xbmcvfs.translatePath('special://temp/'))
            if os.path.exists(temp_root):
                for item in os.listdir(temp_root):
                    ip = os.path.join(temp_root, item)
                    if os.path.isdir(ip): shutil.rmtree(ip, ignore_errors=True)
                    else:
                        try: os.remove(ip)
                        except: pass
            deleted_count += 1
        if clean_thumbs:
            safe_remove_dir(os.path.join(KODI_HOME, 'userdata', 'Thumbnails'))
            tmdb_path = os.path.join(KODI_HOME, 'userdata', 'addon_data', 'plugin.video.themoviedb.helper')
            safe_remove_dir(os.path.join(tmdb_path, 'blur_v3'))
            safe_remove_dir(os.path.join(tmdb_path, 'crop_v2'))
            deleted_count += 1
        if clean_textures:
            db_path = os.path.join(KODI_HOME, 'userdata', 'Database')
            if os.path.exists(db_path):
                for f in os.listdir(db_path):
                    if f.startswith('Textures') and f.endswith('.db'):
                        try: os.remove(os.path.join(db_path, f))
                        except: pass
            deleted_count += 1

        dialog.update(100, "[COLOR green]Cleaning finished![/COLOR]")
        dialog.close()

        if requires_restart:
            xbmcgui.Dialog().ok(
                "[COLOR green][B]CLEANING COMPLETE[/B][/COLOR]",
                "[COLOR yellow]Kodi will force close NOW.[/COLOR]"
            )
            os._exit(1)
        else:
            xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR cyan]Deleted {deleted_count} checked locations.[/COLOR]")

    except Exception as e:
        dialog.close()
        xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR red]Cleaning Error:[/COLOR]\n{str(e)}")

def show_info():
    bp = ADDON.getSetting('backup_folder')
    bp_show = f"[COLOR cyan]{bp}[/COLOR]" if bp else "[COLOR red](not set!)[/COLOR]"
    
    clean_lines = []
    def get_sz_str(path):
        return f"[COLOR springgreen]({fmt_size(calc_folder_size(path))})[/COLOR]"

    clean_lines.append(f" • [COLOR silver]addons/packages[/COLOR]  {get_sz_str(os.path.join(KODI_HOME, 'addons', 'packages'))}")
    clean_lines.append(f" • [COLOR silver]addons/temp[/COLOR]  {get_sz_str(os.path.join(KODI_HOME, 'addons', 'temp'))}")
    
    cache_sz = calc_folder_size(os.path.join(KODI_HOME, 'cache')) + calc_folder_size(os.path.join(KODI_HOME, 'temp'))
    clean_lines.append(f" • [COLOR silver]Cache & Temp (Kodi)[/COLOR]  [COLOR springgreen]({fmt_size(cache_sz)})[/COLOR]")

    tb_sz = calc_folder_size(os.path.join(KODI_HOME, 'userdata', 'Thumbnails'))
    clean_lines.append(f" • [COLOR silver]Thumbnails & Image Cache[/COLOR]  [COLOR springgreen]({fmt_size(tb_sz)})[/COLOR]")

    msg = (
        "[COLOR deepskyblue][B]=== LOCATIONS ===[/B][/COLOR]\n"
        f"[COLOR gold]Kodi:[/COLOR] [COLOR cyan]{KODI_HOME}[/COLOR]\n"
        f"[COLOR gold]Backup:[/COLOR] {bp_show}\n\n"
        "[COLOR orangered][B]=== DISK SPACE USED (CLEANING) ===[/B][/COLOR]\n"
        f"{chr(10).join(clean_lines)}"
    )
    xbmcgui.Dialog().textviewer(ADDON_NAME + "  -  Info", msg)

def main_menu():
    options = [
        "[B][COLOR cyan]1. Create new BACKUP[/COLOR][/B]", 
        "[B][COLOR lime]2. RESTORE from a backup[/COLOR][/B]", 
        "[B][COLOR red]3. CLEANING unnecessary files[/COLOR][/B]",
        "[B][COLOR yellow]4. Settings (Folders and Options)[/COLOR][/B]",
        "[B][COLOR hotpink]5. INFO (Disk space used)[/COLOR][/B]"
    ]
    
    choice = xbmcgui.Dialog().select("[COLOR gold][B]Backup & Maintenance Menu[/B][/COLOR]", options)
    
    if choice == 0: do_backup()
    elif choice == 1: do_restore()
    elif choice == 2: do_clean()
    elif choice == 3: ADDON.openSettings()
    elif choice == 4: show_info()

if __name__ == '__main__':
    main_menu()