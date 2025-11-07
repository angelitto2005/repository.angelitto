# -*- coding: utf-8 -*-

"""
    MODIFIED SCRIPT
    
    Combines the robust repository structure from jurialmunkey's script
    with the automatic cleanup and ease-of-use features from your original script.

    Instructions:
    1. Place this script in the root folder of your repository.
    2. Run it.
    3. It will automatically:
        a. Delete the old 'zips' folder, 'addons.xml', and 'addons.xml.md5'.
        b. Re-create the 'zips' folder.
        c. Go through each addon folder, create a zip file, and place it in 'zips/<addon_id>/'.
        d. Copy metadata (addon.xml, icon.png, fanart.jpg, etc.) alongside the zip.
        e. Generate a new 'addons.xml' and 'addons.xml.md5' in the root folder.
        f. Keep the console window open to show the results.
"""

import os
import shutil
import hashlib
import zipfile
from xml.etree import ElementTree

# Lista de fișiere și foldere de ignorat la crearea arhivei .zip
IGNORE = [
    ".git",
    ".github",
    ".gitignore",
    ".DS_Store",
    "thumbs.db",
    ".idea",
    "venv",
]


def _setup_colors():
    """ Activează culorile în consolă, dacă este posibil. """
    color = os.system("color")
    console = 0
    if os.name == 'nt':  # Verificare specifică pentru Windows
        from ctypes import windll

        k = windll.kernel32
        console = k.SetConsoleMode(k.GetStdHandle(-11), 7)
    return color == 1 or console == 1


# Setup culori pentru consolă
_COLOR_ESCAPE = "\x1b[{}m"
_COLORS = {
    "black": "30",
    "red": "31",
    "green": "4;32",
    "yellow": "3;33",
    "blue": "34",
    "magenta": "35",
    "cyan": "1;36",
    "grey": "37",
    "endc": "0",
}
_SUPPORTS_COLOR = _setup_colors()


def color_text(text, color):
    """ Colorează textul pentru afișare în consolă. """
    return (
        '{}{}{}'.format(
            _COLOR_ESCAPE.format(_COLORS[color]),
            text,
            _COLOR_ESCAPE.format(_COLORS["endc"]),
        )
        if _SUPPORTS_COLOR
        else text
    )


def convert_bytes(num):
    """ Convertește bytes în unități mai mari (KB, MB, GB). """
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0


