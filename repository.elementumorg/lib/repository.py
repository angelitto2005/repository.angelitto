import json
import logging
import re
from collections import namedtuple, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5
from xml.etree import ElementTree  # nosec

from lib.cache import LoadingCache
from lib.github import GitHubRepositoryApi, GitHubApiError
from lib.utils import string_types, is_http_like, request, remove_prefix
from lib.version import try_parse_version

Addon = namedtuple("Addon", (
    "id", "username", "branch", "assets", "asset_prefix", "repository", "tag_pattern", "token", "platforms"))
EntrySchema = namedtuple("EntrySchema", ("required", "validators"))


class InvalidSchemaError(Exception):
    pass


class InvalidFormatException(Exception):
    pass


class NotFoundException(Exception):
    pass


class AddonNotFound(NotFoundException):
    pass


class ReleaseAssetNotFound(NotFoundException):
    pass


def validate_string(key, value):
    if not isinstance(value, string_types):
        raise InvalidSchemaError("Expected str for '{}'".format(key))


def validate_string_map(key, value):
    if not (isinstance(value, dict)
            and all(isinstance(k, string_types) and isinstance(v, string_types) for k, v in value.items())):
        raise InvalidSchemaError("Expected dict[str, str] for '{}'".format(key))


def validate_string_list(key, value):
    if not (isinstance(value, list) and all(isinstance(v, string_types) for v in value)):
        raise InvalidSchemaError("Expected list[str] for '{}'".format(key))


_entry_schema = EntrySchema(required=("id", "username"), validators=dict(
    id=validate_string,
    username=validate_string,
    branch=validate_string,
    assets=validate_string_map,
    asset_prefix=validate_string,
    repository=validate_string,
    tag_pattern=validate_string,
    token=validate_string,
    platforms=validate_string_list,
))


def validate_entry_schema(entry):
    if not isinstance(entry, dict):
        raise InvalidSchemaError("Expecting dictionary for entry")
    for key in _entry_schema.required:
        if key not in entry:
            raise InvalidSchemaError("Key '{}' is required".format(key))
    for key, value in entry.items():
        validator = _entry_schema.validators.get(key)
        if not validator:
            raise InvalidSchemaError("Key '{}' is not valid".format(key))
        validator(key, value)


def validate_schema(data):
    if not isinstance(data, (list, tuple)):
        raise InvalidSchemaError("Expecting list/tuple for data")
    for entry in data:
        validate_entry_schema(entry)


class TagMatchPredicate(object):
    def __init__(self, version, tag_pattern=None):
        self._version = version
        self._tag_pattern = tag_pattern
        self._tag_group = tag_pattern.groupindex.get("version", 1) if tag_pattern and tag_pattern.groups else None
        self._parsed_version = try_parse_version(version)

    def __call__(self, value):
        if self._tag_pattern:
            match = self._tag_pattern.match(value)
            if not match:
                return False
            elif self._tag_group:
                value = match.group(self._tag_group)

        return value == self._version or (
                self._parsed_version and self._parsed_version == try_parse_version(value))


