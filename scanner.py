import yfinance as yf
import requests
import os

# --- CONFIGURATION ---
WATCHLIST_FILE = "watchlist.txt"  # Nama file daftar saham Anda

# Telegram Config
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_tickers_from_file():
    """Membaca daftar saham dari file teks eksternal"""
    if not os.path.exists(WATCHLIST_FILE):
        print(f"Warning: {WATCHLIST_FILE} not found! Using default list.")
        # Default fallback jika file lupa dibuat
        return ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK"]
    
    with open(WATCHLIST_FILE, 'r') as f:
        # Baca per baris, hilangkan spasi, uppercase, abaikan baris kosong
        codes = [line.strip().upper() for line in f.readlines() if line.strip()]
    
    # Tambahkan .JK jika belum ada
    tickers = [f"{code}.JK" if not code.endswith(".JK") else code for code in codes]
    print(f"Loaded {len(tickers)} stocks from {WATCHLIST_FILE}")
    return tickers

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def get_top_movers():
    # 1. Load Tickers dari File
    tickers = get_tickers_from_file()
    
    if not tickers:
        return []

    print(f"Scanning {len(tickers)} stocks...")
    
    # 2. Batch Download
    try:
        data = yf.download(tickers, period="1mo", group_by='ticker', progress=False, threads=True)
    except Exception as e:
        print(f"Download Error: {e}")
        return []

    analyzed_stocks = []

    # Handle single vs multiple tickers structure
    if len(tickers) == 1:
        iterator = [(tickers[0], data)]
    else:
        iterator = data.columns.levels[0]

    for ticker in iterator:
        try:
            df = data[ticker].dropna()
            if len(df) < 20: continue

            today = df.iloc[-1]
            prev_close = df.iloc[-2]['Close']
            
            vol_today = today['Volume']
            close_today = today['Close']
            avg_vol = df['Volume'].iloc[:-1].tail(20).mean()

            # Filter Saham Mati (Opsional: bisa Anda turunkan jika main saham third liner)
            if avg_vol < 5000: continue 

            spike_ratio = vol_today / avg_vol if avg_vol > 0 else 0
            price_change = ((close_today - prev_close) / prev_close) * 100

            analyzed_stocks.append({
                "code": ticker.replace(".JK", ""),
                "price": int(close_today),
                "change": price_change,
                "spike": spike_ratio
            })

        except Exception:
            continue

    # 3. Sorting (Top 10 Spike Tertinggi)
    sorted_stocks = sorted(analyzed_stocks, key=lambda x: x['spike'], reverse=True)
    return sorted_stocks[:10]

def main():
    top_10 = get_top_movers()
    
    if not top_10:
        print("No data found.")
        return

    msg = "🔥 *CUSTOM WATCHLIST ALERT* 🔥\n"
    msg += "_Top Volume Spike dari Daftar Pantauan Anda_\n\n"
    
    for i, stock in enumerate(top_10, 1):
        icon = "🟢" if stock['change'] > 0 else "🔴"
        if stock['spike'] > 3.0: icon = "🚀"
        
        msg += (
            f"{i}. *{stock['code']}* {icon}\n"
            f"   Spike: *{stock['spike']:.1f}x* Lipat\n"
            f"   Harga: {stock['price']} ({stock['change']:+.2f}%)\n"
        )
    
    send_telegram_message(msg)
    print("Report sent!")

if __name__ == "__main__":
    main()
