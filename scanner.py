import requests
import os
import datetime
import time
from tradingview_screener import Query, Column

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOAPI_KEY = os.environ.get("GOAPI_KEY")

# --- KAMUS BROKER MANUAL (UPDATED) ---
# Daftar ini sudah dilengkapi (HP, YJ, CP, dll)
BROKER_MAP = {
    # RITEL / UMUM
    'YP': 'Mirae Asset', 'PD': 'Indo Premier', 'CC': 'Mandiri Sek', 
    'NI': 'BNI Sek', 'XC': 'Ajaib', 'KK': 'Phillip', 
    'SQ': 'BCA Sekuritas', 'XL': 'Stockbit', 'GR': 'Panin',
    'OD': 'BRI Danareksa', 'AZ': 'Sucor', 'EP': 'MNC Sek', 'DR': 'RHB',
    'YJ': 'Lautandhana', 'CP': 'Valbury', 'HP': 'Henan Putihrai', # <--- HP Added
    
    # INSTITUSI / ASING / BANDAR
    'BK': 'JP Morgan', 'ZP': 'Maybank', 'AK': 'UBS', 
    'RX': 'Macquarie', 'KZ': 'CLSA', 'CS': 'Credit Suisse',
    'DX': 'Bahana', 'BB': 'Verdhana', 'YU': 'CGS CIMB',
    'LG': 'Trimegah', 'AI': 'UOB Kay Hian', 'MG': 'Semesta Indovest',
    'CD': 'Mega Capital', 'RF': 'Buana Capital', 'IF': 'Samuel',
    'DH': 'Sinarmas', 'XZ': 'Trimegah (Retail)', 'BK': 'JP Morgan'
}

# Broker Ritel (Indikasi Distribusi jika mereka beli)
RETAIL_CODES = ['YP', 'PD', 'XC', 'XL', 'SQ', 'KK', 'NI', 'CC', 'GR', 'DR', 'YJ']

def get_dynamic_universe():
    """TradingView Screener: Cari saham teramai hari ini"""
    print("🔄 Screening Top Volume via TradingView...")
    try:
        # Cari saham active (Volume & Value besar)
        qh = Query() \
            .select('name', 'close', 'volume', 'Value.Traded') \
            .set_markets('indonesia') \
            .where(
                Column('close') >= 50,              # Harga diatas 50
                Column('Value.Traded') > 2000000000 # Transaksi > 2 Miliar
            ) \
            .order_by('volume', ascending=False) \
            .limit(15) 
            
        # FIX ERROR: Handle return type (Count, List) vs List
        raw_data = qh.get_scanner_data()
        
        target_data = []
        if isinstance(raw_data, tuple):
            # Jika formatnya (Total, [List Data]), ambil elemen ke-2
            target_data = raw_data[1]
        else:
            # Jika formatnya langsung List
            target_data = raw_data

        clean_tickers = []
        for row in target_data:
            # Row biasanya: ['IDX:BBRI', 4500, ...]
            # Kita ambil elemen pertama dan buang "IDX:"
            ticker_raw = row[0] if isinstance(row[0], str) else row[1] 
            if "IDX:" in str(ticker_raw):
                clean_tickers.append(ticker_raw.replace("IDX:", ""))
        
        print(f"✅ Dapat {len(clean_tickers)} saham: {clean_tickers}")
        return clean_tickers

    except Exception as e:
        print(f"⚠️ TradingView Error: {e}")
        # Fallback Universe jika TV error
        return ["BBRI", "BBCA", "BMRI", "ADRO", "TLKM", "ASII", "GOTO", "ANTM", "BRMS", "BUMI", "PANI", "BREN"]

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    max_len = 4000
    for i in range(0, len(message), max_len):
        chunk = message[i:i+max_len]
        requests.post(url, json={"chat_id": CHAT_ID, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True})

def get_broker_summary(ticker, date_str):
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    headers = {"X-API-KEY": GOAPI_KEY, "Accept": "application/json", "User-Agent": "Bot/1.0"}
    params = {"date": date_str}
    
    try:
        time.sleep(0.3) # Rate limit safety
        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json()
        
        if data.get('status') != 'success' or not data.get('data'): return None
        summary = data['data']
        
        buyers = summary.get('top_buyers', [])
        sellers = summary.get('top_sellers', [])
        
        if not buyers or not sellers: return None
        
        return analyze_bandar(ticker, buyers, sellers)
    except Exception:
        return None

