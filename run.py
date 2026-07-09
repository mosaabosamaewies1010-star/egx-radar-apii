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
    from app.models import Opportunity
    db.create_all()
    from scripts.seed_stocks import seed as seed_stocks
    seed_stocks()
    if Opportunity.query.count() == 0:
        import os, sys
        csv_path = os.path.join(os.path.dirname(__file__), "scripts", "trades_I7.csv")
        if os.path.exists(csv_path):
            sys.path.insert(0, os.path.dirname(__file__))
            from scripts.import_backtest import run as seed_db
            logging.getLogger(__name__).info("Seeding database from backtest CSV...")
            seed_db(csv_path)
            logging.getLogger(__name__).info("Database seeded.")

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") == "1"

    if not debug:
        # Start background scheduler only in production (not in Flask reloader)
        from app.jobs.scheduler import create_scheduler
        scheduler = create_scheduler(app)
        scheduler.start()
        logging.getLogger(__name__).info("Background scheduler started")

    app.run(debug=debug, port=5001)
