from tmdbhelper.lib.api.api_keys.tmdb import USER_TOKEN, API_READ_ACCESS_TOKEN
from tmdbhelper.lib.addon.logger import kodi_log


API_URL = 'https://api.themoviedb.org/4'


class TMDbUserAuthenticator():

    interval = 5
    expires_in = 120
    user_token = USER_TOKEN
    api_read_access_token = API_READ_ACCESS_TOKEN

    def __init__(self, parent):
        self._parent = parent
        self.progress = 0

    @property
    def read_access_headers(self):
        return {'Authorization': f'Bearer {self.api_read_access_token}'}

    def get_request_url(self, *args, **kwargs):
        return self._parent.get_request_url(*args, **kwargs)

    def get_response_json(self, *args, **kwargs):
        return self._parent.get_response_json(*args, headers=self.read_access_headers, **kwargs)

    def get_simple_api_request(self, *args, **kwargs):
        return self._parent.get_simple_api_request(*args, headers=self.read_access_headers, **kwargs)

    @property
    def xbmc_monitor(self):
        try:
            return self._xbmc_monitor
        except AttributeError:
            from xbmc import Monitor
            self._xbmc_monitor = Monitor()
            return self._xbmc_monitor

    @property
    def dialog_progress(self):
        try:
            return self._dialog_progress
        except AttributeError:
            from xbmcgui import DialogProgress
            self._dialog_progress = DialogProgress()
            return self._dialog_progress

    @property
    def request_token(self):
        try:
            return self._request_token
        except AttributeError:
            self._request_token = self.get_request_token()
            return self._request_token

    def get_request_token(self):
        request = self.create_request_token()
        if not request or not request.get('success'):
            self.dialog_ok('TMDb Get Request Token', 'Getting token from auth/request_token failed!')
            return
        return request.get('request_token')

    def create_request_token(self):
        return self.get_response_json('auth/request_token', method='post')

    @property
    def access_token(self):
        try:
            return self._access_token
        except AttributeError:
            if not self.authorised_access:
                return
            try:
                access_token = self.authorised_access['access_token']
                self._access_token = access_token
                return self._access_token
            except KeyError:
                return

    @property
    def stored_authorisation(self):
        try:
            return self._stored_authorisation
        except AttributeError:
            from tmdbhelper.lib.files.futils import json_loads as data_loads
            try:
                token = data_loads(self.user_token.value)
            except Exception as exc:
                kodi_log(exc, 1)
                return
            if not token:
                return
            self._stored_authorisation = token
            return self._stored_authorisation

    @stored_authorisation.setter
    def stored_authorisation(self, value):
        if not value:
            return
        from tmdbhelper.lib.files.futils import json_dumps as data_dumps
        self.user_token.value = data_dumps(value)
        self._stored_authorisation = value

    def create_access_token(self):
        response = self.get_simple_api_request(self.get_request_url('auth/access_token'), postdata={'request_token': self.request_token}, method='json')
        if response is None or not response.status_code:
            return
        if response.status_code == 200:
            return response.json()
        if response.status_code == 422:
            return {'status_code': 422}

    def poller(self):
        if not self.on_poll():
            return self.on_aborted()

        if self.expires_in <= self.progress:
            return self.on_expired()

        request = self.create_access_token()

        if not request:
            return self.on_failed()

        if request.get('success') and request.get('access_token'):
            return self.on_success(request)

        self.xbmc_monitor.waitForAbort(self.interval)
        if self.xbmc_monitor.abortRequested():
            return

        return self.poller()

    def on_success(self, request):
        """Triggered when device authentication was aborted"""
        kodi_log(u'TMDb authentication success!', 1)
        self.dialog_progress.close()
        self.dialog_ok('TMDb Get Access Token', 'Successfully authenticated access token!')
        return request

    def on_failed(self):
        """Triggered when device authentication was aborted"""
        kodi_log(u'TMDb authentication failed!', 1)
        self.dialog_progress.close()

    def on_aborted(self):
        """Triggered when device authentication was aborted"""
        kodi_log(u'TMDb authentication aborted!', 1)
        self.dialog_progress.close()

    def on_expired(self):
        """Triggered when the device authentication code has expired"""
        kodi_log(u'TMDb authentication expired!', 1)
        self.dialog_progress.close()

    def on_poll(self):
        """Triggered before each poll"""
        if self.dialog_progress.iscanceled():
            self.dialog_progress.close()
            return False
        self.progress += self.interval
        progress = (self.progress * 100) / self.expires_in
        self.dialog_progress.update(int(progress))
        return True

    def dialog_ok(self, header, message):
        from xbmcgui import Dialog
        Dialog().ok(header, message)

    def dialog_yesno(self, header, message):
        from xbmcgui import Dialog, DLG_YESNO_YES_BTN
        return Dialog().yesno(header, message, defaultbutton=DLG_YESNO_YES_BTN)

    def revoke_login(self):
        self.user_token.value = ''

    @property
    def authorised_access(self):
        try:
            return self._authorised_access
        except AttributeError:
            authorised_access = self.get_authorised_access()
            if not authorised_access:
                return
            self._authorised_access = authorised_access
            return self._authorised_access

    def get_authorised_access(self):
        if self.stored_authorisation:
            return self.stored_authorisation

        if not self.request_token:
            return

        request_token_url = f'https://www.themoviedb.org/auth/access?request_token={self.request_token}'

        if self.dialog_yesno(
                'Open default Web Browser to Authorise?',
                'Use the default system browser to authorise TMDb Token.\nSelecting NO will output TMDB REQUEST TOKEN AUTHORISATION URL to Kodi log instead. Use log method to copy-paste URL from log into external web browser on systems where a default browser cannot be accessed.'):
            import webbrowser
            webbrowser.open(request_token_url, new=0, autoraise=True)
        else:
            kodi_log(f'TMDB REQUEST TOKEN AUTHORISATION URL:\n{request_token_url}', 1)

        self.dialog_progress.create('TMDb Authorise Request Token', f'{request_token_url}')

        authorised_access = self.poller()
        if not authorised_access:
            return

        self.stored_authorisation = authorised_access
        return self.stored_authorisation
