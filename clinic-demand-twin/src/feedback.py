"""
Persistencia ligera del feedback mediante CSV.
Aquí no se recalibra el modelo: estos datos son la base para
aprendizaje supervisado futuro (False Positive -> subir umbrales;
Recovered -> validar la eficacia de la alerta).
"""

import os
from datetime import datetime

import pandas as pd

_STORAGE_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage")
_FEEDBACK_CSV = os.path.join(_STORAGE_DIR, "feedback.csv")

_COLUMNS = ["timestamp", "alert_id", "client_id", "clinic_name",
            "family_name", "category_type", "alert_type", "status", "note"]


def _ensure_file() -> None:
    os.makedirs(_STORAGE_DIR, exist_ok=True)
    if not os.path.exists(_FEEDBACK_CSV):
        pd.DataFrame(columns=_COLUMNS).to_csv(_FEEDBACK_CSV, index=False)


def save_feedback(
    alert_id: str,
    client_id,
    clinic_name: str,
    family_name: str,
    category_type: str,
    alert_type: str,
    status: str,
    note: str = "",
) -> None:
    _ensure_file()
    row = pd.DataFrame([{
        "timestamp":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alert_id":      alert_id,
        "client_id":     client_id,
        "clinic_name":   clinic_name,
        "family_name":   family_name,
        "category_type": category_type,
        "alert_type":    alert_type,
        "status":        status,
        "note":          note,
    }])
    row.to_csv(_FEEDBACK_CSV, mode="a",
               header=not os.path.exists(_FEEDBACK_CSV) or os.path.getsize(_FEEDBACK_CSV) == 0,
               index=False)


def load_feedback() -> pd.DataFrame:
    _ensure_file()
    try:
        df = pd.read_csv(_FEEDBACK_CSV)
        return df if not df.empty else pd.DataFrame(columns=_COLUMNS)
    except Exception:
        return pd.DataFrame(columns=_COLUMNS)


def feedback_status_map(feedback_df: pd.DataFrame) -> dict:
    """Devuelve {alert_id: ultimo_estado} para mostrarlo en la tabla de alertas."""
    if feedback_df.empty:
        return {}
    latest = (
        feedback_df.sort_values("timestamp")
        .drop_duplicates("alert_id", keep="last")
    )
    return dict(zip(latest["alert_id"], latest["status"]))
