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
            "usdt": None,
            "usdt_promedio_compra": None,
            "usdt_promedio_venta": None,
            "fecha_bcv": None,
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
            "payTypes": ["BANESCO", "MERCANTIL"],
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

def main():
    storage = GitHubStorage()
    current_time = time.time()
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # === PARTE 1: TASAS ACTUALES (tasas_cambio.json) ===
    cached_data, sha_actual = storage.get_file("tasas_cambio.json")
    
    scraper = ExchangeScraper()
    scraper.get_bcv_rates()
    scraper.get_binance_rates()
    
    scraper.data["timestamp"] = current_time
    scraper.data["human_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Resiliencia: Si algo falló, rellenar con caché
    if cached_data:
        keys_to_check = ["dolar", "euro", "usdt", "usdt_promedio_compra", "usdt_promedio_venta"]
        for key in keys_to_check:
            if not scraper.data.get(key) and cached_data.get(key):
                print(f"⚠️ Recuperando {key} de caché...")
                scraper.data[key] = cached_data[key]

    storage.update_file("tasas_cambio.json", scraper.data, sha_actual, "Auto-update: Tasas Actuales")

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

    # === PARTE 3: HISTÓRICO BINANCE P2P (binance_p2p_daily.json) ===
    # Solo procedemos si obtuvimos una tasa válida de Binance
    if scraper.data.get("usdt"):
      binance_hist, sha_binance = storage.get_file("binance_p2p_daily.json")

      # Estructura idéntica al dataset consolidado
      new_binance_entry = {
          "date": current_date,
          "buy_rate": scraper.data.get("usdt"),
          "sell_rate": scraper.data.get("usdt_promedio_venta"),
          "avg_buy_rate": scraper.data.get("usdt_promedio_compra"),
          "avg_sell_rate": scraper.data.get("usdt_promedio_venta"),
      }

      if (
          binance_hist
          and isinstance(binance_hist, list)
          and len(binance_hist) > 0
      ):
        # 1. Si el último registro es de hoy, actualizamos el cierre
        if binance_hist[-1].get("date") == current_date:
          if binance_hist[-1] != new_binance_entry:
            binance_hist[-1] = new_binance_entry
            storage.update_file(
                "binance_p2p_daily.json",
                binance_hist,
                sha_binance,
                f"Auto-update: Cierre Binance P2P ({current_date})",
            )
            print(
                f"✅ Tasa de cierre actualizada para hoy ({current_date}) en"
                " binance_p2p_daily.json"
            )
          else:
            print("Tasa Binance P2P sin variaciones. Histórico intacto.")

        # 2. Si ya cambió de día calendario, agregamos la nueva fecha
        else:
          binance_hist.append(new_binance_entry)
          storage.update_file(
              "binance_p2p_daily.json",
              binance_hist,
              sha_binance,
              f"Auto-update: Nuevo día Binance P2P ({current_date})",
          )
          print(
              f"✅ Nueva jornada ({current_date}) añadida a"
              " binance_p2p_daily.json"
          )

      # 3. Si el archivo aún no estuviese en el repo, se inicializa
      elif binance_hist is None:
        print(
            "Archivo binance_p2p_daily.json no encontrado en GitHub."
            " Inicializando..."
        )
        storage.update_file(
            "binance_p2p_daily.json",
            [new_binance_entry],
            sha_binance,
            f"Inicializando binance_p2p_daily.json ({current_date})",
        )

    return scraper.data

if __name__ == "__main__":
    main()