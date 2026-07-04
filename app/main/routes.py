import struct
import zlib
from datetime import date
from functools import lru_cache

from flask import Blueprint, abort, current_app, render_template, send_from_directory
from flask_login import current_user

from ..models import DailyPlan


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Home page with the user's single saved daily plan."""

    daily_plan = None
    if current_user.is_authenticated:
        daily_plan = DailyPlan.query.filter_by(user_id=current_user.id).first()

    return render_template(
        "home.html",
        daily_plan=daily_plan,
        today=date.today(),
    )


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
    """Serve a root-scoped, online-only service worker."""

    response = send_from_directory(
        current_app.static_folder,
        "service-worker.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@main_bp.route("/pwa-icon-<int:size>.png")
def pwa_icon(size):
    """Serve generated PNG icons required by installable PWAs."""

    if size not in {192, 512}:
        abort(404)

    response = current_app.response_class(_pwa_icon_png(size), mimetype="image/png")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@lru_cache(maxsize=2)
def _pwa_icon_png(size):
    """Render the brand mark: a full-bleed indigo→violet diagonal gradient with
    a centred white diamond. Full-bleed so it reads well as a maskable icon; the
    diamond stays inside the safe zone so platform masks never clip it.
    """
    top_left = (79, 70, 229)      # #4f46e5 (indigo)
    bottom_right = (139, 92, 246)  # #8b5cf6 (violet)
    white = (255, 255, 255)

    center = (size - 1) / 2
    diamond_radius = size * 0.27  # half-diagonal, within the maskable safe zone
    max_diagonal = 2 * (size - 1)

    raw = bytearray()
    for y in range(size):
        raw.append(0)  # PNG "no filter" byte for this scanline
        for x in range(size):
            if abs(x - center) + abs(y - center) <= diamond_radius:
                raw.extend(white)
            else:
                blend = (x + y) / max_diagonal
                raw.extend(
                    round(start + (end - start) * blend)
                    for start, end in zip(top_left, bottom_right)
                )

    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _png_chunk(chunk_type, data):
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum)
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum & 0xFFFFFFFF)
