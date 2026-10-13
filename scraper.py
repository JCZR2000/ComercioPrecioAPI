import os
import json
import time
import base64
import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURACIÓN ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Content-Type": "application/json",
    "Origin": "https://p2p.binance.com"
}

class ExchangeScraper:
    def __init__(self):
        self.data = {
        "dolar": None,
        "euro": None,
        # Binance
        "usdt": None,
        "usdt_promedio_compra": None,
        "usdt_promedio_venta": None,
        # Bybit
        "bybit_usdt": None,
        "bybit_promedio_compra": None,
        "bybit_promedio_venta": None,
        # OKX
        "okx_usdt": None,
        "okx_promedio_compra": None,
        "okx_promedio_venta": None,
        # Data Historico
        "fecha_bcv": None,
        "timestamp": 0,
        "human_date": "",
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
            response = requests.get(url, headers=HEADERS, verify=False, timeout=20)
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

            try:
                # Intentamos buscar la etiqueta oculta de Drupal que usa el BCV (suele tener el formato YYYY-MM-DD)
                fecha_elemento = soup.find("span", class_="date-display-single")
                if fecha_elemento and fecha_elemento.has_attr("content"):
                    self.data["fecha_bcv"] = fecha_elemento["content"].split("T")[0]
                else:
                    # Si falla, buscamos textualmente "Fecha Valor:" y decodificamos el texto
                    texto_fecha = soup.find(string=re.compile("Fecha Valor:"))
                    if texto_fecha:
                        # Busca el patrón: "05 Mayo 2026"
                        match = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', texto_fecha)
                        if match:
                            dia = match.group(1).zfill(2) # Rellena con 0 a la izquierda si es un solo dígito
                            mes_str = match.group(2).capitalize()
                            anio = match.group(3)
                            
                            # Diccionario para traducir el mes a número
                            meses = {
                                "Enero": "01", "Febrero": "02", "Marzo": "03", "Abril": "04",
                                "Mayo": "05", "Junio": "06", "Julio": "07", "Agosto": "08",
                                "Septiembre": "09", "Octubre": "10", "Noviembre": "11", "Diciembre": "12"
                            }
                            mes = meses.get(mes_str, "01") # Por defecto Enero si algo falla
                            
                            # Formateamos YYYY-MM-DD
                            self.data["fecha_bcv"] = f"{anio}-{mes}-{dia}"
            except Exception as e:
                print(f"Advertencia: No se pudo extraer la Fecha Valor del BCV: {e}")

        except Exception as e:
            print(f"Error BCV: {e}")

    def _fetch_binance_data(self, trade_type, rows=10):
        """
        Consulta Binance con manejo de errores mejorado.
        Reducimos rows a 10 por defecto para evitar bloqueos.
        """
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        
        payload = {
            "proMerchantAds": False,
            "page": 1,
            "rows": rows, 
            "payTypes": ["BANESCO", "MERCANTIL", "BANCO DE VENEZUELA", "TRANSFERENCIA BANCARIA"],
            "countries": ["VE"],
            "publisherType": None,
            "asset": "USDT",
            "fiat": "VES",
            "tradeType": trade_type
        }

        try:
            # Añadimos un pequeño delay aleatorio si quieres ser más pro, 
            # pero aquí el sleep en el orquestador basta.
            response = requests.post(url, json=payload, headers=HEADERS, timeout=15)
            
            if response.status_code != 200:
                print(f"⚠️ Binance Error {response.status_code}: {response.text[:100]}")
                return []

            res_json = response.json()
            
            if res_json.get("code") != "000000":
                 print(f"⚠️ Binance API Error Code: {res_json.get('code')} - {res_json.get('message')}")

            if res_json.get("data"):
                prices = [float(ad["adv"]["price"]) for ad in res_json["data"]]
                return prices
            else:
                print(f"⚠️ Binance devolvió lista vacía para {trade_type} (¿Filtros muy estrictos?)")
                
        except Exception as e:
            print(f"❌ Excepción consultando Binance ({trade_type}): {e}")
        
        return []

    def get_binance_rates(self):
        print("Consultando Binance P2P...")
        
        # 1. COMPRA (BUY)
        buy_prices = self._fetch_binance_data("BUY", rows=15)
        if buy_prices:
            self.data["usdt"] = buy_prices[0] # El mejor precio
            avg_buy = sum(buy_prices) / len(buy_prices)
            self.data["usdt_promedio_compra"] = round(avg_buy, 2)
            print(f"✅ Binance Compra: Mejor {self.data['usdt']} | Promedio {self.data['usdt_promedio_compra']}")
        
        # PAUSA TÁCTICA: Esperar 3 segundos para no saturar y evitar ban
        time.sleep(3)
        
        # 2. VENTA (SELL)
        sell_prices = self._fetch_binance_data("SELL", rows=15)
        if sell_prices:
            avg_sell = sum(sell_prices) / len(sell_prices)
            self.data["usdt_promedio_venta"] = round(avg_sell, 2)
            print(f"✅ Binance Venta: Promedio {self.data['usdt_promedio_venta']}")

    def get_bybit_rates(self):
      print("Consultando Bybit P2P...")
      url = "https://api2.bybit.com/fiat/otc/item/online"
      headers = {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          ),
          "Content-Type": "application/json",
          "Accept": "application/json",
      }

      # 1. COMPRA (side="1")
      try:
        payload_buy = {
            "userId": "",
            "tokenId": "USDT",
            "currencyId": "VES",
            "payment": [],
            "side": "1",
            "size": "10",
            "page": "1",
            "amount": "",
            "authMaker": False,
            "canTrade": False,
        }
        r = requests.post(
            url, json=payload_buy, headers=headers, timeout=12
        ).json()
        items = (r.get("result") or {}).get("items", [])
        if items:
          prices = [float(x["price"]) for x in items if "price" in x]
          self.data["bybit_usdt"] = prices[0]
          self.data["bybit_promedio_compra"] = round(
              sum(prices) / len(prices), 2
          )
          print(
              f"✅ Bybit Compra: Mejor {self.data['bybit_usdt']} | Promedio"
              f" {self.data['bybit_promedio_compra']}"
          )
      except Exception as e:
        print(f"❌ Error Bybit Compra: {e}")

      time.sleep(2)

      # 2. VENTA (side="0")
      try:
        payload_sell = {
            "userId": "",
            "tokenId": "USDT",
            "currencyId": "VES",
            "payment": [],
            "side": "0",
            "size": "10",
            "page": "1",
            "amount": "",
            "authMaker": False,
            "canTrade": False,
        }
        r = requests.post(
            url, json=payload_sell, headers=headers, timeout=12
        ).json()
        items = r.get("result", {}).get("items", [])
        if items:
          prices = [float(x["price"]) for x in items if "price" in x]
          self.data["bybit_promedio_venta"] = round(
              sum(prices) / len(prices), 2
          )
          print(f"✅ Bybit Venta: Promedio {self.data['bybit_promedio_venta']}")
      except Exception as e:
        print(f"❌ Error Bybit Venta: {e}")

    def get_okx_rates(self):
      print("Consultando OKX P2P...")
      url = "https://www.okx.com/v3/c2c/tradingOrders/books"
      headers = {
          "User-Agent": (
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          ),
          "Accept": "application/json",
          "Referer": "https://www.okx.com/es-la/p2p-markets/ves/buy-usdt",
      }

      # 1. COMPRA (side="buy")
      try:
        params_buy = {
            "quoteCurrency": "ves",
            "baseCurrency": "usdt",
            "side": "buy",
            "paymentMethod": ["BANCO DE VENEZUELA", "MERCANTIL", "BANESCO"],
            "userType": "all",
        }
        r = requests.get(
            url, headers=headers, params=params_buy, timeout=12
        ).json()
        orders = (r.get("data") or {}).get("buy", [])
        if orders:
          prices = [float(x["price"]) for x in orders[:10]]
          self.data["okx_usdt"] = prices[0]
          self.data["okx_promedio_compra"] = round(sum(prices) / len(prices), 2)
          print(
              f"✅ OKX Compra: Mejor {self.data['okx_usdt']} | Promedio"
              f" {self.data['okx_promedio_compra']}"
          )
      except Exception as e:
        print(f"❌ Error OKX Compra: {e}")

      time.sleep(2)

      # 2. VENTA (side="sell")
      try:
        params_sell = {
            "quoteCurrency": "ves",
            "baseCurrency": "usdt",
            "side": "sell",
            "paymentMethod": ["BANCO DE VENEZUELA", "MERCANTIL", "BANESCO"],
            "userType": "all",
        }
        r = requests.get(
            url, headers=headers, params=params_sell, timeout=12
        ).json()
        orders = r.get("data", {}).get("sell", [])
        if orders:
          prices = [float(x["price"]) for x in orders[:10]]
          self.data["okx_promedio_venta"] = round(sum(prices) / len(prices), 2)
          print(f"✅ OKX Venta: Promedio {self.data['okx_promedio_venta']}")
      except Exception as e:
        print(f"❌ Error OKX Venta: {e}")

