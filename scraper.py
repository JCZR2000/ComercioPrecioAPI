import os
import json
import time
import base64
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import urllib3

# Desactivar advertencias de SSL inseguro (necesario para BCV)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURACIÓN ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # Token personal de GitHub (Classic) con scope 'repo'
REPO_OWNER = os.getenv("REPO_OWNER")      # Tu usuario de GitHub
REPO_NAME = os.getenv("REPO_NAME")        # Nombre del repositorio
FILE_PATH = "tasas_cambio.json"           # Archivo donde se guardará
#CACHE_DURATION_HOURS = 4

# Headers para simular navegador real
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

class ExchangeScraper:
    def __init__(self):
        self.data = {
            "dolar": None,
            "euro": None,
            "usdt": None,
            "timestamp": 0,
            "human_date": ""
        }

    def _clean_number(self, text_value):
        """Convierte formato '123,45' a float 123.45"""
        if not text_value:
            return None
        try:
            # Eliminar espacios y cambiar coma por punto
            clean = text_value.strip().replace('.', '').replace(',', '.')
            return float(clean)
        except ValueError:
            return None

    def get_bcv_rates(self):
        """Scraping resiliente del BCV"""
        url = "https://www.bcv.org.ve/"
        print("Scraping BCV...")
        
        try:
            response = requests.get(url, headers=HEADERS, verify=False, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')

            # Lógica basada en el HTML proporcionado por el usuario
            def extract_val(dom_id):
                # Busca el div por ID, luego busca la clase 'centrado' y dentro el strong
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
            # No lanzamos excepción para permitir que Binance funcione
    
    def get_binance_rate(self):
        """Obtiene precio USDT en VES desde API P2P de Binance"""
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        payload = {
            "proMerchantAds": False,
            "page": 1,
            "rows": 1,
            "payTypes": ["BANESCO", "MERCANTIL"],
            "countries": ["VE"],
            "publisherType": None,
            "asset": "USDT",
            "fiat": "VES",
            "tradeType": "BUY" # Ojo: BUY desde la perspectiva del usuario P2P es lo que vende el anunciante
        }
        
        print("Consultando Binance...")
        try:
            response = requests.post(url, json=payload, headers=HEADERS, timeout=10)
            res_json = response.json()
            
            if res_json.get("data"):
                price_str = res_json["data"][0]["adv"]["price"]
                self.data["usdt"] = float(price_str)
                print(f"Precio Binance encontrado: {self.data['usdt']}")
        except Exception as e:
            print(f"Error Binance: {e}")

class GitHubStorage:
    def __init__(self):
        self.api_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"
        self.headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

    def get_file(self):
        """Obtiene el archivo actual y su SHA (necesario para actualizar)"""
        sha = None
        try:
            r = requests.get(self.api_url, headers=self.headers)
            if r.status_code == 200:
                content = r.json()
                sha = content.get('sha') # 1. Capturamos el SHA antes de nada
                
                # Intentamos decodificar el contenido
                file_content = base64.b64decode(content['content']).decode('utf-8')
                return json.loads(file_content), sha
                
            elif r.status_code == 404:
                print("El archivo no existe aún. Se creará uno nuevo.")
                return None, None
                
        except json.JSONDecodeError:
            print("El archivo existe pero tiene JSON inválido. Se sobrescribirá.")
            return None, sha # <--- ¡Aquí está la magia! Devolvemos el SHA para poder arreglarlo
            
        except Exception as e:
            print(f"Error accediendo a GitHub: {e}")
            
        return None, sha

    def update_file(self, content_dict, sha=None):
        """Sube el nuevo JSON a GitHub"""
        message = "Auto-update exchange rates"
        content_str = json.dumps(content_dict, indent=2)
        content_b64 = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
        
        data = {
            "message": message,
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
    
    # 1. Leemos el archivo SOLO para obtener el SHA y datos de respaldo
    # YA NO verificamos si es viejo o nuevo. Si el Cron se ejecutó, es hora de actualizar.
    cached_data, sha = storage.get_file()
    
    current_time = time.time()
    
    # 2. Scraping Incondicional
    scraper = ExchangeScraper()
    scraper.get_bcv_rates()
    scraper.get_binance_rate()
    
    scraper.data["timestamp"] = current_time
    scraper.data["human_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 3. Resiliencia: Si el scraping falló (ej. BCV caído), usamos el dato viejo
    if cached_data:
        if not scraper.data["dolar"] and cached_data.get("dolar"):
            print("BCV falló, usando Dólar en caché.")
            scraper.data["dolar"] = cached_data["dolar"]
            
        if not scraper.data["euro"] and cached_data.get("euro"):
            print("BCV falló, usando Euro en caché.")
            scraper.data["euro"] = cached_data["euro"]
            
        if not scraper.data["usdt"] and cached_data.get("usdt"):
            print("Binance falló, usando USDT en caché.")
            scraper.data["usdt"] = cached_data["usdt"]

    # 4. Guardar siempre
    storage.update_file(scraper.data, sha)
    return scraper.data

if __name__ == "__main__":
    # Simulación de ejecución
    resultado = main()
    print(json.dumps(resultado, indent=2))