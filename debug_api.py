import os
import requests
import datetime

def test_connection():
    # 1. Cek Apakah Key Terbaca
    api_key = os.environ.get("GOAPI_KEY")
    
    print("--- DIAGNOSTIC START ---")
    if not api_key:
        print("❌ CRITICAL: GOAPI_KEY is None! Cek GitHub Secrets & YAML file.")
        return
    else:
        # Tampilkan 4 karakter pertama key untuk memastikan bukan string kosong/salah
        print(f"✅ API Key detected: {api_key[:4]}****")

    # 2. Setup Parameter (Pakai Hardcode BBCA biar pasti)
    ticker = "BBCA"
    # Ambil tanggal kemarin (karena hari ini market jalan/belum closing data mungkin belum ready)
    # Gunakan tanggal pasti hari kerja terakhir (misal 18 Des 2024) agar tidak error hari libur
    date_check = "2024-12-18" 
    
    url = f"https://api.goapi.io/stock/idx/{ticker}/broker_summary"
    
    headers = {
        "X-API-KEY": api_key,
        "Accept": "application/json",
        "User-Agent": "Python-Debug/1.0"
    }
    
    params = {"date": date_check}
    
    print(f"📡 Sending Request to: {url}")
    print(f"📅 Date Param: {date_check}")
    
    try:
        response = requests.get(url, headers=headers, params=params)
        
        print(f"🔄 HTTP Status Code: {response.status_code}")
        
        # 3. Analisa Response
        if response.status_code == 200:
            data = response.json()
            print("✅ SUCCESS! Connected to GoAPI.")
            print("Response Data Sample:", str(data)[:200]) # Print 200 char pertama
        elif response.status_code == 401:
            print("❌ ERROR 401: Unauthorized. API Key Anda salah atau expired.")
        elif response.status_code == 403:
            print("❌ ERROR 403: Forbidden. Mungkin paket Anda habis atau IP di-block.")
        elif response.status_code == 404:
            print("❌ ERROR 404: Endpoint URL salah / Ticker tidak ditemukan.")
        else:
            print("❌ UNKNOWN ERROR:")
            print(response.text)
            
    except Exception as e:
        print(f"❌ CONNECTION ERROR: {e}")

if __name__ == "__main__":
    test_connection()
