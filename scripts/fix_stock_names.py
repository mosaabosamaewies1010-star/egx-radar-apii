"""
One-time script: force-update ALL stock Arabic/English names in the database.
Fixes incorrect names that were seeded with wrong data.

Run locally against production DB:
    DATABASE_URL=<external_url> python scripts/fix_stock_names.py

Or via Render Shell:
    python scripts/fix_stock_names.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app, db
from app.models.stock import Stock
from scripts.seed_stocks import EGX_STOCKS


def fix_names():
    app = create_app()
    with app.app_context():
        updated = not_found = unchanged = 0

        for symbol, name_ar, name_en, sector, is_sharia in EGX_STOCKS:
            stock = Stock.query.filter_by(symbol=symbol).first()
            if not stock:
                not_found += 1
                print(f"  NOT FOUND: {symbol}")
                continue

            changed = (
                stock.name_ar != name_ar
                or stock.name_en != name_en
                or stock.sector != sector
                or stock.is_sharia != is_sharia
            )

            if changed:
                print(f"  UPDATE {symbol}: '{stock.name_ar}' → '{name_ar}'")
                stock.name_ar   = name_ar
                stock.name_en   = name_en
                stock.sector    = sector
                stock.is_sharia = is_sharia
                updated += 1
            else:
                unchanged += 1

        db.session.commit()
        print(f"\nDone: {updated} updated, {unchanged} unchanged, {not_found} not found in DB.")
        print("Run seed_stocks.py after this to add any missing symbols.")


if __name__ == "__main__":
    fix_names()
