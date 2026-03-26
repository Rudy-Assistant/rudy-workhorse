@echo off
title Market Check
echo ============================================
echo   Market Check — Watchlist + Forex
echo ============================================
echo.
cd /d "%USERPROFILE%\Desktop"
python -c "from rudy.financial import MarketData, Watchlist; md=MarketData(); wl=Watchlist(); print('=== WATCHLIST ==='); [print(f'  {s}: ${q[\"price\"]:.2f} ({q[\"change_pct\"]:+.1f}%%)') for s in wl.symbols for q in [md.quote(s)] if 'price' in q]; print(); print('=== FOREX (USD) ==='); [print(f'  {p}: {md.forex(p.split(\"/\")[0], p.split(\"/\")[1]).get(\"rate\", \"?\"):.2f}') for p in ['USD/PHP','USD/JPY','USD/KRW','USD/THB']]"
echo.
pause
