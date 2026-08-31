from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# No login_view: there is no page to send a browser to. Signing in happens
# inside the client, so an unauthenticated request is answered with 401 and the
# client shows its own form - see register_login_handlers().
