import requests
import os
import datetime
import time
import pandas as pd
import yfinance as yf
from tradingview_screener import Query, Column

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")

# --- STATIC UNIVERSE (SAFEGUARD) ---
# Daftar ini mencakup 95% likuiditas IHSG (Bluechip & Gorengan Premium)
LIQUID_STOCKS = [
    "BBCA", "BBRI", "BMRI", "BBNI", "BBTN", "BRIS", "ARTO", "BTPS",
    "ADRO", "PTBA", "ITMG", "PGAS", "MEDC", "AKRA", "HRUM", "ELSA",
    "ANTM", "INCO", "MDKA", "TINS", "NCKL", "MBMA", "AMMN", "BRMS", "PSAB",
    "TLKM", "EXCL", "ISAT", "JSMR", "TOWR", "TBIG",
    "ASII", "UNTR", "GOTO", "BUKA", "EMTK",
    "BSDE", "CTRA", "SMRA", "PWON", "PANI",
    "ICBP", "INDF", "MYOR", "UNVR", "KLBF", "CPIN", "JPFA", "ACES", "AMRT",
    "BREN", "TPIA", "BRPT", "CUAN", "DEWA", "BUMI", "ENRG", "DAAZ"
]

# --- KAMUS BROKER ---
BROKER_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'CC': 'Mandiri', 'NI': 'BNI', 
    'XC': 'Ajaib', 'KK': 'Phillip', 'SQ': 'BCA', 'XL': 'Stockbit', 
    'GR': 'Panin', 'OD': 'Danareksa', 'AZ': 'Sucor', 'EP': 'MNC', 
    'DR': 'RHB', 'YJ': 'Lautandhana', 'CP': 'Valbury', 'HP': 'Henan Putihrai',
    'BK': 'JP Morgan', 'ZP': 'Maybank', 'AK': 'UBS', 'RX': 'Macquarie', 
    'KZ': 'CLSA', 'CS': 'Credit Suisse', 'DX': 'Bahana', 'BB': 'Verdhana', 
    'YU': 'CGS CIMB', 'LG': 'Trimegah', 'AI': 'UOB', 'MG': 'Semesta',
    'RF': 'Buana', 'IF': 'Samuel', 'DH': 'Sinarmas', 'XZ': 'Trimegah(R)'
}

RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'SQ', 'KK', 'NI', 'CC', 'GR', 'DR', 'YJ', 'EP']

def get_time_context():
    """
    Menentukan apakah skrip dijalankan Pagi atau Sore (WIB).
    Return: (date_str, mode_string)
    """
    # GitHub Runner pakai UTC. Kita convert ke WIB (UTC+7) manual.
    utc_now = datetime.datetime.utcnow()
    wib_now = utc_now + datetime.timedelta(hours=7)
    
    current_hour = wib_now.hour
    
    # Batas Pagi: Sebelum jam 12:00 WIB
    if current_hour < 12:
        mode = "MORNING"
        # Kalau pagi, kita mau liat data KEMARIN (Closing sebelumnya)
        target_date = wib_now - datetime.timedelta(days=1)
        # Handle Weekend mundur ke Jumat
        while target_date.weekday() > 4: 
            target_date -= datetime.timedelta(days=1)
    else:
        mode = "AFTERNOON"
        # Kalau sore (setelah market tutup), kita mau liat data HARI INI
        target_date = wib_now
        # Handle Weekend mundur ke Jumat
        while target_date.weekday() > 4: 
            target_date -= datetime.timedelta(days=1)
            
    date_str = target_date.strftime("%Y-%m-%d")
    print(f"🕒 Waktu Server (WIB): {wib_now.strftime('%H:%M')} | Mode: {mode}")
    print(f"📅 Target Analisa Data: {date_str}")
    
    return date_str, mode

def get_dynamic_universe(mode):
    """
    Mengambil data TradingView sesuai Mode Waktu.
    Pagi -> Filter by Market Cap (Data Stabil).
    Sore -> Filter by Volume (Data Trending Hari Ini).
    """
    print(f"🔄 Screening TradingView (Mode: {mode})...")
    try:
        qh = Query().select('name', 'close', 'volume', 'market_cap_basic').set_markets('indonesia')
        
        if mode == "MORNING":
            # Pagi hari volume 0, jadi kita cari Big Cap / Saham Lapis 1 & 2
            # Filter: Market Cap > 1 Triliun
            qh = qh.where(
                Column('close') >= 50,
                Column('market_cap_basic') > 1000000000000 
            ).order_by('market_cap_basic', ascending=False)
            
        else: # AFTERNOON
            # Sore hari market rame, kita cari Top Volume / Trending Stocks
            # Filter: Transaksi Aktif
            qh = qh.where(
                Column('close') >= 50,
                Column('volume') > 50000 # Minimal ada volume
            ).order_by('volume', ascending=False)

        qh = qh.limit(20)
            
        raw_data = qh.get_scanner_data()
        target_data = raw_data[1] if isinstance(raw_data, tuple) else raw_data
        
        clean_tickers = []
        for row in target_data:
            for item in row:
                if isinstance(item, str) and "IDX:" in item:
                    clean_tickers.append(item.replace("IDX:", ""))
                    break
        
        print(f"✅ TradingView dapat: {len(clean_tickers)} saham")
        return clean_tickers

    except Exception as e:
        print(f"⚠️ TradingView Skip: {e}")
        return []

