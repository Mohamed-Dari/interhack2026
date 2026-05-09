"""
Carga de datos para Clinic Demand Twin.

Orden de prioridad:
1. CSV locales normalizados en data/
2. Excel real de Inibsa, normalizado y cacheado en data/
3. Datos sintéticos de demo generados por src.mock_data

Esquema interno:
- sales: date, client_id, product_id, units, revenue
- clients: client_id, clinic_name, city, region, clinic_segment
- products: product_id, product_name, family_id, family_name, category_type
- potential: client_id, family_id, monthly_potential_units
- campaigns: campaign_id, family_id, start_date, end_date, campaign_name
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

CSV_FILES = {
    "sales": DATA_DIR / "sales.csv",
    "clients": DATA_DIR / "clients.csv",
    "products": DATA_DIR / "products.csv",
    "potential": DATA_DIR / "potential.csv",
    "campaigns": DATA_DIR / "campaigns.csv",
}

EXCEL_PATH = PROJECT_ROOT.parent / "Inibsa challenge" / "Datasets.xlsx"

FAMILY_DISPLAY = {
    ("Categoria C1", "Familia C1"): ("Anestesia", "commodity"),
    ("Categoria C2", "Familia C2"): ("Biomateriales y Bioseguridad", "commodity"),
    ("Categoria T1", "Familia T1"): ("Biomateriales T1", "technical"),
    ("Categoria T1", "Familia T2"): ("Biomateriales T2", "technical"),
}

REQUIRED_COLUMNS = {
    "sales": {"date", "client_id", "product_id", "units", "revenue"},
    "clients": {"client_id", "clinic_name", "city", "region", "clinic_segment"},
    "products": {"product_id", "product_name", "family_id", "family_name", "category_type"},
    "potential": {"client_id", "family_id", "monthly_potential_units"},
    "campaigns": {"campaign_id", "family_id", "start_date", "end_date", "campaign_name"},
}


def _csvs_exist(data_dir: Path = DATA_DIR) -> bool:
    return all((data_dir / f"{name}.csv").exists() for name in CSV_FILES)


def _excel_path() -> Path | None:
    return EXCEL_PATH if EXCEL_PATH.exists() else None


def _ensure_required(name: str, df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS[name] - set(df.columns)
    if missing:
        raise ValueError(f"{name}.csv no contiene las columnas obligatorias: {sorted(missing)}")


def _save_csvs(
    sales: pd.DataFrame,
    clients: pd.DataFrame,
    products: pd.DataFrame,
    potential: pd.DataFrame,
    campaigns: pd.DataFrame,
    data_dir: Path = DATA_DIR,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    sales.to_csv(data_dir / "sales.csv", index=False)
    clients.to_csv(data_dir / "clients.csv", index=False)
    products.to_csv(data_dir / "products.csv", index=False)
    potential.to_csv(data_dir / "potential.csv", index=False)
    campaigns.to_csv(data_dir / "campaigns.csv", index=False)


def _load_from_csvs(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, ...]:
    sales = pd.read_csv(data_dir / "sales.csv", parse_dates=["date"])
    clients = pd.read_csv(data_dir / "clients.csv")
    products = pd.read_csv(data_dir / "products.csv")
    potential = pd.read_csv(data_dir / "potential.csv")
    campaigns = pd.read_csv(data_dir / "campaigns.csv", parse_dates=["start_date", "end_date"])

    frames = {
        "sales": sales,
        "clients": clients,
        "products": products,
        "potential": potential,
        "campaigns": campaigns,
    }
    for name, df in frames.items():
        _ensure_required(name, df)
        df.attrs["source"] = "CSV locals"
    return sales, clients, products, potential, campaigns


def _parse_excel(path: Path) -> tuple[pd.DataFrame, ...]:
    xl = pd.ExcelFile(path, engine="openpyxl")

    ventas = xl.parse("Ventas")
    ventas = ventas.rename(
        columns={
            "Fecha": "date",
            "Id. Cliente": "client_id",
            "Id.Cliente": "client_id",
            "Id. Producto": "product_id",
            "Id.Producto": "product_id",
            "Unidades": "units",
            "Valores_H": "revenue",
        }
    )
    sales = ventas[["date", "client_id", "product_id", "units", "revenue"]].copy()
    sales["date"] = pd.to_datetime(sales["date"], errors="coerce")
    sales["client_id"] = pd.to_numeric(sales["client_id"], errors="coerce")
    sales["product_id"] = pd.to_numeric(sales["product_id"], errors="coerce")
    sales["units"] = pd.to_numeric(sales["units"], errors="coerce")
    sales["revenue"] = pd.to_numeric(sales["revenue"], errors="coerce")
    sales = sales.dropna(subset=["date", "client_id", "product_id", "units", "revenue"])
    sales = sales[sales["units"] > 0].copy()
    sales["client_id"] = sales["client_id"].astype(int)
    sales["product_id"] = sales["product_id"].astype(int)

    prod_raw = xl.parse("Productos")
    prod_raw = prod_raw.rename(
        columns={
            "Id.Prod": "product_id",
            "Bloque analítico": "block",
            "Categoria_H": "category_name",
            "Familia_H": "source_family",
        }
    )
    prod_raw = prod_raw.dropna(subset=["product_id", "category_name", "source_family"]).copy()
    prod_raw["product_id"] = prod_raw["product_id"].astype(int)
    prod_raw["category_type"] = prod_raw["block"].map(
        {"Commodities": "commodity", "Productos Técnicos": "technical"}
    ).fillna("commodity")

    product_family_keys = (
        prod_raw[["category_name", "source_family"]]
        .drop_duplicates()
        .sort_values(["category_name", "source_family"])
        .reset_index(drop=True)
    )
    product_family_keys["family_id"] = range(1, len(product_family_keys) + 1)
    products = prod_raw.merge(product_family_keys, on=["category_name", "source_family"], how="left")
    display = products.apply(
        lambda row: FAMILY_DISPLAY.get(
            (row["category_name"], row["source_family"]),
            (row["source_family"], row["category_type"]),
        ),
        axis=1,
    )
    products["family_name"] = [item[0] for item in display]
    products["category_type"] = [item[1] for item in display]
    products["product_name"] = "Producto " + products["product_id"].astype(str)
    products = products[["product_id", "product_name", "family_id", "family_name", "category_type"]]

    cli_raw = xl.parse("Clientes")
    cli_raw = cli_raw.rename(columns={"Id. Cliente": "client_id", "Id.Cliente": "client_id", "Provincia": "region"})
    clients = cli_raw[["client_id", "region"]].dropna(subset=["client_id"]).copy()
    clients["client_id"] = clients["client_id"].astype(int)
    clients["region"] = clients["region"].fillna("Desconocido")
    clients["city"] = clients["region"]
    clients["clinic_name"] = "Clínica " + clients["client_id"].astype(str)
    clients = clients.drop_duplicates("client_id")

    sales_for_segment = sales.groupby("client_id")["revenue"].sum().reset_index(name="total_revenue")
    if not sales_for_segment.empty and sales_for_segment["total_revenue"].nunique() > 1:
        pct_rank = sales_for_segment["total_revenue"].rank(pct=True, method="first")
        sales_for_segment["clinic_segment"] = np.select(
            [pct_rank <= 0.33, pct_rank <= 0.66],
            ["small", "medium"],
            default="large",
        )
    else:
        sales_for_segment["clinic_segment"] = "small"
    clients = clients.merge(sales_for_segment[["client_id", "clinic_segment"]], on="client_id", how="left")
    clients["clinic_segment"] = clients["clinic_segment"].fillna("small")
    clients = clients[["client_id", "clinic_name", "city", "region", "clinic_segment"]]

    sales_with_family = sales.merge(products[["product_id", "family_id"]], on="product_id", how="left")
    price_by_family = (
        sales_with_family.groupby("family_id")
        .agg(total_revenue=("revenue", "sum"), total_units=("units", "sum"))
        .reset_index()
    )
    price_by_family["avg_unit_price"] = (
        price_by_family["total_revenue"] / price_by_family["total_units"].clip(lower=1)
    )
    price_map = price_by_family.set_index("family_id")["avg_unit_price"].to_dict()

    pot_raw = xl.parse("Potencial")
    pot_raw = pot_raw.rename(
        columns={
            "Id.Cliente": "client_id",
            "Id. Cliente": "client_id",
            "Familia": "potential_family",
            "Categoria Productos": "category_name",
            "Potencial_H": "annual_potential_revenue",
        }
    )
    pot_raw = pot_raw.dropna(subset=["client_id", "category_name", "annual_potential_revenue"]).copy()
    pot_raw["client_id"] = pot_raw["client_id"].astype(int)
    pot_raw["annual_potential_revenue"] = pd.to_numeric(
        pot_raw["annual_potential_revenue"], errors="coerce"
    ).fillna(0)

    category_to_families = (
        products.merge(
            prod_raw[["product_id", "category_name"]].drop_duplicates("product_id"),
            on="product_id",
            how="left",
        )[["category_name", "family_id"]]
        .drop_duplicates()
    )

    expanded_potential = pot_raw.merge(category_to_families, on="category_name", how="left")
    expanded_potential = expanded_potential.dropna(subset=["family_id"])
    expanded_potential["family_id"] = expanded_potential["family_id"].astype(int)
    family_counts = category_to_families.groupby("category_name")["family_id"].nunique().to_dict()
    expanded_potential["family_count"] = expanded_potential["category_name"].map(family_counts).fillna(1)
    expanded_potential["allocated_annual_revenue"] = (
        expanded_potential["annual_potential_revenue"] / expanded_potential["family_count"]
    )
    expanded_potential["avg_unit_price"] = expanded_potential["family_id"].map(price_map).fillna(
        np.nanmedian(list(price_map.values())) if price_map else 100.0
    )
    expanded_potential["monthly_potential_units"] = (
        expanded_potential["allocated_annual_revenue"] / 12 / expanded_potential["avg_unit_price"].clip(lower=0.01)
    )
    potential = (
        expanded_potential.groupby(["client_id", "family_id"])["monthly_potential_units"]
        .sum()
        .reset_index()
    )

    camp_raw = xl.parse("Campañas")
    camp_raw = camp_raw.rename(
        columns={"Campaña": "campaign_name", "Fecha inicio": "start_date", "Fecha fin": "end_date"}
    )
    camp_raw = camp_raw.dropna(subset=["campaign_name", "start_date", "end_date"]).copy()
    camp_raw["start_date"] = pd.to_datetime(camp_raw["start_date"], errors="coerce")
    camp_raw["end_date"] = pd.to_datetime(camp_raw["end_date"], errors="coerce")
    families = products[["family_id"]].drop_duplicates()
    campaigns = camp_raw.assign(_key=1).merge(families.assign(_key=1), on="_key").drop(columns="_key")
    campaigns["campaign_id"] = [
        f"real_{i}_{family_id}" for i, family_id in zip(campaigns.index + 1, campaigns["family_id"])
    ]
    campaigns = campaigns[["campaign_id", "family_id", "start_date", "end_date", "campaign_name"]]

    for df in (sales, clients, products, potential, campaigns):
        df.attrs["source"] = "Excel Inibsa normalitzat"
    return sales, clients, products, potential, campaigns


def load_all_data(data_dir: str | Path = DATA_DIR, source: str | None = None) -> tuple[pd.DataFrame, ...]:
    """
    Carga todos los datasets.

    Usa CLINIC_TWIN_DATA_SOURCE con auto, csv, excel o mock para forzar una fuente.
    """
    data_dir = Path(data_dir)
    selected = (source or os.getenv("CLINIC_TWIN_DATA_SOURCE", "auto")).lower()

    if selected == "mock":
        from src.mock_data import generate_all_data

        frames = generate_all_data(data_dir)
        for df in frames:
            df.attrs["source"] = "Dades sintètiques"
        return frames

    if selected in {"auto", "csv"} and _csvs_exist(data_dir):
        return _load_from_csvs(data_dir)

    if selected in {"auto", "excel"}:
        path = _excel_path()
        if path is not None:
            frames = _parse_excel(path)
            _save_csvs(*frames, data_dir=data_dir)
            return frames
        if selected == "excel":
            raise FileNotFoundError("No s'ha trobat Datasets.xlsx a les rutes esperades.")

    from src.mock_data import generate_all_data

    frames = generate_all_data(data_dir)
    for df in frames:
        df.attrs["source"] = "Dades sintètiques"
    return frames
