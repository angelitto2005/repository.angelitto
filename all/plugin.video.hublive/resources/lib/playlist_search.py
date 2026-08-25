import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import zipfile
from urllib.parse import urljoin, urlparse

import requests
import xbmc
import xbmcaddon
import xbmcvfs


_INDEX_ARCHIVE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data",
    "playlist_search.db.zip",
)
_DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/unicsuc/ratb/main/"
    "search-index/manifest.json"
)
_RAW_BASE_URL = "https://raw.githubusercontent.com/unicsuc/ratb/main"
_REPO_CONTENTS_URL = "https://api.github.com/repos/unicsuc/ratb/contents"
_REFRESH_RETRY_TTL = 1800
_DOWNLOAD_TIMEOUT = (5, 20)
_INDEX_DOWNLOAD_TIMEOUT = (5, 120)
_MAX_RESULTS = 2000
_INDEX_SCHEMA_VERSION = "3-catalog-sqlite"
_COMPATIBLE_SCHEMA_VERSIONS = {
    "2-standard-sqlite",
    _INDEX_SCHEMA_VERSION,
}
_STREAM_RE = re.compile(r"[?&]stream=(\d+)")
_SERVER_NAME_RE = re.compile(
    r"^Server\s+(\d+)(?:\s+.*)?$",
    re.IGNORECASE,
)
_index_ready = False


def _profile_folder():
    profile = xbmcaddon.Addon().getAddonInfo("profile")
    try:
        profile = xbmcvfs.translatePath(profile)
    except Exception:
        profile = xbmc.translatePath(profile)
    folder = os.path.join(profile, "playlist_search")
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder


def _index_file():
    return os.path.join(_profile_folder(), "playlist_search.db")


def _manifest_file():
    return os.path.join(_profile_folder(), "manifest.json")


def _remote_state_file():
    return os.path.join(_profile_folder(), "remote_state.json")


def _load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_json_file(path, value):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def _addon_setting(setting_id, default=""):
    try:
        value = xbmcaddon.Addon().getSetting(setting_id)
        return value if value != "" else default
    except Exception:
        return default


def _manifest_url():
    return _addon_setting("playlist_index_url", _DEFAULT_MANIFEST_URL).strip()


def _check_interval_seconds():
    try:
        hours = float(_addon_setting("playlist_index_check_hours", "12"))
    except (TypeError, ValueError):
        hours = 12
    return max(1, hours) * 3600


def _auto_update_enabled():
    value = _addon_setting("playlist_index_auto_update", "true")
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def _has_current_schema(index_file):
    if not os.path.exists(index_file):
        return False
    try:
        connection = sqlite3.connect(index_file)
        try:
            row = connection.execute(
                "SELECT value FROM build_metadata WHERE key = 'schema_version'"
            ).fetchone()
            return bool(row and row[0] in _COMPATIBLE_SCHEMA_VERSIONS)
        finally:
            connection.close()
    except Exception:
        return False


def _validate_index(index_file, manifest=None):
    if not _has_current_schema(index_file):
        raise RuntimeError("Schema indexului nu este compatibilă.")
    connection = sqlite3.connect(index_file)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("Verificarea de integritate SQLite a eșuat.")
        metadata = dict(
            connection.execute("SELECT key, value FROM build_metadata").fetchall()
        )
        if metadata.get("schema_version") not in _COMPATIBLE_SCHEMA_VERSIONS:
            raise RuntimeError("Versiunea schemei SQLite nu corespunde.")
        if manifest:
            expected_channels = int(manifest.get("channel_count") or 0)
            expected_playlists = int(manifest.get("playlist_count") or 0)
            actual_channels = connection.execute(
                "SELECT count(*) FROM channels"
            ).fetchone()[0]
            actual_playlists = connection.execute(
                "SELECT count(*) FROM playlist_metadata"
            ).fetchone()[0]
            expected_categories = int(manifest.get("category_count") or 0)
            if expected_channels and actual_channels != expected_channels:
                raise RuntimeError("Numărul canalelor nu corespunde manifestului.")
            if expected_playlists and actual_playlists != expected_playlists:
                raise RuntimeError("Numărul playlisturilor nu corespunde manifestului.")
            if expected_categories:
                actual_categories = connection.execute(
                    "SELECT count(*) FROM categories"
                ).fetchone()[0]
                if actual_categories != expected_categories:
                    raise RuntimeError(
                        "Numărul categoriilor nu corespunde manifestului."
                    )
        return metadata
    finally:
        connection.close()