def get_combined_universe(mode):
    dynamic = get_dynamic_universe(mode)
    # Gabung dan Unique
    final_list = list(set(LIQUID_STOCKS + dynamic))
    print(f"🚀 Total Universe Scan: {len(final_list)} Saham")
    return final_list

def get_3month_context(ticker):
    try:
        df = yf.download(f"{ticker}.JK", period="3mo", progress=False)
        if df.empty: return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # VWAP Calculation
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        vwap_3mo = (typical_price * df['Volume']).sum() / df['Volume'].sum()
        curr_price = df['Close'].iloc[-1]
        
        diff_pct = ((curr_price - vwap_3mo) / vwap_3mo) * 100
        
        position = "WAJAR"
        if diff_pct < -3.0: position = "DISKON"
        elif diff_pct > 7.0: position = "PREMIUM"
        
        return {"vwap": int(vwap_3mo), "curr_price": int(curr_price), "position": position}
    except Exception:
        return None

def get_broker_summary(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json", "User-Agent": "Bot/3.0"}
    params = {"date": date_str}
    
    try:
        # Rate limit safety
        time.sleep(0.15) 
        response = requests.get(url, headers=headers, params=params, timeout=5)
        data = response.json()
        
        if data.get('status') != 'success' or not data.get('data'): return None
        summary = data['data']
        
        if 'top_buyers' not in summary or 'top_sellers' not in summary: return None
        return analyze_bandar(ticker, summary['top_buyers'], summary['top_sellers'])
    except Exception:
        return None

def clean_broker(code):
    name = BROKER_MAP.get(code, "")
    short_name = " ".join(name.split()[:2])
    return f"{code}-{short_name}" if short_name else code

def analyze_bandar(ticker, buyers, sellers):
    if not buyers or not sellers: return None
    
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    b1 = buyers[0]['code']
    s1 = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    status = "Netral"
    score = 0
    
    if net_money > 0:
        status = "Akumulasi"
        score = 1
        if b1 not in RETAIL_CODES and s1 in RETAIL_CODES:
            status = "🔥 PAUS MASUK"
            score = 3
    elif net_money < 0:
        status = "Distribusi"
        score = -1
        if b1 in RETAIL_CODES:
            status = "⚠️ GUYUR RITEL" 
            score = -3
            
    return {
        "net_money": net_money,
        "score": score,
        "status": status,
        "buyer": clean_broker(b1),
        "seller": clean_broker(s1),
        "avg_daily": avg_price
    }

def format_money(val):
    val = float(val)
    if abs(val) >= 1_000_000_000: return f"{val/1_000_000_000:.1f} M"
    elif abs(val) >= 1_000_000: return f"{val/1_000_000:.0f} jt"
    return f"{val:.0f}"

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(message), max_len):
        requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i+max_len], "parse_mode": "HTML", "disable_web_page_preview": True})

def main():
    if not GOAPI_KEY:
        print("❌ GOAPI_KEY Missing")
        return

    # 1. TENTUKAN WAKTU & MODE
    date_str, mode = get_time_context()
    
    # 2. GENERATE UNIVERSE BERDASARKAN MODE
    tickers = get_combined_universe(mode)
    
    results = []
    print(f"🕵️ Scanning Bandarmology...")
    
    # 3. SCANNING LOOP
    for i, t in enumerate(tickers):
        if i % 10 == 0: print(f"Processing {i+1}/{len(tickers)}...") 
        
        flow = get_broker_summary(t, date_str)
        if not flow: continue 
        
        ctx = get_3month_context(t)
        if ctx:
            combined = {**ctx, **flow, "code": t}
        else:
            combined = {**flow, "code": t, "vwap": 0, "curr_price": 0, "position": "N/A"}
            
        results.append(combined)
            
    # 4. FILTERING (Hanya tampilkan Akumulasi)
    winners = sorted([x for x in results if x['net_money'] > 0], key=lambda x: x['net_money'], reverse=True)
    
    if not winners:
        send_telegram(f"⚠️ Report {date_str} ({mode}): Tidak ada akumulasi signifikan.")
        return

    # 5. REPORTING
    title = "🌅 MORNING BRIEFING" if mode == "MORNING" else "🌇 CLOSING BELL REPORT"
    
    msg = f"🦅 <b>{title}</b>\n"
    msg += f"📅 Data: {date_str}\n"
    msg += f"🔍 Mode: {mode} (Top {'MarketCap' if mode=='MORNING' else 'Volume'})\n"
    msg += "="*25 + "\n\n"
    
    for s in winners[:10]:
        icon = "🟢"
        if s['score'] >= 3: icon = "🐳🔥"
        
        pos_note = ""
        if s['position'] == "DISKON": pos_note = "💎 DISKON"
        elif s['position'] == "PREMIUM": pos_note = "⚠️ PREMIUM"
        else: pos_note = "✅ WAJAR"

        msg += f"<b>{s['code']}</b> {icon}\n"
        msg += f"💰 Net: <b>+{format_money(s['net_money'])}</b>\n"
        msg += f"📊 Posisi: {pos_note}\n"
        msg += f"🛒 Buy: {s['buyer']} @ {s['avg_daily']}\n"
        msg += "-"*20 + "\n"
        
    send_telegram(msg)
    print(f"✅ Report ({mode}) Sent!")

if __name__ == "__main__":
    main()
