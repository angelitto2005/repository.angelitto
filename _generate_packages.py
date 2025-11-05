# -*- coding: utf-8 -*-

import os
import hashlib
import zipfile
import xml.etree.ElementTree as ET

class Generator:
    """
        Generates packages with absolute asset paths in addons.xml.
        (v6 - Absolute Asset Paths)
    """
    def __init__(self, github_username, repo_name):
        self.github_username = github_username
        self.repo_name = repo_name
        self.base_url = f"https://raw.githubusercontent.com/{self.github_username}/{self.repo_name}/master/"
        
        self.zips_folder = 'zips'
        print(f"--- Încep generarea repository-ului (v6 - Căi Absolute) ---")
        
        if not os.path.exists(self.zips_folder):
            os.makedirs(self.zips_folder)
            
        self.addons = self._discover_addons()
        if not self.addons:
            print("EROARE: Nu am găsit niciun dosar de addon valid.")
            return

        print(f"\nAm găsit {len(self.addons)} addon-uri valide: {self.addons}\n")
        
        self._generate_addons_file()
        self._generate_zip_files()
        
        print("\n--- Proces terminat cu succes! ---")

    def _discover_addons(self):
        addon_list = []
        for item in os.listdir("."):
            if os.path.isdir(item) and item != self.zips_folder and os.path.exists(os.path.join(item, 'addon.xml')):
                addon_list.append(item)
        return addon_list

    def _generate_addons_file(self):
        print("--- Generare addons.xml și md5 cu căi absolute ---")
        root = ET.Element("addons")
        for addon_id in self.addons:
            try:
                addon_xml_path = os.path.join(addon_id, "addon.xml")
                addon_root = ET.parse(addon_xml_path).getroot()

                # --- MODIFICARE CHEIE: Rescrie căile pentru assets ---
                for md_extension in addon_root.findall('extension[@point="xbmc.addon.metadata"]'):
                    assets = md_extension.find('assets')
                    if assets is not None:
                        for asset in assets:
                            if not asset.text.startswith('http'):
                                asset.text = f"{self.base_url}{addon_id}/{asset.text}"
                # ---------------------------------------------------
                
                root.append(addon_root)
                print(f"-> Procesat XML pentru: {addon_id}")
            except Exception as e:
                print(f"EROARE la procesarea {addon_id}: {e}")
        tree = ET.ElementTree(root)
        tree.write("addons.xml", encoding="utf-8", xml_declaration=True)
        try:
            with open("addons.xml", "rb") as f: md5 = hashlib.md5(f.read()).hexdigest()
            with open("addons.xml.md5", "w") as f: f.write(md5)
            print("-> Fișierele addons.xml și addons.xml.md5 au fost create/actualizate.")
        except Exception as e:
            print(f"EROARE la generarea md5: {e}")

    def _is_repository_addon(self, addon_id):
        # ... (această funcție rămâne la fel)
        try:
            tree = ET.parse(os.path.join(addon_id, 'addon.xml'))
            for ext in tree.getroot().findall('extension'):
                if ext.get('point') == 'xbmc.addon.repository':
                    return True
        except Exception: return False
        return False

    def _generate_zip_files(self):
        # ... (această funcție rămâne la fel)
        print(f"\n--- Generare arhive .zip în folderul '{self.zips_folder}' ---")
        for addon_id in self.addons:
            try:
                root = ET.parse(os.path.join(addon_id, "addon.xml")).getroot()
                version = root.get("version")
                zip_filename = os.path.join(self.zips_folder, f"{addon_id}-{version}.zip")
                is_repo = self._is_repository_addon(addon_id)
                
                if is_repo: print(f"-> Se creează arhiva cu folder (repository): {os.path.basename(zip_filename)}")
                else: print(f"-> Se creează arhiva plată (addon): {os.path.basename(zip_filename)}")
                
                with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
                    for base, dirs, files in os.walk(addon_id):
                        for file in files:
                            file_path = os.path.join(base, file)
                            archive_path = os.path.relpath(file_path, os.path.join(addon_id, '..') if is_repo else addon_id)
                            zf.write(file_path, archive_path)
            except Exception as e:
                print(f"  -> EROARE la crearea arhivei pentru {addon_id}: {e}")

if __name__ == "__main__":
    # --- AICI TREBUIE SĂ SPECIFICAȚI DATELE DUMNEAVOASTRĂ ---
    GITHUB_USER = "angelitto2005"
    REPO_NAME = "repository.angelitto"
    # ----------------------------------------------------
    Generator(GITHUB_USER, REPO_NAME)
    input("\nPress any key to close the window...")