def _extract_index_archive(archive_path, target_path, manifest=None):
    temp_target = f"{target_path}.new"
    if os.path.exists(temp_target):
        os.remove(temp_target)
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = archive.namelist()
            if members != ["playlist_search.db"]:
                raise RuntimeError("Arhiva indexului are un conținut neașteptat.")
            with archive.open("playlist_search.db", "r") as source, open(
                temp_target, "wb"
            ) as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)
        _validate_index(temp_target, manifest)
        os.replace(temp_target, target_path)
    except Exception:
        if os.path.exists(temp_target):
            os.remove(temp_target)
        raise


def _install_bundled_index():
    target = _index_file()
    if _has_current_schema(target):
        return target
    if not os.path.exists(_INDEX_ARCHIVE):
        return None
    _extract_index_archive(_INDEX_ARCHIVE, target)
    xbmc.log(
        "[PlaylistSearch] Installed bundled fallback index",
        level=xbmc.LOGINFO,
    )
    return target


def _validate_manifest(manifest, manifest_url):
    if not isinstance(manifest, dict):
        raise RuntimeError("Manifestul indexului nu este un obiect JSON.")
    if manifest.get("schema_version") not in _COMPATIBLE_SCHEMA_VERSIONS:
        raise RuntimeError("Manifestul folosește o schemă incompatibilă.")
    try:
        archive_size = int(manifest.get("archive_size") or 0)
        channel_count = int(manifest.get("channel_count") or 0)
        playlist_count = int(manifest.get("playlist_count") or 0)
    except (TypeError, ValueError):
        raise RuntimeError("Manifestul conține valori numerice invalide.")
    archive_sha256 = (manifest.get("archive_sha256") or "").lower()
    if (
        archive_size <= 0
        or channel_count <= 0
        or playlist_count <= 0
        or not re.fullmatch(r"[0-9a-f]{64}", archive_sha256)
    ):
        raise RuntimeError("Manifestul indexului este incomplet.")
    archive_url = manifest.get("archive_url") or manifest.get("archive")
    if not archive_url:
        raise RuntimeError("Manifestul nu conține URL-ul arhivei.")
    manifest = dict(manifest)
    manifest["archive_url"] = urljoin(manifest_url, archive_url)
    manifest["archive_size"] = archive_size
    manifest["channel_count"] = channel_count
    manifest["playlist_count"] = playlist_count
    manifest["category_count"] = int(manifest.get("category_count") or 0)
    manifest["archive_sha256"] = archive_sha256
    return manifest


