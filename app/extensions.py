from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
# Counters live in the worker process. Gunicorn runs several of them, so a
# determined client gets the configured budget once per worker rather than once
# overall - still a hard ceiling on guessing, where before there was none. Point
# storage_uri at Redis if an exact shared limit is ever needed.
limiter = Limiter(get_remote_address, storage_uri="memory://")
