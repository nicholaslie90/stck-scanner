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

# --- UNIVERSE SAHAM (LIQUID & VOLATILE) ---
# Kita tidak pakai TradingView scanner lagi biar tidak pernah error "0 results".
# List ini mencakup saham yang layak trading untuk modal 15jt.
STOCKS = [
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS", "ARTO", "BBTN", # Bank
    "ADRO", "PTBA", "ITMG", "PGAS", "MEDC", "AKRA", "ELSA", # Energi
    "ANTM", "INCO", "MDKA", "TINS", "NCKL", "MBMA", "AMMN", "BRMS", "PSAB", # Tambang
    "TLKM", "EXCL", "ISAT", "TOWR", # Telco
    "ASII", "UNTR", "GOTO", "BUKA", "EMTK", # Tech/Conglo
    "BSDE", "CTRA", "SMRA", "PANI", "ASRI", # Properti
    "ICBP", "INDF", "MYOR", "UNVR", "KLBF", "CPIN", "JPFA", # Consumer
    "BREN", "TPIA", "BRPT", "CUAN", "DEWA", "BUMI", "ENRG", "DAAZ", "SRTG", "DSNG" # Gorengan/High Beta
]

# --- KAMUS BROKER ---
BROKER_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'CC': 'Mandiri', 'NI': 'BNI', 'XC': 'Ajaib', 
    'KK': 'Phillip', 'SQ': 'BCA', 'XL': 'Stockbit', 'GR': 'Panin', 'OD': 'Danareksa',
    'AZ': 'Sucor', 'EP': 'MNC', 'DR': 'RHB', 'YJ': 'Lautandhana', 'CP': 'Valbury', 
    'HP': 'Henan', 'BK': 'JP Morgan', 'ZP': 'Maybank', 'AK': 'UBS', 'RX': 'Macquarie', 
    'KZ': 'CLSA', 'CS': 'Credit Suisse', 'DX': 'Bahana', 'BB': 'Verdhana', 'YU': 'CGS', 
    'LG': 'Trimegah', 'AI': 'UOB', 'MG': 'Semesta', 'RF': 'Buana', 'IF': 'Samuel', 'DH': 'Sinarmas'
}
RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'SQ', 'KK', 'NI', 'CC', 'GR', 'DR', 'EP']

def get_time_mode():
    """Menentukan Pagi (Plan) atau Sore (Summary)"""
    # Server Github = UTC. WIB = UTC+7.
    utc_now = datetime.datetime.utcnow()
    wib_now = utc_now + datetime.timedelta(hours=7)
    
    # Batas jam 12 Siang WIB
    if wib_now.hour < 12:
        # PAGI: Kita butuh data KEMARIN (H-1) untuk plan hari ini
        date_target = wib_now - datetime.timedelta(days=1)
        while date_target.weekday() > 4: date_target -= datetime.timedelta(days=1)
        return "MORNING", date_target.strftime("%Y-%m-%d")
    else:
        # SORE: Kita butuh data HARI INI
        date_target = wib_now
        while date_target.weekday() > 4: date_target -= datetime.timedelta(days=1)
        return "AFTERNOON", date_target.strftime("%Y-%m-%d")

