from app import create_app


app = create_app()


if __name__ == "__main__":
    # This server speaks http, and a browser never sends a Secure cookie back
    # over http - left on, the login form would just reload itself forever.
    # Only this entry point is relaxed; Gunicorn never reaches it. Running the
    # local server through `flask --app run.py run` skips this block, so set
    # SECURE_COOKIES=false in .env when developing that way.
    app.config.update(SESSION_COOKIE_SECURE=False, REMEMBER_COOKIE_SECURE=False)
    # 5001, not Flask's default 5000: on macOS the AirPlay Receiver in Control
    # Center already listens on *:5000 and answers every request with 403.
    app.run(debug=True, use_reloader=False, port=5001)