class GitHubStorage:
    def __init__(self):
        self.base_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/"
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

    def get_file(self, file_name):
        sha = None
        api_url = self.base_url + file_name
        try:
            r = requests.get(api_url, headers=self.headers)
            if r.status_code == 200:
                content = r.json()
                sha = content.get('sha')
                file_content = base64.b64decode(content['content']).decode('utf-8')
                return json.loads(file_content), sha
            elif r.status_code == 404:
                print(f"El archivo {file_name} no existe aún.")
                return None, None
        except json.JSONDecodeError:
            print(f"JSON corrupto en {file_name}. Se sobrescribirá.")
            return None, sha
        except Exception as e:
            print(f"Error leyendo GitHub ({file_name}): {e}")
        return None, sha

    def update_file(self, file_name, content_data, sha=None, commit_message="Auto-update"):
        api_url = self.base_url + file_name
        content_str = json.dumps(content_data, indent=2)
        content_b64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
        data = {
            "message": commit_message,
            "content": content_b64
        }
        if sha:
            data["sha"] = sha
            
        r = requests.put(api_url, headers=self.headers, json=data)
        if r.status_code in [200, 201]:
            print(f"✅ Archivo {file_name} actualizado correctamente.")
        else:
            print(f"❌ Error actualizando {file_name}: {r.text}")

