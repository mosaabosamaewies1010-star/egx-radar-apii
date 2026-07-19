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
    from sqlalchemy import text
    db.create_all()
    # Add new columns if they don't exist yet
    for col_sql in [
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_method   VARCHAR(30)",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS receipt_image    TEXT",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS admin_note       TEXT",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS original_amount  FLOAT",
        "ALTER TABLE payments ADD COLUMN IF NOT EXISTS discount_applied BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users    ADD COLUMN IF NOT EXISTS referral_code          VARCHAR(20)",
        "ALTER TABLE users    ADD COLUMN IF NOT EXISTS referred_by_id         INTEGER",
        "ALTER TABLE users    ADD COLUMN IF NOT EXISTS referral_discount_used  BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users    ADD COLUMN IF NOT EXISTS discount_credits        INTEGER DEFAULT 0",
        "ALTER TABLE users    ADD COLUMN IF NOT EXISTS pro_expires_at          TIMESTAMP",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS eps                     FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS week52_high             FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS week52_low              FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS book_value              FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS last_change_amt         FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS last_change_pct         FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS day_open                FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS day_high                FLOAT",
        "ALTER TABLE stocks   ADD COLUMN IF NOT EXISTS day_low                 FLOAT",
    ]:
        try:
            db.session.execute(text(col_sql))
            db.session.commit()
        except Exception:
            db.session.rollback()
    logging.getLogger(__name__).info("DB tables ready.")
    try:
        from scripts.seed_stocks import seed as seed_stocks
        seed_stocks()
    except Exception:
        logging.getLogger(__name__).exception("seed_stocks failed")

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") == "1"

    if not debug:
        # Start background scheduler only in production (not in Flask reloader)
        from app.jobs.scheduler import create_scheduler
        scheduler = create_scheduler(app)
        scheduler.start()
        logging.getLogger(__name__).info("Background scheduler started")

    app.run(debug=debug, port=5001)
