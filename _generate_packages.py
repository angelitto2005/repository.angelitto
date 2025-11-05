# -*- coding: utf-8 -*-

import os
import hashlib
import zipfile
import xml.etree.ElementTree as ET

class Generator:
    """
        Generates a new addons.xml and addons.xml.md5
        and packages all addons into zip files by
        auto-discovering them. (v2 - Flat Zips)
    """
    def __init__(self):
        print("--- Încep generarea repository-ului (v2 - Arhive Plate) ---")
        
        self.addons = self._discover_addons()
        
        if not self.addons:
            print("EROARE: Nu am găsit niciun dosar de addon valid (care să conțină addon.xml).")
            return

        print(f"\nAm găsit {len(self.addons)} addon-uri valide: {self.addons}\n")
        
        self._generate_addons_file()
        self._generate_zip_files()
        
        print("\n--- Proces terminat cu succes! ---")

    def _discover_addons(self):
        print("Caut automat dosarele de addon-uri...")
        addon_list = []
        for item in os.listdir("."):
            if os.path.isdir(item):
                if os.path.exists(os.path.join(item, 'addon.xml')):
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
                print(f"-> Procesat: {addon_id}")
            except Exception as e:
                print(f"EROARE la procesarea {addon_id}: {e}")
        
        tree = ET.ElementTree(root)
        tree.write("addons.xml", encoding="utf-8", xml_declaration=True)
        
        try:
            with open("addons.xml", "rb") as f:
                md5 = hashlib.md5(f.read()).hexdigest()
            with open("addons.xml.md5", "w") as f:
                f.write(md5)
            print("-> Fișierele addons.xml și addons.xml.md5 au fost create/actualizate.")
        except Exception as e:
            print(f"EROARE la generarea md5: {e}")

    def _generate_zip_files(self):
        print("\n--- Generare arhive .zip ---")
        for addon_id in self.addons:
            addon_xml_path = os.path.join(addon_id, "addon.xml")
            
            try:
                root = ET.parse(addon_xml_path).getroot()
                version = root.get("version")
                zip_filename = f"{addon_id}-{version}.zip"

                print(f"-> Se creează arhiva plată: {zip_filename}")
                
                with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
                    for base, dirs, files in os.walk(addon_id):
                        for file in files:
                            file_path = os.path.join(base, file)
                            # --- ACEASTA ESTE LINIA MODIFICATĂ ---
                            archive_path = os.path.relpath(file_path, addon_id)
                            # ------------------------------------
                            zf.write(file_path, archive_path)
            
            except Exception as e:
                print(f"  -> EROARE la crearea arhivei pentru {addon_id}: {e}")

if __name__ == "__main__":
    Generator()