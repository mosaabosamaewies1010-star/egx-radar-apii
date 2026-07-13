from datetime import timedelta
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
from flask_caching import Cache
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
import os

load_dotenv()

db      = SQLAlchemy()
cache   = Cache()
jwt     = JWTManager()

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")


def create_app(config_name: str = "development") -> Flask:
    app = Flask(__name__)

    # Config
    app.config["SQLALCHEMY_DATABASE_URI"]        = os.getenv("DATABASE_URL", "sqlite:///egx_radar.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {
        "pool_pre_ping": True,      # يتحقق من الـ connection قبل كل استخدام
        "pool_recycle":  300,       # يجدد الـ connection كل 5 دقايق
        "pool_size":     5,
        "max_overflow":  10,
    }
    app.config["SECRET_KEY"]                     = os.getenv("SECRET_KEY", "dev-secret")
    app.config["CACHE_TYPE"]                     = "SimpleCache"
    app.config["CACHE_DEFAULT_TIMEOUT"]          = 300   # 5 minutes
    app.config["JWT_SECRET_KEY"]                 = os.getenv("JWT_SECRET_KEY", "dev-jwt-secret")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"]       = timedelta(days=30)

    # Extensions
    db.init_app(app)
    Migrate(app, db)
    cache.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)
    CORS(app, origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","))

    # Register blueprints (routes already include full paths)
    from app.routes.stocks        import stocks_bp
    from app.routes.market        import market_bp
    from app.routes.opportunities import opps_bp
    from app.routes.health        import health_bp
    from app.routes.analytics     import analytics_bp
    from app.routes.auth          import auth_bp
    from app.routes.portfolio     import portfolio_bp
    from app.routes.watchlist     import watchlist_bp
    from app.routes.notifications import notifications_bp
    from app.routes.discover      import discover_bp
    from app.routes.morning_brief import morning_brief_bp
    from app.routes.my_day        import my_day_bp
    from app.routes.payments      import payments_bp
    from app.routes.performance   import performance_bp
    from app.routes.bot           import bot_bp
    from app.routes.admin         import admin_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(stocks_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(opps_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(discover_bp)
    app.register_blueprint(morning_brief_bp)
    app.register_blueprint(my_day_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(performance_bp)
    app.register_blueprint(bot_bp)
    app.register_blueprint(admin_bp)

    return app
