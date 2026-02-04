# netlify/functions/tasas.py
import json
# Importa la lógica del script de arriba (asegúrate de que el código esté accesible)
from scraper import main as get_rates 

def handler(event, context):
    try:
        data = get_rates()
        return {
            'statusCode': 200,
            'body': json.dumps(data),
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*' # CORS para tu frontend
            }
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({"error": str(e)})
        }