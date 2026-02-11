import os
import json
import time
import base64
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import urllib3

# Desactivar advertencias de SSL inseguro (necesario para BCV)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURACIÓN ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
FILE_PATH = "tasas_cambio.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

class ExchangeScraper:
    def __init__(self):
        self.data = {
            "dolar": None,
            "euro": None,
            "usdt": None,            # Mejor precio de compra (El más barato)
            "usdt_promedio_compra": None, # Promedio de los primeros 30 (Lo que paga el usuario)
            "usdt_promedio_venta": None,  # Promedio de los primeros 30 (Lo que recibe el usuario)
            "timestamp": 0,
            "human_date": ""
        }

    def _clean_number(self, text_value):
        if not text_value:
            return None
        try:
            clean = text_value.strip().replace('.', '').replace(',', '.')
            return float(clean)
        except ValueError:
            return None

    def get_bcv_rates(self):
        url = "https://www.bcv.org.ve/"
        print("Scraping BCV...")
        try:
            response = requests.get(url, headers=HEADERS, verify=False, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            def extract_val(dom_id):
                container = soup.find(id=dom_id)
                if container:
                    val_div = container.find("div", class_="centrado")
                    if val_div:
                        strong_tag = val_div.find("strong")
                        if strong_tag:
                            return strong_tag.get_text()
                return None

            self.data["euro"] = self._clean_number(extract_val("euro"))
            self.data["dolar"] = self._clean_number(extract_val("dolar"))

        except Exception as e:
            print(f"Error BCV: {e}")

    def _fetch_binance_data(self, trade_type, rows):
        """
        Función auxiliar para consultar Binance.
        trade_type: "BUY" (El usuario compra) o "SELL" (El usuario vende)
        rows: Cantidad de anuncios a traer
        """
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        payload = {
            "proMerchantAds": False,
            "page": 1,
            "rows": rows, # Aquí definimos cuántos traemos
            "payTypes": ["BANESCO", "MERCANTIL"],
            "countries": ["VE"],
            "publisherType": None,
            "asset": "USDT",
            "fiat": "VES",
            "tradeType": trade_type
        }

        try:
            response = requests.post(url, json=payload, headers=HEADERS, timeout=10)
            res_json = response.json()
            if res_json.get("data"):
                # Extraemos solo los precios como una lista de floats
                prices = [float(ad["adv"]["price"]) for ad in res_json["data"]]
                return prices
        except Exception as e:
            print(f"Error consultando Binance ({trade_type}): {e}")
        
        return []

    def get_binance_rates(self):
        print("Consultando Binance P2P...")
        
        # 1. Obtener precios de COMPRA (Lo que el usuario paga por USDT)
        # Pedimos 30 para el promedio
        buy_prices = self._fetch_binance_data("BUY", 30)
        
        if buy_prices:
            # El mejor precio (el primero, el más barato)
            self.data["usdt"] = buy_prices[0]
            
            # Promedio de los 30 precios
            avg_buy = sum(buy_prices) / len(buy_prices)
            self.data["usdt_promedio_compra"] = round(avg_buy, 2)
            print(f"Binance Compra - Mejor: {self.data['usdt']}, Promedio (30): {self.data['usdt_promedio_compra']}")
        
        # 2. Obtener precios de VENTA (Lo que el usuario recibe por sus USDT)
        # Pedimos 30 para el promedio
        sell_prices = self._fetch_binance_data("SELL", 30)
        
        if sell_prices:
            # Promedio de los 30 precios
            avg_sell = sum(sell_prices) / len(sell_prices)
            self.data["usdt_promedio_venta"] = round(avg_sell, 2)
            print(f"Binance Venta - Promedio (30): {self.data['usdt_promedio_venta']}")

class GitHubStorage:
    def __init__(self):
        self.api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

    def get_file(self):
        sha = None
        try:
            r = requests.get(self.api_url, headers=self.headers)
            if r.status_code == 200:
                content = r.json()
                sha = content.get('sha')
                file_content = base64.b64decode(content['content']).decode('utf-8')
                return json.loads(file_content), sha
            elif r.status_code == 404:
                print("El archivo no existe aún.")
                return None, None
        except json.JSONDecodeError:
            print("JSON corrupto en GitHub. Se sobrescribirá.")
            return None, sha
        except Exception as e:
            print(f"Error GitHub: {e}")
        return None, sha

    def update_file(self, content_dict, sha=None):
        content_str = json.dumps(content_dict, indent=2)
        content_b64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
        data = {
            "message": "Auto-update: Tasas con Promedios",
            "content": content_b64
        }
        if sha:
            data["sha"] = sha
            
        r = requests.put(self.api_url, headers=self.headers, json=data)
        if r.status_code in [200, 201]:
            print("GitHub actualizado correctamente.")
        else:
            print(f"Error actualizando GitHub: {r.text}")

def main():
    storage = GitHubStorage()
    cached_data, sha = storage.get_file()
    
    current_time = time.time()
    
    scraper = ExchangeScraper()
    scraper.get_bcv_rates()
    scraper.get_binance_rates() # Ahora obtiene promedios y mejor precio
    
    scraper.data["timestamp"] = current_time
    scraper.data["human_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Resiliencia: Mantener datos viejos si fallan
    if cached_data:
        for key in ["dolar", "euro", "usdt", "usdt_promedio_compra", "usdt_promedio_venta"]:
            if not scraper.data.get(key) and cached_data.get(key):
                print(f"Recuperando {key} de caché...")
                scraper.data[key] = cached_data[key]

    storage.update_file(scraper.data, sha)
    return scraper.data

if __name__ == "__main__":
    main()