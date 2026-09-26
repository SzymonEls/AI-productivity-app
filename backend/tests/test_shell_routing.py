"""Which addresses get the client shell, and which get a JSON error."""


def test_unknown_api_address_is_a_json_404(client):
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.get_json() == {"ok": False, "message": "This resource was not found."}


def test_wrong_method_on_an_api_endpoint_is_not_the_shell(client):
    # The catch-all used to claim this and answer 200 with index.html.
    response = client.get("/api/sync/push")

    assert response.status_code == 404
    assert response.is_json


def test_missing_static_file_is_a_404(client):
    assert client.get("/static/does-not-exist.js").status_code == 404


def test_client_routes_still_get_the_shell(client):
    # 503 when the client has not been built on this machine; never a 404.
    for path in ("/", "/projects/1", "/api-docs"):
        assert client.get(path).status_code in {200, 503}, path


def test_unknown_non_api_404_is_not_json(app):
    # Only /api speaks JSON; everything else keeps Flask's own error page.
    with app.test_request_context("/nowhere"):
        from app import wants_json_response

        assert not wants_json_response()


def test_demo_mode_refuses_writes_with_json(tmp_path, monkeypatch):
    from app import create_app
    from app.config import Config

    class DemoConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'demo.db'}"
        SECRET_KEY = "test-secret"
        SESSION_COOKIE_SECURE = False
        DEMO_MODE = True
        DEMO_BLOCK_MESSAGE = "Demo mode - changes are disabled."
        TESTING = True

    monkeypatch.delenv("SKIP_DB_BOOTSTRAP", raising=False)
    client = create_app(DemoConfig).test_client()

    # Outside /api too: the guard used to redirect there, to an endpoint that
    # no longer exists.
    for path in ("/api/sync/push", "/somewhere"):
        response = client.post(path, json={})
        assert response.status_code == 403, path
        assert response.get_json()["message"] == "Demo mode - changes are disabled."