def get_broker_flow(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json"}
    try:
        time.sleep(0.1) # Rate limit friendly
        res = requests.get(url, headers=headers, params={"date": date_str}, timeout=5)
        data = res.json()
        if data.get('status') == 'success' and data.get('data'):
            d = data['data']
            if 'top_buyers' in d and 'top_sellers' in d:
                return d['top_buyers'], d['top_sellers']
    except: pass
    return [], []

def get_technicals(ticker):
    """Ambil data harga penutupan & VWAP sederhana"""
    try:
        df = yf.download(f"{ticker}.JK", period="5d", progress=False)
        if df.empty: return None
        
        # Flatten columns
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        
        close = df['Close'].iloc[-1]
        prev_close = df['Close'].iloc[-2]
        change = ((close - prev_close)/prev_close)*100
        
        # Simple VWAP (Typical Price * Vol) / Vol sum over 5 days
        typ = (df['High'] + df['Low'] + df['Close']) / 3
        vwap = (typ * df['Volume']).sum() / df['Volume'].sum()
        
        return {"close": int(close), "change": change, "vwap": int(vwap)}
    except: return None

def analyze_stock(ticker, date_str):
    # 1. Get Bandarmology
    buyers, sellers = get_broker_flow(ticker, date_str)
    if not buyers: return None
    
    # Hitung Net Money
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    top_buy = buyers[0]['code']
    top_sell = sellers[0]['code']
    avg_bandar = int(float(buyers[0]['avg_price']))
    
    # 2. Get Technicals
    tech = get_technicals(ticker)
    if not tech: 
        # Fallback kalau YF error
        tech = {"close": avg_bandar, "change": 0.0, "vwap": avg_bandar}
    
    # 3. GENERATE REASONING / NARRATIVE
    reasoning = []
    score = 0
    
    # Analisa Bandar
    if net_money > 1_000_000_000: # Akumulasi > 1 Milyar
        score += 2
        if top_buy not in RETAIL_CODES and top_sell in RETAIL_CODES:
            reasoning.append("🐳 **PAUS MASUK:** Institusi tampung barang Ritel.")
            score += 2
        else:
            reasoning.append("✅ **AKUMULASI:** Net Buy positif signifikan.")
    elif net_money < -1_000_000_000:
        score -= 2
        reasoning.append("⚠️ **DISTRIBUSI:** Tekanan jual besar.")
    
    # Analisa Harga vs Bandar
    if tech['close'] < avg_bandar:
        reasoning.append(f"💎 **DISKON:** Harga close ({tech['close']}) di bawah modal Bandar ({avg_bandar}).")
        score += 1
    elif tech['close'] > avg_bandar * 1.05:
        reasoning.append("⚠️ **PREMIUM:** Harga sudah lari jauh dari modal Bandar.")
        score -= 1
        
    # Formatting
    buyer_name = BROKER_MAP.get(top_buy, top_buy)
    seller_name = BROKER_MAP.get(top_sell, top_sell)
    
    return {
        "code": ticker,
        "score": score,
        "net_money": net_money,
        "close": tech['close'],
        "change": tech['change'],
        "avg_bandar": avg_bandar,
        "buyer": f"{top_buy}-{buyer_name}",
        "seller": f"{top_sell}-{seller_name}",
        "reasoning": reasoning
    }

def format_money(val):
    v = abs(val)
    if v >= 1_000_000_000: return f"{val/1_000_000_000:.1f}M"
    return f"{val/1_000_000:.0f}jt"

def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Chunking untuk pesan panjang
    for i in range(0, len(message), 4000):
        requests.post(url, json={"chat_id": CHAT_ID, "text": message[i:i+4000], "parse_mode": "Markdown"})

def main():
    if not GOAPI_KEY: return
    
    mode, date_str = get_time_mode()
    print(f"Running Mode: {mode} for Date: {date_str}")
    
    results = []
    for i, t in enumerate(STOCKS):
        if i % 5 == 0: print(f"Scanning {t}...")
        res = analyze_stock(t, date_str)
        if res: results.append(res)
        
    # Sorting Strategy
    # Morning: Cari Score Tertinggi (Akumulasi + Diskon)
    # Afternoon: Cari Top Akumulasi & Top Distribusi (Summary)
    results.sort(key=lambda x: x['score'], reverse=True)
    
    if not results:
        send_telegram("⚠️ Market Data Error / Libur.")
        return

    # --- MEMBUAT LAPORAN (REPORTING) ---
    
    if mode == "MORNING":
        msg = f"☕ *MORNING TRADING INSIGHT*\n"
        msg += f"📅 Data Closing: {date_str}\n"
        msg += f"_Rekomendasi Saham Pantauan Hari Ini_\n\n"
        
        # Ambil Top 5 Terbaik
        for s in results[:5]:
            icon = "🔥" if s['score'] >= 4 else "✅"
            reasons = "\n".join([f"  • {r}" for r in s['reasoning']])
            
            msg += f"*{s['code']}* ({s['change']:+.1f}%) {icon}\n"
            msg += f"💰 Net: `{format_money(s['net_money'])}`\n"
            msg += f"🎯 Entry Area: *{s['avg_bandar']} - {s['close']}*\n"
            msg += f"🛒 *{s['buyer']}* (Buyer Utama)\n"
            msg += f"{reasons}\n"
            msg += "----------------------------\n"
            
    else: # AFTERNOON
        msg = f"🌇 *CLOSING MARKET WRAP*\n"
        msg += f"📅 {date_str}\n"
        msg += f"_Ringkasan Pergerakan Bandar Hari Ini_\n\n"
        
        msg += "🏆 *TOP ACCUMULATION (Pemenang)*\n"
        for s in results[:4]: # Top 4
            msg += f"• *{s['code']}* (+{format_money(s['net_money'])}) - {s['buyer']}\n"
        
        msg += "\n💀 *TOP DISTRIBUTION (Buangan)*\n"
        # Ambil 4 terbawah (Distribusi terbesar)
        dist_list = sorted(results, key=lambda x: x['net_money'])[:4]
        for s in dist_list:
            msg += f"• *{s['code']}* ({format_money(s['net_money'])}) - {s['seller']}\n"
            
        msg += "\n🔍 *DEEP DIVE HIGHLIGHT*\n"
        # Ambil 1 Saham Paling Menarik (Score tertinggi) untuk dibahas
        highlight = results[0]
        msg += f"*{highlight['code']}* menjadi sorotan hari ini:\n"
        msg += "\n".join([f"👉 {r}" for r in highlight['reasoning']])
        
    send_telegram(msg)
    print("Done.")

if __name__ == "__main__":
    main()
