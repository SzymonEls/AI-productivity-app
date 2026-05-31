import struct
import zlib
from datetime import date
from functools import lru_cache

from flask import Blueprint, abort, current_app, render_template, send_from_directory
from flask_login import current_user

from ..ai.service import MARKDOWN_RESPONSE, is_openai_configured
from ..models import AIPlan


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    """Home page with the pinned daily AI markdown response."""

    latest_plan = None
    if current_user.is_authenticated:
        latest_plan = (
            AIPlan.query.filter_by(user_id=current_user.id)
            .filter(AIPlan.plan_type.in_([MARKDOWN_RESPONSE, "daily_plan", "manual_daily_plan"]))
            .filter_by(is_pinned=True)
            .order_by(AIPlan.created_at.desc())
            .first()
        )
        if latest_plan is None:
            latest_plan = (
                AIPlan.query.filter_by(user_id=current_user.id)
                .filter(AIPlan.plan_type.in_([MARKDOWN_RESPONSE, "daily_plan", "manual_daily_plan"]))
                .order_by(AIPlan.created_at.desc())
                .first()
            )

    return render_template(
        "home.html",
        latest_plan=latest_plan,
        is_openai_ready=current_user.is_authenticated and is_openai_configured(),
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
    background = (248, 250, 252)
    circle = (31, 41, 55)
    white = (255, 255, 255)
    accent = (20, 184, 166)

    pixels = [[background for _ in range(size)] for _ in range(size)]
    center = size / 2
    radius = size * 0.4
    safe_radius = size * 0.47

    for y in range(size):
        for x in range(size):
            distance = ((x - center) ** 2 + (y - center) ** 2) ** 0.5
            if distance <= safe_radius:
                pixels[y][x] = circle if distance <= radius else background

    thickness = max(8, int(size * 0.055))
    _draw_line(pixels, size * 0.28, size * 0.62, size * 0.41, size * 0.32, white, thickness)
    _draw_line(pixels, size * 0.41, size * 0.32, size * 0.54, size * 0.62, white, thickness)
    _draw_line(pixels, size * 0.34, size * 0.5, size * 0.49, size * 0.5, white, thickness)
    _draw_line(pixels, size * 0.64, size * 0.34, size * 0.64, size * 0.62, white, thickness)
    _draw_line(pixels, size * 0.59, size * 0.34, size * 0.69, size * 0.34, white, thickness)
    _draw_line(pixels, size * 0.59, size * 0.62, size * 0.69, size * 0.62, white, thickness)
    _draw_line(pixels, size * 0.28, size * 0.74, size * 0.72, size * 0.74, accent, max(8, int(size * 0.04)))

    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for red, green, blue in row:
            raw.extend((red, green, blue))

    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _draw_line(pixels, x1, y1, x2, y2, color, thickness):
    size = len(pixels)
    min_x = max(0, int(min(x1, x2) - thickness))
    max_x = min(size - 1, int(max(x1, x2) + thickness))
    min_y = max(0, int(min(y1, y2) - thickness))
    max_y = min(size - 1, int(max(y1, y2) + thickness))
    dx = x2 - x1
    dy = y2 - y1
    length_squared = dx * dx + dy * dy

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            if length_squared:
                position = ((x - x1) * dx + (y - y1) * dy) / length_squared
                position = min(1, max(0, position))
                nearest_x = x1 + position * dx
                nearest_y = y1 + position * dy
            else:
                nearest_x = x1
                nearest_y = y1
            if ((x - nearest_x) ** 2 + (y - nearest_y) ** 2) ** 0.5 <= thickness / 2:
                pixels[y][x] = color


def _png_chunk(chunk_type, data):
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum)
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum & 0xFFFFFFFF)
