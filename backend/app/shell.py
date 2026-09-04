"""What the server still hands to a browser.

Not pages any more: the shell, and the two files a PWA is installed from. Every
view is built from the local copy in the client, so the only HTML here is the
one file that loads it.
"""

import os

from flask import Blueprint, current_app, send_from_directory

main_bp = Blueprint("main", __name__)

# Served by Flask's static handler, not by these routes.
RESERVED_PREFIXES = ("api/", "static/")


def _client_directory():
    return os.path.join(current_app.static_folder, "client")


@main_bp.route("/")
@main_bp.route("/<path:_client_route>")
def client(_client_route=None):
    """Hand back the client for every address it owns.

    One file for every path: the History API decides what to draw, so a reload
    or a shared link lands where it says rather than bouncing to the top. An
    unknown address gets the shell too, and the client shows its own "not here"
    - the server has no idea which addresses the client knows.
    """
    index = os.path.join(_client_directory(), "index.html")
    if not os.path.exists(index):
        return (
            "The client has not been built. Run: cd frontend && npm install && npm run build",
            503,
        )

    response = send_from_directory(_client_directory(), "index.html")
    # The shell names hashed assets, so it is the one file that must never come
    # from a stale cache after a deploy.
    response.headers["Cache-Control"] = "no-cache"
    return response


@main_bp.route("/manifest.webmanifest")
def web_manifest():
    """Serve the PWA manifest from the app root."""
    return send_from_directory(
        current_app.static_folder,
        "manifest.webmanifest",
        mimetype="application/manifest+json",
    )


@main_bp.route("/service-worker.js")
def service_worker():
    """Serve a root-scoped service worker."""
    response = send_from_directory(
        current_app.static_folder,
        "service-worker.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response
