"""
Generates synthetic data matching the Inibsa real-data schema.
5 designed demo cases are hard-coded for reliable storytelling.
"""
import os
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ── Constants ──────────────────────────────────────────────────────────────────
RANDOM_SEED = 42
START_DATE = datetime(2021, 1, 1)
END_DATE = datetime(2025, 12, 31)
N_CLIENTS = 100

CATEGORIES = [
    {"cat_id": "C1", "cat_name": "Categoria C1", "family_name": "Anestesia",       "category_type": "commodity"},
    {"cat_id": "C2", "cat_name": "Categoria C2", "family_name": "Biomateriales",   "category_type": "commodity"},
    {"cat_id": "T1", "cat_name": "Categoria T1", "family_name": "Bioseguridad",    "category_type": "technical"},
]

FAMILIES = [
    {"family_id": 1, "family_name": "Familia C1", "cat_id": "C1", "bloque": "Commodities"},
    {"family_id": 2, "family_name": "Familia C2", "cat_id": "C2", "bloque": "Commodities"},
    {"family_id": 3, "family_name": "Familia T1", "cat_id": "T1", "bloque": "Productos Técnicos"},
    {"family_id": 4, "family_name": "Familia T2", "cat_id": "T1", "bloque": "Productos Técnicos"},
]

PROVINCES = [
    "Barcelona", "Madrid", "Valencia", "Sevilla", "Zaragoza",
    "Málaga", "Bilbao", "Alicante", "Córdoba", "Valladolid",
    "Murcia", "Palma", "Las Palmas", "Granada", "Vitoria",
]

AVG_PRICES = {"C1": 55.0, "C2": 95.0, "T1": 420.0}

# ── Helpers ────────────────────────────────────────────────────────────────────

def _month_iter(start: datetime, end: datetime):
    cur = start.replace(day=1)
    while cur <= end:
        yield cur
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)


def _rand_day(month_dt: datetime) -> datetime:
    return month_dt + timedelta(days=random.randint(0, 27))


# ── Table generators ───────────────────────────────────────────────────────────

def _make_products() -> pd.DataFrame:
    rows, pid = [], 100
    for fam in FAMILIES:
        for i in range(6 if fam["cat_id"] != "T1" else 5):
            rows.append({
                "product_id":    pid,
                "product_name":  f"{fam['family_name']} SKU-{i+1}",
                "family_id":     fam["family_id"],
                "family_name":   fam["family_name"],
                "cat_id":        fam["cat_id"],
                "category_name": next(c["cat_name"] for c in CATEGORIES if c["cat_id"] == fam["cat_id"]),
                "category_type": fam["bloque"].replace("Commodities", "commodity").replace("Productos Técnicos", "technical"),
            })
            pid += 1
    return pd.DataFrame(rows)


def _make_clients() -> pd.DataFrame:
    rows = []
    for cid in range(1, N_CLIENTS + 1):
        prov = random.choice(PROVINCES)
        rows.append({
            "client_id":      cid,
            "clinic_name":    f"Clínica Dental {cid:03d}",
            "city":           prov,
            "region":         prov,
            "clinic_segment": random.choices(["small", "medium", "large"], weights=[0.5, 0.35, 0.15])[0],
        })
    return pd.DataFrame(rows)


def _make_potential(clients_df: pd.DataFrame) -> pd.DataFrame:
    """Annual revenue potential per client × category (mirroring Potencial_H from Excel)."""
    rows = []
    for _, c in clients_df.iterrows():
        for cat in CATEGORIES:
            base_annual = random.uniform(800, 15000) if cat["category_type"] == "commodity" else random.uniform(500, 8000)
            rows.append({
                "client_id":              c["client_id"],
                "cat_id":                 cat["cat_id"],
                "cat_name":               cat["cat_name"],
                "family_name":            cat["family_name"],
                "category_type":          cat["category_type"],
                "annual_potential_revenue": round(base_annual, 2),
                "monthly_potential":      round(base_annual / 12, 2),
            })
    return pd.DataFrame(rows)


def _make_campaigns() -> pd.DataFrame:
    return pd.DataFrame([
        {"campaign_id": 1, "campaign_name": "2022_1", "start_date": "2022-03-14", "end_date": "2022-03-26"},
        {"campaign_id": 2, "campaign_name": "2022_2", "start_date": "2022-11-24", "end_date": "2022-11-25"},
        {"campaign_id": 3, "campaign_name": "2023_1", "start_date": "2023-09-12", "end_date": "2023-09-15"},
        {"campaign_id": 4, "campaign_name": "2024_1", "start_date": "2024-03-04", "end_date": "2024-03-16"},
        {"campaign_id": 5, "campaign_name": "2024_3", "start_date": "2024-09-12", "end_date": "2024-09-15"},
        {"campaign_id": 6, "campaign_name": "2024_4", "start_date": "2024-11-28", "end_date": "2024-11-29"},
    ])


# ── Sales generation ───────────────────────────────────────────────────────────

