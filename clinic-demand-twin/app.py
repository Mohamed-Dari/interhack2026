"""Aplicación Streamlit de Clinic Demand Twin."""

from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_loader import load_all_data
from src.explanations import add_explanations
from src.feedback import feedback_status_map, load_feedback, save_feedback
from src.preprocessing import (
    aggregate_by_family_month,
    campaign_calendar,
    compute_commodity_stats,
    compute_technical_stats,
    get_reference_periods,
)
from src.scoring import score_alerts
from src.signal_engine import generate_all_alerts


st.set_page_config(
    page_title="Clinic Demand Twin",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

ALERT_COLORS = {
    "replenishment_expected": "#2563eb",
    "capture_window": "#f59e0b",
    "churn_risk": "#dc2626",
    "anomalous_drop": "#7c2d12",
}
ALERT_TYPE_LABELS = {
    "replenishment_expected": "Reposició esperada",
    "capture_window": "Captura de demanda",
    "churn_risk": "Risc comercial",
    "anomalous_drop": "Caiguda anòmala",
}
CATEGORY_LABELS = {
    "commodity": "Consum recurrent",
    "technical": "Producte tècnic",
}
CHANNEL_LABELS = {
    "delegado": "Delegat",
    "televenta": "Televenta",
    "marketing_automation": "Automatització",
}
URGENCY_LABELS = {"high": "Alta", "medium": "Mitjana", "low": "Baixa"}
URGENCY_COLORS = {"high": "#dc2626", "medium": "#f59e0b", "low": "#16a34a"}
URGENCY_LABEL_COLORS = {"Alta": "#dc2626", "Mitjana": "#f59e0b", "Baixa": "#16a34a"}
CLASSIFICATION_LABELS = {
    "loyal": "alta captura histórica",
    "promiscuous": "captura parcial",
    "marginal": "captura baja",
}


@st.cache_data(show_spinner="Carregant i processant dades...")
def build_pipeline() -> dict:
    sales, clients, products, potential, campaigns = load_all_data()
    model_date = pd.to_datetime(sales["date"]).max() if not sales.empty else pd.NaT
    historical_months, reference_months = get_reference_periods(sales, n_recent=2)
    agg = aggregate_by_family_month(sales, products)
    commodity_stats = compute_commodity_stats(agg, potential, products, historical_months, reference_months)
    technical_stats = compute_technical_stats(
        sales,
        products,
        reference_months,
        reference_end_date=model_date,
    )
    campaigns_by_family = campaign_calendar(campaigns)
    alerts = generate_all_alerts(
        commodity_stats,
        technical_stats,
        potential,
        clients,
        sorted(reference_months),
        campaigns_by_family,
    )
    if not alerts.empty:
        alerts = score_alerts(alerts, clients)
        alerts = add_explanations(alerts)

    return {
        "sales": sales,
        "clients": clients,
        "products": products,
        "potential": potential,
        "campaigns": campaigns,
        "agg": agg,
        "historical_months": historical_months,
        "reference_months": reference_months,
        "alerts": alerts,
        "source": sales.attrs.get("source", "desconeguda"),
        "model_date": model_date,
    }


data = build_pipeline()
alerts_df = data["alerts"]
clients_df = data["clients"]
products_df = data["products"]
potential_df = data["potential"]
agg_df = data["agg"]
historical_months = data["historical_months"]
reference_months = data["reference_months"]


with st.sidebar:
    st.title("Clinic Demand Twin")
    st.caption("Smart Demand Signals · Inibsa")
    st.divider()
    page = st.radio("Navegació", ["Overview", "Alert Ranking", "Alert Detail", "Feedback"])
    st.divider()
    st.caption(f"Font de dades: {data['source']}")
    if pd.notna(data["model_date"]):
        st.caption(f"Data del model: {data['model_date'].date()}")
    st.caption(f"Període recent: {', '.join(sorted(reference_months)) or '-'}")
    st.caption(f"Alertes generades: {len(alerts_df)}")


def _empty_alerts_guard() -> None:
    if alerts_df.empty:
        st.warning("No s'han generat alertes amb les dades actuals.")
        st.stop()


def _units_or_na(value) -> str:
    if value is None or pd.isna(value) or float(value) <= 0:
        return "n/d"
    return f"{float(value):,.1f}"


def _classification_label(value) -> str:
    return CLASSIFICATION_LABELS.get(value, value or "-")


def _overview_data() -> pd.DataFrame:
    df = alerts_df.copy()
    df["alert_type_label"] = df["alert_type"].map(ALERT_TYPE_LABELS).fillna(df["alert_type"])
    df["category_label"] = df["category_type"].map(CATEGORY_LABELS).fillna(df["category_type"])
    df["urgency_label"] = df["urgency"].map(URGENCY_LABELS).fillna(df["urgency"])
    df["channel_label"] = df["recommended_channel"].map(CHANNEL_LABELS).fillna(df["recommended_channel"])
    return df


def _format_eur(value: float) -> str:
    return f"{value:,.0f} EUR"


if page == "Overview":
    st.title("Overview executiu")
    _empty_alerts_guard()

    overview_df = _overview_data()
    total_alerts = len(alerts_df)
    high_alerts = int((alerts_df["urgency"] == "high").sum())
    opportunity = float(alerts_df["estimated_revenue_opportunity"].sum())
    at_risk = int(alerts_df[alerts_df["alert_type"].isin(["churn_risk", "anomalous_drop"])]["client_id"].nunique())
    capture_windows = int((alerts_df["alert_type"] == "capture_window").sum())
    top_family = (
        overview_df.groupby("family_name")["estimated_revenue_opportunity"].sum().sort_values(ascending=False)
    )
    top_family_name = top_family.index[0] if not top_family.empty else "-"
    top_family_value = float(top_family.iloc[0]) if not top_family.empty else 0
    high_share = high_alerts / total_alerts if total_alerts else 0

    st.caption(
        f"Dades fins a {data['model_date'].date() if pd.notna(data['model_date']) else '-'} · "
        f"període recent: {', '.join(sorted(reference_months)) or '-'}"
    )
    st.info(
        f"{high_alerts:,} alertes d'urgència alta ({high_share:.0%} del total). "
        f"La família amb més oportunitat estimada és {top_family_name} amb {_format_eur(top_family_value)}."
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Alertes", f"{total_alerts:,}")
    c2.metric("Urgència alta", f"{high_alerts:,}", delta=f"{high_share:.0%}")
    c3.metric("Oportunitat", _format_eur(opportunity))
    c4.metric("Clients en risc", at_risk)
    c5.metric("Captura demanda", f"{capture_windows:,}")

    st.divider()

    left, right = st.columns([1.25, 1])
    with left:
        st.subheader("Mapa de prioritat")
        scatter = overview_df.copy()
        scatter["opportunity_k"] = scatter["estimated_revenue_opportunity"] / 1000
        fig = px.scatter(
            scatter,
            x="priority_score",
            y="estimated_revenue_opportunity",
            color="alert_type_label",
            symbol="category_label",
            size="uncaptured_demand",
            size_max=18,
            hover_data={
                "clinic_name": True,
                "family_name": True,
                "urgency_label": True,
                "channel_label": True,
                "priority_score": ":.1f",
                "estimated_revenue_opportunity": ":,.0f",
                "uncaptured_demand": ":,.1f",
                "alert_type_label": False,
                "category_label": False,
                "opportunity_k": False,
            },
            labels={
                "priority_score": "Prioritat",
                "estimated_revenue_opportunity": "Oportunitat estimada",
                "alert_type_label": "Tipus",
                "category_label": "Categoria",
            },
            color_discrete_map={ALERT_TYPE_LABELS[k]: v for k, v in ALERT_COLORS.items()},
        )
        fig.update_yaxes(tickprefix="€", separatethousands=True)
        fig.update_layout(height=390, legend_title_text="", margin=dict(t=20, r=10, b=10, l=10))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Pla d'acció recomanat")
        channel_summary = (
            overview_df.groupby("channel_label", as_index=False)
            .agg(
                alertes=("alert_id", "count"),
                clients=("client_id", "nunique"),
                alta=("urgency", lambda s: int((s == "high").sum())),
                oportunitat=("estimated_revenue_opportunity", "sum"),
            )
            .sort_values("oportunitat", ascending=False)
        )
        st.dataframe(
            channel_summary,
            use_container_width=True,
            hide_index=True,
            height=175,
            column_config={
                "channel_label": st.column_config.TextColumn("Canal"),
                "alertes": st.column_config.NumberColumn("Alertes"),
                "clients": st.column_config.NumberColumn("Clients"),
                "alta": st.column_config.NumberColumn("Alta urgència"),
                "oportunitat": st.column_config.NumberColumn("Oportunitat", format="%.0f EUR"),
            },
        )

        st.subheader("Top alertes")
        top_alerts = overview_df.head(7)[
            ["priority_score", "clinic_name", "family_name", "alert_type_label", "channel_label"]
        ].rename(
            columns={
                "priority_score": "Score",
                "clinic_name": "Clínica",
                "family_name": "Família",
                "alert_type_label": "Motiu",
                "channel_label": "Canal",
            }
        )
        st.dataframe(top_alerts, use_container_width=True, hide_index=True, height=220)

    left, right = st.columns(2)
    with left:
        st.subheader("Motiu de les alertes")
        counts = (
            overview_df["alert_type_label"]
            .value_counts()
            .reset_index()
        )
        counts.columns = ["Motiu", "Alertes"]
        fig = px.bar(
            counts.sort_values("Alertes"),
            x="Alertes",
            y="Motiu",
            orientation="h",
            color="Motiu",
            color_discrete_map={ALERT_TYPE_LABELS[k]: v for k, v in ALERT_COLORS.items()},
            text="Alertes",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(height=320, showlegend=False, margin=dict(t=20, r=40, b=10, l=10))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Urgència per categoria")
        category_urgency = (
            overview_df.groupby(["category_label", "urgency_label"], as_index=False)
            .size()
            .rename(columns={"size": "Alertes"})
        )
        fig = px.bar(
            category_urgency,
            x="category_label",
            y="Alertes",
            color="urgency_label",
            barmode="stack",
            color_discrete_map=URGENCY_LABEL_COLORS,
            category_orders={"urgency_label": ["Alta", "Mitjana", "Baixa"]},
            labels={"category_label": "Categoria", "urgency_label": "Urgència"},
        )
        fig.update_layout(height=320, legend_title_text="", margin=dict(t=20, r=10, b=10, l=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Oportunitat estimada per família")
    by_family = (
        overview_df.groupby("family_name", as_index=False)["estimated_revenue_opportunity"]
        .sum()
        .sort_values("estimated_revenue_opportunity", ascending=True)
    )
    fig = px.bar(
        by_family,
        x="estimated_revenue_opportunity",
        y="family_name",
        orientation="h",
        text="estimated_revenue_opportunity",
        labels={"estimated_revenue_opportunity": "Oportunitat estimada", "family_name": "Família"},
        color="estimated_revenue_opportunity",
        color_continuous_scale="Teal",
    )
    fig.update_traces(texttemplate="%{text:,.0f} EUR", textposition="outside")
    fig.update_xaxes(tickprefix="€", separatethousands=True)
    fig.update_layout(height=320, showlegend=False, coloraxis_showscale=False, margin=dict(t=20, r=80, b=10, l=10))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Resum tècnic de la lectura"):
        st.write(
            "La prioritat combina severitat de la desviació, oportunitat estimada, urgència i confiança. "
            "El mapa mostra quines alertes tenen score alt i valor econòmic alt; la taula de canals converteix això en accions comercials."
        )


elif page == "Alert Ranking":
    st.title("Alert Ranking")
    _empty_alerts_guard()

    feedback_map = feedback_status_map(load_feedback())
    enriched = alerts_df.merge(clients_df[["client_id", "region"]], on="client_id", how="left")

    f1, f2, f3, f4, f5 = st.columns(5)
    selected_category = f1.selectbox("Categoria", ["Totes"] + sorted(enriched["category_type"].dropna().unique()))
    selected_urgency = f2.selectbox("Urgència", ["Totes", "high", "medium", "low"])
    selected_channel = f3.selectbox("Canal", ["Tots"] + sorted(enriched["recommended_channel"].dropna().unique()))
    selected_region = f4.selectbox("Regió", ["Totes"] + sorted(enriched["region"].dropna().unique()))
    selected_type = f5.selectbox("Tipus", ["Tots"] + sorted(enriched["alert_type"].dropna().unique()))

    filtered = enriched.copy()
    if selected_category != "Totes":
        filtered = filtered[filtered["category_type"] == selected_category]
    if selected_urgency != "Totes":
        filtered = filtered[filtered["urgency"] == selected_urgency]
    if selected_channel != "Tots":
        filtered = filtered[filtered["recommended_channel"] == selected_channel]
    if selected_region != "Totes":
        filtered = filtered[filtered["region"] == selected_region]
    if selected_type != "Tots":
        filtered = filtered[filtered["alert_type"] == selected_type]

    st.caption(f"{len(filtered)} alertes amb els filtres actuals")
    visible = filtered[
        [
            "alert_id",
            "priority_score",
            "clinic_name",
            "family_name",
            "alert_type",
            "urgency",
            "estimated_revenue_opportunity",
            "recommended_channel",
            "confidence",
        ]
    ].copy()
    visible["feedback"] = visible["alert_id"].map(lambda alert_id: feedback_map.get(alert_id, "-"))
    st.dataframe(visible, use_container_width=True, height=520, hide_index=True)
    st.download_button(
        "Exportar CSV",
        filtered.to_csv(index=False).encode("utf-8"),
        "clinic_demand_alerts.csv",
        "text/csv",
    )


elif page == "Alert Detail":
    st.title("Alert Detail")
    _empty_alerts_guard()

    options = {
        f"{row.priority_score:05.1f} · {row.clinic_name} · {row.family_name} · {row.alert_type}": row.alert_id
        for row in alerts_df.itertuples()
    }
    selected = st.selectbox("Selecciona una alerta", list(options.keys()))
    alert = alerts_df[alerts_df["alert_id"] == options[selected]].iloc[0]

    st.subheader(f"{alert['clinic_name']} · {alert['family_name']}")
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Priority score", f"{alert['priority_score']}/100")
    h2.metric("Urgència", alert["urgency"])
    h3.metric("Oportunitat", f"{alert['estimated_revenue_opportunity']:,.0f} EUR")
    h4.metric("Canal", alert["recommended_channel"])

    left, right = st.columns([2, 1])
    with left:
        st.markdown("#### Explicació")
        st.info(alert["explanation"])
        st.markdown("#### Acció recomanada")
        st.success(alert["recommended_action"])
        if alert.get("campaign_context"):
            st.warning(alert.get("campaign_note", "possible efecto campaña"))

    with right:
        st.markdown("#### Senyal")
        st.metric("Expected units", f"{alert['expected_units']:,.1f}")
        st.metric("Observed units", f"{alert['observed_units']:,.1f}")
        st.metric("Potential units", _units_or_na(alert.get("potential_units")))
        st.metric("Uncaptured demand", _units_or_na(alert.get("uncaptured_demand")))
        if alert["category_type"] == "commodity":
            capture_rate = alert.get("capture_rate")
            st.metric("Capture rate", f"{capture_rate * 100:.0f}%" if pd.notna(capture_rate) else "-")
            st.metric("Classificació", _classification_label(alert.get("client_classification")))
            if alert.get("potential_imputed"):
                st.caption("Potencial estimat internament a partir de l'històric.")
        else:
            st.metric("Dies sense compra", f"{int(alert.get('days_since_last_purchase') or 0)}")
            st.metric("Interval medià", f"{int(alert.get('median_interpurchase_days') or 0)} dies")

    st.markdown("#### Expected vs observed")
    client_id = alert["client_id"]
    family_id = alert["family_id"]
    monthly = agg_df[(agg_df["client_id"] == client_id) & (agg_df["family_id"] == family_id)].copy()
    all_months = sorted(historical_months | reference_months)
    monthly = pd.DataFrame({"year_month": all_months}).merge(monthly, on="year_month", how="left")
    monthly["units"] = monthly["units"].fillna(0)
    hist_units = monthly[monthly["year_month"].isin(historical_months)]["units"] if historical_months else pd.Series(dtype=float)
    hist_avg = hist_units.mean() if not hist_units.empty else 0
    hist_p10 = hist_units.quantile(0.10) if len(hist_units) >= 4 else None
    hist_p90 = hist_units.quantile(0.90) if len(hist_units) >= 4 else None

    fig = go.Figure()
    if hist_p10 is not None and hist_p90 is not None and pd.notna(hist_p10) and pd.notna(hist_p90):
        fig.add_trace(
            go.Scatter(
                x=monthly["year_month"],
                y=[hist_p90] * len(monthly),
                mode="lines",
                line={"width": 0},
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=monthly["year_month"],
                y=[hist_p10] * len(monthly),
                mode="lines",
                name="Banda histórica P10-P90",
                fill="tonexty",
                fillcolor="rgba(17, 24, 39, 0.12)",
                line={"width": 0},
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Bar(
            x=monthly["year_month"],
            y=monthly["units"],
            name="Observed",
            marker_color=[
                URGENCY_COLORS.get(alert["urgency"], "#dc2626") if month in reference_months else "#2563eb"
                for month in monthly["year_month"]
            ],
        )
    )
    fig.add_trace(
        go.Scatter(
            x=monthly["year_month"],
            y=[hist_avg] * len(monthly),
            mode="lines",
            name="Expected baseline",
            line={"color": "#111827", "dash": "dash"},
        )
    )
    potential_match = potential_df[
        (potential_df["client_id"] == client_id) & (potential_df["family_id"] == family_id)
    ]
    if not potential_match.empty:
        monthly_potential = float(potential_match.iloc[0]["monthly_potential_units"])
        if monthly_potential > 0:
            fig.add_trace(
                go.Scatter(
                    x=monthly["year_month"],
                    y=[monthly_potential] * len(monthly),
                    mode="lines",
                    name="Monthly potential",
                    line={"color": "#f59e0b", "dash": "dot"},
                )
            )
    fig.update_layout(height=360, xaxis_title="Mes", yaxis_title="Unitats", legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Feedback")
    note = st.text_input("Add note", key=f"note_{alert['alert_id']}")
    b1, b2, b3, b4 = st.columns(4)

    def persist(status: str) -> None:
        save_feedback(
            alert["alert_id"],
            alert["client_id"],
            alert["clinic_name"],
            alert["family_name"],
            alert["category_type"],
            alert["alert_type"],
            status,
            note,
        )

    if b1.button("Mark as contacted"):
        persist("contacted")
        st.success("Feedback guardat")
    if b2.button("Mark as false positive"):
        persist("false_positive")
        st.warning("Feedback guardat")
    if b3.button("Mark as recovered"):
        persist("recovered")
        st.success("Feedback guardat")
    if b4.button("Add note"):
        persist("noted")
        st.info("Nota guardada")


elif page == "Feedback":
    st.title("Feedback")
    feedback = load_feedback()
    if feedback.empty:
        st.info("Encara no hi ha feedback registrat.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registres", len(feedback))
        c2.metric("Contacted", int((feedback["status"] == "contacted").sum()))
        c3.metric("False positive", int((feedback["status"] == "false_positive").sum()))
        c4.metric("Recovered", int((feedback["status"] == "recovered").sum()))
        st.dataframe(feedback.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)
        st.download_button(
            "Exportar feedback",
            feedback.to_csv(index=False).encode("utf-8"),
            "feedback.csv",
            "text/csv",
        )

    st.markdown("#### Base per aprenentatge futur")
    st.write(
        "El feedback queda guardat a `storage/feedback.csv`. En una iteració següent es pot creuar amb vendes "
        "posteriors per mesurar recuperació, ajustar llindars i reduir falsos positius per família, segment i canal."
    )
