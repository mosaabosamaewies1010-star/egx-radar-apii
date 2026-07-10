# EGX Radar — Change Log

## v1.0 Beta — 2026-07-10

### Strategy
- SRA v1.0 — Smart Recovery Accumulation engine (capitulation + smart money)
- Scanner v1.0 — daily scan of all active EGX stocks
- KB v1.0 — Knowledge Base starts empty, self-learns from closed trades
- Similarity Engine v1.0 — matches current setup to historical cases

### Entry Rules (frozen — do not modify before 100 closed trades)
- RSI at low (oversold zone)
- OBV uptrend (accumulation)
- RVOL spike > 1.5x
- Market breadth and sector slope filters
- Grade: A+ / A / B based on composite score

### Exit Profiles
- FAST: ~7% target, shorter hold
- BALANCED: ~15% target, longer hold
- SL: computed from ATR

### Infrastructure
- Backend: Flask + PostgreSQL on Render (free tier)
- Frontend: Next.js on Vercel
- Daily pipeline: GitHub Actions at 14:35 Cairo (Sun–Thu)
- Monitoring: Telegram alerts after each scan
- Telemetry: analytics_events table

---

## Template for future entries

## v1.x — YYYY-MM-DD

### Strategy Changes
- [ ] SRA Score: what changed and why
- [ ] Entry rules: what changed
- [ ] Exit rules: what changed
- [ ] Similarity Engine: what changed

### Infrastructure Changes
- [ ] ...

### Reason
- Based on: X closed trades, Y win rate, Z observation