def _add_commodity_month(sales, cid, prod_ids, cat_id, month_dt, revenue_target, jitter=0.25):
    if revenue_target <= 0:
        return
    actual = max(0, revenue_target * random.uniform(1 - jitter, 1 + jitter))
    if actual == 0:
        return
    price = AVG_PRICES[cat_id] * random.uniform(0.8, 1.2)
    units = max(1, round(actual / price))
    pid = random.choice(prod_ids)
    sales.append({
        "date": _rand_day(month_dt).strftime("%Y-%m-%d"),
        "client_id": cid,
        "product_id": pid,
        "units": units,
        "revenue": round(actual, 2),
    })


def _add_technical_purchase(sales, cid, prod_ids, cat_id, date):
    price = AVG_PRICES[cat_id] * random.uniform(0.7, 1.4)
    units = random.randint(1, 5)
    sales.append({
        "date": date.strftime("%Y-%m-%d"),
        "client_id": cid,
        "product_id": random.choice(prod_ids),
        "units": units,
        "revenue": round(units * price, 2),
    })


def _make_sales(clients_df, products_df, potential_df):  # noqa: C901
    months = list(_month_iter(START_DATE, END_DATE))
    last2 = {m.strftime("%Y-%m") for m in months[-2:]}

    sales = []

    # Campaign months (global) for boost
    camp_months = {
        "2022-03", "2022-11", "2023-09", "2024-03", "2024-09", "2024-11"
    }

    for _, client in clients_df.iterrows():
        cid = client["client_id"]

        for cat in CATEGORIES:
            ctype = cat["category_type"]
            cid_key = cat["cat_id"]

            pot_row = potential_df[(potential_df.client_id == cid) & (potential_df.cat_id == cid_key)]
            if pot_row.empty:
                continue
            monthly_pot = pot_row.iloc[0]["monthly_potential"]

            # Products for this category
            cat_prods = products_df[products_df.cat_id == cid_key]["product_id"].tolist()
            if not cat_prods:
                continue

            # ── Designed cases (override defaults) ────────────────────────
            if ctype == "commodity":
                # Case 1 – loyal with sudden recent drop
                if cid == 1 and cid_key == "C1":
                    hist_cr, recent_cr = 0.82, 0.15
                # Case 2 – promiscuous with uncaptured demand
                elif cid == 2 and cid_key == "C2":
                    hist_cr, recent_cr = 0.30, 0.28
                # Case 5 – campaign contextualised peak
                elif cid == 5 and cid_key == "C1":
                    hist_cr, recent_cr = 0.55, 0.58
                else:
                    hist_cr = random.uniform(0.1, 0.95)
                    recent_cr = hist_cr * random.uniform(0.6, 1.2)

                for m in months:
                    ym = m.strftime("%Y-%m")
                    in_recent = ym in last2
                    cr = recent_cr if in_recent else hist_cr
                    boost = 1.6 if (ym in camp_months and not in_recent) else 1.0
                    target = monthly_pot * cr * boost
                    if random.random() < 0.08:  # 8% chance of zero month
                        continue
                    _add_commodity_month(sales, cid, cat_prods, cid_key, m, target)

            else:  # technical
                # Case 3 – normal pause → NO alert  (median=90d, last=55d ago)
                if cid == 3 and cid_key == "T1":
                    median_days, n_purchases = 90, 10
                    last_date = END_DATE - timedelta(days=55)
                # Case 4 – sustained deterioration → SHOULD alert (median=40d, last=160d)
                elif cid == 4 and cid_key == "T1":
                    median_days, n_purchases = 40, 14
                    last_date = END_DATE - timedelta(days=160)
                else:
                    median_days = random.randint(25, 120)
                    n_purchases = random.randint(0, 20)
                    if n_purchases == 0:
                        continue
                    last_date = END_DATE - timedelta(days=random.randint(0, 120))

                dates = [last_date]
                for _ in range(n_purchases - 1):
                    gap = max(7, int(np.random.normal(median_days, median_days * 0.25)))
                    prev = dates[-1] - timedelta(days=gap)
                    if prev < START_DATE:
                        break
                    dates.append(prev)

                for dt in dates:
                    if START_DATE <= dt <= END_DATE:
                        _add_technical_purchase(sales, cid, cat_prods, cid_key, dt)

    df = pd.DataFrame(sales)
    if not df.empty:
        df.insert(0, "sale_id", range(1, len(df) + 1))
    return df


# ── Public entry point ─────────────────────────────────────────────────────────

def generate_all_data(data_dir: str = "data") -> tuple:
    np.random.seed(RANDOM_SEED)
    random.seed(RANDOM_SEED)

    os.makedirs(data_dir, exist_ok=True)

    products_df  = _make_products()
    clients_df   = _make_clients()
    potential_df = _make_potential(clients_df)
    campaigns_df = _make_campaigns()
    sales_df     = _make_sales(clients_df, products_df, potential_df)

    products_df.to_csv(f"{data_dir}/products.csv",  index=False)
    clients_df.to_csv(f"{data_dir}/clients.csv",    index=False)
    potential_df.to_csv(f"{data_dir}/potential.csv", index=False)
    campaigns_df.to_csv(f"{data_dir}/campaigns.csv", index=False)
    sales_df.to_csv(f"{data_dir}/sales.csv",        index=False)

    print(f"[mock_data] {len(sales_df):,} sales · {len(clients_df)} clients · {len(products_df)} products")
    return sales_df, clients_df, products_df, potential_df, campaigns_df