def update_daily_p2p_history(
    storage, file_name, current_date, buy, sell, avg_buy, avg_sell, label
):
  """Mantiene y actualiza el cierre diario en el archivo histórico correspondiente."""
  if not buy:
    return

  hist_data, sha = storage.get_file(file_name)
  new_entry = {
      "date": current_date,
      "buy_rate": buy,
      "sell_rate": sell,
      "avg_buy_rate": avg_buy,
      "avg_sell_rate": avg_sell,
  }

  if isinstance(hist_data, list) and len(hist_data) > 0:
    if hist_data[-1].get("date") == current_date:
      if hist_data[-1] != new_entry:
        hist_data[-1] = new_entry
        storage.update_file(
            file_name,
            hist_data,
            sha,
            f"Auto-update: Cierre {label} ({current_date})",
        )
        print(f"✅ Cierre diario actualizado en {file_name}")
      else:
        print(f"{label} sin variaciones. Histórico intacto.")
    else:
      hist_data.append(new_entry)
      storage.update_file(
          file_name,
          hist_data,
          sha,
          f"Auto-update: Nuevo día {label} ({current_date})",
      )
      print(f"✅ Nueva fecha añadida a {file_name}")
  else:
    # El archivo no existe o contiene una lista vacía []
    print(f"Inicializando {file_name}...")
    storage.update_file(
        file_name, [new_entry], sha, f"Inicializando {file_name}"
    )

