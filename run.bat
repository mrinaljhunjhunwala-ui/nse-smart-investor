@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  NSE Smart Investor — Windows launcher
REM
REM  Usage:
REM    run.bat                                     — show help
REM    run.bat --mode dashboard                    — launch Streamlit UI
REM    run.bat --mode portfolio --portfolio-csv portfolio.csv
REM    run.bat --mode score --tickers RELIANCE.NS TCS.NS
REM    run.bat --mode score --index nifty100
REM    run.bat --mode screen --index nifty200
REM    run.bat --mode scan --index nifty50
REM    run.bat --mode trail
REM    run.bat --mode backtest --strategy rsi_macd --index nifty50
REM    run.bat --mode sector --n-sectors 3
REM    run.bat --mode lstm --tickers TCS.NS --period 3y
REM ─────────────────────────────────────────────────────────────────────────────

set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM  Detect Python launcher
where py >nul 2>&1
if %errorlevel% == 0 (
    set PY=py
) else (
    set PY=C:\Users\ASUS\AppData\Local\Python\pythoncore-3.14-64\python.exe
)

REM  No args — show help
if "%1"=="" (
    echo.
    echo  NSE Smart Investor — Quick Reference
    echo  ─────────────────────────────────────────────────────────────────────
    echo  run.bat --mode dashboard                          ^| Launch web UI
    echo  run.bat --mode portfolio --portfolio-csv FILE.csv ^| Portfolio health
    echo  run.bat --mode score --tickers RELIANCE.NS TCS.NS ^| Score stocks
    echo  run.bat --mode score --index nifty100             ^| Score NIFTY100
    echo  run.bat --mode screen --index nifty200            ^| Smart screener
    echo  run.bat --mode scan --index nifty50               ^| Scan + paper trade
    echo  run.bat --mode trail                              ^| Update trailing stops
    echo  run.bat --mode backtest --index nifty50           ^| Backtest
    echo  ─────────────────────────────────────────────────────────────────────
    goto end
)

%PY% main.py %*

:end
