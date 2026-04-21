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

# Calea catre radacina Kodi (Windows, Linux, Android)
KODI_HOME = os.path.normpath(xbmcvfs.translatePath('special://home/'))

def show_notification(message, is_error=False):
    icon = xbmcgui.NOTIFICATION_ERROR if is_error else xbmcgui.NOTIFICATION_INFO
    color = "red" if is_error else "green"
    xbmcgui.Dialog().notification("[B][COLOR cyan]My Custom [B][COLOR gray]Backup[/COLOR][/B]", f"[COLOR {color}]{message}[/COLOR]", icon, 4000)

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

def gather_files_for_backup():
    files_to_zip = []

    # Citim setarile alese de tine (bifele On/Off)
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

    # 1. Fisierele XML specifice (doar cele bifate)
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

    # 2. Foldere complete (addon_data, playlists - doar daca sunt bifate)
    dirs_to_add = []
    if b_adata: dirs_to_add.append('userdata/addon_data')
    if b_play: dirs_to_add.append('userdata/playlists')

    for d in dirs_to_add:
        full_path = os.path.join(KODI_HOME, os.path.normpath(d))
        if os.path.exists(full_path):
            for root, dirs, files in os.walk(full_path):
                # EXCLUDERE JUNK DIRECTORIES
                for junk in ['__pycache__', '.git', '.svn', 'blur_v3', 'crop_v2']:
                    if junk in dirs:
                        dirs.remove(junk)
                
                for file in files:
                    # EXCLUDERE JUNK FILES (.pyc)
                    if file.endswith('.pyc'):
                        continue
                    fp = os.path.join(root, file)
                    rel = os.path.relpath(fp, KODI_HOME)
                    files_to_zip.append((fp, rel))

    # 3. Addons (Folderul principal de addons se salveaza mereu, dar aplicam filtrele pe el)
    addons_path = os.path.join(KODI_HOME, 'addons')
    if os.path.exists(addons_path):
        for root, dirs, files in os.walk(addons_path):
            if root == addons_path:
                if 'packages' in dirs: dirs.remove('packages')
                if 'temp' in dirs: dirs.remove('temp')
            
            # EXCLUDERE JUNK DIRECTORIES din interiorul addons
            for junk in ['__pycache__', '.git', '.svn', 'blur_v3', 'crop_v2']:
                if junk in dirs:
                    dirs.remove(junk)
            
            for file in files:
                # EXCLUDERE JUNK FILES (.pyc)
                if file.endswith('.pyc'):
                    continue
                fp = os.path.join(root, file)
                rel = os.path.relpath(fp, KODI_HOME)
                files_to_zip.append((fp, rel))

    # 4. Baza de date - Luam doar ce e bifat in setari
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

    # FILTRU FINAL DE SIGURANTA (Nu salvam profiles.xml niciodata)
    final_files = []
    for fp, rel in files_to_zip:
        if not rel.endswith('profiles.xml'):
            final_files.append((fp, rel))

    return final_files

def do_backup():
    if not BACKUP_FOLDER:
        show_notification("Seteaza folderul de backup mai intai!", True)
        ADDON.openSettings()
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_filename = f"MCB_Kodi_{timestamp}.zip"
    zip_filepath = os.path.join(BACKUP_FOLDER, zip_filename)

    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, "[B][COLOR orange]Se analizeaza fisierele...[/COLOR][/B]")

    try:
        files_to_zip = gather_files_for_backup()
        total_files = len(files_to_zip)

        if total_files == 0:
            dialog.close()
            xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR red]Nu s-a gasit niciun fisier valid![/COLOR]")
            return

        dialog.update(0, f"[COLOR cyan]Incepere arhivare... ({total_files} fisiere)[/COLOR]")

        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for index, (full_path, rel_path) in enumerate(files_to_zip):
                if dialog.iscanceled():
                    break
                
                percent = int((index / float(total_files)) * 100)
                dialog.update(percent, f"[B][COLOR cyan]Se arhiveaza ({percent}%):[/COLOR][/B]\n[COLOR white]{os.path.basename(rel_path)}[/COLOR]")

                zip_path_format = rel_path.replace('\\', '/')
                zipf.write(full_path, zip_path_format)
        
        dialog.close()
        xbmcgui.Dialog().ok(
            ADDON_NAME, 
            f"[B][COLOR lime]Backup finalizat![/COLOR][/B]\n"
            f"[B][COLOR yellow]Fisiere salvate: {total_files}[/COLOR][/B]\n"
            f"[B][COLOR cyan]Nume: {zip_filename}[/COLOR][/B]"
        )
    
    except Exception as e:
        dialog.close()
        xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR red]Eroare la backup:[/COLOR]\n{str(e)}")

