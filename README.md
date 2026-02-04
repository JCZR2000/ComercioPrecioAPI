# 🇻🇪 ComercioPrecio API

Una API gratuita, serverless y de código abierto que proporciona las tasas de cambio actualizadas para Venezuela (BCV y Paralelo/Binance).

El sistema funciona de forma autónoma utilizando **GitHub Actions** para actualizar un archivo JSON estático cada 4 horas, sirviendo como una "base de datos" de alta velocidad sin costes de servidor.

## 🚀 API Endpoint (Uso)

Para obtener los datos, simplemente realiza una petición GET a la siguiente URL Raw de GitHub. Al ser un archivo estático, la respuesta es inmediata.

```http
GET [https://raw.githubusercontent.com/JCZR2000/ComercioPrecioAPI/main/tasas_cambio.json]
