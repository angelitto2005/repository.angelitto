from lib.httpserver import HTTPRequestHandler, add_get_route
from lib.repository import Repository, NotFoundException


def add_repository_routes(repository):
    # type: (Repository) -> None

    @add_get_route("/addons.xml")
    def route_get_addons(ctx):
        # type: (HTTPRequestHandler) -> None
        ctx.send_response_with_data(repository.get_addons_xml(), "application/xml")

    @add_get_route("/addons.xml.md5")
    def route_get_addons_md5(ctx):
        # type: (HTTPRequestHandler) -> None
        ctx.send_response_with_data(repository.get_addons_xml_md5(), "text/plain")

    @add_get_route("/{w}/{p}")
    def route_get_assets(ctx, addon_id, asset):
        # type: (HTTPRequestHandler, str, str) -> None
        try:
            with repository.get_asset(addon_id, asset) as response:
                ctx.send_file_contents(
                    response.raw, response.status_code,
                    length=response.headers.get("Content-Length"),
                    content_type=response.headers.get("Content-Type"),
                    content_disposition=response.headers.get("Content-Disposition"))
        except NotFoundException:
            ctx.send_response_and_end(404)

    @add_get_route("/update")
    def route_update(ctx):
        # type: (HTTPRequestHandler) -> None
        repository.update()
        repository.clear_cache()
        ctx.send_response_and_end(200)