def do_restore():
    if not BACKUP_FOLDER:
        show_notification("Seteaza folderul de backup mai intai!", True)
        ADDON.openSettings()
        return

    zip_files = []
    display_list = []
    
    # Sortam si filtram fisierele din folder
    for f in sorted(os.listdir(BACKUP_FOLDER), reverse=True):
        fl = f.lower()
        # Cautam prefixul MCB sau pe cel vechi Kodi_Backup
        if (fl.startswith('mcb_kodi_') or fl.startswith('kodi_backup_')) and fl.endswith('.zip'):
            zip_files.append(f)
            
            # Taiem prefixul corespunzator pentru a extrage data
            if fl.startswith('mcb_kodi_'):
                stem = f[len('MCB_Kodi_'):-len('.zip')]
            else:
                stem = f[len('Kodi_Backup_'):-len('.zip')]
            
            # Parsare manuala 100% safe (fara strptime care pica pe Android/Cube)
            nice = f # Fallback in caz de eroare (afiseaza numele fisierului brut)
            try:
                # Noul format: 2023-11-25_14-30-05 (19 caractere)
                if len(stem) == 19 and '_' in stem:
                    date_part, time_part = stem.split('_')
                    yyyy, mm, dd = date_part.split('-')
                    HH, MM, SS = time_part.split('-')
                # Vechiul format din acest script: 20231125_143005 (15 caractere)
                elif len(stem) == 15 and '_' in stem:
                    date_part, time_part = stem.split('_')
                    yyyy, mm, dd = date_part[0:4], date_part[4:6], date_part[6:8]
                    HH, MM, SS = time_part[0:2], time_part[2:4], time_part[4:6]
                else:
                    raise ValueError
                
                luni = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                nice = f"{dd} {luni[int(mm)]} {yyyy}  -  {HH}:{MM}:{SS}"
            except Exception:
                pass
            
            display_list.append(f"[COLOR cyan]{nice}[/COLOR]")

    if not zip_files:
        xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR red]Nu exista nicio arhiva de backup in folder![/COLOR]")
        return

    # Aratam lista formatata frumos userului
    selected_index = xbmcgui.Dialog().select("[COLOR cyan]Alege fisierul de RESTORE[/COLOR]", display_list)
    if selected_index == -1:
        return

    selected_zip = zip_files[selected_index]
    zip_filepath = os.path.join(BACKUP_FOLDER, selected_zip)

    confirm = xbmcgui.Dialog().yesno(
        "[COLOR red][B]AVERTISMENT RESTORE[/B][/COLOR]",
        "[COLOR white]Aceasta actiune va suprascrie setarile actuale![/COLOR]\n"
        "[COLOR yellow]Kodi SE VA INCHIDE FORTAT la final.[/COLOR]\n\n"
        "[COLOR green]Esti sigur ca vrei sa continui?[/COLOR]"
    )
    
    if not confirm:
        return

    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, f"[COLOR yellow]Se extrag fisierele din:[/COLOR]\n[COLOR white]{selected_zip}[/COLOR]")
    dialog.update(50, "[COLOR magenta]Asteapta... Poate dura cateva minute.[/COLOR]")

    try:
        with zipfile.ZipFile(zip_filepath, 'r') as zipf:
            zipf.extractall(KODI_HOME)
        
        dialog.update(100, "[COLOR green]Finalizat![/COLOR]")
        dialog.close()
        
        xbmcgui.Dialog().ok(
            "[COLOR green][B]RESTORE COMPLET[/B][/COLOR]", 
            "[COLOR white]Fisierele au fost restaurate cu succes![/COLOR]\n\n"
            "[COLOR yellow]Kodi se va incheia fortat ACUM.[/COLOR]\n"
            "[COLOR cyan]Dupa inchidere, porneste-l normal.[/COLOR]"
        )
        os._exit(1)

    except Exception as e:
        dialog.close()
        xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR red]Eroare la Restore:[/COLOR]\n{str(e)}")

