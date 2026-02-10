import requests
import os
import datetime
import yfinance as yf
import math
import numpy as np

# --- CONFIGURATION ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
SOURCE_FILE = "watchlist.txt"

def load_targets():
    """Load stock list from watchlist.txt"""
    if not os.path.exists(SOURCE_FILE): return []
    with open(SOURCE_FILE, 'r') as f:
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def push_notification(msg):
    """Send message to Telegram"""
    if not TG_TOKEN or not TG_CHAT: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(0, len(msg), 4000):
        try: 
            requests.post(url, json={"chat_id": TG_CHAT, "text": msg[i:i+4000], "parse_mode": "Markdown"})
        except Exception as e:
            print(f"Telegram Error: {e}")

def format_val(v):
    if math.isnan(v): return "0"
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M"
    return str(int(v))

def get_fundamentals(ticker):
    """
    Fetch key fundamentals (PE, PBV, ROE).
    Includes safety cast to float to prevent TypeErrors.
    """
    try:
        stock = yf.Ticker(f"{ticker}.JK")
        info = stock.info
        
        # Helper to safely convert values to float
        def safe_get(key, default=999.0):
            val = info.get(key)
            try:
                if val is None: return default
                return float(val)
            except (ValueError, TypeError):
                return default

        return {
            'pe': safe_get('trailingPE', 999.0), 
            'pbv': safe_get('priceToBook', 999.0),
            'roe': safe_get('returnOnEquity', 0.0),
            'div_yield': safe_get('dividendYield', 0.0)
        }
    except:
        return {'pe': 999.0, 'pbv': 999.0, 'roe': 0.0, 'div_yield': 0.0}

def calc_trading_plan(high, low, close):
    daily_range = high - low
    if daily_range == 0: return close, close, close
    entry_price = low + (daily_range * 0.20)
    target_price = high - (daily_range * 0.10)
    stop_loss = low * 0.98
    return int(entry_price), int(target_price), int(stop_loss)

def analyze_market(tickers):
    print(f"⚡ Screening {len(tickers)} stocks via YFinance (3-Month Horizon)...")
    
    yf_tickers = [f"{t}.JK" for t in tickers]
    
    try:
        # UPDATED: Fetch '3mo' to find the 3-Month Low
        df = yf.download(yf_tickers, period="3mo", group_by='ticker', progress=False, threads=True)
    except Exception as e:
        print(f"⚠️ YFinance Connection Error: {e}")
        return []

    candidates = []
    
    for t in tickers:
        try:
            # Handle YFinance MultiIndex structure
            if len(tickers) == 1:
                data = df
            else:
                if f"{t}.JK" in df.columns.levels[0]:
                    data = df[f"{t}.JK"]
                else:
                    continue
            
            if data.empty or len(data) < 20: continue # Need enough data for 3mo check
            
            # --- EXTRACT DATA ---
            curr = data.iloc[-1]
            close = float(curr['Close'])
            high_today = float(curr['High'])
            low_today = float(curr['Low'])
            open_price = float(curr['Open'])
            vol = float(curr['Volume'])
            value_tx = close * vol

            if math.isnan(close) or math.isnan(vol) or value_tx == 0: continue

            # --- METRICS ---
            # 1. 3-Month High/Low Calculation
            low_3mo = data['Low'].min()
            high_3mo = data['High'].max()
            
            # Distance from 3-Month Low (%)
            # 0% = Price is at the absolute lowest of 3 months
            dist_from_low3mo = ((close - low_3mo) / low_3mo) * 100
            
            # Position in 3-Month Range (0.0 = Low, 1.0 = High)
            range_3mo = high_3mo - low_3mo
            pos_score_3mo = (close - low_3mo) / range_3mo if range_3mo > 0 else 0.5

            # 2. Scalping Metrics
            swing_pct = ((high_today - low_today) / low_today) * 100
            hist_vol = data['Volume'].iloc[-21:-1] # Last 20 days excluding today
            avg_vol = hist_vol.mean() if len(hist_vol) > 0 else vol
            rvol = vol / avg_vol if avg_vol > 0 else 0

            # 3. Trading Plan
            entry, target, sl = calc_trading_plan(high_today, low_today, close)

            # --- FILTERING ---
            
            # Flag for "Value Opportunity" (Near 3mo Low)
            is_value_play = False
            fund_data = {}
            
            # If price is within 5% of 3-month low OR in bottom 15% of 3-month range
            if dist_from_low3mo < 5.0 or pos_score_3mo < 0.15:
                is_value_play = True
                # ONLY fetch fundamentals for these candidates (Save time)
                fund_data = get_fundamentals(t)
            
            # Standard Scalper Filter (Liquidity & Volatility)
            # We keep scalper candidates even if they aren't value plays
            is_scalper_play = (value_tx >= 2_000_000_000) and (swing_pct >= 1.5 or rvol >= 2.0)
            
            if not is_scalper_play and not is_value_play: continue

            candidates.append({
                'id': t,
                'price': close,
                'change': ((close - open_price) / open_price) * 100,
                'value_tx': value_tx,
                # Scalper Data
                'swing': swing_pct,
                'rvol': rvol,
                'plan_entry': entry,
                'plan_target': target,
                'plan_sl': sl,
                # Value Data
                'is_value': is_value_play,
                'dist_low3mo': dist_from_low3mo,
                'pe': fund_data.get('pe', 0),
                'pbv': fund_data.get('pbv', 0)
            })
            
        except Exception: 
            continue
            
    # Sort: Prioritize Value Plays near Low, then Scalper Activity
    candidates.sort(key=lambda x: (x['is_value'], x['rvol']), reverse=True)
    
    return candidates[:15]