def _download_archive(http, manifest, progress_callback=None):
    archive_path = os.path.join(_profile_folder(), "playlist_search.db.zip.part")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        response = http.get(
            manifest["archive_url"],
            headers={"User-Agent": "HubLive-Playlist-Index"},
            timeout=_INDEX_DOWNLOAD_TIMEOUT,
            stream=True,
        )
        response.raise_for_status()
        with open(archive_path, "wb") as destination:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                destination.write(chunk)
                digest.update(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    percent = min(
                        90,
                        int((downloaded / manifest["archive_size"]) * 90),
                    )
                    progress_callback(percent, "Se descarcă indexul ratb...")
        if downloaded != manifest["archive_size"]:
            raise RuntimeError("Dimensiunea arhivei descărcate nu corespunde.")
        if digest.hexdigest().lower() != manifest["archive_sha256"]:
            raise RuntimeError("SHA-256 al arhivei descărcate nu corespunde.")
        return archive_path
    except Exception as exc:
        if os.path.exists(archive_path):
            os.remove(archive_path)
        if isinstance(exc, InterruptedError):
            raise
        raise RuntimeError(f"Descărcarea indexului a eșuat: {exc}")


def update_playlist_index(
    force=False,
    progress_callback=None,
    session=None,
):
    global _index_ready
    manifest_url = _manifest_url()
    if not manifest_url:
        raise RuntimeError("URL-ul manifestului indexului nu este configurat.")

    target = _index_file()
    has_local_index = _has_current_schema(target)
    state = _load_json_file(_remote_state_file())
    now = time.time()
    try:
        checked_at = float(state.get("checked_at", 0) or 0)
    except (TypeError, ValueError):
        checked_at = 0
    if (
        not force
        and has_local_index
        and now - checked_at < _check_interval_seconds()
    ):
        return {
            "updated": False,
            "checked": False,
            "manifest": _load_json_file(_manifest_file()),
        }

    http = session or requests.Session()
    headers = {
        "Accept": "application/json",
        "User-Agent": "HubLive-Playlist-Index",
    }
    if not force and state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if not force and state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    if progress_callback:
        progress_callback(0, "Se verifică manifestul indexului ratb...")

    response = http.get(
        manifest_url,
        headers=headers,
        timeout=_DOWNLOAD_TIMEOUT,
    )
    if response.status_code == 304:
        state["checked_at"] = now
        _save_json_file(_remote_state_file(), state)
        return {
            "updated": False,
            "checked": True,
            "manifest": _load_json_file(_manifest_file()),
        }
    response.raise_for_status()
    manifest = _validate_manifest(response.json(), manifest_url)
    local_manifest = _load_json_file(_manifest_file())

    if (
        has_local_index
        and local_manifest.get("archive_sha256") == manifest["archive_sha256"]
    ):
        state.update(
            {
                "checked_at": now,
                "etag": response.headers.get("ETag", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "archive_sha256": manifest["archive_sha256"],
            }
        )
        _save_json_file(_manifest_file(), manifest)
        _save_json_file(_remote_state_file(), state)
        return {"updated": False, "checked": True, "manifest": manifest}

    archive_path = _download_archive(http, manifest, progress_callback)
    try:
        if progress_callback:
            progress_callback(92, "Se validează indexul ratb...")
        _extract_index_archive(archive_path, target, manifest)
        _save_json_file(_manifest_file(), manifest)
        state.update(
            {
                "checked_at": now,
                "etag": response.headers.get("ETag", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "archive_sha256": manifest["archive_sha256"],
            }
        )
        _save_json_file(_remote_state_file(), state)
    finally:
        if os.path.exists(archive_path):
            os.remove(archive_path)

    _index_ready = True
    if progress_callback:
        progress_callback(100, "Indexul ratb a fost actualizat.")
    return {"updated": True, "checked": True, "manifest": manifest}


def _ensure_index():
    global _index_ready
    target = _index_file()
    if _index_ready and _has_current_schema(target):
        return target

    try:
        _install_bundled_index()
    except Exception as exc:
        xbmc.log(
            f"[PlaylistSearch] Bundled index install failed: {exc}",
            level=xbmc.LOGWARNING,
        )

    should_update = _auto_update_enabled() or not _has_current_schema(target)
    if should_update:
        try:
            update_playlist_index(force=False)
        except Exception as exc:
            xbmc.log(
                f"[PlaylistSearch] Remote index update failed: {exc}",
                level=xbmc.LOGWARNING,
            )

    if _has_current_schema(target):
        _index_ready = True
        return target
    xbmc.log(
        "[PlaylistSearch] No valid local or remote search index is available",
        level=xbmc.LOGWARNING,
    )
    return None


def _normalize_portal(url):
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    port = parsed.port
    if port in (None, 80) and parsed.scheme.lower() == "http":
        return host
    if port in (None, 443) and parsed.scheme.lower() == "https":
        return host
    return f"{host}:{port}" if port else host


def _portal_host(url):
    return (urlparse((url or "").strip()).hostname or "").lower()


def _server_key(server):
    return (
        server.get("id") or "",
        server.get("name") or "",
        (server.get("portal_url") or "").rstrip("/"),
    )


def _search_text(query):
    return " ".join((query or "").casefold().split())


def _load_metadata(connection):
    rows = connection.execute(
        """
        SELECT playlist, server_id, server_name, portal_url, portal_key, blob_sha
        FROM playlist_metadata
        """
    ).fetchall()
    return {
        row[0]: {
            "playlist": row[0],
            "server_id": row[1],
            "server_name": row[2],
            "portal_url": row[3],
            "portal_key": row[4],
            "blob_sha": row[5],
        }
        for row in rows
    }


def _playlist_for_server_name(server_name):
    match = _SERVER_NAME_RE.match((server_name or "").strip())
    if not match:
        return None
    return f"server_{int(match.group(1))}.m3u"


def _find_server(server_id, servers):
    for server in servers or []:
        if (server.get("id") or "") == (server_id or ""):
            return server
    return None


def _has_catalog_schema(connection):
    row = connection.execute(
        "SELECT value FROM build_metadata WHERE key = 'schema_version'"
    ).fetchone()
    if not row or row[0] != _INDEX_SCHEMA_VERSION:
        return False
    required_tables = {"categories", "channels", "logos", "playlist_metadata"}
    tables = {
        item[0]
        for item in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    return required_tables.issubset(tables)


def _validated_catalog_playlist(connection, server):
    if not server:
        return None
    playlist = _playlist_for_server_name(server.get("name"))
    if not playlist:
        return None
    manifest = _load_metadata(connection).get(playlist)
    if not manifest:
        return None
    expected_key = (
        manifest["server_id"],
        manifest["server_name"],
        manifest["portal_url"],
    )
    return playlist if _server_key(server) == expected_key else None


def get_playlist_categories(server_id, servers):
    index_file = _ensure_index()
    server = _find_server(server_id, servers)
    if not index_file or not server:
        return []

    connection = sqlite3.connect(index_file)
    try:
        if not _has_catalog_schema(connection):
            return []
        playlist = _validated_catalog_playlist(connection, server)
        if not playlist:
            return []
        rows = connection.execute(
            """
            SELECT category_id, title, channel_count
            FROM categories
            WHERE playlist = ?
            ORDER BY position
            """,
            (playlist,),
        ).fetchall()
        return [
            {
                "id": category_id,
                "title": title,
                "channel_count": channel_count,
                "_source": "ratb",
            }
            for category_id, title, channel_count in rows
        ]
    except Exception as exc:
        xbmc.log(
            f"[PlaylistCatalog] Category query failed for {server_id}: {exc}",
            level=xbmc.LOGWARNING,
        )
        return []
    finally:
        connection.close()


def get_playlist_channels(server_id, category_id, servers):
    index_file = _ensure_index()
    server = _find_server(server_id, servers)
    if not index_file or not server or not str(category_id).startswith("ratb:"):
        return []

    connection = sqlite3.connect(index_file)
    try:
        if not _has_catalog_schema(connection):
            return []
        playlist = _validated_catalog_playlist(connection, server)
        if not playlist:
            return []
        rows = connection.execute(
            """
            SELECT c.stream_id, c.name, COALESCE(l.url, ''), c.tvg_id
            FROM channels AS c
            LEFT JOIN logos AS l ON l.logo_id = c.logo_id
            WHERE c.playlist = ? AND c.category_id = ?
            ORDER BY c.position
            """,
            (playlist, category_id),
        ).fetchall()
        return [
            {
                "id": stream_id,
                "name": name,
                "logo": logo,
                "tvg_id": tvg_id,
                "cmd": "",
                "tv_genre_id": category_id,
                "_source": "ratb",
            }
            for stream_id, name, logo, tvg_id in rows
        ]
    except Exception as exc:
        xbmc.log(
            f"[PlaylistCatalog] Channel query failed for "
            f"{server_id}/{category_id}: {exc}",
            level=xbmc.LOGWARNING,
        )
        return []
    finally:
        connection.close()


def _blob_sha(content):
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _override_paths(playlist):
    safe_name = os.path.basename(playlist)
    folder = _profile_folder()
    return (
        os.path.join(folder, f"override_{safe_name}"),
        os.path.join(folder, f"override_{safe_name}.state"),
    )


def _load_override_state(playlist):
    _, state_file = _override_paths(playlist)
    try:
        if not os.path.exists(state_file):
            return {}
        state = {}
        with open(state_file, "r", encoding="utf-8") as handle:
            for line in handle:
                key, separator, value = line.rstrip("\n").partition("=")
                if separator:
                    state[key] = value
        return state
    except Exception:
        return {}


def _save_override_state(playlist, server, blob_sha, checked_at):
    _, state_file = _override_paths(playlist)
    temp_file = f"{state_file}.tmp"
    with open(temp_file, "w", encoding="utf-8") as handle:
        handle.write(f"server_id={server.get('id') or ''}\n")
        handle.write(f"server_name={server.get('name') or ''}\n")
        handle.write(f"portal_url={(server.get('portal_url') or '').rstrip('/')}\n")
        handle.write(f"blob_sha={blob_sha or ''}\n")
        handle.write(f"checked_at={checked_at}\n")
    os.replace(temp_file, state_file)


def _override_matches_server(playlist, server):
    playlist_file, _ = _override_paths(playlist)
    state = _load_override_state(playlist)
    actual = (
        state.get("server_id", ""),
        state.get("server_name", ""),
        state.get("portal_url", ""),
    )
    return os.path.exists(playlist_file) and actual == _server_key(server)


def _first_stream_host(text):
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(("http://", "https://")):
            return _portal_host(line)
    return ""


def _refresh_changed_playlist(playlist, server, base_blob_sha):
    playlist_file, _ = _override_paths(playlist)
    state = _load_override_state(playlist)
    now = time.time()
    try:
        checked_at = float(state.get("checked_at", 0) or 0)
    except (TypeError, ValueError):
        checked_at = 0

    if now - checked_at < _REFRESH_RETRY_TTL:
        return _override_matches_server(playlist, server)

    try:
        response = requests.get(
            f"{_RAW_BASE_URL}/{playlist}",
            timeout=_DOWNLOAD_TIMEOUT,
        )
        response.raise_for_status()
        content = response.content
        current_blob_sha = _blob_sha(content)
        playlist_host = _first_stream_host(
            content.decode("utf-8", errors="ignore")
        )
        server_host = _portal_host(server.get("portal_url"))

        if current_blob_sha == base_blob_sha or playlist_host != server_host:
            _save_override_state(playlist, server, current_blob_sha, now)
            xbmc.log(
                f"[PlaylistSearch] {playlist} disabled for {server.get('id')}: "
                "repository playlist does not match the changed server",
                level=xbmc.LOGWARNING,
            )
            return False

        temp_file = f"{playlist_file}.tmp"
        with open(temp_file, "wb") as handle:
            handle.write(content)
        os.replace(temp_file, playlist_file)
        _save_override_state(playlist, server, current_blob_sha, now)
        xbmc.log(
            f"[PlaylistSearch] Activated updated {playlist} for {server.get('id')}",
            level=xbmc.LOGINFO,
        )
        return True
    except Exception as exc:
        try:
            _save_override_state(playlist, server, "", now)
        except Exception:
            pass
        xbmc.log(
            f"[PlaylistSearch] Could not refresh {playlist}: {exc}",
            level=xbmc.LOGWARNING,
        )
        return False


def _parse_override_matches(playlist, query, server):
    playlist_file, _ = _override_paths(playlist)
    query_text = (query or "").casefold()
    results = []
    pending = None

    try:
        with open(playlist_file, "r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line.startswith("#EXTINF"):
                    pending = line
                    continue
                if not pending or not line or line.startswith("#"):
                    continue

                name = pending.rsplit(",", 1)[-1].strip()
                stream_match = _STREAM_RE.search(line)
                if stream_match and query_text in name.casefold():
                    results.append(
                        {
                            "id": stream_match.group(1),
                            "name": name,
                            "_server_id": server.get("id"),
                            "_server_name": server.get("name"),
                        }
                    )
                    if len(results) >= _MAX_RESULTS:
                        break
                pending = None
    except Exception as exc:
        xbmc.log(
            f"[PlaylistSearch] Failed to scan override {playlist}: {exc}",
            level=xbmc.LOGWARNING,
        )
        return []
    return results


def _create_standard_schema(connection):
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE channels(
            name TEXT NOT NULL,
            name_search TEXT NOT NULL,
            playlist TEXT NOT NULL,
            stream_id TEXT NOT NULL
        );
        CREATE INDEX idx_channels_playlist ON channels(playlist);
        CREATE TABLE playlist_metadata(
            playlist TEXT PRIMARY KEY,
            server_id TEXT NOT NULL,
            server_name TEXT NOT NULL,
            portal_url TEXT NOT NULL,
            portal_key TEXT NOT NULL,
            blob_sha TEXT NOT NULL
        );
        CREATE TABLE build_metadata(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def _insert_playlist_content(connection, playlist, content):
    text = content.decode("utf-8", errors="ignore")
    rows = []
    pending = None
    inserted = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXTINF"):
            pending = line
            continue
        if not pending or not line or line.startswith("#"):
            continue

        stream_match = _STREAM_RE.search(line)
        if stream_match:
            name = pending.rsplit(",", 1)[-1].strip()
            rows.append(
                (
                    name,
                    " ".join(name.casefold().split()),
                    playlist,
                    stream_match.group(1),
                )
            )
        pending = None

        if len(rows) >= 10000:
            connection.executemany(
                "INSERT INTO channels VALUES(?,?,?,?)", rows
            )
            inserted += len(rows)
            rows = []

    if rows:
        connection.executemany("INSERT INTO channels VALUES(?,?,?,?)", rows)
        inserted += len(rows)
    return inserted


def rebuild_playlist_index(
    servers,
    progress_callback=None,
    is_cancelled=None,
    session=None,
):
    global _index_ready
    current_index = _ensure_index()
    if not current_index:
        raise RuntimeError("Indexul de bază nu este disponibil.")

    http = session or requests.Session()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "HubLive-Playlist-Indexer",
    }
    response = http.get(
        _REPO_CONTENTS_URL,
        headers=headers,
        timeout=_DOWNLOAD_TIMEOUT,
    )
    response.raise_for_status()
    repo_items = response.json()
    if not isinstance(repo_items, list):
        raise RuntimeError("Răspuns GitHub invalid pentru lista de playlisturi.")

    server_by_number = {}
    for server in servers or []:
        match = _SERVER_NAME_RE.match((server.get("name") or "").strip())
        if match:
            server_by_number[int(match.group(1))] = server

    candidates = []
    for item in repo_items:
        name = item.get("name") or ""
        match = re.fullmatch(r"server_(\d+)\.m3u", name, re.IGNORECASE)
        if not match or item.get("type") != "file":
            continue
        server = server_by_number.get(int(match.group(1)))
        if server:
            candidates.append((name, item, server))
    candidates.sort(key=lambda entry: int(re.search(r"\d+", entry[0]).group()))

    temp_index = f"{current_index}.rebuild"
    if os.path.exists(temp_index):
        os.remove(temp_index)
    shutil.copy2(current_index, temp_index)

    connection = sqlite3.connect(temp_index)
    downloaded = 0
    reused = 0
    skipped = 0
    channel_count = 0
    active_playlists = set()
    try:
        metadata = _load_metadata(connection)
        total = len(candidates) or 1

        for position, (playlist, item, server) in enumerate(candidates, start=1):
            if is_cancelled and is_cancelled():
                raise InterruptedError("Reindexarea a fost anulată.")

            if progress_callback:
                progress_callback(
                    int(((position - 1) / total) * 100),
                    f"{playlist} ({position}/{len(candidates)})",
                )

            repo_sha = item.get("sha") or ""
            server_key = _server_key(server)
            existing = metadata.get(playlist)
            existing_key = (
                existing["server_id"],
                existing["server_name"],
                existing["portal_url"],
            ) if existing else None

            if (
                existing
                and existing["blob_sha"] == repo_sha
                and existing_key == server_key
            ):
                active_playlists.add(playlist)
                reused += 1
                continue

            connection.execute(
                "DELETE FROM channels WHERE playlist = ?", (playlist,)
            )
            connection.execute(
                "DELETE FROM playlist_metadata WHERE playlist = ?", (playlist,)
            )

            if existing and existing["blob_sha"] == repo_sha:
                skipped += 1
                continue

            download_url = item.get("download_url")
            if not download_url:
                skipped += 1
                continue

            playlist_response = http.get(
                download_url,
                headers={"User-Agent": headers["User-Agent"]},
                timeout=_DOWNLOAD_TIMEOUT,
            )
            playlist_response.raise_for_status()
            content = playlist_response.content
            if _first_stream_host(
                content.decode("utf-8", errors="ignore")
            ) != _portal_host(server.get("portal_url")):
                skipped += 1
                continue

            inserted = _insert_playlist_content(
                connection, playlist, content
            )
            if not inserted:
                skipped += 1
                continue

            normalized_url = (server.get("portal_url") or "").rstrip("/")
            connection.execute(
                "INSERT INTO playlist_metadata VALUES(?,?,?,?,?,?)",
                (
                    playlist,
                    server.get("id") or "",
                    server.get("name") or "",
                    normalized_url,
                    _normalize_portal(normalized_url),
                    repo_sha or _blob_sha(content),
                ),
            )
            active_playlists.add(playlist)
            downloaded += 1
            connection.commit()

        existing_playlists = {
            row[0]
            for row in connection.execute(
                "SELECT playlist FROM playlist_metadata"
            ).fetchall()
        }
        stale_playlists = existing_playlists - active_playlists
        for playlist in stale_playlists:
            connection.execute(
                "DELETE FROM channels WHERE playlist = ?", (playlist,)
            )
            connection.execute(
                "DELETE FROM playlist_metadata WHERE playlist = ?", (playlist,)
            )

        channel_count = connection.execute(
            "SELECT count(*) FROM channels"
        ).fetchone()[0]
        build_values = {
            "schema_version": _INDEX_SCHEMA_VERSION,
            "channel_count": str(channel_count),
            "playlist_count": str(len(active_playlists)),
            "updated_at": str(int(time.time())),
        }
        for key, value in build_values.items():
            connection.execute(
                "INSERT OR REPLACE INTO build_metadata VALUES(?,?)",
                (key, value),
            )
        connection.commit()

        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("Verificarea de integritate SQLite a eșuat.")
    except Exception:
        connection.close()
        if os.path.exists(temp_index):
            os.remove(temp_index)
        raise
    else:
        connection.close()

    os.replace(temp_index, current_index)
    _index_ready = True
    if progress_callback:
        progress_callback(100, "Indexul ratb a fost actualizat.")
    return {
        "playlists": len(active_playlists),
        "channels": channel_count,
        "downloaded": downloaded,
        "reused": reused,
        "skipped": skipped,
    }


def search_playlist_index(query, servers):
    index_file = _ensure_index()
    search_text = _search_text(query)
    if not index_file or not search_text:
        return [], set()

    server_id_counts = {}
    for server in servers or []:
        server_id = server.get("id") or ""
        server_id_counts[server_id] = server_id_counts.get(server_id, 0) + 1

    results = []
    covered_server_keys = set()
    connection = sqlite3.connect(index_file)
    try:
        metadata = _load_metadata(connection)
        valid_playlists = {}
        override_servers = []

        for server in servers or []:
            server_key = _server_key(server)
            server_id = server.get("id") or ""
            if not server_id or server_id_counts.get(server_id, 0) != 1:
                continue

            playlist = _playlist_for_server_name(server.get("name"))
            manifest = metadata.get(playlist)
            if not manifest:
                continue

            expected_key = (
                manifest["server_id"],
                manifest["server_name"],
                manifest["portal_url"],
            )
            if server_key == expected_key:
                valid_playlists[playlist] = server
                covered_server_keys.add(server_key)
                continue

            if _override_matches_server(playlist, server) or _refresh_changed_playlist(
                playlist, server, manifest["blob_sha"]
            ):
                override_servers.append((playlist, server))
                covered_server_keys.add(server_key)

        if valid_playlists:
            placeholders = ",".join("?" for _ in valid_playlists)
            params = [search_text]
            params.extend(valid_playlists)
            params.append(_MAX_RESULTS)
            rows = connection.execute(
                f"""
                SELECT name, playlist, stream_id
                FROM channels
                WHERE instr(name_search, ?) > 0
                  AND playlist IN ({placeholders})
                LIMIT ?
                """,
                params,
            ).fetchall()
            for name, playlist, stream_id in rows:
                server = valid_playlists[playlist]
                results.append(
                    {
                        "id": stream_id,
                        "name": name,
                        "_server_id": server.get("id"),
                        "_server_name": server.get("name"),
                    }
                )

        for playlist, server in override_servers:
            results.extend(_parse_override_matches(playlist, query, server))
    except Exception as exc:
        xbmc.log(
            f"[PlaylistSearch] Index query failed: {exc}",
            level=xbmc.LOGWARNING,
        )
        return [], set()
    finally:
        connection.close()

    xbmc.log(
        f"[PlaylistSearch] Found {len(results)} results across "
        f"{len(covered_server_keys)} validated playlists",
        level=xbmc.LOGINFO,
    )
    return results, covered_server_keys
