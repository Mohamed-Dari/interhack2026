"""
Loads data from three sources, in priority order:
  1. Real Inibsa Excel (Datasets.xlsx) → converts to internal schema
  2. Pre-generated CSVs in data/
  3. Synthetic mock data (auto-generated and saved to data/)

Internal schema columns (always returned):
  sales_df      : sale_id, date, client_id, product_id, units, revenue
  clients_df    : client_id, clinic_name, city, region, clinic_segment
  products_df   : product_id, product_name, family_id, family_name, cat_id,
                  category_name, category_type
  potential_df  : client_id, cat_id, cat_name, family_name, category_type,
                  annual_potential_revenue, monthly_potential
  campaigns_df  : campaign_id, campaign_name, start_date, end_date
"""

import os
import sys
import numpy as np
import pandas as pd

# ── paths ──────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

EXCEL_PATH = os.path.join(
    os.path.dirname(_ROOT),
    "interhack2026", "Inibsa challenge", "Datasets.xlsx"
)
DATA_DIR = os.path.join(_ROOT, "data")

_CSV_FILES = {
    "sales":     os.path.join(DATA_DIR, "sales.csv"),
    "clients":   os.path.join(DATA_DIR, "clients.csv"),
    "products":  os.path.join(DATA_DIR, "products.csv"),
    "potential": os.path.join(DATA_DIR, "potential.csv"),
    "campaigns": os.path.join(DATA_DIR, "campaigns.csv"),
}

# Category → numeric family id (used when loading from Excel)
_CAT_FAMILY_MAP = {"C1": 1, "C2": 2, "T1": 3}
_CAT_NAME_MAP   = {
    "Categoria C1": "C1",
    "Categoria C2": "C2",
    "Categoria T1": "T1",
}
_CAT_DISPLAY = {
    "C1": ("Anestesia",      "commodity"),
    "C2": ("Biomateriales",  "commodity"),   # aggregates Biomateriales C2 + Bioseguridad C2
    "T1": ("Biomateriales",  "technical"),   # Biomateriales Técnicos (T1/T2 families)
}


# ── Excel loader ───────────────────────────────────────────────────────────────