def clean_broker_name(code):
    """Ubah Kode jadi Nama Pendek"""
    name = BROKER_MAP.get(code, "")
    if name:
        # Ambil 2 kata pertama saja biar rapi dan pendek
        short_name = " ".join(name.split()[:2])
        return f"{code}-{short_name}"
    return code

def analyze_bandar(ticker, buyers, sellers):
    # Hitung Net Money Flow (Top 3)
    buy_val = sum([float(x['value']) for x in buyers[:3]])
    sell_val = sum([float(x['value']) for x in sellers[:3]])
    net_money = buy_val - sell_val
    
    buyer_1_code = buyers[0]['code']
    seller_1_code = sellers[0]['code']
    avg_price = int(float(buyers[0]['avg_price']))
    
    status = "Netral"
    score = 0
    
    # Logic Bandarmology
    if net_money > 0:
        status = "Akumulasi"
        score = 1
        # Jika Top Buyer BUKAN Ritel & Top Seller ADALAH Ritel
        if buyer_1_code not in RETAIL_CODES and seller_1_code in RETAIL_CODES:
            status = "🔥 PAUS MASUK"
            score = 3
            
    elif net_money < 0:
        status = "Distribusi"
        score = -1
        # Jika Top Buyer ADALAH Ritel (Ritel nampung barang bandar)
        if buyer_1_code in RETAIL_CODES:
            status = "⚠️ DUMP KE RITEL" 
            score = -3
            
    return {
        "code": ticker,
        "net_money": net_money,
        "score": score,
        "status": status,
        "top_buyer_display": clean_broker_name(buyer_1_code),
        "top_seller_display": clean_broker_name(seller_1_code),
        "avg_price": avg_price
    }

def format_money(val):
    val = float(val)
    if abs(val) >= 1_000_000_000: return f"{val/1_000_000_000:.1f} M"
    elif abs(val) >= 1_000_000: return f"{val/1_000_000:.0f} jt"
    return f"{val:.0f}"

def get_last_trading_day():
    d = datetime.date.today()
    # Jika run hari Sabtu(5)/Minggu(6), mundur ke Jumat
    while d.weekday() > 4: d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

def main():
    if not GOAPI_KEY:
        print("❌ GOAPI_KEY Belum diset!")
        return
    
    # 1. GENERATE WATCHLIST DINAMIS
    tickers = get_dynamic_universe()
    
    date_str = get_last_trading_day()
    print(f"🕵️ Scanning {len(tickers)} saham teramai tanggal {date_str}...")
    
    results = []
    for t in tickers:
        data = get_broker_summary(t, date_str)
        if data: results.append(data)
        
    # 2. FILTERING (Hanya tampilkan yang Net Buy Positif / Akumulasi)
    winners = sorted([x for x in results if x['net_money'] > 0], key=lambda x: x['net_money'], reverse=True)
    
    if not winners:
        send_telegram_message("⚠️ Tidak ada akumulasi signifikan di Top Volume hari ini.")
        return

    # 3. REPORTING
    msg = f"📡 <b>SMART BANDAR DETECTOR</b>\n"
    msg += f"📅 {date_str} | Market Leader\n"
    msg += "="*25 + "\n\n"
    
    # Tampilkan Top 10
    for s in winners[:10]:
        icon = "🟢"
        if s['score'] >= 3: icon = "🐳🔥"
        
        msg += f"<b>{s['code']}</b> {icon}\n"
        msg += f"💰 Net: <b>+{format_money(s['net_money'])}</b>\n"
        msg += f"🛒 Buy: <b>{s['top_buyer_display']}</b>\n"
        msg += f"   Avg: {s['avg_price']}\n"
        msg += f"📦 Sell: {s['top_seller_display']}\n"
        msg += f"📊 {s['status']}\n"
        msg += "-"*20 + "\n"
        
    send_telegram_message(msg)
    print("Report Sent!")

if __name__ == "__main__":
    main()
