"""
Template-based explanations — no LLM required.
Each template is filled with numeric values from the alert row.
"""

import pandas as pd


# ── Templates ──────────────────────────────────────────────────────────────────

_COMMODITY = {
    "anomalous_drop": (
        "{clinic} presenta una caída anormal en {family}. "
        "Se esperaban {expected} € este período según su patrón histórico "
        "({n_ref} meses), pero solo se observaron {observed} €. "
        "Con una captura histórica del {cr:.0f}% es cliente leal: esta caída "
        "es una señal de riesgo real. {camp}"
        "Recomendación: contacto urgente vía {channel}."
    ),
    "churn_risk": (
        "{clinic} muestra señales de fuga en {family}. "
        "Históricamente compra al {cr:.0f}% de su potencial, "
        "pero en los últimos {n_ref} meses solo se han registrado {observed} € "
        "frente a los {expected} € esperados. {camp}"
        "Recomendación: contacto preventivo vía {channel}."
    ),
    "capture_window": (
        "{clinic} tiene demanda no capturada en {family}. "
        "El potencial mensual declarado es {pot} €/mes "
        "y la captura histórica es del {cr:.0f}% (perfil: {cls}). "
        "Oportunidad estimada: {uncaptured} € en el período. {camp}"
        "Recomendación: acción comercial vía {channel} para aumentar cuota."
    ),
    "replenishment_expected": (
        "{clinic} tiene reposición pendiente en {family}. "
        "Se esperaban {expected} € en los últimos {n_ref} meses "
        "según patrón histórico, pero se han observado {observed} €. {camp}"
        "Recomendación: seguimiento vía {channel}."
    ),
}

_TECHNICAL = {
    "replenishment_expected": (
        "{clinic} supera ligeramente su intervalo habitual en {family}. "
        "El intervalo mediano entre compras es {median} días "
        "y llevan {days} días sin comprar ({n} compras históricas). {camp}"
        "Recomendación: contacto proactivo vía {channel}."
    ),
    "churn_risk": (
        "{clinic} lleva {days} días sin comprar {family}, "
        "cuando el patrón habitual es cada {median} días. "
        "Con {n} compras históricas, la confianza en el patrón es {conf}. {camp}"
        "Recomendación: contacto urgente vía {channel}."
    ),
    "anomalous_drop": (
        "{clinic} ha superado ampliamente su ciclo de recompra en {family}. "
        "Llevan {days} días sin compra frente a un intervalo habitual de {median} días "
        "(ratio {ratio:.1f}×). Deterioro sostenido que requiere atención inmediata. {camp}"
        "Recomendación: llamada urgente vía {channel}."
    ),
}

_ACTIONS = {
    "delegado":              "Asignar visita del delegado esta semana.",
    "televenta":             "Llamada de televenta en las próximas 48 horas.",
    "marketing_automation":  "Incluir en campaña automática (email / WhatsApp).",
}


# ── Builders ───────────────────────────────────────────────────────────────────

def _camp_note(row: pd.Series) -> str:
    if row.get("campaign_context"):
        return f"⚠️ Coincide con {row.get('campaign_note', 'campaña activa')} — considerar efecto puntual. "
    return ""


def _fmt(value, decimals=0) -> str:
    """Format numeric values gracefully."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if decimals == 0:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


def generate_explanation(row: pd.Series) -> str:
    cat    = row.get("category_type", "commodity")
    atype  = row.get("alert_type",   "replenishment_expected")
    ch     = row.get("recommended_channel", "televenta")
    camp   = _camp_note(row)

    n_ref = 2  # reference window length is always 2 months

    try:
        if cat == "commodity":
            tpl = _COMMODITY.get(atype, _COMMODITY["replenishment_expected"])
            return tpl.format(
                clinic    = row.get("clinic_name", ""),
                family    = row.get("family_name", ""),
                expected  = _fmt(row.get("expected")),
                observed  = _fmt(row.get("observed")),
                pot       = _fmt(row.get("monthly_potential")),
                uncaptured= _fmt(row.get("uncaptured")),
                cr        = float(row.get("capture_rate") or 0) * 100,
                cls       = row.get("client_classification", ""),
                n_ref     = n_ref,
                camp      = camp,
                channel   = ch,
            )
        else:
            tpl = _TECHNICAL.get(atype, _TECHNICAL["replenishment_expected"])
            median = row.get("median_interpurchase") or 0
            days   = row.get("days_since")           or 0
            ratio  = days / max(median, 1)
            return tpl.format(
                clinic  = row.get("clinic_name", ""),
                family  = row.get("family_name", ""),
                days    = _fmt(days),
                median  = _fmt(median),
                n       = row.get("n_purchases", 0),
                conf    = row.get("confidence", "medium"),
                ratio   = ratio,
                camp    = camp,
                channel = ch,
            )
    except Exception:
        return (
            f"Alerta detectada para {row.get('clinic_name', '')} "
            f"en {row.get('family_name', '')}."
        )


def generate_action(row: pd.Series) -> str:
    return _ACTIONS.get(row.get("recommended_channel", "televenta"),
                        "Contactar al cliente.")


def add_explanations(alerts_df: pd.DataFrame) -> pd.DataFrame:
    df = alerts_df.copy()
    df["explanation"]        = df.apply(generate_explanation, axis=1)
    df["recommended_action"] = df.apply(generate_action, axis=1)
    return df
