"""
Sync Sharia-compliant stocks from EGX official website.

Usage:
  # Auto mode — fetches from EGX website:
  python scripts/sync_sharia_from_egx.py

  # Manual mode — paste symbols directly (useful when EGX blocks scraping):
  python scripts/sync_sharia_from_egx.py --symbols "ADIB,SAUD,FAIT,FAITA,ISPH,AMOC,..."

  # Dry-run (show changes without saving):
  python scripts/sync_sharia_from_egx.py --dry-run

The EGX 33 Shariah index is rebalanced every ~6 months (January & July).
Run this script after each rebalancing to keep the DB in sync.
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

EGX_SHARIAH_URL = "https://www.egx.com.eg/ar/shariaCompliant.aspx"

# ── EGX scraper ──────────────────────────────────────────────────────────────

def fetch_egx_sharia_symbols() -> list[str]:
    """Scrape current Sharia symbols from EGX website."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("⚠  Missing dependencies: pip install requests beautifulsoup4")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(EGX_SHARIAH_URL, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠  Could not reach EGX website: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # EGX renders a table — look for Reuters codes (pattern: XXXX.CA)
    import re
    symbols = []
    for cell in soup.find_all(string=re.compile(r"^[A-Z]{2,6}\.CA$")):
        sym = cell.strip().replace(".CA", "")
        if sym not in symbols:
            symbols.append(sym)

    if not symbols:
        # Fallback: look for table rows with stock codes
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if cells and re.match(r"^[A-Z]{2,6}(\.CA)?$", cells[0].get_text(strip=True)):
                sym = cells[0].get_text(strip=True).replace(".CA", "")
                if sym not in symbols:
                    symbols.append(sym)

    return symbols


# ── DB update ─────────────────────────────────────────────────────────────────

def apply_update(new_sharia_symbols: list[str], dry_run: bool = False):
    from app import create_app, db
    from app.models.stock import Stock

    new_set = set(new_sharia_symbols)
    app = create_app()
    with app.app_context():
        all_stocks = Stock.query.all()
        to_add    = []  # currently False, should be True
        to_remove = []  # currently True, should be False
        not_found = []  # symbol in EGX list but not in our DB

        for sym in new_set:
            stock = next((s for s in all_stocks if s.symbol == sym), None)
            if stock is None:
                not_found.append(sym)
            elif not stock.is_sharia:
                to_add.append(stock)

        for stock in all_stocks:
            if stock.is_sharia and stock.symbol not in new_set:
                to_remove.append(stock)

        print(f"\n{'[DRY RUN] ' if dry_run else ''}EGX Sharia sync — {len(new_set)} official symbols")
        print(f"  ✅ Already correct: {len(all_stocks) - len(to_add) - len(to_remove) - len(not_found)}")
        print(f"  ➕ Will mark as Sharia: {len(to_add)} → {[s.symbol for s in to_add]}")
        print(f"  ➖ Will remove Sharia: {len(to_remove)} → {[s.symbol for s in to_remove]}")
        if not_found:
            print(f"  ⚠  In EGX list but not in DB: {not_found} (add these to seed_stocks.py)")

        if dry_run:
            print("\n  (dry-run — no changes saved)")
            return

        if not to_add and not to_remove:
            print("\n  ✓ DB already matches EGX list — nothing to update.")
            return

        confirm = input("\nApply changes? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

        for stock in to_add:
            stock.is_sharia = True
        for stock in to_remove:
            stock.is_sharia = False

        db.session.commit()
        print(f"\n✓ Done: +{len(to_add)} Sharia, -{len(to_remove)} Sharia")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sync EGX Sharia stocks")
    parser.add_argument("--symbols", help="Comma-separated symbols (manual mode)")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without saving")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip().upper().replace(".CA", "") for s in args.symbols.split(",") if s.strip()]
        print(f"Manual mode: {len(symbols)} symbols provided")
    else:
        print(f"Fetching from {EGX_SHARIAH_URL} ...")
        symbols = fetch_egx_sharia_symbols()
        if not symbols:
            print("\n⚠  Auto-fetch failed. Use manual mode:")
            print("   1. Open https://www.egx.com.eg/ar/shariaCompliant.aspx")
            print("   2. Copy all stock symbols")
            print('   3. Run: python scripts/sync_sharia_from_egx.py --symbols "ADIB,SAUD,..."')
            sys.exit(1)
        print(f"Found {len(symbols)} symbols on EGX website")

    apply_update(symbols, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