def main():
    storage = GitHubStorage()
    current_time = time.time()
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # === PARTE 1: TASAS ACTUALES (tasas_cambio.json) ===
    scraper = ExchangeScraper()
    scraper.get_bcv_rates()
    scraper.get_binance_rates()
    scraper.get_bybit_rates()
    scraper.get_okx_rates()

    scraper.data["timestamp"] = current_time
    scraper.data["human_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Resiliencia: Si algo falló, rellenar con caché
    cached_data, sha_actual = storage.get_file("tasas_cambio.json")
    if cached_data:
        keys_to_check = [
            "dolar",
            "euro",
            "usdt",
            "usdt_promedio_compra",
            "usdt_promedio_venta",
            "bybit_usdt",
            "bybit_promedio_compra",
            "bybit_promedio_venta",
            "okx_usdt",
            "okx_promedio_compra",
            "okx_promedio_venta",
        ]
        for key in keys_to_check:
            if not scraper.data.get(key) and cached_data.get(key):
                print(f"⚠️ Recuperando {key} de caché...")
                scraper.data[key] = cached_data[key]

    # Actualizar tasas_cambio.json con todas las plataformas
    storage.update_file(
      "tasas_cambio.json",
      scraper.data,
      sha_actual,
      "Auto-update: Tasas Actuales",
    )

    # === PARTE 2: HISTÓRICO BCV (base_datos_bcv.json) ===
    # Solo procedemos si el scraping del BCV fue exitoso
    if scraper.data["dolar"] and scraper.data["euro"]:
        hist_data, sha_hist = storage.get_file("base_datos_bcv.json")
        
        # Obtenemos la Fecha del BCV o, como respaldo, usamos la del servidor
        fecha_registro = scraper.data.get("fecha_bcv") or current_date
        
        if hist_data and isinstance(hist_data, list) and len(hist_data) > 0:
            last_entry = hist_data[-1]  
            last_dolar = last_entry.get("dolar")
            last_euro = last_entry.get("euro")
            
            if scraper.data["dolar"] != last_dolar or scraper.data["euro"] != last_euro:
                print(f"¡Nuevas tasas detectadas! Fecha BCV: {fecha_registro} | Dólar: {scraper.data['dolar']} | Euro: {scraper.data['euro']}")
                
                new_entry = {
                    "fecha": fecha_registro,
                    "dolar": scraper.data["dolar"],
                    "euro": scraper.data["euro"],
                    "usdt": None  
                }
                
                hist_data.append(new_entry)
                storage.update_file("base_datos_bcv.json", hist_data, sha_hist, f"Auto-update: Histórico BCV ({fecha_registro})")
            else:
                print("Las tasas del BCV no han cambiado. Histórico intacto.")
                
        elif hist_data is None:
            print(f"Archivo histórico no encontrado. Creando uno nuevo con fecha {fecha_registro}...")
            new_entry = {
                "fecha": fecha_registro,
                "dolar": scraper.data["dolar"],
                "euro": scraper.data["euro"],
                "usdt": None
            }
            storage.update_file("base_datos_bcv.json", [new_entry], sha_hist, "Inicializando base_datos_bcv.json")

    # === PARTE 3: HISTÓRICOS P2P INDEPENDIENTES ===

    # Binance P2P
    update_daily_p2p_history(
        storage,
        "binance_p2p_daily.json",
        current_date,
        scraper.data.get("usdt"),
        scraper.data.get("usdt_promedio_venta"),
        scraper.data.get("usdt_promedio_compra"),
        scraper.data.get("usdt_promedio_venta"),
        "Binance P2P",
    )

    # Bybit P2P
    update_daily_p2p_history(
        storage,
        "bybit_p2p_daily.json",
        current_date,
        scraper.data.get("bybit_usdt"),
        scraper.data.get("bybit_promedio_venta"),
        scraper.data.get("bybit_promedio_compra"),
        scraper.data.get("bybit_promedio_venta"),
        "Bybit P2P",
    )

    # OKX P2P
    update_daily_p2p_history(
        storage,
        "okx_p2p_daily.json",
        current_date,
        scraper.data.get("okx_usdt"),
        scraper.data.get("okx_promedio_venta"),
        scraper.data.get("okx_promedio_compra"),
        scraper.data.get("okx_promedio_venta"),
        "OKX P2P",
    )

    return scraper.data

if __name__ == "__main__":
    main()