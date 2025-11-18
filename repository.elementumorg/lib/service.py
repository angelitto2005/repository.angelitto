import logging
import os
import threading
from xml.etree import ElementTree  # nosec

import xbmc

from lib.entries import ENTRIES_PATH
from lib.httpserver import threaded_http_server
from lib.kodi import ADDON_PATH, get_repository_port, set_logger
from lib.repository import Repository
from lib.routes import add_repository_routes

set_logger()
add_repository_routes(Repository(
    files=(os.path.join(ADDON_PATH, "resources", "repository.json"), ENTRIES_PATH)))


def update_repository_port(port, xml_path=os.path.join(ADDON_PATH, "addon.xml")):
    base_url = "http://127.0.0.1:{}/".format(port)
    tree = ElementTree.parse(xml_path)
    tree.find("extension[@point='xbmc.addon.repository']/dir/info").text = base_url + "addons.xml"
    tree.find("extension[@point='xbmc.addon.repository']/dir/checksum").text = base_url + "addons.xml.md5"
    tree.find("extension[@point='xbmc.addon.repository']/dir/datadir").text = base_url
    tree.write(xml_path, encoding="UTF-8", xml_declaration=True)


class ServiceMonitor(xbmc.Monitor):
    def __init__(self, port):
        super(ServiceMonitor, self).__init__()
        self._port = port

    def onSettingsChanged(self):
        port = get_repository_port()
        if port != self._port:
            update_repository_port(port)
            self._port = port


class HTTPServerRunner(threading.Thread):
    def __init__(self, port):
        self._port = port
        self._server = None
        super(HTTPServerRunner, self).__init__()

    def run(self):
        self._server = server = threaded_http_server("", self._port)
        logging.debug("Server started at port %d", self._port)
        server.serve_forever()
        logging.debug("Closing server")
        server.server_close()
        logging.debug("Server terminated")

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        self.join()
        return False


def run():
    port = get_repository_port()
    with HTTPServerRunner(port):
        ServiceMonitor(port).waitForAbort()