def do_clean():
    # Citim setarile din meniu
    clean_packages = (ADDON.getSetting('clean_packages') == 'true')
    clean_temp = (ADDON.getSetting('clean_temp') == 'true')
    clean_cache = (ADDON.getSetting('clean_cache') == 'true')
    clean_thumbs = (ADDON.getSetting('clean_thumbnails') == 'true')
    clean_textures = (ADDON.getSetting('clean_textures') == 'true')

    if not any([clean_packages, clean_temp, clean_cache, clean_thumbs, clean_textures]):
        xbmcgui.Dialog().ok(ADDON_NAME, "[COLOR yellow]Nu ai bifat nicio optiune de curatare in Setari![/COLOR]")
        ADDON.openSettings()
        return

    requires_restart = clean_thumbs or clean_textures

    msg = "[COLOR white]Se vor sterge fisierele inutile bifate in Setari.[/COLOR]\n"
    if requires_restart:
        msg += "\n[COLOR red][B]ATENTIE:[/B] Deoarece ai ales stergerea Thumbnails / Textures, Kodi SE VA INCHIDE FORTAT la final pentru a regenera imaginile corect![/COLOR]\n"
    msg += "\n[COLOR green]Esti sigur ca vrei sa continui?[/COLOR]"

    confirm = xbmcgui.Dialog().yesno("[COLOR cyan][B]Confirmare Curatare[/B][/COLOR]", msg)
    if not confirm:
        return

    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, "[COLOR yellow]Se curata fisierele...[/COLOR]")
    
    deleted_count = 0

    def safe_remove_dir(path):
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
            # Recreem folderul gol pentru a evita erori la unele addonuri
            os.makedirs(path, exist_ok=True)

    try:
        # 1. Pachete
        if clean_packages:
            dialog.update(20, "[COLOR cyan]Se sterge: addons/packages...[/COLOR]")
            safe_remove_dir(os.path.join(KODI_HOME, 'addons', 'packages'))
            deleted_count += 1

        # 2. Temp addons
        if clean_temp:
            dialog.update(40, "[COLOR cyan]Se sterge: addons/temp...[/COLOR]")
            safe_remove_dir(os.path.join(KODI_HOME, 'addons', 'temp'))
            deleted_count += 1

        # 3. Cache Kodi / Temp
        if clean_cache:
            dialog.update(60, "[COLOR cyan]Se sterge: Cache / Temp...[/COLOR]")
            
            # 1. Stergem folderul 'cache' (specific Windows)
            safe_remove_dir(os.path.join(KODI_HOME, 'cache'))
            
            # 2. Stergem folderul 'temp' din radacina (specific Android / Linux)
            safe_remove_dir(os.path.join(KODI_HOME, 'temp'))
            
            # 3. Curatam suplimentar si locatia virtuala 'special://temp/' recunoscuta de Kodi
            temp_root = os.path.normpath(xbmcvfs.translatePath('special://temp/'))
            if os.path.exists(temp_root):
                for item in os.listdir(temp_root):
                    item_path = os.path.join(temp_root, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                    else:
                        try: os.remove(item_path)
                        except: pass
            deleted_count += 1

        # 4. Thumbnails & TMDb Helper caches
        if clean_thumbs:
            dialog.update(80, "[COLOR cyan]Se sterg: Thumbnails si Image Cache...[/COLOR]")
            safe_remove_dir(os.path.join(KODI_HOME, 'userdata', 'Thumbnails'))
            
            # Caches suplimentare pentru imagini blurate/taiate din TMDb Helper
            tmdb_path = os.path.join(KODI_HOME, 'userdata', 'addon_data', 'plugin.video.themoviedb.helper')
            safe_remove_dir(os.path.join(tmdb_path, 'blur_v3'))
            safe_remove_dir(os.path.join(tmdb_path, 'crop_v2'))
            
            deleted_count += 1

        # 5. Textures DB
        if clean_textures:
            dialog.update(90, "[COLOR cyan]Se sterge: Textures*.db...[/COLOR]")
            db_path = os.path.join(KODI_HOME, 'userdata', 'Database')
            if os.path.exists(db_path):
                for f in os.listdir(db_path):
                    if f.startswith('Textures') and f.endswith('.db'):
                        try: os.remove(os.path.join(db_path, f))
                        except: pass
            deleted_count += 1

        dialog.update(100, "[COLOR green]Curatare finalizata![/COLOR]")
        dialog.close()

        if requires_restart:
            xbmcgui.Dialog().ok(
                "[COLOR green][B]CURATARE COMPLETA[/B][/COLOR]",
                "[COLOR white]Fisierele selectate au fost sterse![/COLOR]\n\n"
                "[COLOR yellow]Kodi se va incheia fortat ACUM.[/COLOR]\n"
                "[COLOR cyan]Dupa restart, imaginile se vor descarca din nou automat.[/COLOR]"
            )
            os._exit(1)
        else:
            xbmcgui.Dialog().ok(
                "[COLOR green][B]CURATARE COMPLETA[/B][/COLOR]",
                "[COLOR white]Curatarea s-a terminat cu succes![/COLOR]\n"
                f"[COLOR cyan]S-au sters {deleted_count} locatii bifate.[/COLOR]"
            )

    except Exception as e:
        dialog.close()
        xbmcgui.Dialog().ok(ADDON_NAME, f"[COLOR red]Eroare la Curatare:[/COLOR]\n{str(e)}")


def show_info():
    # --- 1. SETARI LOCATII ---
    bp = ADDON.getSetting('backup_folder')
    bp_show = f"[COLOR cyan]{xbmcvfs.translatePath(bp)}[/COLOR]" if bp else "[COLOR red](nesetat!)[/COLOR]"

    # --- 2. SETARI BACKUP ---
    all_xml = [
        ('backup_fav', 'favourites'), ('backup_gui', 'guisettings'),
        ('backup_src', 'sources'), ('backup_pass', 'passwords'),
        ('backup_media', 'mediasources'), ('backup_adv', 'advancedsettings'),
        ('backup_gen', 'keymaps/gen')
    ]
    active_xml = [name for key, name in all_xml if ADDON.getSetting(key) == 'true']
    xml_txt = "[COLOR white]" + ", ".join(active_xml) + "[/COLOR]" if active_xml else "[COLOR gray]niciunul[/COLOR]"

    active_dirs = ['addons']
    if ADDON.getSetting('backup_adata') == 'true': active_dirs.append('addon_data')
    if ADDON.getSetting('backup_play') == 'true': active_dirs.append('playlists')
    dir_txt = "[COLOR white]" + ", ".join(active_dirs) + "[/COLOR]"

    active_db = []
    if ADDON.getSetting('backup_db_vid') == 'true': active_db.append('MyVideos')
    if ADDON.getSetting('backup_db_add') == 'true': active_db.append('Addons')
    if ADDON.getSetting('backup_db_view') == 'true': active_db.append('ViewModes')
    db_txt = "[COLOR white]" + ", ".join(active_db) + "[/COLOR]" if active_db else "[COLOR gray]niciunul[/COLOR]"

    # --- 3. DIMENSIUNI CLEANING ---
    clean_lines = []
    def get_sz_str(path):
        return f"[COLOR springgreen]({fmt_size(calc_folder_size(path))})[/COLOR]"

    # Packages & Temp
    clean_lines.append(f" • [COLOR silver]addons/packages[/COLOR]  {get_sz_str(os.path.join(KODI_HOME, 'addons', 'packages'))}")
    clean_lines.append(f" • [COLOR silver]addons/temp[/COLOR]  {get_sz_str(os.path.join(KODI_HOME, 'addons', 'temp'))}")
    
    # Cache & Temp Radacina
    cache_sz = calc_folder_size(os.path.join(KODI_HOME, 'cache')) + calc_folder_size(os.path.join(KODI_HOME, 'temp'))
    temp_root = os.path.normpath(xbmcvfs.translatePath('special://temp/'))
    if temp_root != os.path.join(KODI_HOME, 'temp'): # Previne dubla numarare
        cache_sz += calc_folder_size(temp_root)
    clean_lines.append(f" • [COLOR silver]Cache & Temp (Kodi)[/COLOR]  [COLOR springgreen]({fmt_size(cache_sz)})[/COLOR]")

    # Thumbnails + TMDb
    tb_sz = calc_folder_size(os.path.join(KODI_HOME, 'userdata', 'Thumbnails'))
    tmdb_base = os.path.join(KODI_HOME, 'userdata', 'addon_data', 'plugin.video.themoviedb.helper')
    tb_sz += calc_folder_size(os.path.join(tmdb_base, 'blur_v3'))
    tb_sz += calc_folder_size(os.path.join(tmdb_base, 'crop_v2'))
    clean_lines.append(f" • [COLOR silver]Thumbnails & Image Cache[/COLOR]  [COLOR springgreen]({fmt_size(tb_sz)})[/COLOR]")
    
    # Textures DB
    tex_sz = 0
    db_path = os.path.join(KODI_HOME, 'userdata', 'Database')
    if os.path.exists(db_path):
        for f in os.listdir(db_path):
            if f.lower().startswith('textures') and f.lower().endswith('.db'):
                try: tex_sz += os.path.getsize(os.path.join(db_path, f))
                except OSError: pass
    clean_lines.append(f" • [COLOR silver]Textures DB[/COLOR]  [COLOR springgreen]({fmt_size(tex_sz)})[/COLOR]")

    clean_txt = '\n'.join(clean_lines)

    # --- 4. ASAMBLARE MESAJ FINAL ---
    msg = (
        "[COLOR deepskyblue][B]=== LOCATII ===[/B][/COLOR]\n"
        f"[COLOR gold]Kodi:[/COLOR] [COLOR cyan]{KODI_HOME}[/COLOR]\n"
        f"[COLOR gold]Backup:[/COLOR] {bp_show}\n\n"
        
        "[COLOR lime][B]=== DE SALVAT (BACKUP) ===[/B][/COLOR]\n"
        f"[COLOR gray]XML:[/COLOR]  {xml_txt}\n"
        f"[COLOR gray]Foldere:[/COLOR]  {dir_txt}\n"
        f"[COLOR gray]Baze date:[/COLOR]  {db_txt}\n\n"

        "[COLOR orangered][B]=== SPATIU OCUPAT (CLEANING) ===[/B][/COLOR]\n"
        f"{clean_txt}\n\n"

        "[COLOR gray][B]=== IGNORATE (JUNK SKIP) ===[/B][/COLOR]\n"
        "[COLOR silver]__pycache__, .git, .svn, *.pyc, blur_v3, crop_v2, temp, packages[/COLOR]"
    )

    xbmcgui.Dialog().textviewer(ADDON_NAME + "  -  Sumar Configuratie", msg)


def main_menu():
    options = [
        "[B][COLOR cyan]1. Creare BACKUP nou[/COLOR][/B]", 
        "[B][COLOR lime]2. RESTORE dintr-un backup[/COLOR][/B]", 
        "[B][COLOR red]3. CURATARE (Cleaning) fisiere inutile[/COLOR][/B]",
        "[B][COLOR yellow]4. Setari (Foldere si Optiuni)[/COLOR][/B]",
        "[B][COLOR hotpink]5. INFO (Sumar setari si spatiu)[/COLOR][/B]"
    ]
    
    choice = xbmcgui.Dialog().select("[COLOR gold][B]Meniu Backup & Mentenanta[/B][/COLOR]", options)
    
    if choice == 0:
        do_backup()
    elif choice == 1:
        do_restore()
    elif choice == 2:
        do_clean()
    elif choice == 3:
        ADDON.openSettings()
    elif choice == 4:
        show_info()

if __name__ == '__main__':
    main_menu()