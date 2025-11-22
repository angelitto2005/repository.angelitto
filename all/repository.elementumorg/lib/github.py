from lib.utils import request


class _Dict(dict):
    def __getattr__(self, name):
        return self[name]


class GitHubApiError(Exception):
    pass


class GitHubRepositoryApi(object):
    def __init__(self, username, repository, base_url="https://api.github.com", version="2022-11-28", token=None):
        self._base_url = "{}/repos/{username}/{repository}".format(
            base_url, username=username, repository=repository)
        self._version = version
        self._token = token

    def get_repository_info(self):
        return self._request_json("")

    def get_refs_tags(self):
        return self._request_json("/git/refs/tags")

    def get_release(self, release):
        return self._request_json("/releases/{}".format(release))

    def get_latest_release(self):
        return self.get_release("latest")

    def get_release_by_tag(self, tag_name):
        return self.get_release("tags/{}".format(tag_name))

    def get_release_asset(self, asset_id):
        return self._request(
            "/releases/assets/{}".format(asset_id),
            headers={"Accept": "application/octet-stream"})

    def get_zip(self, ref=None):
        # One could also use "https://github.com/{username}/{repository}/archive/{branch}.zip"
        # to avoid GitHub API rate limiting
        return self._request(
            "/zipball/{}".format(ref) if ref else "/zipball",
            headers={"Accept": "application/vnd.github.raw"})

    def get_contents(self, path, ref=None):
        # One could also use "https://raw.githubusercontent.com/{username}/{repository}/{branch}/{path}"
        # to avoid GitHub API rate limiting
        return self._request(
            "/contents/{}".format(path),
            params=dict(ref=ref) if ref else None,
            headers={"Accept": "application/vnd.github.raw"})

    def _request_json(self, url, params=None):
        with self._request(url, params=params, headers={"Accept": "application/vnd.github+json"}) as response:
            return response.json(object_pairs_hook=_Dict)

    def _request(self, url, params=None, headers=None):
        full_url = self._base_url + url
        response = request(full_url, params=params, headers=self._headers(headers))
        if response.status_code >= 400:
            try:
                response.close()
            finally:
                raise GitHubApiError("Call to {} failed with HTTP {}".format(full_url, response.status_code))
        return response

    def _headers(self, headers):
        if headers is None:
            headers = {}
        if self._token:
            headers["Authorization"] = "Bearer {}".format(self._token)
        headers["X-GitHub-Api-Version"] = self._version
        return headers

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self._base_url == other._base_url and self._version == other._version and self._token == other._token
        return NotImplemented

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self._base_url, self._version, self._token))
