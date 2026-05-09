"""Explicaciones basadas en plantillas. No se usa ningún LLM."""

from __future__ import annotations

import pandas as pd


ACTION_BY_CHANNEL = {
    "delegado": "Asignar visita del delegado esta semana con propuesta concreta de reposición o recuperación.",
    "televenta": "Contacto por televenta en las próximas 48 horas y registro del resultado en feedback.",
    "marketing_automation": "Activar una secuencia automática con recordatorio de reposición y oferta de la familia.",
}

CLASSIFICATION_LABELS = {
    "loyal": "alta captura histórica",
    "promiscuous": "captura parcial",
    "marginal": "captura baja",
}


def _num(value, decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "-"
    if decimals == 0:
        return f"{float(value):,.0f}"
    return f"{float(value):,.{decimals}f}"


def _campaign_sentence(row: pd.Series) -> str:
    if row.get("campaign_context"):
        return f" Coincide con {row.get('campaign_note', 'una campaña activa')}; conviene no interpretar picos aislados como demanda estructural."
    return ""


def _classification_label(value) -> str:
    return CLASSIFICATION_LABELS.get(value, value or "sin clasificar")


def _commodity_explanation(row: pd.Series) -> str:
    clinic = row.get("clinic_name", "La clínica")
    family = row.get("family_name", "la familia")
    capture = float(row.get("capture_rate") or 0) * 100
    classification = _classification_label(row.get("client_classification"))
    campaign = _campaign_sentence(row)
    potential_note = " El potencial usado es una estimación interna basada en histórico." if row.get("potential_imputed") else ""

    if row.get("alert_type") == "capture_window":
        return (
            f"{clinic} presenta demanda no capturada en {family}. "
            f"El potencial esperado para el periodo es {_num(row.get('potential_units'))} unidades y se observaron "
            f"{_num(row.get('observed_units'))}. Su captura histórica es del {capture:.0f}% "
            f"({classification}), por lo que existe una ventana razonable de aumentar cuota."
            f"{potential_note}"
            f"{campaign} Recomendación: {row.get('recommended_action')}"
        )

    if row.get("alert_type") == "churn_risk":
        return (
            f"{clinic} muestra una caída compatible con riesgo comercial en {family}. Esperábamos "
            f"{_num(row.get('expected_units'))} unidades según su patrón histórico, pero se observaron "
            f"{_num(row.get('observed_units'))}. El cliente era {classification}, con captura histórica "
            f"del {capture:.0f}%."
            f"{campaign} Recomendación: {row.get('recommended_action')}"
        )

    if row.get("alert_type") == "anomalous_drop":
        return (
            f"{clinic} presenta una caída relevante en {family}. Esperábamos "
            f"{_num(row.get('expected_units'))} unidades este periodo según su patrón histórico y potencial declarado, "
            f"pero se observaron {_num(row.get('observed_units'))}. El cliente tiene una captura histórica "
            f"del {capture:.0f}%, por lo que la desviación requiere atención comercial."
            f"{campaign} Recomendación: {row.get('recommended_action')}"
        )

    return (
        f"{clinic} parece tener reposición pendiente en {family}. Esperábamos "
        f"{_num(row.get('expected_units'))} unidades y se observaron {_num(row.get('observed_units'))}."
        f"{campaign} Recomendación: {row.get('recommended_action')}"
    )


def _technical_explanation(row: pd.Series) -> str:
    clinic = row.get("clinic_name", "La clínica")
    family = row.get("family_name", "la familia")
    days = _num(row.get("days_since_last_purchase"))
    median = _num(row.get("median_interpurchase_days"))
    n_purchases = _num(row.get("n_purchases"))
    campaign = _campaign_sentence(row)

    if row.get("alert_type") == "anomalous_drop":
        return (
            f"{clinic} ha superado ampliamente su ciclo habitual en {family}. "
            f"Lleva {days} días sin compra frente a una mediana histórica de {median} días "
            f"({n_purchases} compras históricas). Es una señal de deterioro sostenido."
            f"{campaign} Recomendación: {row.get('recommended_action')}"
        )

    if row.get("alert_type") == "churn_risk":
        return (
            f"{clinic} lleva {days} días sin comprar {family}, cuando su patrón habitual es cada "
            f"{median} días. La ausencia reciente es compatible con una pausa prolongada; conviene verificar actividad, stock o cambio de proveedor."
            f"{campaign} Recomendación: {row.get('recommended_action')}"
        )

    return (
        f"{clinic} supera su ventana esperada de recompra en {family}. "
        f"Mediana histórica: {median} días; días desde última compra: {days}."
        f"{campaign} Recomendación: {row.get('recommended_action')}"
    )


def generate_action(row: pd.Series) -> str:
    return ACTION_BY_CHANNEL.get(row.get("recommended_channel"), "Contactar al cliente y registrar el resultado.")


def generate_explanation(row: pd.Series) -> str:
    if row.get("category_type") == "technical":
        return _technical_explanation(row)
    return _commodity_explanation(row)


def add_explanations(alerts_df: pd.DataFrame) -> pd.DataFrame:
    if alerts_df.empty:
        return alerts_df
    df = alerts_df.copy()
    df["recommended_action"] = df.apply(generate_action, axis=1)
    df["explanation"] = df.apply(generate_explanation, axis=1)
    return df