def main():
    targets = load_targets()
    if not targets:
        print("❌ Watchlist empty.")
        return

    results = analyze_market(targets)
    if not results:
        print("⚠️ No stocks found.")
        return

    # --- REPORTING ---
    wib_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=7)).strftime('%H:%M')
    
    txt = f"📊 *HYBRID MARKET SCAN* 📊\n"
    txt += f"⏱️ Time: {wib_time} WIB\n"
    txt += f"_Focus: Scalping & 3-Month Lows_\n\n"
    
    for s in results:
        icon = "⚪"
        if s['change'] > 0: icon = "🟢"
        elif s['change'] < 0: icon = "🔴"
        
        # --- HEADER ---
        txt += f"*{s['id']}* {icon} ({s['change']:+.1f}%)\n"
        
        # --- VALUE INVESTING SECTION ---
        if s['is_value']:
            txt += f"💎 *VALUE ALERT (Near 3Mo Low)*\n"
            txt += f"   • Low Distance: *{s['dist_low3mo']:.1f}%* from bottom\n"
            
            # Valuation Check
            pe = s['pe']
            pbv = s['pbv']
            val_status = "Neutral"
            if pe > 0 and pe < 10 and pbv < 1.0: val_status = "✅ UNDERVALUED"
            elif pe > 25: val_status = "⚠️ EXPENSIVE"
            
            # Format Fundamentals nicely
            pe_str = f"{pe:.1f}x" if pe != 999 else "-"
            pbv_str = f"{pbv:.1f}x" if pbv != 999 else "-"
            
            txt += f"   • Fund: PE {pe_str} | PBV {pbv_str}\n"
            txt += f"   • Status: {val_status}\n"
        
        # --- SCALPING SECTION ---
        # Show this if it has volume/volatility
        if s['swing'] > 1.0 or s['rvol'] > 1.0:
            rvol_icon = "🔈"
            if s['rvol'] > 1.5: rvol_icon = "🔊"
            if s['rvol'] > 3.0: rvol_icon = "📢"
            
            txt += f"⚔️ *Day Trade Data*\n"
            txt += f"   • Vol: {s['rvol']:.1f}x Avg {rvol_icon} | Swing: {s['swing']:.1f}%\n"
            txt += f"   • Plan: Buy {s['plan_entry']} | TP {s['plan_target']} | SL {s['plan_sl']}\n"
            
        txt += "----------------------------\n"
        
    push_notification(txt)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
