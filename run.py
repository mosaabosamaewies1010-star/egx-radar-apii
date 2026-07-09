"""App entry point."""
import logging
import os

from app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = create_app()

with app.app_context():
    from app import db
    db.create_all()
    logging.getLogger(__name__).info("DB tables ready.")
    if os.getenv("FLASK_ENV") != "production":
        try:
            from scripts.seed_stocks import seed as seed_stocks
            seed_stocks()
        except Exception:
            pass

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") == "1"

    if not debug:
        # Start background scheduler only in production (not in Flask reloader)
        from app.jobs.scheduler import create_scheduler
        scheduler = create_scheduler(app)
        scheduler.start()
        logging.getLogger(__name__).info("Background scheduler started")

    app.run(debug=debug, port=5001)
