# -*- coding: utf-8 -*-

import os
import hashlib
import zipfile
import xml.etree.ElementTree as ET
import shutil

class Generator:
    """
        Generates a professional repository with the universally correct zip structure for all addons.
        (v10 - Universal Structure)
    """
    def __init__(self):
        self.zips_folder = 'zips'
        print(f"--- Încep generarea repository-ului (v10 - Structura Universală Corectă) ---")
        
        # ==================== MODIFICARE CHEIE: CURATARE AUTOMATA ====================
        print("\n--- Pasul 1: Curățare fișiere/foldere vechi ---")
        
        # Sterge folderul zips, daca exista
        if os.path.exists(self.zips_folder):
            shutil.rmtree(self.zips_folder)
            print(f"-> Am șters folderul '{self.zips_folder}' vechi.")
            
        # Sterge addons.xml, daca exista
        if os.path.exists("addons.xml"):
            os.remove("addons.xml")
            print("-> Am șters addons.xml vechi.")
            
        # Sterge addons.xml.md5, daca exista
        if os.path.exists("addons.xml.md5"):
            os.remove("addons.xml.md5")
            print("-> Am șters addons.xml.md5 vechi.")
        
        print("-> Curățare finalizată.")
        # ==================== SFARSIT MODIFICARE ====================

        # Cream din nou folderul zips, acum fiind siguri ca este gol
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
            if os.path.isdir(item) and item not in ['.git', self.zips_folder] and os.path.exists(os.path.join(item, 'addon.xml')):
                addon_list.append(item)
        return addon_list

    def _generate_addons_file(self):
        print("\n--- Pasul 2: Generare addons.xml și md5 ---")
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

    def _generate_zip_files(self):
        print(f"\n--- Pasul 3: Generare arhive .zip cu structură universală ---")
        for addon_id in self.addons:
            try:
                addon_zip_folder = os.path.join(self.zips_folder, addon_id)
                if not os.path.exists(addon_zip_folder):
                    os.makedirs(addon_zip_folder)

                root = ET.parse(os.path.join(addon_id, "addon.xml")).getroot()
                version = root.get("version")
                zip_filename = os.path.join(addon_zip_folder, f"{addon_id}-{version}.zip")
                
                print(f"-> Se creează arhiva: {os.path.relpath(zip_filename)}")
                
                with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
                    for base, dirs, files in os.walk(addon_id):
                        for file in files:
                            file_path = os.path.join(base, file)
                            # --- ACEASTA ESTE LINIA CHEIE, REVENITĂ LA VERSIUNEA SIMPLĂ ȘI CORECTĂ ---
                            archive_path = os.path.relpath(file_path, os.path.join(addon_id, '..'))
                            # ------------------------------------------------------------------
                            zf.write(file_path, archive_path)
            except Exception as e:
                print(f"  -> EROARE la crearea arhivei pentru {addon_id}: {e}")

if __name__ == "__main__":
    Generator()
    input("\nApasa orice tasta pentru a inchide fereastra...")