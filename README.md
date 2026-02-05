# 🇻🇪 ComercioPrecio API

Una API gratuita, serverless y de código abierto que proporciona las tasas de cambio actualizadas para Venezuela (BCV y Paralelo/Binance).

El sistema funciona de forma autónoma utilizando **GitHub Actions** para actualizar un archivo JSON estático cada 4 horas, sirviendo como una "base de datos" de alta velocidad sin costes de servidor.

## 🚀 API Endpoint (Uso)

Para obtener los datos, simplemente realiza una petición GET a la siguiente URL Raw de GitHub. Al ser un archivo estático, la respuesta es inmediata.

```http
GET [https://raw.githubusercontent.com/JCZR2000/ComercioPrecioAPI/main/tasas_cambio.json]
```

## ⚙️ ¿Cómo funciona?

1. **Cron Job:** Un flujo de trabajo de GitHub Actions _(scraper.yml)_ se despierta automáticamente **cada 4 horas.**

2. **Scraping:**

· Se conecta al sitio web del **BCV** (ignorando errores SSL comunes) para extraer el Dólar y Euro oficial.

· Consulta la API interna de **Binance P2P**, filtrando anuncios verificados que acepten **Banesco** o **Mercantil** para obtener un precio real de mercado.


3. **Persistencia:**

· El script verifica si hay cambios.

· Si los hay, sobrescribe el archivo _tasas_cambio.json_ en el mismo repositorio utilizando la API de GitHub.

4. **Resiliencia:** Si alguna fuente falla (ej. página del BCV caída), el sistema mantiene el último valor conocido para no romper la API.


## 🛠️ Tecnologías


· **Python 3.10+**

· **BeautifulSoup4:** Para el web scraping del BCV.

· **Requests:** Para peticiones HTTP.

· **GitHub Actions:** Para la automatización (Cron).

· **GitHub API:** Para el almacenamiento de datos (Self-updating repo).


## 📦 Instalación / Fork


Si deseas desplegar tu propia instancia de esta API:


1. Haz un Fork de este repositorio.

2. Habilita los permisos de escritura para el GITHUB_TOKEN:

· Ve a **Settings** > **Actions** > **General**.

· En "Workflow permissions", selecciona **Read and write permissions**.

· Guarda los cambios.

3. Habilita las Actions:

· Ve a la pestaña **Actions** y activa los flujos de trabajo si están deshabilitados.

4. ¡Listo! El scraper comenzará a ejecutarse automáticamente según el horario programado.


## Ejecución Local (Desarrollo)


1. Clona el repositorio.

2. Instala las dependencias:


```
Bash

pip install -r requirements.txt
```


3. Configura las variables de entorno (necesarias solo en local):

```
PowerShell

$env:GITHUB_TOKEN="tu_personal_access_token"
$env:REPO_OWNER="tu_usuario"
$env:REPO_NAME="nombre_repo"
```

Ejecuta el script Bash:

```
python scraper.py
```

## 📄 Licencia


Este proyecto está bajo la Licencia MIT. Eres libre de usarlo y modificarlo.
