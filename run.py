from app import create_app


app = create_app()


if __name__ == "__main__":
    # 5001, not Flask's default 5000: on macOS the AirPlay Receiver in Control
    # Center already listens on *:5000 and answers every request with 403.
    app.run(debug=True, use_reloader=False, port=5001)
