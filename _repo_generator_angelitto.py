""" 
    Put this script in the root folder of your repo and it will
    zip up all addon folders, create a new zip in your zips folder
    and then update the md5 and addons.xml file
"""

import os
import shutil
import hashlib
import zipfile
import re
import copy
from xml.etree import ElementTree

SCRIPT_VERSION = 8
# Am adaugat "all" in lista pentru a scana si acel folder
KODI_VERSIONS = ["krypton", "leia", "matrix", "nexusrepo", "omega", "repo", "all"]
IGNORE = [
    ".git",
    ".github",
    ".gitignore",
    ".DS_Store",
    "thumbs.db",
    ".idea",
    "venv",
]
# Numele repoului tau curent
MAIN_REPO_ID = "repository.angelitto"


def _setup_colors():
    color = os.system("color")
    console = 0
    if os.name == 'nt':
        from ctypes import windll
        k = windll.kernel32
        console = k.SetConsoleMode(k.GetStdHandle(-11), 7)
    return color == 1 or console == 1


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
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if num < 1024.0:
            return "%3.1f %s" % (num, x)
        num /= 1024.0


class Generator:
    def __init__(self, release):
        self.release_path = release
        self.zips_path = os.path.join(self.release_path, "zips")
        addons_xml_path = os.path.join(self.zips_path, "addons.xml")
        md5_path = os.path.join(self.zips_path, "addons.xml.md5")

        if not os.path.exists(self.zips_path):
            os.makedirs(self.zips_path)

        self._remove_binaries()

        if self._generate_addons_file(addons_xml_path):
            print(
                "Successfully updated {}".format(color_text(addons_xml_path, 'yellow'))
            )

            if self._generate_md5_file(addons_xml_path, md5_path):
                print("Successfully updated {}".format(color_text(md5_path, 'yellow')))

    def _remove_binaries(self):
        for parent, dirnames, filenames in os.walk(self.release_path):
            for fn in filenames:
                if fn.lower().endswith("pyo") or fn.lower().endswith("pyc"):
                    compiled = os.path.join(parent, fn)
                    try:
                        os.remove(compiled)
                        print("Removed compiled python file: {}".format(color_text(compiled, 'green')))
                    except:
                        print("Failed to remove compiled python file: {}".format(color_text(compiled, 'red')))
            for dir in dirnames:
                if "pycache" in dir.lower():
                    compiled = os.path.join(parent, dir)
                    try:
                        shutil.rmtree(compiled)
                        print("Removed __pycache__ cache folder: {}".format(color_text(compiled, 'green')))
                    except:
                        print("Failed to remove __pycache__ cache folder:  {}".format(color_text(compiled, 'red')))

    def _create_zip(self, folder, addon_id, version):
        addon_folder = os.path.join(self.release_path, folder)
        zip_folder = os.path.join(self.zips_path, addon_id)
        if not os.path.exists(zip_folder):
            os.makedirs(zip_folder)

        zip_name = "{0}-{1}.zip".format(addon_id, version)
        final_zip = os.path.join(zip_folder, zip_name)
        
        # Sterge orice alt fisier .zip din acest folder care nu este versiunea curenta
        for f in os.listdir(zip_folder):
            if f.endswith(".zip") and f != zip_name:
                try:
                    os.remove(os.path.join(zip_folder, f))
                    print("Sters versiune veche: {} ({})".format(color_text(f, 'red'), addon_id))
                except:
                    pass

        # Daca e repo-ul principal, fortam stergerea zipului curent ca sa il recream proaspat
        if addon_id == MAIN_REPO_ID and os.path.exists(final_zip):
            try:
                os.remove(final_zip)
            except:
                pass

        if not os.path.exists(final_zip):
            zip = zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED)
            root_len = len(os.path.dirname(os.path.abspath(addon_folder)))

            for root, dirs, files in os.walk(addon_folder):
                for i in IGNORE:
                    if i in dirs:
                        try:
                            dirs.remove(i)
                        except:
                            pass
                    for f in files:
                        if f.startswith(i):
                            try:
                                files.remove(f)
                            except:
                                pass

                archive_root = os.path.abspath(root)[root_len:]

                for f in files:
                    fullpath = os.path.join(root, f)
                    archive_name = os.path.join(archive_root, f)
                    zip.write(fullpath, archive_name, zipfile.ZIP_DEFLATED)

            zip.close()
            size = convert_bytes(os.path.getsize(final_zip))
            print(
                "Zip created for {} ({}) - {}".format(
                    color_text(addon_id, 'cyan'),
                    color_text(version, 'green'),
                    color_text(size, 'yellow'),
                )
            )

    def _platforms(self, folder):
        root = os.path.join(self.release_path, folder, "platforms")
        if not os.path.isdir(root):
            return []
        return sorted(
            d for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d))
        )

    @staticmethod
    def _is_metadata_extension(ext):
        return ext.get("point") in ("xbmc.addon.metadata", "kodi.addon.metadata")

    @staticmethod
    def _entry_platform(entry):
        for ext in entry.findall("extension"):
            if Generator._is_metadata_extension(ext):
                node = ext.find("platform")
                if node is not None and node.text:
                    return node.text.strip()
        return ""

    def _platform_manifest(self, addon_root, platform):
        manifest = copy.deepcopy(addon_root)
        os_name = platform.split("-", 1)[0]
        for ext in manifest.findall("extension"):
            for attr in list(ext.attrib):
                if attr.startswith("library_") and not attr.endswith("_" + os_name):
                    del ext.attrib[attr]
            if self._is_metadata_extension(ext):
                node = ext.find("platform")
                if node is None:
                    node = ElementTree.SubElement(ext, "platform")
                node.text = platform
        return manifest

    def _entry_manifest(self, addon_root, addon_id, version, platform):
        manifest = self._platform_manifest(addon_root, platform)
        for ext in manifest.findall("extension"):
            if self._is_metadata_extension(ext):
                path = ElementTree.SubElement(ext, "path")
                path.text = "{}+{}/{}-{}.zip".format(addon_id, platform, addon_id, version)
        return manifest

    def _platform_manifest_text(self, folder, platform):
        """Source addon.xml for one platform, with its original formatting."""
        path = os.path.join(self.release_path, folder, "addon.xml")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        os_name = platform.split("-", 1)[0]

        def _strip_libraries(match):
            tag = match.group(0)

            def _keep(attr_match):
                name = attr_match.group(1)
                return attr_match.group(0) if name == os_name else ""

            return re.sub(r'\s*library_([A-Za-z0-9]+)="[^"]*"', _keep, tag)

        text = re.sub(r'<extension\b[^>]*\bpoint="kodi\.vfs"[^>]*>', _strip_libraries, text)
        text = re.sub(r'<platform>[^<]*</platform>',
                      '<platform>%s</platform>' % platform, text, count=1)
        return text.encode("utf-8")

    def _create_platform_zip(self, folder, addon_id, version, platform):
        package_id = "{}+{}".format(addon_id, platform)
        zip_folder = os.path.join(self.zips_path, package_id)
        if not os.path.exists(zip_folder):
            os.makedirs(zip_folder)

        zip_name = "{}-{}.zip".format(addon_id, version)
        final_zip = os.path.join(zip_folder, zip_name)

        for f in os.listdir(zip_folder):
            if f.endswith(".zip") and f != zip_name:
                try:
                    os.remove(os.path.join(zip_folder, f))
                    print("Sters versiune veche: {} ({})".format(color_text(f, 'red'), package_id))
                except:
                    pass

        if os.path.exists(final_zip):
            try:
                os.remove(final_zip)
            except:
                pass

        addon_folder = os.path.join(self.release_path, folder)
        platform_folder = os.path.join(addon_folder, "platforms", platform)
        xml_bytes = self._platform_manifest_text(folder, platform)

        with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as zip:
            for root, dirs, files in os.walk(addon_folder):
                if "platforms" in dirs:
                    dirs.remove("platforms")
                for i in IGNORE:
                    if i in dirs:
                        dirs.remove(i)
                    files[:] = [f for f in files if not f.startswith(i)]

                rel_root = os.path.relpath(root, addon_folder)
                for f in files:
                    fullpath = os.path.join(root, f)
                    if rel_root == ".":
                        archive_name = "{}/{}".format(addon_id, f)
                    else:
                        archive_name = "{}/{}/{}".format(
                            addon_id, rel_root.replace(os.sep, "/"), f
                        )
                    if rel_root == "." and f == "addon.xml":
                        zip.writestr(archive_name, xml_bytes)
                    else:
                        zip.write(fullpath, archive_name, zipfile.ZIP_DEFLATED)

            for root, dirs, files in os.walk(platform_folder):
                rel_root = os.path.relpath(root, platform_folder)
                for f in files:
                    fullpath = os.path.join(root, f)
                    if rel_root == ".":
                        archive_name = "{}/{}".format(addon_id, f)
                    else:
                        archive_name = "{}/{}/{}".format(
                            addon_id, rel_root.replace(os.sep, "/"), f
                        )
                    zip.write(fullpath, archive_name, zipfile.ZIP_DEFLATED)

        size = convert_bytes(os.path.getsize(final_zip))
        print(
            "Zip created for {} ({}) - {}".format(
                color_text(package_id, 'cyan'),
                color_text(version, 'green'),
                color_text(size, 'yellow'),
            )
        )

    def _update_platform_packages(self, addons_root, folder, addon_root, addon_id, version, platforms):
        changed = False
        wanted = set(platforms)

        for entry in list(addons_root.findall("addon")):
            if entry.get("id") == addon_id and self._entry_platform(entry) not in wanted:
                addons_root.remove(entry)
                changed = True
                print(
                    "Sters intrare veche pentru {} (platforma: {})".format(
                        color_text(addon_id, 'cyan'),
                        self._entry_platform(entry) or "nespecificata",
                    )
                )

        for platform in platforms:
            existing = None
            for entry in addons_root.findall("addon"):
                if entry.get("id") == addon_id and self._entry_platform(entry) == platform:
                    existing = entry
                    break

            if existing is not None and existing.get("version") == version:
                continue

            manifest = self._entry_manifest(addon_root, addon_id, version, platform)
            if existing is not None:
                index = list(addons_root).index(existing)
                addons_root.remove(existing)
                addons_root.insert(index, manifest)
            else:
                addons_root.append(manifest)

            self._create_platform_zip(folder, addon_id, version, platform)
            self._copy_meta_files(
                addon_id,
                os.path.join(self.zips_path, "{}+{}".format(addon_id, platform)),
                source_folder=folder,
                manifest_bytes=self._platform_manifest_text(folder, platform),
            )
            changed = True

        return changed

    def _copy_meta_files(self, addon_id, addon_folder, source_folder=None, manifest=None,
                         manifest_bytes=None):
        source_id = source_folder or addon_id
        try:
            if manifest is not None:
                root = manifest
            elif manifest_bytes is not None:
                root = ElementTree.fromstring(manifest_bytes.decode("utf-8"))
            else:
                xml_path = os.path.join(self.release_path, source_id, "addon.xml")
                with open(xml_path, "r", encoding="utf-8") as f:
                    xml_content = f.read().strip()
                root = ElementTree.fromstring(xml_content)
        except Exception as e:
            print("Eroare la citirea addon.xml pentru meta files: {}".format(e))
            return

        copyfiles = []
        if manifest is None and manifest_bytes is None:
            copyfiles.append("addon.xml")
        for ext in root.findall("extension"):
            if ext.get("point") in ["xbmc.addon.metadata", "kodi.addon.metadata"]:
                assets = ext.find("assets")
                if assets is None:
                    continue
                for art in [a for a in assets if a.text]:
                    copyfiles.append(os.path.normpath(art.text))

        src_folder = os.path.join(self.release_path, source_id)

        if manifest is not None or manifest_bytes is not None:
            if not os.path.exists(addon_folder):
                os.makedirs(addon_folder)
            if manifest_bytes is None:
                manifest_bytes = ElementTree.tostring(manifest, encoding="utf-8",
                                                      xml_declaration=True)
            with open(os.path.join(addon_folder, "addon.xml"), "wb") as f:
                f.write(manifest_bytes)

        for file in copyfiles:
            addon_path = os.path.join(src_folder, file)
            if not os.path.exists(addon_path):
                continue

            zips_path = os.path.join(addon_folder, file)
            asset_path = os.path.split(zips_path)[0]
            if not os.path.exists(asset_path):
                os.makedirs(asset_path)

            shutil.copy(addon_path, zips_path)

    def _get_file_hash(self, filepath):
        try:
            with open(filepath, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None

    def _update_root_files(self, addon_id, version):
        zip_name = "{}-{}.zip".format(addon_id, version)
        src_zip = os.path.join(self.zips_path, addon_id, zip_name)
        dst_zip = zip_name

        if not os.path.exists(src_zip):
            return

        should_copy = False
        if not os.path.exists(dst_zip):
            should_copy = True
        else:
            src_hash = self._get_file_hash(src_zip)
            dst_hash = self._get_file_hash(dst_zip)
            if src_hash != dst_hash:
                should_copy = True
                print("Detectat modificari in continutul arhivei {} (hash diferit).".format(color_text(addon_id, 'cyan')))

        if should_copy:
            for f in os.listdir("."):
                if f.startswith(addon_id) and f.endswith(".zip") and f != zip_name:
                    try:
                        os.remove(f)
                        print("Sters zip vechi din root: {}".format(color_text(f, 'red')))
                    except:
                        pass
            
            shutil.copy(src_zip, dst_zip)
            print("Copiat/Actualizat {} in root.".format(color_text(zip_name, 'green')))
            self._update_html_file(zip_name)

    def _update_html_file(self, new_zip_name):
        html_file = "index.html"
        if not os.path.exists(html_file):
            print("Fisierul {} nu a fost gasit.".format(color_text(html_file, 'red')))
            return

        try:
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            escaped_id = MAIN_REPO_ID.replace('.', r'\.')
            pattern = r'<a href="{}-.*?\.zip">{}-.*?\.zip</a>'.format(escaped_id, escaped_id)
            replacement = '<a href="{}">{}</a>'.format(new_zip_name, new_zip_name)
            
            new_content, count = re.subn(pattern, replacement, content)

            if count > 0:
                if new_content != content:
                    with open(html_file, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print("Actualizat link in {}.".format(color_text(html_file, 'yellow')))
            else:
                pass 

        except Exception as e:
            print("Eroare la actualizarea index.html: {}".format(e))

    def _generate_addons_file(self, addons_xml_path):
        if not os.path.exists(addons_xml_path):
            addons_root = ElementTree.Element('addons')
            addons_xml = ElementTree.ElementTree(addons_root)
        else:
            addons_xml = ElementTree.parse(addons_xml_path)
            addons_root = addons_xml.getroot()

        folders = [
            i
            for i in os.listdir(self.release_path)
            if os.path.isdir(os.path.join(self.release_path, i))
            and i != "zips"
            and not i.startswith(".")
            and os.path.exists(os.path.join(self.release_path, i, "addon.xml"))
        ]

        addon_xpath = "addon[@id='{}']"
        changed = False
        for addon in folders:
            try:
                addon_xml_path = os.path.join(self.release_path, addon, "addon.xml")
                
                # --- FIX MAJOR: Citim fisierul ca text si stergem caracterele invizibile (BOM/Whitespace) ---
                with open(addon_xml_path, "r", encoding="utf-8") as f:
                    xml_content = f.read().strip()
                
                # Parsam string-ul curatat
                addon_root = ElementTree.fromstring(xml_content)
                # --------------------------------------------------------------------------------------------

                id = addon_root.get('id')
                version = addon_root.get('version')

                updated = False
                addon_entry = addons_root.find(addon_xpath.format(id))
                
                force_update = (id == MAIN_REPO_ID)

                platforms = self._platforms(addon)
                if platforms:
                    if self._update_platform_packages(
                        addons_root, addon, addon_root, id, version, platforms
                    ):
                        changed = True
                    continue

                if addon_entry is not None and addon_entry.get('version') != version:
                    index = addons_root.findall('addon').index(addon_entry)
                    addons_root.remove(addon_entry)
                    addons_root.insert(index, addon_root)
                    updated = True
                    changed = True
                elif addon_entry is None:
                    addons_root.append(addon_root)
                    updated = True
                    changed = True
                
                if updated or force_update:
                    self._create_zip(addon, id, version)
                    self._copy_meta_files(addon, os.path.join(self.zips_path, id))
                    
                    if id == MAIN_REPO_ID:
                        self._update_root_files(id, version)

            except Exception as e:
                print(
                    "Excluding {}: {}".format(
                        color_text(addon, 'yellow'), color_text(e, 'red')
                    )
                )

        if changed:
            addons_root[:] = sorted(addons_root, key=lambda addon: addon.get('id'))
            try:
                addons_xml.write(
                    addons_xml_path, encoding="utf-8", xml_declaration=True
                )
                return changed
            except Exception as e:
                print(
                    "An error occurred updating {}!\n{}".format(
                        color_text(addons_xml_path, 'yellow'), color_text(e, 'red')
                    )
                )

    def _generate_md5_file(self, addons_xml_path, md5_path):
        try:
            m = hashlib.md5(
                open(addons_xml_path, "r", encoding="utf-8").read().encode("utf-8")
            ).hexdigest()
            self._save_file(m, file=md5_path)
            return True
        except Exception as e:
            print(
                "An error occurred updating {}!\n{}".format(
                    color_text(md5_path, 'yellow'), color_text(e, 'red')
                )
            )

    def _save_file(self, data, file):
        try:
            open(file, "w").write(data)
        except Exception as e:
            print(
                "An error occurred saving {}!\n{}".format(
                    color_text(file, 'yellow'), color_text(e, 'red')
                )
            )

if __name__ == "__main__":
    for release in [r for r in KODI_VERSIONS if os.path.exists(r)]:
        print(release)
        Generator(release)
    print("\n" + "="*40)
    print(color_text("Procesul de generare a repository-ului s-a încheiat.", "green"))
    print("="*40)
    input("\nApasă tasta ENTER pentru a închide fereastra...")