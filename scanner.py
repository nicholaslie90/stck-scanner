import requests
import os
import datetime
import time
import pandas as pd
import yfinance as yf

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")
WATCHLIST_FILE = "watchlist.txt"

# --- KAMUS BROKER (MAPPING) ---
BROKER_MAP = {
    'YP': 'Mirae (Ritel)', 'PD': 'IndoPremier (Ritel)', 'XC': 'Ajaib (Ritel)', 
    'XL': 'Stockbit (Ritel)', 'SQ': 'BCA Sekuritas', 'NI': 'BNI Sekuritas',
    'KK': 'Phillip (Ritel)', 'CC': 'Mandiri', 'DR': 'RHB', 'OD': 'Danareksa',
    'AZ': 'Sucor', 'MG': 'Semesta (Bandar)', 'BK': 'JP Morgan', 'AK': 'UBS', 
    'ZP': 'Maybank', 'KZ': 'CLSA', 'RX': 'Macquarie', 'BB': 'Verdhana', 
    'AI': 'UOB', 'YU': 'CGS CIMB', 'LG': 'Trimegah', 'RF': 'Buana', 
    'IF': 'Samuel', 'CP': 'Valbury', 'HP': 'Henan Putihrai', 'YJ': 'Lautandhana'
}

# Broker Ritel Murni (Indikasi FOMO jika mereka Top Buyer)
RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'KK', 'CC', 'NI']

def get_my_watchlist():
    """Membaca file watchlist.txt dari repo"""
    if not os.path.exists(WATCHLIST_FILE):
        print(f"⚠️ Warning: {WATCHLIST_FILE} tidak ditemukan. Menggunakan default.")
        return ["BBCA", "BBRI", "BMRI", "ADRO", "TLKM", "ASII", "GOTO", "ANTM"]
    
    with open(WATCHLIST_FILE, 'r') as f:
        # Bersihkan format: Hapus spasi, enter, dan .JK jika user menulisnya
        # GoAPI butuh "BBCA", YFinance butuh "BBCA.JK" (nanti kita handle)
        tickers = [line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]
    
    print(f"📋 Loaded {len(tickers)} stocks from watchlist.")
    return list(set(tickers)) # Hapus duplikat jika ada

def get_target_date():
    """
    Logika Waktu:
    - Pagi (< 12:00 WIB) -> Data Closing Kemarin (Plan Hari Ini)
    - Sore (> 12:00 WIB) -> Data Closing Hari Ini (Summary)
    """
    utc_now = datetime.datetime.utcnow()
    wib_now = utc_now + datetime.timedelta(hours=7)
    
    if wib_now.hour < 12: # Mode Pagi
        target = wib_now - datetime.timedelta(days=1)
        while target.weekday() > 4: # Skip Weekend
            target -= datetime.timedelta(days=1)
        return target.strftime("%Y-%m-%d"), "PLAN (Data Kemarin)"
    else: # Mode Sore
        target = wib_now
        while target.weekday() > 4: 
            target -= datetime.timedelta(days=1)
        return target.strftime("%Y-%m-%d"), "SUMMARY (Data Hari Ini)"