class Repository(object):
    ZIP_EXTENSION = ".zip"
    VERSION_SEPARATOR = "-"
    RELEASE_ASSET_PREFIX = "release_asset://"

    def __init__(self, files=(), urls=(), max_threads=5, platform=None,
                 cache_ttl=60 * 60, default_branch="main", token=None):
        self.files = files
        self.urls = urls
        self._max_threads = max_threads
        self._default_branch = default_branch
        self._token = token
        self._addons = OrderedDict()

        if platform is None:
            from lib.platform.core import PLATFORM
            self._platform = PLATFORM
        else:
            self._platform = platform

        self._addons_xml_cache = LoadingCache(self._get_addons_xml, cache_ttl)
        self._fallback_ref_cache = LoadingCache(self._get_fallback_ref, cache_ttl)
        self._refs_tags_cache = LoadingCache(self._get_refs_tags, cache_ttl)
        self.update()

    def update(self, clear=False):
        logging.debug("Updating repository (clear=%s)", clear)
        if clear:
            self._addons.clear()
        for u in self.urls:
            self._load_url(u)
        for f in self.files:
            self._load_file(f)

    def _load_file(self, path):
        with open(path) as f:
            self._load_data(json.load(f))

    def _load_url(self, url):
        with request(url) as r:
            r.raise_for_status()
            self._load_data(r.json())

    def _load_data(self, data):
        validate_schema(data)
        platform_name = self._platform.name()
        for addon_data in data:
            addon_id = addon_data["id"]
            platforms = addon_data.get("platforms")
            tag_pattern = addon_data.get("tag_pattern")

            if platforms and platform_name not in platforms:
                logging.debug("Skipping addon %s as it does not support platform %s", addon_id, platform_name)
                continue

            self._addons[addon_id] = Addon(
                id=addon_id,
                username=addon_data["username"],
                branch=addon_data.get("branch"),
                assets=addon_data.get("assets", {}),
                asset_prefix=addon_data.get("asset_prefix", ""),
                repository=addon_data.get("repository", addon_id),
                tag_pattern=re.compile(tag_pattern) if tag_pattern else None,
                token=addon_data.get("token"),
                platforms=platforms,
            )

    def clear_cache(self):
        logging.debug("Clearing repository cache")
        self._addons_xml_cache.clear()
        self._fallback_ref_cache.clear()
        self._refs_tags_cache.clear()

    def _get_addon_xml(self, addon):
        with self._get_asset(addon, "addon.xml") as r:
            r.raise_for_status()
            addon_xml = r.content

        try:
            return ElementTree.fromstring(addon_xml)
        except Exception as e:
            logging.error("Failed getting '%s' addon XML: %s", addon.id, e, exc_info=True)
            return None

    def _get_addons_xml(self):
        root = ElementTree.Element("addons")
        num_threads = min(self._max_threads, len(self._addons))
        if num_threads <= 1:
            results = map(self._get_addon_xml, self._addons.values())
        else:
            with ThreadPoolExecutor(num_threads) as pool:
                futures = [pool.submit(self._get_addon_xml, addon) for addon in self._addons.values()]
                results = map(lambda f: f.result(), futures)

        for result in results:
            if result is not None:
                root.append(result)

        return ElementTree.tostring(root, encoding="utf-8", method="xml")

    def get_addons_xml(self):
        return self._addons_xml_cache.get()

    def get_addons_xml_md5(self):
        m = md5()
        m.update(self.get_addons_xml())
        return m.hexdigest().encode("utf-8")

    def get_asset(self, addon_id, asset):
        addon = self._addons.get(addon_id)
        if addon is None:
            raise AddonNotFound("No such addon: {}".format(addon_id))
        return self._get_asset(addon, asset)

    def _get_asset(self, addon, asset):
        logging.debug("Getting asset for addon %s: %s", addon.id, asset)
        repo = GitHubRepositoryApi(addon.username, addon.repository, token=addon.token or self._token)
        ref = addon.branch or self._fallback_ref_cache.get(repo, tag_pattern=addon.tag_pattern)
        logging.debug("Using ref %s for addon %s", ref, addon.id)
        formats = dict(
            id=addon.id, username=addon.username, repository=addon.repository,
            ref=ref, system=self._platform.system, arch=self._platform.arch)

        is_zip = asset.startswith(addon.id + self.VERSION_SEPARATOR) and asset.endswith(self.ZIP_EXTENSION)
        if is_zip:
            formats["version"] = asset[len(addon.id) + len(self.VERSION_SEPARATOR):-len(self.ZIP_EXTENSION)]
            asset = "zip"

        try:
            asset_path = self._format(addon.assets[asset], **formats)
        except KeyError:
            if is_zip:
                version = formats["version"]
                zip_ref = self._get_version_tag(repo, version, tag_pattern=addon.tag_pattern, default=ref)
                logging.debug("Automatically detected zip ref. Wanted %s, detected %s", version, zip_ref)
                return repo.get_zip(zip_ref)
            asset_path = self._format(addon.asset_prefix, **formats) + asset

        if asset_path.startswith(self.RELEASE_ASSET_PREFIX):
            release_tag, asset_name = asset_path[len(self.RELEASE_ASSET_PREFIX):].rsplit("/", maxsplit=1)
            release = repo.get_release_by_tag(release_tag)
            for release_asset in release.assets:
                if release_asset.name == asset_name:
                    response = repo.get_release_asset(release_asset.id)
                    break
            else:
                raise ReleaseAssetNotFound("Unable to find release asset: {}".format(asset_path))
        elif is_http_like(asset_path):
            response = request(asset_path)
        else:
            response = repo.get_contents(asset_path, ref)

        return response

    def _get_fallback_ref(self, repo, tag_pattern=None):
        if tag_pattern is None:
            ref = self._get_latest_release_tag(repo) or self._get_matching_tag(repo, lambda _: True)
        else:
            ref = self._get_matching_tag(repo, tag_pattern.match) or self._get_latest_release_tag(repo)
        return ref or self._get_repository_default_branch(repo) or self._default_branch

    def _get_matching_tag(self, repo, predicate, default=None):
        return next((tag_name for tag_name in (
            remove_prefix(tag.ref, "refs/tags/") for tag in reversed(self._refs_tags_cache.get(repo))
        ) if predicate(tag_name)), default)

    def _get_version_tag(self, repo, version, tag_pattern=None, default=None):
        return self._get_matching_tag(repo, TagMatchPredicate(version, tag_pattern=tag_pattern), default=default)

    @staticmethod
    def _get_refs_tags(repo):
        try:
            return repo.get_refs_tags()
        except GitHubApiError:
            return []

    @staticmethod
    def _get_latest_release_tag(repo):
        try:
            return repo.get_latest_release().tag_name
        except GitHubApiError:
            return None

    @staticmethod
    def _get_repository_default_branch(repo):
        try:
            return repo.get_repository_info().default_branch
        except GitHubApiError:
            return None

    @staticmethod
    def _format(value, **formats):
        try:
            return value.format(**formats)
        except KeyError as e:
            raise InvalidSchemaError("Format contains an invalid parameter: {}".format(e))
