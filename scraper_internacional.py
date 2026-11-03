"""Scraper del modo Internacional de Tasa3 -> tasas_internacionales.json.

Valores: unidades de la moneda por 1 USD (oficial, blue) o por 1 USDT (P2P).
Uso local: python scraper_internacional.py --dry-run  (imprime el JSON, no escribe en GitHub)
"""
import sys
import time
from datetime import datetime, timezone

import requests

from scraper import GitHubStorage, HEADERS

FILE_NAME = "tasas_internacionales.json"
RAW_URL = "https://raw.githubusercontent.com/JCZR2000/ComercioPrecioAPI/main/" + FILE_NAME
MONEDAS = ["BRL", "COP", "PEN", "MXN", "ARS", "CLP", "EUR"]
OFICIAL_CADA = 3500  # segundos entre consultas a la tasa oficial (algo menos de 1 h)
MIN_PRECIOS = 3  # menos que esto en Binance -> se prueba Bybit
P2P_KEYS = ["usdt_compra", "usdt_venta", "usdt_promedio_compra", "usdt_promedio_venta", "usdt_fuente"]


def fetch_oficial():
    """Devuelve ({moneda: tasa}, 'AAAA-MM-DD') o ({}, None)."""
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=15).json()
        if r.get("result") != "success":
            raise ValueError(r.get("error-type"))
        fecha = datetime.strptime(r["time_last_update_utc"], "%a, %d %b %Y %H:%M:%S %z")
        return {m: r["rates"][m] for m in MONEDAS if m in r["rates"]}, fecha.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"❌ Error oficial (open.er-api): {e}")
        return {}, None


def fetch_binance(fiat, trade_type):
    payload = {
        "proMerchantAds": False, "page": 1, "rows": 10, "payTypes": [],
        "countries": [], "publisherType": None, "asset": "USDT",
        "fiat": fiat, "tradeType": trade_type,
    }
    try:
        r = requests.post(
            "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
            json=payload, headers=HEADERS, timeout=15,
        ).json()
        return [float(a["adv"]["price"]) for a in (r.get("data") or [])]
    except Exception as e:
        print(f"❌ Binance {fiat} {trade_type}: {e}")
        return []


def fetch_bybit(fiat, side):
    payload = {
        "userId": "", "tokenId": "USDT", "currencyId": fiat, "payment": [],
        "side": side, "size": "10", "page": "1", "amount": "",
        "authMaker": False, "canTrade": False,
    }
    try:
        r = requests.post(
            "https://api2.bybit.com/fiat/otc/item/online", json=payload,
            headers={"User-Agent": HEADERS["User-Agent"], "Content-Type": "application/json"},
            timeout=12,
        ).json()
        return [float(x["price"]) for x in (r.get("result") or {}).get("items", []) if "price" in x]
    except Exception as e:
        print(f"❌ Bybit {fiat} side {side}: {e}")
        return []


def avg(prices):
    return round(sum(prices) / len(prices), 4)


def fetch_p2p(fiat):
    """Binance; si alguna lista trae < MIN_PRECIOS precios, repite ambas con Bybit.
    Devuelve dict con los campos P2P o None si no hay datos."""
    buy = fetch_binance(fiat, "BUY")
    time.sleep(2)
    sell = fetch_binance(fiat, "SELL")
    fuente = "binance"
    if len(buy) < MIN_PRECIOS or len(sell) < MIN_PRECIOS:
        time.sleep(2)
        b_buy, b_sell = fetch_bybit(fiat, "1"), None
        time.sleep(2)
        b_sell = fetch_bybit(fiat, "0")
        if len(b_buy) >= MIN_PRECIOS and len(b_sell) >= MIN_PRECIOS:
            buy, sell, fuente = b_buy, b_sell, "bybit"
    if not buy or not sell:
        return None
    return {
        "usdt_compra": buy[0], "usdt_venta": sell[0],
        "usdt_promedio_compra": avg(buy), "usdt_promedio_venta": avg(sell),
        "usdt_fuente": fuente, "usdt_timestamp": time.time(),
    }


def fetch_blue():
    try:
        r = requests.get("https://dolarapi.com/v1/dolares/blue", timeout=15).json()
        return float(r["compra"]), float(r["venta"])
    except Exception as e:
        print(f"❌ Error dólar blue: {e}")
        return None, None


def load_previous(storage, dry_run):
    if not dry_run:
        return storage.get_file(FILE_NAME)
    try:
        r = requests.get(RAW_URL, timeout=15)
        return (r.json() if r.status_code == 200 else None), None
    except Exception:
        return None, None


def main():
    import json
    dry_run = "--dry-run" in sys.argv
    storage = None if dry_run else GitHubStorage()
    previous, sha = load_previous(storage, dry_run)
    prev_monedas = (previous or {}).get("monedas", {})

    # open.er-api.com pide máx. 1 consulta por hora (si no, bloquea la IP 20 min)
    oficial_ts = (previous or {}).get("oficial_ts") or 0
    if previous and time.time() - oficial_ts < OFICIAL_CADA:
        oficiales, fecha_oficial = {}, previous.get("fecha_oficial")
        print("Oficial: consultado hace menos de 1 h, se reutiliza")
    else:
        oficiales, fecha_oficial = fetch_oficial()
        if oficiales:
            oficial_ts = time.time()
        elif previous:
            fecha_oficial = previous.get("fecha_oficial")

    monedas = {}
    for m in MONEDAS:
        prev = prev_monedas.get(m, {})
        entry = {"oficial": oficiales.get(m) or prev.get("oficial")}
        print(f"Consultando P2P {m}...")
        p2p = fetch_p2p(m)
        if p2p:
            entry.update(p2p)
        else:
            # conserva valores y marca de tiempo previos: la app sabe que son viejos
            for k in P2P_KEYS + ["usdt_timestamp"]:
                entry[k] = prev.get(k)
            print(f"⚠️ {m}: sin P2P, se conserva el valor previo")
        if m == "ARS":
            compra, venta = fetch_blue()
            entry["blue_compra"] = compra or prev.get("blue_compra")
            entry["blue_venta"] = venta or prev.get("blue_venta")
        monedas[m] = entry
        time.sleep(2)

    now = datetime.now(timezone.utc)
    data = {
        "timestamp": time.time(),
        "human_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha_oficial": fecha_oficial,
        "oficial_ts": oficial_ts,
        "monedas": monedas,
    }
    if dry_run:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    storage.update_file(FILE_NAME, data, sha, "Actualización tasas internacionales")


if __name__ == "__main__":
    main()