def get_broker_summary(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json"}
    try:
        time.sleep(0.3) # Rate Limit Safety
        res = requests.get(url, headers=headers, params={"date": date_str}, timeout=10)
        data = res.json()
        if data.get('status') == 'success' and data.get('data'):
            return data['data']
    except Exception as e:
        print(f"   ⚠️ Error fetch {ticker}: {e}")
    return None

def analyze_flow(ticker, data):
    # Validasi Data Bandar
    if not data or 'top_buyers' not in data or 'top_sellers' not in data:
        return None

    buyers = data['top_buyers']
    sellers = data['top_sellers']
    
    if not buyers or not sellers: return None

    # --- 1. Analisa Bandarmology ---
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    top_buyer = buyers[0]['code']
    top_seller = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    score = 0
    tags = []
    
    # Logic Scoring Agresif
    if net_money > 1_000_000_000: # Akumulasi > 1 Milyar
        score += 3
        tags.append("BIG_FLOW")
    elif net_money > 200_000_000: # Akumulasi Kecil
        score += 1
    elif net_money < -500_000_000: # Distribusi
        score -= 5 
        tags.append("DISTRIBUSI")

    # Kualitas Broker
    if top_buyer in RETAIL_CODES:
        score -= 2 
        tags.append("RETAIL_BUY")
    elif top_buyer in ['BK', 'AK', 'ZP', 'MG', 'BB', 'KZ', 'RX']:
        score += 2 
        tags.append("WHALE_BUY")
        
    # Skenario Makan Ritel (Sangat Bagus)
    if top_seller in RETAIL_CODES and "WHALE_BUY" in tags:
        score += 2
        tags.append("EATING_RETAIL")

    # --- 2. Analisa Teknikal Simple (Posisi Harga) ---
    curr_price = avg_price
    change = 0
    try:
        # Download data singkat YFinance
        df = yf.download(f"{ticker}.JK", period="2d", progress=False)
        if not df.empty:
            curr_price = int(df['Close'].iloc[-1])
            prev = df['Close'].iloc[-2]
            change = ((curr_price - prev) / prev) * 100
    except:
        pass # Fallback ke harga avg bandar kalau YF gagal

    return {
        "code": ticker,
        "score": score,
        "net_money": net_money,
        "avg_price": avg_price,
        "curr_price": curr_price,
        "change": change,
        "top_buyer": top_buyer,
        "top_seller": top_seller,
        "tags": tags
    }

def format_money(val):
    if abs(val) >= 1_000_000_000: return f"{val/1_000_000_000:.1f} M"
    if abs(val) >= 1_000_000: return f"{val/1_000_000:.0f} jt"
    return str(int(val))

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Chunking message if too long
    for i in range(0, len(message), 4000):
        requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i+4000], "parse_mode": "Markdown"})

def main():
    if not GOAPI_KEY: 
        print("❌ API Key Missing")
        return

    # 1. Setup
    my_stocks = get_my_watchlist()
    date_str, mode_name = get_target_date()
    
    print(f"💀 BANDAR WATCHLIST RUNNING... Target: {date_str} ({mode_name})")
    
    results = []
    
    # 2. Scanning
    for i, ticker in enumerate(my_stocks):
        if i % 5 == 0: print(f"Scanning {ticker}...")
        res = analyze_flow(ticker, get_broker_summary(ticker, date_str))
        if res: results.append(res)
        
    # 3. Filtering & Sorting
    # Urutkan berdasarkan Score tertinggi (Akumulasi Bandar)
    winners = sorted(results, key=lambda x: x['score'], reverse=True)
    
    if not winners:
        send_telegram(f"⚠️ *Laporan {date_str}:* Data Kosong / Libur.")
        return

    # 4. Reporting
    msg = f"💀 *MY WATCHLIST INSIGHT*\n"
    msg += f"📅 Data: {date_str} | {mode_name}\n"
    msg += f"_Analisa Pergerakan Bandar Saham Anda_\n\n"
    
    for s in winners:
        # Icon Logic
        icon = "⚪" # Netral
        if s['score'] >= 3: icon = "🟢"
        if "EATING_RETAIL" in s['tags']: icon = "🐳🔥" # Sinyal Kuat
        if s['score'] < 0: icon = "🔴" # Distribusi/Jelek
        
        # Nama Broker
        b_name = BROKER_MAP.get(s['top_buyer'], s['top_buyer'])
        s_name = BROKER_MAP.get(s['top_seller'], s['top_seller'])
        
        # Posisi Harga
        posisi = "Wajar"
        if s['curr_price'] < s['avg_price']: posisi = "💎 Diskon"
        elif s['curr_price'] > s['avg_price'] * 1.05: posisi = "⚠️ Premium"
        
        msg += f"*{s['code']}* ({s['change']:+.1f}%) {icon}\n"
        msg += f"💰 Net: `{format_money(s['net_money'])}`\n"
        msg += f"🛒 Buy: *{b_name}* (Avg {s['avg_price']})\n"
        msg += f"📦 Sell: {s_name}\n"
        msg += f"📊 Posisi: {posisi}\n"
        msg += "----------------------------\n"
        
    send_telegram(msg)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
