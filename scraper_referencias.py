"""Datos de referencia del modo Internacional de Tasa3 -> intl_referencias.json.

Sales tax de EE. UU. (Kintsugi, CC BY 4.0), salario mínimo y comisiones de cobro (tablas manuales en datos_manuales/).
Uso local: python scraper_referencias.py --local [ruta]  (solo escribe el archivo, no publica)
           python scraper_referencias.py --test          (autoprueba de la validación)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from scraper import GitHubStorage

FILE_NAME = "intl_referencias.json"
RAW_URL = "https://raw.githubusercontent.com/JCZR2000/ComercioPrecioAPI/main/" + FILE_NAME
TAX_URL = "https://trykintsugi.com/data/us-state-sales-tax-rates.json"
WAGES_PATH = Path(__file__).parent / "datos_manuales" / "salario_minimo.json"
FEES_PATH = Path(__file__).parent / "datos_manuales" / "comisiones_cobro.json"
# máximo según el tipo de campo (también "pct" y "fijo" de conversion_por_moneda)
FEE_LIMITS = {"pct": 15, "fijo": 50}
FEE_FIELDS = [f"{step}_{kind}" for step in ("cobro", "retiro", "conversion") for kind in FEE_LIMITS]
# clave en nuestro JSON -> columna de Kintsugi
TAX_FIELDS = {
    "estatal": "state_rate_pct",
    "comun": "most_common_combined_rate_pct",
    "min": "min_combined_rate_pct",
    "max": "max_combined_rate_pct",
}


def build_sales_tax(source):
    """Convierte el JSON de Kintsugi; lanza ValueError si no es fiable."""
    rows = source["rows"]
    if len(rows) != 51 or len({r["code"] for r in rows}) != 51:
        raise ValueError(f"se esperaban 51 estados distintos, hay {len(rows)} filas")
    estados = []
    for r in rows:
        entry = {"code": r["code"], "nombre": r["name"]}
        for key, column in TAX_FIELDS.items():
            value = r[column]
            if not isinstance(value, (int, float)) or not 0 <= value <= 15:
                raise ValueError(f"{r['code']}: {column} fuera de rango ({value})")
            entry[key] = value
        estados.append(entry)
    return {
        "fuente": "Kintsugi", "licencia": "CC BY 4.0", "url": TAX_URL,
        "fecha_datos": source["date_modified"], "estados": estados,
    }


def fetch_sales_tax():
    try:
        r = requests.get(TAX_URL, timeout=30)
        r.raise_for_status()
        return build_sales_tax(r.json())
    except Exception as e:
        print(f"❌ Sales tax: {e}")
        return None


def check_fees(entry, keys, where):
    for key in keys:
        value = entry[key]
        if not isinstance(value, (int, float)) or not 0 <= value <= FEE_LIMITS[key.split("_")[-1]]:
            raise ValueError(f"{where}: {key} fuera de rango ({value})")


def build_fees(table):
    """Valida la tabla manual de comisiones; lanza ValueError (o KeyError) si no es fiable."""
    for p in table["plataformas"]:
        if p["tasa"] not in ("oficial", "p2p"):
            raise ValueError(f"{p['id']}: tasa desconocida ({p['tasa']})")
        check_fees(p, FEE_FIELDS, p["id"])
        for code, entry in p.get("conversion_por_moneda", {}).items():
            check_fees(entry, FEE_LIMITS, f"{p['id']} {code}")
        for code, entry in p.get("por_pais", {}).items():
            if len(code) != 2:
                raise ValueError(f"{p['id']}: país inválido ({code})")
            check_fees(entry, [k for k in FEE_FIELDS if k in entry], f"{p['id']} {code}")
    return table


def load_previous(storage):
    if storage:
        return storage.get_file(FILE_NAME)
    try:
        r = requests.get(RAW_URL, timeout=15)
        return (r.json() if r.status_code == 200 else None), None
    except Exception:
        return None, None


def self_test():
    row = {c: 5 for c in TAX_FIELDS.values()}
    good = {"date_modified": "2026-11-01", "rows": [{**row, "code": str(i), "name": "x"} for i in range(51)]}
    assert len(build_sales_tax(good)["estados"]) == 51
    bad_rate = {**good, "rows": good["rows"][:50] + [{**good["rows"][50], "state_rate_pct": 16}]}
    for bad in (bad_rate, {**good, "rows": good["rows"][:50]}):
        try:
            build_sales_tax(bad)
        except ValueError:
            continue
        raise AssertionError("se aceptó un sales tax inválido")
    fees = {"id": "x", "tasa": "oficial", **{k: 1 for k in FEE_FIELDS}}
    assert build_fees({"plataformas": [fees]})
    for change in ({"cobro_pct": 16}, {"tasa": "otra"}, {"por_pais": {"CO": {"cobro_pct": 40}}}):
        try:
            build_fees({"plataformas": [{**fees, **change}]})
        except ValueError:
            continue
        raise AssertionError(f"se aceptaron comisiones inválidas: {change}")
    build_fees(json.loads(FEES_PATH.read_text(encoding="utf-8")))
    print("OK")


def main():
    if "--test" in sys.argv:
        return self_test()
    local = "--local" in sys.argv
    storage = None if local else GitHubStorage()
    previous, sha = load_previous(storage)

    # Si el archivo manual está roto, esto falla y no se publica nada
    wages = json.loads(WAGES_PATH.read_text(encoding="utf-8"))
    fees = build_fees(json.loads(FEES_PATH.read_text(encoding="utf-8")))
    sales_tax = fetch_sales_tax() or (previous or {}).get("us_sales_tax")
    if not sales_tax:
        sys.exit("Sin sales tax válido ni anterior: no se publica nada")

    data = {
        "version": 1,
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "us_sales_tax": sales_tax,
        "salario_minimo": wages,
        "comisiones_cobro": fees,
    }
    if local:
        args = sys.argv[sys.argv.index("--local") + 1:]
        path = Path(args[0] if args else FILE_NAME)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Escrito {path}")
        return
    storage.update_file(FILE_NAME, data, sha, "Actualización datos de referencia internacionales")


if __name__ == "__main__":
    main()
