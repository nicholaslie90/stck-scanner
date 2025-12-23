import requests
import os
import datetime
import yfinance as yf
import math

# --- CONFIGURATION ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
SOURCE_FILE = "watchlist.txt"

def load_targets():
    """Load daftar saham dari watchlist.txt"""
    if not os.path.exists(SOURCE_FILE): return []
    with open(SOURCE_FILE, 'r') as f:
        # Bersihkan text dan pastikan format benar
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def push_notification(msg):
    """Kirim pesan ke Telegram"""
    if not TG_TOKEN or not TG_CHAT: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    # Chunking pesan panjang
    for i in range(0, len(msg), 4000):
        try: 
            requests.post(url, json={"chat_id": TG_CHAT, "text": msg[i:i+4000], "parse_mode": "Markdown"})
        except Exception as e:
            print(f"Telegram Error: {e}")

def format_val(v):
    """Format angka milyaran/jutaan"""
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M"
    return str(int(v))

def analyze_market(tickers):
    print(f"⚡ Screening {len(tickers)} stocks via YFinance...")
    
    # Tambahkan .JK untuk Yahoo Finance
    yf_tickers = [f"{t}.JK" for t in tickers]
    
    try:
        # Download data hari ini (Intraday)
        # Gunakan threads=True untuk mempercepat download
        df = yf.download(yf_tickers, period="1d", group_by='ticker', progress=False, threads=True)
    except Exception as e:
        print(f"⚠️ YFinance Connection Error: {e}")
        return []

    candidates = []
    
    for t in tickers:
        try:
            # Handle struktur data YFinance (MultiIndex)
            if len(tickers) == 1:
                data = df
            else:
                data = df[f"{t}.JK"]
            
            if data.empty: continue
            
            # Ambil candle terakhir
            # iloc[-1] mengambil data paling update (realtime/closing)
            high = float(data['High'].iloc[-1])
            low = float(data['Low'].iloc[-1])
            close = float(data['Close'].iloc[-1])
            open_price = float(data['Open'].iloc[-1])
            vol = float(data['Volume'].iloc[-1])
            
            # Skip saham suspensi (Volume 0 atau Open 0)
            if open_price == 0 or vol == 0 or high == low: continue
            
            # --- LOGIC SCALPER ---
            
            # 1. Swing (%) = Seberapa lebar range hari ini
            # Rumus: (High - Low) / Low
            swing_pct = ((high - low) / low) * 100
            
            # 2. Value Transaksi (Estimasi)
            value_tx = close * vol
            
            # 3. Posisi Harga (0.0 = Low, 1.0 = High)
            # Ini penting untuk tau apakah harga lagi di pucuk atau di dasar
            range_price = high - low
            pos_score = (close - low) / range_price if range_price > 0 else 0.5
            
            # --- FILTERING ---
            # Swing minimal 1.5% (biar ada gerak)
            # Value minimal 1 Miliar (biar liquid)
            if swing_pct >= 1.5 and value_tx >= 1_000_000_000:
                
                # Filter tambahan: Buang saham yang diam di tengah (0.4 - 0.6)
                # KECUALI swingnya sangat besar (> 5%)
                is_boring = 0.4 < pos_score < 0.6
                if is_boring and swing_pct < 5.0:
                    continue 

                candidates.append({
                    'id': t,
                    'swing': swing_pct,
                    'price': close,
                    'high': high,
                    'low': low,
                    'value_tx': value_tx,
                    'change': ((close - open_price) / open_price) * 100,
                    'pos_score': pos_score
                })
        except Exception: 
            continue
            
    # Sorting: Kombinasi Swing Lebar & Value Besar
    # Kita pakai Logaritma Value supaya saham big cap tidak mendominasi
    candidates.sort(key=lambda x: (x['swing'] * math.log(x['value_tx'])), reverse=True)
    
    return candidates[:15] # Ambil Top 15

def main():
    targets = load_targets()
    if not targets:
        print("❌ Watchlist kosong atau file tidak ditemukan.")
        return

    results = analyze_market(targets)
    
    if not results:
        print("⚠️ Tidak ada saham yang lolos filter volatilitas hari ini.")
        return

    # --- REPORTING ---
    wib_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=7)).strftime('%H:%M')
    
    txt = f"⚡ *SCALPER VOLATILITY SCAN* ⚡\n"
    txt += f"⏱️ Time: {wib_time} WIB\n"
    txt += f"_Filter: Swing > 1.5% & Active_\n\n"
    
    for s in results:
        # Icon Arah Harga
        icon = "⚪"
        if s['change'] > 0: icon = "🟢" # Naik
        elif s['change'] < 0: icon = "🔴" # Turun
        
        # Indikator Posisi Harga (Visual Bar)
        # 🔥 = Near High (Breakout/Strong)
        # 🔻 = Near Low (Rebound/Dip Buy)
        pos_info = "Mid"
        if s['pos_score'] >= 0.8: pos_info = "🔥 *Near High*"
        elif s['pos_score'] <= 0.2: pos_info = "🔻 *Near Low*"
        
        txt += f"*{s['id']}* {icon} (Chg: {s['change']:+.1f}%)\n"
        txt += f"🌊 Swing: *{s['swing']:.1f}%* | Val: {format_val(s['value_tx'])}\n"
        txt += f"📍 Pos: {pos_info}\n"
        txt += f"📏 Range: {int(s['low'])} - {int(s['high'])}\n"
        txt += f"🎯 Curr: {int(s['price'])}\n"
        txt += "----------------------------\n"
        
    push_notification(txt)
    print("✅ Report Sent!")

if __name__ == "__main__":
    main()
