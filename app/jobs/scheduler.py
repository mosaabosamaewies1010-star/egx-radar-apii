"""
APScheduler configuration.
Jobs run in Cairo time (Africa/Cairo, UTC+2).
EGX market: Sun–Thu 10:30–14:30.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

CAIRO_TZ = "Africa/Cairo"


def create_scheduler(app) -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler (not yet started)."""
    scheduler = BackgroundScheduler(timezone=CAIRO_TZ)

    from app.jobs.regime_job  import run_regime_job
    from app.jobs.daily_scan  import run_daily_scan
    from app.jobs.outcome_job import run_outcome_job
    from app.jobs.expire_pro  import run_expire_pro_job

    # 15:00 Cairo — compute market regime (30 min after close)
    scheduler.add_job(
        func=lambda: run_regime_job(app),
        trigger=CronTrigger(day_of_week="sun,mon,tue,wed,thu", hour=15, minute=0, timezone=CAIRO_TZ),
        id="regime_job",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 15:30 Cairo — daily stock scan (1 h after close, after regime is committed)
    scheduler.add_job(
        func=lambda: run_daily_scan(app),
        trigger=CronTrigger(day_of_week="sun,mon,tue,wed,thu", hour=15, minute=30, timezone=CAIRO_TZ),
        id="daily_scan",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # 16:00 Cairo — auto-close PENDING opportunities (EOD price check)
    scheduler.add_job(
        func=lambda: run_outcome_job(app),
        trigger=CronTrigger(day_of_week="sun,mon,tue,wed,thu", hour=16, minute=0, timezone=CAIRO_TZ),
        id="outcome_job",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 00:05 Cairo, every day — downgrade users whose PRO subscription expired
    # (subscriptions can lapse on any day, not just trading days)
    scheduler.add_job(
        func=lambda: run_expire_pro_job(app),
        trigger=CronTrigger(hour=0, minute=5, timezone=CAIRO_TZ),
        id="expire_pro_job",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info(
        "Scheduler configured: regime_job@15:00, daily_scan@15:30, "
        "outcome_job@16:00, expire_pro_job@00:05 (Cairo)"
    )
    return scheduler