def _load_from_excel(path: str) -> tuple:
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as e:
        print(f"[data_loader] Cannot open Excel: {e}")
        return None

    # ── Ventas ─────────────────────────────────────────────────────────────
    ventas = xl.parse("Ventas", header=0)
    ventas.columns = ["invoice_id", "date", "client_id", "product_id", "units", "revenue"]
    ventas = ventas[ventas["units"] > 0].copy()          # drop returns
    ventas["date"] = pd.to_datetime(ventas["date"])
    ventas = ventas.reset_index(drop=True)
    ventas.insert(0, "sale_id", range(1, len(ventas) + 1))
    sales_df = ventas[["sale_id", "date", "client_id", "product_id", "units", "revenue"]]

    # ── Productos ──────────────────────────────────────────────────────────
    prod_raw = xl.parse("Productos", header=0)
    prod_raw.columns = ["product_id", "bloque", "cat_name", "family_name"]
    prod_raw["cat_id"] = prod_raw["cat_name"].map(_CAT_NAME_MAP)
    prod_raw["category_type"] = prod_raw["bloque"].map({
        "Commodities": "commodity", "Productos Técnicos": "technical"
    })
    # Assign numeric family_id per unique family_name
    fam_ids = {name: i + 1 for i, name in enumerate(sorted(prod_raw["family_name"].unique()))}
    prod_raw["family_id"] = prod_raw["family_name"].map(fam_ids)
    prod_raw["product_name"] = prod_raw["product_id"].astype(str)
    prod_raw["category_name"] = prod_raw["cat_name"]
    products_df = prod_raw[["product_id", "product_name", "family_id", "family_name",
                             "cat_id", "category_name", "category_type"]]

    # ── Clientes ───────────────────────────────────────────────────────────
    cli_raw = xl.parse("Clientes", header=0)
    cli_raw.columns = ["client_id", "postal_code", "province"]
    cli_raw = cli_raw.dropna(subset=["client_id"])
    cli_raw["client_id"] = cli_raw["client_id"].astype(int)
    cli_raw["clinic_name"] = "Clínica " + cli_raw["client_id"].astype(str)
    cli_raw["city"]   = cli_raw["province"].fillna("Desconocido")
    cli_raw["region"] = cli_raw["province"].fillna("Desconocido")
    # Segment by spending (computed after sales merge)
    clients_df = cli_raw[["client_id", "clinic_name", "city", "region"]].copy()
    clients_df = clients_df.drop_duplicates("client_id")

    # Infer segment from total sales volume
    total_rev = (
        sales_df.groupby("client_id")["revenue"].sum().reset_index(name="total_rev")
    )
    q33 = total_rev["total_rev"].quantile(0.33)
    q66 = total_rev["total_rev"].quantile(0.66)
    total_rev["clinic_segment"] = pd.cut(
        total_rev["total_rev"], bins=[-np.inf, q33, q66, np.inf],
        labels=["small", "medium", "large"]
    ).astype(str)
    clients_df = clients_df.merge(total_rev[["client_id", "clinic_segment"]], on="client_id", how="left")
    clients_df["clinic_segment"] = clients_df["clinic_segment"].fillna("small")

    # ── Potencial ──────────────────────────────────────────────────────────
    pot_raw = xl.parse("Potencial", header=0)
    pot_raw.columns = ["client_id", "familia", "cat_name", "potencial_h"]
    pot_raw["cat_id"] = pot_raw["cat_name"].map(_CAT_NAME_MAP)
    pot_raw = pot_raw.dropna(subset=["cat_id"])
    # Aggregate: sum potencial_h per (client, cat_id) in case of multiple family rows
    pot_agg = (
        pot_raw.groupby(["client_id", "cat_id"])["potencial_h"]
        .sum().reset_index(name="annual_potential_revenue")
    )
    pot_agg["cat_name"]      = pot_agg["cat_id"].map({"C1": "Categoria C1", "C2": "Categoria C2", "T1": "Categoria T1"})
    pot_agg["family_name"]   = pot_agg["cat_id"].map({k: v[0] for k, v in _CAT_DISPLAY.items()})
    pot_agg["category_type"] = pot_agg["cat_id"].map({k: v[1] for k, v in _CAT_DISPLAY.items()})
    pot_agg["monthly_potential"] = (pot_agg["annual_potential_revenue"] / 12).round(2)
    potential_df = pot_agg

    # ── Campañas ───────────────────────────────────────────────────────────
    camp_raw = xl.parse("Campañas", header=0)
    camp_raw.columns = ["campaign_name", "start_date", "end_date"]
    camp_raw = camp_raw.dropna(subset=["campaign_name"])
    camp_raw["campaign_id"] = range(1, len(camp_raw) + 1)
    camp_raw["start_date"] = pd.to_datetime(camp_raw["start_date"])
    camp_raw["end_date"]   = pd.to_datetime(camp_raw["end_date"])
    campaigns_df = camp_raw[["campaign_id", "campaign_name", "start_date", "end_date"]]

    print(f"[data_loader] Excel loaded: {len(sales_df):,} sales · {len(clients_df):,} clients")
    return sales_df, clients_df, products_df, potential_df, campaigns_df


# ── CSV loader ─────────────────────────────────────────────────────────────────

def _csvs_exist() -> bool:
    return all(os.path.exists(p) for p in _CSV_FILES.values())


def _load_from_csvs() -> tuple:
    sales_df     = pd.read_csv(_CSV_FILES["sales"],     parse_dates=["date"])
    clients_df   = pd.read_csv(_CSV_FILES["clients"])
    products_df  = pd.read_csv(_CSV_FILES["products"])
    potential_df = pd.read_csv(_CSV_FILES["potential"])
    campaigns_df = pd.read_csv(_CSV_FILES["campaigns"], parse_dates=["start_date", "end_date"])
    print(f"[data_loader] CSVs loaded: {len(sales_df):,} sales")
    return sales_df, clients_df, products_df, potential_df, campaigns_df


# ── Public API ─────────────────────────────────────────────────────────────────

def load_all_data(data_dir: str = DATA_DIR) -> tuple:
    """Return (sales, clients, products, potential, campaigns) DataFrames."""

    # 1. Try Excel
    if os.path.exists(EXCEL_PATH):
        result = _load_from_excel(EXCEL_PATH)
        if result is not None:
            return result

    # 2. Try pre-generated CSVs
    if _csvs_exist():
        return _load_from_csvs()

    # 3. Generate synthetic data
    print("[data_loader] No data found — generating synthetic demo data...")
    sys.path.insert(0, _ROOT)
    from src.mock_data import generate_all_data
    return generate_all_data(data_dir)
