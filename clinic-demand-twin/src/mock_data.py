"""Generador de datos sintéticos para una demo fiable de hackathon."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


RANDOM_SEED = 42
N_CLIENTS = 100
START_MONTH = pd.Timestamp("2024-05-01")
END_MONTH = pd.Timestamp("2026-04-01")

FAMILIES = [
    {"family_id": 1, "family_name": "Anestesia", "category_type": "commodity", "price": 52.0},
    {"family_id": 2, "family_name": "Biomateriales", "category_type": "commodity", "price": 118.0},
    {"family_id": 3, "family_name": "Bioseguridad", "category_type": "commodity", "price": 34.0},
    {"family_id": 4, "family_name": "Endodoncia Técnica", "category_type": "technical", "price": 340.0},
    {"family_id": 5, "family_name": "Cirugía Guiada", "category_type": "technical", "price": 690.0},
]

PROVINCES = [
    "Barcelona",
    "Madrid",
    "Valencia",
    "Sevilla",
    "Zaragoza",
    "Málaga",
    "Bilbao",
    "Alicante",
    "Córdoba",
    "Valladolid",
    "Murcia",
    "Palma",
    "Las Palmas",
    "Granada",
    "Vitoria",
]


def _months() -> list[pd.Timestamp]:
    return list(pd.date_range(START_MONTH, END_MONTH, freq="MS"))


def _rand_day(month: pd.Timestamp) -> pd.Timestamp:
    return month + pd.Timedelta(days=random.randint(0, 26))


def _make_clients() -> pd.DataFrame:
    rows = []
    for client_id in range(1, N_CLIENTS + 1):
        region = random.choice(PROVINCES)
        rows.append(
            {
                "client_id": client_id,
                "clinic_name": f"Clínica Dental {client_id:03d}",
                "city": region,
                "region": region,
                "clinic_segment": random.choices(
                    ["small", "medium", "large"], weights=[0.50, 0.35, 0.15]
                )[0],
            }
        )
    return pd.DataFrame(rows)


def _make_products() -> pd.DataFrame:
    rows = []
    product_id = 1000
    for family in FAMILIES:
        for index in range(1, 6):
            rows.append(
                {
                    "product_id": product_id,
                    "product_name": f"{family['family_name']} SKU-{index}",
                    "family_id": family["family_id"],
                    "family_name": family["family_name"],
                    "category_type": family["category_type"],
                }
            )
            product_id += 1
    return pd.DataFrame(rows)


def _make_potential(clients: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for client in clients.itertuples():
        segment_multiplier = {"small": 0.8, "medium": 1.25, "large": 1.8}[client.clinic_segment]
        for family in FAMILIES:
            if family["category_type"] == "commodity":
                base_units = random.uniform(12, 75)
            else:
                base_units = random.uniform(1.2, 8)
            rows.append(
                {
                    "client_id": client.client_id,
                    "family_id": family["family_id"],
                    "monthly_potential_units": round(base_units * segment_multiplier, 2),
                }
            )
    return pd.DataFrame(rows)


def _make_campaigns() -> pd.DataFrame:
    campaigns = [
        (1, 1, "2025-02-10", "2025-02-21", "Campaña Anestesia Invierno"),
        (2, 2, "2025-09-15", "2025-09-26", "Impulso Biomateriales"),
        (3, 4, "2025-11-10", "2025-11-21", "Semana Técnica Endodoncia"),
        (4, 1, "2026-03-09", "2026-03-20", "Campaña Anestesia Primavera"),
        (5, 5, "2026-03-16", "2026-03-27", "Cirugía Guiada Premium"),
    ]
    return pd.DataFrame(
        campaigns,
        columns=["campaign_id", "family_id", "start_date", "end_date", "campaign_name"],
    )


def _add_sale(
    rows: list[dict],
    date: pd.Timestamp,
    client_id: int,
    product_id: int,
    units: float,
    unit_price: float,
) -> None:
    if units <= 0:
        return
    rows.append(
        {
            "date": date.strftime("%Y-%m-%d"),
            "client_id": client_id,
            "product_id": product_id,
            "units": int(max(1, round(units))),
            "revenue": round(max(1, round(units)) * unit_price * random.uniform(0.88, 1.12), 2),
        }
    )


def _make_commodity_sales(
    rows: list[dict],
    products: pd.DataFrame,
    potential: pd.DataFrame,
    months: list[pd.Timestamp],
) -> None:
    recent_months = {months[-1].strftime("%Y-%m"), months[-2].strftime("%Y-%m")}

    for client_id in range(1, N_CLIENTS + 1):
        for family in [item for item in FAMILIES if item["category_type"] == "commodity"]:
            family_id = family["family_id"]
            prods = products[products["family_id"] == family_id]["product_id"].tolist()
            pot = float(
                potential[
                    (potential["client_id"] == client_id) & (potential["family_id"] == family_id)
                ]["monthly_potential_units"].iloc[0]
            )

            if client_id == 1 and family_id == 1:
                hist_capture, recent_capture = 0.82, 0.18
            elif client_id == 2 and family_id == 2:
                hist_capture, recent_capture = 0.32, 0.22
            elif client_id == 5 and family_id == 1:
                hist_capture, recent_capture = 0.48, 0.42
            else:
                hist_capture = random.uniform(0.06, 0.94)
                recent_capture = max(0, hist_capture * random.uniform(0.45, 1.18))

            for month in months:
                ym = month.strftime("%Y-%m")
                capture = recent_capture if ym in recent_months else hist_capture
                if client_id == 5 and family_id == 1 and ym == "2026-03":
                    capture *= 1.9
                if random.random() < 0.06:
                    continue

                units = pot * capture * random.uniform(0.80, 1.20)
                _add_sale(rows, _rand_day(month), client_id, random.choice(prods), units, family["price"])


def _technical_dates(
    client_id: int,
    family_id: int,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[pd.Timestamp]:
    if client_id == 3 and family_id == 4:
        median_days, last_gap, n_purchases = 90, 55, 8
    elif client_id == 4 and family_id == 5:
        median_days, last_gap, n_purchases = 42, 165, 10
    else:
        median_days = random.randint(35, 125)
        last_gap = random.randint(5, 130)
        n_purchases = random.randint(0, 9)

    if n_purchases == 0:
        return []

    dates = [end + pd.Timedelta(days=26) - pd.Timedelta(days=last_gap)]
    while len(dates) < n_purchases:
        gap = max(14, int(np.random.normal(median_days, median_days * 0.22)))
        next_date = dates[-1] - pd.Timedelta(days=gap)
        if next_date < start:
            break
        dates.append(next_date)
    return [date for date in dates if start <= date <= end + pd.Timedelta(days=27)]


def _make_technical_sales(
    rows: list[dict],
    products: pd.DataFrame,
    months: list[pd.Timestamp],
) -> None:
    start, end = months[0], months[-1]
    for client_id in range(1, N_CLIENTS + 1):
        for family in [item for item in FAMILIES if item["category_type"] == "technical"]:
            prods = products[products["family_id"] == family["family_id"]]["product_id"].tolist()
            for date in _technical_dates(client_id, family["family_id"], start, end):
                units = random.randint(1, 4)
                _add_sale(rows, date, client_id, random.choice(prods), units, family["price"])


def _make_sales(products: pd.DataFrame, potential: pd.DataFrame) -> pd.DataFrame:
    months = _months()
    rows: list[dict] = []
    _make_commodity_sales(rows, products, potential, months)
    _make_technical_sales(rows, products, months)
    sales = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    return sales


def generate_all_data(data_dir: str | Path = "data") -> tuple[pd.DataFrame, ...]:
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    clients = _make_clients()
    products = _make_products()
    potential = _make_potential(clients)
    campaigns = _make_campaigns()
    sales = _make_sales(products, potential)

    sales.to_csv(data_dir / "sales.csv", index=False)
    clients.to_csv(data_dir / "clients.csv", index=False)
    products.to_csv(data_dir / "products.csv", index=False)
    potential.to_csv(data_dir / "potential.csv", index=False)
    campaigns.to_csv(data_dir / "campaigns.csv", index=False)

    return sales, clients, products, potential, campaigns
