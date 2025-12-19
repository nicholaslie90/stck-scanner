import requests
import os
import datetime
import time
import json

# --- CONFIGURATION (OBFUSCATED) ---
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")

# Hidden API Credentials
API_KEY = os.environ.get("CORE_API_KEY")
API_URL = os.environ.get("CORE_API_URL") 
API_HOST = os.environ.get("CORE_API_HOST")

SOURCE_FILE = "watchlist.txt"
AUTH_ALERT_SENT = False

# --- CLASSIFICATION ---
AGENT_ALPHA = [
    'BK', 'AK', 'ZP', 'MG', 'BB', 'RX', 'KZ', 'CC', 'LG', 'YU', 
    'DX', 'CS', 'AI', 'CD', 'RF', 'AZ'
]
AGENT_BETA = [
    'YP', 'PD', 'XC', 'XL', 'KK', 'SQ', 'NI', 'GR', 'EP'
]

ENTITY_MAP = {
    'YP': 'Mirae', 'PD': 'IndoPremier', 'XC': 'Ajaib', 'XL': 'Stockbit', 
    'SQ': 'BCA', 'NI': 'BNI', 'KK': 'Phillip', 'CC': 'Mandiri', 
    'DR': 'RHB', 'OD': 'Danareksa', 'AZ': 'Sucor', 'MG': 'Semesta', 
    'BK': 'JP Morgan', 'AK': 'UBS', 'ZP': 'Maybank', 'KZ': 'CLSA', 
    'RX': 'Macquarie', 'BB': 'Verdhana', 'AI': 'UOB', 'YU': 'CGS', 
    'LG': 'Trimegah', 'RF': 'Buana', 'IF': 'Samuel', 'CP': 'Valbury', 
    'HP': 'Henan', 'YJ': 'Lautandhana'
}

def load_targets():
    if not os.path.exists(SOURCE_FILE): return []
    with open(SOURCE_FILE, 'r') as f:
        return list(set([line.strip().upper().replace(".JK", "") for line in f.readlines() if line.strip()]))

def get_time_window():
    utc_now = datetime.datetime.utcnow()
    local_now = utc_now + datetime.timedelta(hours=7)
    
    # Logic: Jika pagi (sebelum jam 10), ambil data KEMARIN
    if local_now.hour < 10: 
        ref_date = local_now - datetime.timedelta(days=1)
    else: 
        ref_date = local_now

    # Mundur jika weekend
    while ref_date.weekday() > 4: 
        ref_date -= datetime.timedelta(days=1)
    
    current_str = ref_date.strftime("%Y-%m-%d")
    past_date = ref_date - datetime.timedelta(days=90)
    past_str = past_date.strftime("%Y-%m-%d")
    
    return current_str, past_str

def push_notification(msg):
    if not TG_TOKEN or not TG_CHAT: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for i in range(0, len(msg), 4000):
        try:
            requests.post(url, json={"chat_id": TG_CHAT, "text": msg[i:i+4000], "parse_mode": "Markdown"})
        except: pass

def trigger_auth_alert():
    global AUTH_ALERT_SENT
    if AUTH_ALERT_SENT: return
    msg = "⚠️ *SYSTEM ALERT: SYNC FAILURE* ⚠️\nGateway returned: `401 Unauthorized`.\nPlease rotate the `CORE_API_KEY`."
    push_notification(msg)
    AUTH_ALERT_SENT = True

def query_external_source(target_id, start_dt, end_dt):
    if not API_URL or not API_KEY: return None
    global AUTH_ALERT_SENT
    if AUTH_ALERT_SENT: return None

    endpoint = f"{API_URL}/{target_id}"
    params = {
        "from": start_dt, "to": end_dt,
        "transaction_type": "TRANSACTION_TYPE_NET",
        "market_board": "MARKET_BOARD_REGULER",
        "investor_type": "INVESTOR_TYPE_ALL",
        "limit": 20
    }
    headers = {
        'accept': 'application/json',
        'authorization': f'Bearer {API_KEY}',
        'user-agent': 'Mozilla/5.0 (Macintosh)', 
        'origin': API_HOST,
        'referer': f"{API_HOST}/"
    }

    try:
        time.sleep(0.5) 
        res = requests.get(endpoint, headers=headers, params=params, timeout=10)
        
        if res.status_code == 401:
            trigger_auth_alert()
            return None

        if res.status_code == 200:
            payload = res.json()
            if 'data' in payload: return payload['data']
    except: pass
    return None

def normalize_data(raw_data):
    """
    Fungsi Helper: Membersihkan format data dari API agar siap dihitung.
    Menangani format Dictionary (Stockbit) maupun List.
    """
    # 1. Jika data kosong
    if not raw_data: 
        return []

    # 2. Jika data sudah berupa List (Format lama/bersih)
    if isinstance(raw_data, list):
        return raw_data

    # 3. Jika data berupa Dictionary (Format Stockbit API)
    if isinstance(raw_data, dict):
        clean_list = []
        # Ambil dari key 'broker_summary' -> 'brokers_buy' / 'brokers_sell'
        summary = raw_data.get('broker_summary', {})
        
        if not summary: return []

        # Proses BUYERS
        for b in summary.get('brokers_buy', []):
            clean_list.append({
                'broker_code': b.get('netbs_broker_code'),
                'value': float(b.get('bval', 0)),
                'average_price': float(b.get('netbs_buy_avg_price', 0))
            })
            
        # Proses SELLERS (Value dijadikan negatif)
        for s in summary.get('brokers_sell', []):
            val = float(s.get('sval', 0))
            clean_list.append({
                'broker_code': s.get('netbs_broker_code'),
                'value': -abs(val), # Pastikan negatif
                'average_price': float(s.get('netbs_sell_avg_price', 0))
            })
            
        return clean_list

    return []

