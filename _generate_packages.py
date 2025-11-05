# -*- coding: utf-8 -*-

import os
import hashlib
import zipfile
import xml.etree.ElementTree as ET
import shutil

class Generator:
    """
        Generates a professional repository structure and copies assets into the zips folder.
        (v9 - Asset Copy)
    """
    def __init__(self):
        self.zips_folder = 'zips'
        print(f"--- Încep generarea repository-ului (v9 - Copiere Resurse) ---")
        
        # Sterge si recreeaza folderul zips pentru a fi curat
        if os.path.exists(self.zips_folder):
            shutil.rmtree(self.zips_folder)
        os.makedirs(self.zips_folder)
            
        self.addons = self._discover_addons()
        if not self.addons:
            print("EROARE: Nu am găsit niciun dosar de addon valid.")
            return

        print(f"\nAm găsit {len(self.addons)} addon-uri valide: {self.addons}\n")
        
        self._generate_addons_file()
        self._generate_zip_files_and_assets()
        
        print("\n--- Proces terminat cu succes! ---")

    def _discover_addons(self):
        addon_list = []
        for item in os.listdir("."):
            if os.path.isdir(item) and item not in ['.git', self.zips_folder] and os.path.exists(os.path.join(item, 'addon.xml')):
                addon_list.append(item)
        return addon_list

    def _generate_addons_file(self):
        print("--- Generare addons.xml și md5 ---")
        root = ET.Element("addons")
        for addon_id in self.addons:
            try:
                addon_xml_path = os.path.join(addon_id, "addon.xml")
                addon_root = ET.parse(addon_xml_path).getroot()
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
        try:
            tree = ET.parse(os.path.join(addon_id, 'addon.xml'))
            for ext in tree.getroot().findall('extension'):
                if ext.get('point') == 'xbmc.addon.repository': return True
        except Exception: return False
        return False

    def _generate_zip_files_and_assets(self):
        print(f"\n--- Generare arhive .zip și copiere resurse în '{self.zips_folder}' ---")
        for addon_id in self.addons:
            try:
                addon_zip_folder = os.path.join(self.zips_folder, addon_id)
                if not os.path.exists(addon_zip_folder):
                    os.makedirs(addon_zip_folder)

                root = ET.parse(os.path.join(addon_id, "addon.xml")).getroot()
                version = root.get("version")
                zip_filename = os.path.join(addon_zip_folder, f"{addon_id}-{version}.zip")
                
                is_repo = self._is_repository_addon(addon_id)
                
                # Generare ZIP
                if is_repo: print(f"-> Se creează arhiva cu folder: {os.path.relpath(zip_filename)}")
                else: print(f"-> Se creează arhiva plată: {os.path.relpath(zip_filename)}")
                with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
                    for base, dirs, files in os.walk(addon_id):
                        for file in files:
                            file_path = os.path.join(base, file)
                            archive_path = os.path.relpath(file_path, os.path.join(addon_id, '..') if is_repo else addon_id)
                            zf.write(file_path, archive_path)
                
                # --- MODIFICARE CHEIE: Copiere Assets ---
                print(f"-> Se copiază resursele (pictograme, etc.) pentru {addon_id}")
                for md_extension in root.findall('extension[@point="xbmc.addon.metadata"]'):
                    assets = md_extension.find('assets')
                    if assets is not None:
                        for asset in assets:
                            source_asset_path = os.path.join(addon_id, asset.text)
                            dest_asset_path = os.path.join(addon_zip_folder, asset.text)
                            if os.path.exists(source_asset_path):
                                os.makedirs(os.path.dirname(dest_asset_path), exist_ok=True)
                                shutil.copy(source_asset_path, dest_asset_path)
                # ----------------------------------------
            except Exception as e:
                print(f"  -> EROARE la procesarea {addon_id}: {e}")

if __name__ == "__main__":
    Generator()
    input("\nPress any key to close the window...")