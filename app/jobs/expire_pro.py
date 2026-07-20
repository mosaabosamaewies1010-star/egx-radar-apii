"""
Background job: downgrade users whose PRO subscription has expired.

Access control itself is already enforced live (and correctly) by
User.is_pro_active() via app.utils.pro_guard — a user cannot use PRO
features past pro_expires_at even if this job hasn't run yet.

This job exists only to keep the raw `is_pro` column (used by lightweight,
frequently-polled admin stats that count via SQL rather than Python) in
sync, so those counters don't drift more than ~1 day stale.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def run_expire_pro_job(app) -> None:
    with app.app_context():
        try:
            from app import db
            from app.models.user import User

            now = datetime.now(timezone.utc)
            expired = User.query.filter(
                User.is_pro.is_(True),
                User.pro_expires_at.isnot(None),
                User.pro_expires_at <= now,
            ).all()

            for u in expired:
                u.is_pro = False

            db.session.commit()
            logger.info("expire_pro_job: downgraded %d expired PRO user(s)", len(expired))

        except Exception:
            logger.exception("expire_pro_job: top-level error")