class Generator:
    """
    Generează un repository nou, creând arhive .zip pentru fiecare addon,
    un fișier central addons.xml și un hash MD5 corespunzător.
    """

    def __init__(self):
        """
        Inițializează procesul de generare.
        """
        self.root_path = "."
        self.zips_path = os.path.join(self.root_path, "zips")
        self.addons_xml_path = os.path.join(self.root_path, "addons.xml")
        self.md5_path = os.path.join(self.root_path, "addons.xml.md5")
        
        print("--- Încep generarea repository-ului ---")

        # --- START: Funcționalitate de curățare adăugată de la scriptul original ---
        print("\n--- Pasul 1: Curățare fișiere/foldere vechi ---")
        if os.path.exists(self.zips_path):
            try:
                shutil.rmtree(self.zips_path)
                print(f"-> Folderul '{self.zips_path}' vechi a fost {color_text('șters', 'green')}.")
            except Exception as e:
                print(f"-> {color_text('EROARE', 'red')} la ștergerea folderului '{self.zips_path}': {e}")
        
        if os.path.exists(self.addons_xml_path):
            try:
                os.remove(self.addons_xml_path)
                print(f"-> Fișierul '{self.addons_xml_path}' vechi a fost {color_text('șters', 'green')}.")
            except Exception as e:
                print(f"-> {color_text('EROARE', 'red')} la ștergerea fișierului '{self.addons_xml_path}': {e}")
        
        if os.path.exists(self.md5_path):
            try:
                os.remove(self.md5_path)
                print(f"-> Fișierul '{self.md5_path}' vechi a fost {color_text('șters', 'green')}.")
            except Exception as e:
                print(f"-> {color_text('EROARE', 'red')} la ștergerea fișierului '{self.md5_path}': {e}")
        
        print(f"-> Curățare finalizată. Se creează un nou folder '{self.zips_path}'.")
        os.makedirs(self.zips_path)
        # --- END: Funcționalitate de curățare ---
        
        print("\n--- Pasul 2: Eliminare fișiere Python compilate (.pyc, .pyo) ---")
        self._remove_binaries()

        print("\n--- Pasul 3: Generare fișiere addon și addons.xml ---")
        if self._generate_addons_file():
            print(
                f"\n-> Fișierul central {color_text(self.addons_xml_path, 'yellow')} a fost generat cu succes."
            )

            print("\n--- Pasul 4: Generare fișier MD5 ---")
            if self._generate_md5_file():
                print(f"-> Fișierul {color_text(self.md5_path, 'yellow')} a fost generat cu succes.")

    def _remove_binaries(self):
        """
        Șterge toate fișierele Python compilate și folderele __pycache__.
        """
        for parent, dirnames, filenames in os.walk(self.root_path):
            for fn in filenames:
                if fn.lower().endswith(("pyo", "pyc")):
                    compiled = os.path.join(parent, fn)
                    try:
                        os.remove(compiled)
                        print(f"Am șters: {color_text(compiled, 'green')}")
                    except Exception as e:
                        print(f"Eroare la ștergere {color_text(compiled, 'red')}: {e}")
            
            for dir_name in list(dirnames): # iteram pe o copie
                if "__pycache__" in dir_name.lower():
                    compiled = os.path.join(parent, dir_name)
                    try:
                        shutil.rmtree(compiled)
                        print(f"Am șters folderul: {color_text(compiled, 'green')}")
                        dirnames.remove(dir_name)
                    except Exception as e:
                        print(f"Eroare la ștergerea folderului {color_text(compiled, 'red')}: {e}")

    def _create_zip(self, addon_id, version):
        """
        Creează arhiva .zip pentru un addon specific.
        """
        addon_folder = os.path.join(self.root_path, addon_id)
        zip_addon_folder = os.path.join(self.zips_path, addon_id)
        if not os.path.exists(zip_addon_folder):
            os.makedirs(zip_addon_folder)

        final_zip_path = os.path.join(zip_addon_folder, f"{addon_id}-{version}.zip")
        
        with zipfile.ZipFile(final_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            root_len = len(os.path.dirname(os.path.abspath(addon_folder)))
            
            for root, dirs, files in os.walk(addon_folder):
                # Elimină folderele și fișierele ignorate
                dirs[:] = [d for d in dirs if d not in IGNORE]
                files[:] = [f for f in files if not any(f.startswith(i) for i in IGNORE)]

                archive_root = os.path.abspath(root)[root_len:]
                
                for f in files:
                    fullpath = os.path.join(root, f)
                    archive_name = os.path.join(archive_root, f)
                    zf.write(fullpath, archive_name, zipfile.ZIP_DEFLATED)

        size = convert_bytes(os.path.getsize(final_zip_path))
        print(
            f"  -> Arhivă creată pentru {color_text(addon_id, 'cyan')} "
            f"({color_text(version, 'green')}) - "
            f"{color_text(size, 'yellow')}"
        )

    def _copy_meta_files(self, addon_id):
        """
        Copiază addon.xml și fișierele de artă (icon, fanart) în folderul din zips.
        """
        addon_xml_src_path = os.path.join(self.root_path, addon_id, "addon.xml")
        tree = ElementTree.parse(addon_xml_src_path)
        root = tree.getroot()

        # Fișierele de copiat, începând cu addon.xml
        copy_files = ["addon.xml"]
        
        # Caută tag-ul <assets> pentru a găsi fișierele de artă
        extensions = root.findall("extension")
        for ext in extensions:
            if ext.get("point") in ["xbmc.addon.metadata", "kodi.addon.metadata"]:
                assets = ext.find("assets")
                if assets is not None:
                    for art in assets:
                        if art.text:
                            copy_files.append(os.path.normpath(art.text))
        
        src_folder = os.path.join(self.root_path, addon_id)
        dest_folder = os.path.join(self.zips_path, addon_id)

        print(f"  -> Se copiază metadatele pentru {color_text(addon_id, 'cyan')}:")
        for file in set(copy_files): # Folosim set() pentru a evita duplicatele
            src_path = os.path.join(src_folder, file)
            if not os.path.exists(src_path):
                print(f"    - {color_text('Atenție:', 'yellow')} Fișierul '{file}' nu a fost găsit.")
                continue

            dest_path = os.path.join(dest_folder, os.path.basename(file))
            
            # Asigură-te că folderul destinație există (pentru căi de genul 'resources/icon.png')
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            shutil.copy(src_path, dest_path)
            print(f"    - Copiat: {color_text(file, 'green')}")


    def _generate_addons_file(self):
        """
        Generează fișierul addons.xml prin combinarea fișierelor addon.xml
        din fiecare folder de addon.
        """
        # Găsește toate folderele care conțin un addon.xml
        addon_folders = [
            d for d in os.listdir(self.root_path)
            if os.path.isdir(os.path.join(self.root_path, d))
            and d != "zips"
            and not d.startswith(".")
            and os.path.exists(os.path.join(self.root_path, d, "addon.xml"))
        ]

        addons_root = ElementTree.Element('addons')

        for addon_id in addon_folders:
            try:
                addon_xml_path = os.path.join(self.root_path, addon_id, "addon.xml")
                addon_tree = ElementTree.parse(addon_xml_path)
                addon_root = addon_tree.getroot()
                version = addon_root.get('version')
                
                print(f"\nProcesare addon: {color_text(addon_id, 'cyan')} v{color_text(version, 'green')}")
                
                addons_root.append(addon_root)
                
                # Creează arhiva .zip
                self._create_zip(addon_id, version)
                
                # Copiază fișierele meta
                self._copy_meta_files(addon_id)
                
            except Exception as e:
                print(
                    f"EROARE la procesarea addon-ului {color_text(addon_id, 'yellow')}: {color_text(e, 'red')}"
                )
        
        if not addon_folders:
            print(f"{color_text('Nu s-au găsit addon-uri valide.', 'red')}")
            return False

        # Sortează addon-urile alfabetic după ID
        addons_root[:] = sorted(addons_root, key=lambda addon: addon.get('id'))
        
        # Scrie fișierul final addons.xml
        tree = ElementTree.ElementTree(addons_root)
        try:
            tree.write(
                self.addons_xml_path, encoding="utf-8", xml_declaration=True
            )
            return True
        except Exception as e:
            print(
                f"A apărut o eroare la scrierea {color_text(self.addons_xml_path, 'yellow')}!\n{color_text(e, 'red')}"
            )
            return False

    def _generate_md5_file(self):
        """
        Generează fișierul addons.xml.md5.
        """
        try:
            with open(self.addons_xml_path, "r", encoding="utf-8") as f:
                content = f.read().encode("utf-8")
                m = hashlib.md5(content).hexdigest()
            
            with open(self.md5_path, "w") as f:
                f.write(m)
            
            return True
        except Exception as e:
            print(
                f"A apărut o eroare la scrierea {color_text(self.md5_path, 'yellow')}!\n{color_text(e, 'red')}"
            )
            return False


if __name__ == "__main__":
    Generator()
    print("\n" + "="*40)
    print(color_text("Procesul de generare a repository-ului s-a încheiat.", "green"))
    print("="*40)
    # --- START: Funcționalitate adăugată pentru a menține consola deschisă ---
    input("\nApasă tasta ENTER pentru a închide fereastra...")
    # --- END: Funcționalitate adăugată ---