def process_smart_money(raw_data):
    # Panggil fungsi normalisasi dulu biar aman
    transactions = normalize_data(raw_data)
    
    if not transactions: return None

    alpha_net = 0 
    beta_net = 0  
    
    top_buyer = {'id': '-', 'val': 0, 'avg': 0}
    top_seller = {'id': '-', 'val': 0}

    # Sorting
    try:
        sorted_by_val = sorted(transactions, key=lambda x: abs(x['value']), reverse=True)
    except: return None
    
    if sorted_by_val:
        b_node = [x for x in sorted_by_val if x['value'] > 0]
        if b_node:
            top_buyer = {
                'id': b_node[0]['broker_code'],
                'val': b_node[0]['value'],
                'avg': b_node[0]['average_price']
            }
        s_node = [x for x in sorted_by_val if x['value'] < 0]
        if s_node:
            top_seller = {
                'id': s_node[0]['broker_code'],
                'val': abs(s_node[0]['value'])
            }

    for row in transactions:
        code = row.get('broker_code')
        val = row.get('value', 0)
        
        if code in AGENT_ALPHA:
            alpha_net += val
        elif code in AGENT_BETA:
            beta_net += val

    score = 0
    tags = []
    
    # Scoring Logic
    if alpha_net > 1_000_000_000:
        score += 3
        tags.append("ALPHA_IN")
    elif alpha_net > 200_000_000:
        score += 1
        
    if beta_net < -500_000_000: 
        score += 2 
        tags.append("BETA_OUT")
    elif beta_net > 1_000_000_000:
        score -= 3 
        tags.append("BETA_FOMO")
        
    if top_buyer['id'] in AGENT_ALPHA: score += 2
    elif top_buyer['id'] in AGENT_BETA: score -= 2

    direction = "NEUTRAL"
    if score >= 3: direction = "ACCUMULATION"
    elif score <= -2: direction = "DISTRIBUTION"

    return {
        "score": score,
        "direction": direction,
        "alpha_net": alpha_net,
        "beta_net": beta_net,
        "top_buy": top_buyer,
        "top_sell": top_seller,
        "tags": tags
    }

def format_val(v):
    if abs(v) >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
    if abs(v) >= 1_000_000: return f"{v/1_000_000:.0f}M"
    return str(int(v))

def resolve_name(code):
    return f"{code}-{ENTITY_MAP.get(code, '')}"

def main():
    if not API_KEY: return

    curr_dt, long_dt = get_time_window()
    targets = load_targets()
    
    print(f"🚀 Running Sync for {curr_dt}")
    
    output_buffer = []

    for item in targets:
        if AUTH_ALERT_SENT: break 
        
        print(f"Scanning {item}...")
        
        # Query Data
        raw_d = query_external_source(item, curr_dt, curr_dt)
        raw_t = query_external_source(item, long_dt, curr_dt)
        
        # Process Data
        d_res = process_smart_money(raw_d)
        t_res = process_smart_money(raw_t)
        
        # Hanya masukkan ke report jika ada aktivitas (Net Alpha != 0 atau Score != 0)
        # Ini untuk menghindari output 0 semua di Telegram
        if d_res and (d_res['alpha_net'] != 0 or d_res['beta_net'] != 0):
            final_score = d_res['score']
            if t_res and t_res['direction'] == 'ACCUMULATION':
                final_score += 1
                
            output_buffer.append({
                "id": item,
                "rank": final_score,
                "d": d_res,
                "t": t_res
            })
        else:
            print(f"   -> Skipped {item} (No significant flow/Zero data)")

    if AUTH_ALERT_SENT: 
        print("⛔ Auth failed. Notification sent.")
        return

    output_buffer.sort(key=lambda x: x['rank'], reverse=True)
    
    if not output_buffer: 
        print("⚠️ No valid data found for report.")
        return

    txt = f"🧠 *SMART FLOW INSIGHT* 🧠\n"
    txt += f"📅 {curr_dt}\n"
    txt += f"_Tracking Alpha Agents_\n\n"
    
    for obj in output_buffer:
        d = obj['d']
        
        icon = "⚪"
        if d['score'] >= 5: icon = "🐳🔥" 
        elif d['score'] >= 3: icon = "🟢"
        elif d['score'] <= -2: icon = "🔴"
        
        buy_agent = resolve_name(d['top_buy']['id'])
        sell_agent = resolve_name(d['top_sell']['id'])
        
        alpha_flow = format_val(d['alpha_net'])
        beta_flow = format_val(d['beta_net'])
        
        trend_icon = "↗️" if obj['t'] and obj['t']['direction'] == 'ACCUMULATION' else "➡️"
        
        txt += f"*{obj['id']}* {icon}\n"
        txt += f"🧠 Alpha: `{alpha_flow}` | 👥 Beta: `{beta_flow}`\n"
        txt += f"🛒 Buyer: {buy_agent} @ {int(d['top_buy']['avg'])}\n"
        txt += f"📦 Seller: {sell_agent}\n"
        txt += f"📊 Trend: {trend_icon}\n"
        txt += "----------------------------\n"
        
    push_notification(txt)
    print("✅ Done.")

if __name__ == "__main__":
    main()
