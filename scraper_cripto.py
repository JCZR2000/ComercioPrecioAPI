"""Scraper del Mercado cripto de Tasa3 -> cripto.json (cada 15 min) y cripto_diario.json (1 vez al día).

Fuente: API pública de datos de mercado de Binance (solo lectura, sin clave).
Uso local: python -I scraper_cripto.py --dry-run  (imprime los JSON y su tamaño, no escribe en GitHub)
"""
import base64
import json
import sys
from datetime import datetime, timezone

import requests

COINS = [("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("BNB", "BNB"), ("SOL", "Solana"),
         ("XRP", "XRP"), ("DOGE", "Dogecoin"), ("TON", "Toncoin"), ("TRX", "TRON")]
BASE = "https://data-api.binance.vision/api/v3"
FILE_LIVE = "cripto.json"
FILE_DAILY = "cripto_diario.json"
RAW = "https://raw.githubusercontent.com/JCZR2000/ComercioPrecioAPI/main/"


def r6(x):
    """6 cifras significativas: pesa poco y no pierde precisión útil."""
    return float(f"{float(x):.6g}")


def get(path, **params):
    r = requests.get(f"{BASE}/{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_live():
    """Devuelve la lista de monedas con sus datos de 24 h y 168 cierres por hora, o None si algo falla."""
    symbols = json.dumps([f"{c}USDT" for c, _ in COINS], separators=(",", ":"))
    tickers = {t["symbol"]: t for t in get("ticker/24hr", symbols=symbols)}
    coins = []
    for sym, name in COINS:
        t = tickers.get(f"{sym}USDT")
        h1 = [r6(k[4]) for k in get("klines", symbol=f"{sym}USDT", interval="1h", limit=168)]
        price = r6(t["lastPrice"]) if t else 0
        if not t or price <= 0 or len(h1) < 24:
            print(f"⚠️ {sym}: datos incompletos, no se escribe nada")
            return None
        coins.append({
            "symbol": sym, "name": name, "price": price,
            "change24h": round(float(t["priceChangePercent"]), 2),
            "high24h": r6(t["highPrice"]), "low24h": r6(t["lowPrice"]),
            "volume24h": round(float(t["quoteVolume"])), "h1": h1,
        })
    return coins


def fetch_daily():
    """{moneda: [[fecha, cierre, apertura, máximo, mínimo], ...]} de 365 días, o None si falla."""
    out = {}
    for sym, _ in COINS:
        ks = get("klines", symbol=f"{sym}USDT", interval="1d", limit=365)
        rows = [[datetime.fromtimestamp(k[0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
                 r6(k[4]), r6(k[1]), r6(k[2]), r6(k[3])] for k in ks]
        if len(rows) < 30:
            print(f"⚠️ {sym}: historia diaria incompleta, no se escribe")
            return None
        out[sym] = rows
    return out


def compact(data):
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


class Storage:
    def __init__(self):
        import os
        owner, name = os.environ["REPO_OWNER"], os.environ["REPO_NAME"]
        self.url = f"https://api.github.com/repos/{owner}/{name}/contents/"
        self.headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                        "Accept": "application/vnd.github.v3+json"}

    def get(self, file_name):
        r = requests.get(self.url + file_name, headers=self.headers, timeout=20)
        if r.status_code != 200:
            return None, None
        c = r.json()
        try:
            return json.loads(base64.b64decode(c["content"]).decode("utf-8")), c.get("sha")
        except ValueError:
            return None, c.get("sha")

    def put(self, file_name, data, sha, message):
        body = {"message": message, "content": base64.b64encode(compact(data).encode()).decode()}
        if sha:
            body["sha"] = sha
        r = requests.put(self.url + file_name, headers=self.headers, json=body, timeout=30)
        print(("✅ " if r.status_code in (200, 201) else "❌ ") + f"{file_name}: {r.status_code}")


def previous_raw(file_name):
    try:
        r = requests.get(RAW + file_name, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def main():
    dry = "--dry-run" in sys.argv
    storage = None if dry else Storage()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        coins = fetch_live()
    except Exception as e:  # red, 451, 429...: se conserva el archivo anterior
        print(f"⚠️ Binance no respondió ({e}); se conserva el archivo anterior")
        return
    if coins is None:
        return
    live = {"updated": stamp, "source": "binance", "coins": coins}

    prev_daily, daily_sha = (previous_raw(FILE_DAILY), None) if dry else storage.get(FILE_DAILY)
    today = now.strftime("%Y-%m-%d")
    daily = None
    if (prev_daily or {}).get("updated", "")[:10] != today:
        try:
            coins_daily = fetch_daily()
        except Exception as e:
            print(f"⚠️ Historia diaria falló ({e}); se conserva la anterior")
            coins_daily = None
        if coins_daily:
            daily = {"updated": stamp, "coins": coins_daily}

    if dry:
        for name, d in ((FILE_LIVE, live), (FILE_DAILY, daily)):
            if d:
                print(f"{name}: {len(compact(d)) / 1024:.1f} KB")
        print(compact(live)[:600] + "...")
        return

    _, live_sha = storage.get(FILE_LIVE)
    storage.put(FILE_LIVE, live, live_sha, "Actualización cripto")
    if daily:
        storage.put(FILE_DAILY, daily, daily_sha, "Actualización cripto diario")


if __name__ == "__main__":
    main()
