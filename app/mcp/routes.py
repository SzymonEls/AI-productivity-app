"""
The MCP endpoint: Claude reading and planning the day through tools.

MCP's Streamable HTTP transport, in its stateless form: every message is one
POST of JSON-RPC, answered with plain JSON - no session to keep, no event
stream, so it runs on the same Flask workers as every other page. The protocol
is small enough at this size (initialize, ping, tools/list, tools/call) that it
is spoken here directly rather than through the `mcp` package, which is built
around an ASGI server this app does not have.

Two doors, the same room behind them:

- ``POST /mcp`` with ``Authorization: Bearer <token>`` - Claude Code, which can
  send a header.
- ``POST /mcp/<secret>`` - a claude.ai connector (and so the desktop and mobile
  apps), which cannot, and authenticates by the URL itself.

Both credentials are off until the account page turns them on, each is retired
on its own, and neither is the menu bar app's api_token. What the tools may see
and change - private projects above all - is decided in tools.py.
"""

import json
import logging
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, request

from ..models import User
from . import tools


mcp_bp = Blueprint("mcp", __name__, url_prefix="/mcp")
log = logging.getLogger(__name__)

# Newest first; the first is what a client asking for something else is offered.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@mcp_bp.route("", methods=["POST"])
def endpoint_with_token():
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    user = _user_by("mcp_token", token.strip() if scheme.lower() == "bearer" else "")
    return _serve(user)


@mcp_bp.route("/<secret>", methods=["POST"])
def endpoint_with_secret(secret):
    return _serve(_user_by("mcp_url_secret", secret))


# No event stream to open and no session to end: the transport says to answer
# both with 405, which tells a client to stay on plain POSTs.
@mcp_bp.route("", methods=["GET", "DELETE"])
@mcp_bp.route("/<secret>", methods=["GET", "DELETE"])
def no_stream(secret=None):
    return jsonify({"ok": False, "message": "This MCP server answers POST only."}), 405


def _user_by(column, value):
    if not value:
        return None
    user = User.query.filter(getattr(User, column) == value).first()
    if user is None or not secrets.compare_digest(value, getattr(user, column) or ""):
        return None
    return user


def _serve(user):
    if not _origin_allowed():
        return jsonify(_error(None, INVALID_REQUEST, "Origin not allowed.")), 403
    if user is None:
        return (
            jsonify(_error(None, INVALID_REQUEST, "Invalid or missing MCP credential.")),
            401,
            {"WWW-Authenticate": 'Bearer realm="mcp"'},
        )

    # The tools reuse the endpoints the pages call, which ask current_user and
    # (the timer's) g.api_user who is asking. Both are set for this request
    # only; nothing goes into the session cookie.
    g._login_user = user
    g.api_user = user

    try:
        message = json.loads(request.get_data(as_text=True) or "null")
    except ValueError:
        return jsonify(_error(None, PARSE_ERROR, "Body is not JSON.")), 400

    if isinstance(message, list):
        if not message:
            return jsonify(_error(None, INVALID_REQUEST, "Empty batch.")), 400
        answers = [answer for answer in (_handle(user, entry) for entry in message) if answer]
        return (jsonify(answers), 200) if answers else ("", 202)

    answer = _handle(user, message)
    return (jsonify(answer), 200) if answer else ("", 202)


def _origin_allowed():
    """Refuse a browser page on another site, as the transport asks servers to.

    Claude's own clients send no Origin; a browser always does, and one that
    is not this host is a page somewhere else trying its luck.
    """
    origin = request.headers.get("Origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.host


def _handle(user, message):
    """One JSON-RPC message in, its answer out - or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message.")

    method = message.get("method")
    if "id" not in message:
        # A notification ("initialized", "cancelled") or a client's answer to
        # something; neither wants a reply, and this server asks nothing.
        return None
    request_id = message["id"]
    params = message.get("params") or {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "productivity",
                    "title": "Productivity",
                    "version": current_app.config.get("APP_VERSION", "local"),
                },
                "instructions": tools.INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": tools.definitions()})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "Arguments must be an object.")
        if not tools.exists(name):
            return _error(request_id, INVALID_PARAMS, f"Unknown tool: {name}")
        try:
            return _result(request_id, tools.call(user, name, arguments))
        except Exception:  # noqa: BLE001 - one broken tool must not take the server down
            log.exception("MCP tool %s failed", name)
            return _error(request_id, INTERNAL_ERROR, "The tool failed on the server.")
    return _error(request_id, METHOD_NOT_FOUND, f"Unknown method: {method}")


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
