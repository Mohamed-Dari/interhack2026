"""
Clinic Demand Twin — Streamlit dashboard
=========================================
Pages:
  1. Overview       — KPIs + distribution charts
  2. Alert Ranking  — prioritised, filterable table
  3. Alert Detail   — deep-dive + feedback buttons
  4. Feedback Log   — historical feedback viewer
"""

import os
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Path setup ─────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_loader   import load_all_data
from src.preprocessing import (
    aggregate_by_category_month,
    campaign_months_set,
    compute_commodity_stats,
    compute_technical_stats,
    get_reference_periods,
)
from src.signal_engine import generate_all_alerts
from src.scoring       import score_alerts
from src.explanations  import add_explanations
from src.feedback      import feedback_status_map, load_feedback, save_feedback

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Clinic Demand Twin · Inibsa",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Colour palette ─────────────────────────────────────────────────────────────
URGENCY_BG = {"high": "#e74c3c", "medium": "#e67e22", "low": "#27ae60"}
ATYPE_COLOR = {
    "anomalous_drop":        "#e74c3c",
    "churn_risk":            "#e67e22",
    "capture_window":        "#f1c40f",
    "replenishment_expected":"#3498db",
}
ATYPE_ICON = {
    "anomalous_drop":        "🔴",
    "churn_risk":            "🟠",
    "capture_window":        "🟡",
    "replenishment_expected":"🔵",
}


# ── Data pipeline (cached) ─────────────────────────────────────────────────────

@st.cache_data(show_spinner="Carregant i processant dades…")
def _build_pipeline():
    sales, clients, products, potential, campaigns = load_all_data()

    historical_months, reference_months = get_reference_periods(sales, n_recent=2)

    agg = aggregate_by_category_month(sales, products)

    commodity_stats = compute_commodity_stats(agg, potential, historical_months, reference_months)

    max_date = pd.to_datetime(sales["date"]).max()
    tech_stats = compute_technical_stats(sales, products, reference_end_date=max_date)

    camp_months = campaign_months_set(campaigns)

    alerts = generate_all_alerts(
        commodity_stats, tech_stats, potential, clients,
        list(reference_months), camp_months
    )

    if not alerts.empty:
        alerts = score_alerts(alerts, clients)
        alerts = add_explanations(alerts)

    return {
        "alerts":     alerts,
        "clients":    clients,
        "products":   products,
        "potential":  potential,
        "campaigns":  campaigns,
        "sales":      sales,
        "agg":        agg,
        "hist_months":historical_months,
        "ref_months": reference_months,
        "camp_months":camp_months,
    }


data = _build_pipeline()
alerts_df     = data["alerts"]
clients_df    = data["clients"]
agg_df        = data["agg"]
hist_months   = data["hist_months"]
ref_months    = data["ref_months"]
potential_df  = data["potential"]

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🦷 Clinic Demand Twin")
    st.markdown("*Smart Demand Signals · Inibsa*")
    st.markdown("---")
    page = st.radio("Navegació", ["📊 Overview", "📋 Alert Ranking", "🔍 Alert Detail", "💬 Feedback"])
    st.markdown("---")
    ref_sorted = sorted(ref_months)
    st.caption(f"**Període de referència:** {', '.join(ref_sorted)}")
    n_alerts = len(alerts_df) if not alerts_df.empty else 0
    st.caption(f"**Alertes generades:** {n_alerts}")
    st.caption(f"**Font de dades:** {'Excel real' if 'Clínica ' not in clients_df.iloc[0]['clinic_name'] else 'Dades sintètiques'}")

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
if page == "📊 Overview":
    st.title("📊 Overview — Clinic Demand Twin")
    st.markdown(
        "Plataforma de senyals de demanda per a la força de vendes d'Inibsa. "
        "Detecta oportunitats comercials accionables a partir de l'historial de compra de cada clínica."
    )

    if alerts_df.empty:
        st.warning("No s'han generat alertes. Comprova les dades i torna a executar.")
        st.stop()

    # ── KPIs ──────────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    total          = len(alerts_df)
    high_prio      = int((alerts_df["urgency"] == "high").sum())
    eco_opp        = alerts_df["estimated_revenue_opp"].sum()
    at_risk        = int(alerts_df[alerts_df["urgency"] == "high"]["client_id"].nunique())
    windows        = int((alerts_df["alert_type"] == "capture_window").sum())

    c1.metric("Alertes totals",          total)
    c2.metric("Alta prioritat",          high_prio,
              delta=f"{high_prio/total*100:.0f}% del total")
    c3.metric("Oportunitat €",           f"€{eco_opp:,.0f}")
    c4.metric("Clients en risc",         at_risk)
    c5.metric("Finestres de captura",    windows)

    st.markdown("---")

    # ── Charts row 1 ──────────────────────────────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Distribució per tipus d'alerta")
        counts = alerts_df["alert_type"].value_counts().reset_index()
        counts.columns = ["alert_type", "n"]
        fig = px.bar(
            counts, x="alert_type", y="n", color="alert_type",
            color_discrete_map=ATYPE_COLOR,
            labels={"alert_type": "Tipus", "n": "Alertes"},
        )
        fig.update_layout(showlegend=False, height=280, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("Commodity vs Technical")
        cat_c = alerts_df["category_type"].value_counts().reset_index()
        cat_c.columns = ["category_type", "n"]
        fig2 = px.pie(
            cat_c, names="category_type", values="n",
            color="category_type",
            color_discrete_map={"commodity": "#2ecc71", "technical": "#9b59b6"},
            hole=0.35,
        )
        fig2.update_layout(height=280, margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True)

    # ── Charts row 2 ──────────────────────────────────────────────────────────
    col_c, col_d = st.columns(2)

    with col_c:
        st.subheader("Top 10 oportunitats per família")
        fam_opp = (
            alerts_df.groupby("family_name")["estimated_revenue_opp"]
            .sum().reset_index()
            .sort_values("estimated_revenue_opp").tail(10)
        )
        fig3 = px.bar(
            fam_opp, x="estimated_revenue_opp", y="family_name",
            orientation="h",
            color="estimated_revenue_opp", color_continuous_scale="Blues",
            labels={"estimated_revenue_opp": "Oportunitat (€)", "family_name": "Família"},
        )
        fig3.update_layout(height=280, showlegend=False, margin=dict(t=10))
        st.plotly_chart(fig3, use_container_width=True)

    with col_d:
        st.subheader("Alertes per urgència")
        urg_c = (
            alerts_df["urgency"].value_counts()
            .reindex(["high", "medium", "low"]).fillna(0).reset_index()
        )
        urg_c.columns = ["urgency", "n"]
        fig4 = px.bar(
            urg_c, x="urgency", y="n", color="urgency",
            color_discrete_map=URGENCY_BG,
            labels={"urgency": "Urgència", "n": "Alertes"},
        )
        fig4.update_layout(showlegend=False, height=280, margin=dict(t=10))
        st.plotly_chart(fig4, use_container_width=True)

    # ── Canal recomanat ────────────────────────────────────────────────────────
    st.subheader("Canal recomanat")
    ch_c = alerts_df["recommended_channel"].value_counts().reset_index()
    ch_c.columns = ["canal", "n"]
    fig5 = px.bar(
        ch_c, x="canal", y="n", text="n",
        color="canal",
        color_discrete_map={
            "delegado": "#8e44ad",
            "televenta": "#2980b9",
            "marketing_automation": "#16a085",
        },
        labels={"canal": "Canal", "n": "Alertes"},
    )
    fig5.update_traces(textposition="outside")
    fig5.update_layout(showlegend=False, height=240, margin=dict(t=10))
    st.plotly_chart(fig5, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ALERT RANKING
# ══════════════════════════════════════════════════════════════════════════════
elif page == "📋 Alert Ranking":
    st.title("📋 Alert Ranking")
    st.markdown("Alertes prioritzades per score comercial. Filtra i exporta.")

    if alerts_df.empty:
        st.warning("No hi ha alertes generades.")
        st.stop()

    # Fetch latest feedback status
    fb_status = feedback_status_map(load_feedback())

    # ── Filters ───────────────────────────────────────────────────────────────
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)

    cats   = ["Tots"] + sorted(alerts_df["category_type"].unique())
    urgs   = ["Totes", "high", "medium", "low"]
    chans  = ["Tots"] + sorted(alerts_df["recommended_channel"].unique())
    atypes = ["Tots"] + sorted(alerts_df["alert_type"].unique())

    merged_reg = alerts_df.merge(clients_df[["client_id", "region"]], on="client_id", how="left")
    regions    = ["Totes"] + sorted(merged_reg["region"].dropna().unique())

    sel_cat  = fc1.selectbox("Categoria",  cats)
    sel_urg  = fc2.selectbox("Urgència",   urgs)
    sel_ch   = fc3.selectbox("Canal",      chans)
    sel_reg  = fc4.selectbox("Regió",      regions)
    sel_at   = fc5.selectbox("Tipus",      atypes)

    filtered = alerts_df.merge(clients_df[["client_id", "region"]], on="client_id", how="left")
    if sel_cat != "Tots":
        filtered = filtered[filtered["category_type"] == sel_cat]
    if sel_urg != "Totes":
        filtered = filtered[filtered["urgency"] == sel_urg]
    if sel_ch != "Tots":
        filtered = filtered[filtered["recommended_channel"] == sel_ch]
    if sel_reg != "Totes":
        filtered = filtered[filtered["region"] == sel_reg]
    if sel_at != "Tots":
        filtered = filtered[filtered["alert_type"] == sel_at]

    st.markdown(f"**{len(filtered)} alertes** amb els filtres actuals.")

    # ── Display table ─────────────────────────────────────────────────────────
    show = filtered[[
        "alert_id", "priority_score", "clinic_name", "family_name",
        "alert_type", "urgency", "estimated_revenue_opp",
        "recommended_channel", "confidence", "client_classification", "capture_rate",
    ]].copy()

    show["estimated_revenue_opp"] = show["estimated_revenue_opp"].map("€{:,.0f}".format)
    show["capture_rate"] = show["capture_rate"].apply(
        lambda x: f"{x*100:.0f}%" if pd.notna(x) and x is not None else "—"
    )
    show["client_classification"] = show["client_classification"].fillna("—")
    show["feedback"] = show["alert_id"].map(lambda aid: fb_status.get(aid, "—"))

    st.dataframe(show.reset_index(drop=True), use_container_width=True, height=520)

    # ── Export ────────────────────────────────────────────────────────────────
    csv_bytes = filtered.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Exportar CSV", csv_bytes, "alertes_filtrades.csv", "text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — ALERT DETAIL
# ══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Alert Detail":
    st.title("🔍 Alert Detail")

    if alerts_df.empty:
        st.warning("No hi ha alertes per veure.")
        st.stop()

    # ── Alert selector ────────────────────────────────────────────────────────
    opts = {
        f"[{r.urgency.upper()}] {r.clinic_name} · {r.family_name} ({r.alert_type})": r.alert_id
        for r in alerts_df.itertuples()
    }
    selected_label = st.selectbox("Selecciona una alerta", list(opts.keys()))
    aid = opts[selected_label]
    alert = alerts_df[alerts_df["alert_id"] == aid].iloc[0]

    # ── Header banner ─────────────────────────────────────────────────────────
    bg = URGENCY_BG.get(alert["urgency"], "#888")
    icon = ATYPE_ICON.get(alert["alert_type"], "⚪")
    st.markdown(
        f'<div style="background:{bg};color:#fff;padding:14px 18px;border-radius:10px;margin-bottom:14px">'
        f'<b style="font-size:1.1rem">{icon} {alert["clinic_name"]}</b>'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;{alert["family_name"]}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;{alert["alert_type"].replace("_"," ").title()}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;Urgència: <b>{alert["urgency"].upper()}</b>'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;Score: <b>{alert["priority_score"]}/100</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

    col_l, col_r = st.columns([3, 1])

    with col_l:
        st.markdown("### 📝 Explicació")
        st.info(alert.get("explanation", "—"))
        st.markdown("### ✅ Acció recomanada")
        st.success(alert.get("recommended_action", "—"))

        if alert.get("campaign_context"):
            st.warning(f"🗓️ Context campanya: {alert.get('campaign_note', '')}")

    with col_r:
        st.markdown("### Detalls")
        st.metric("Priority Score",       f"{alert['priority_score']}/100")
        st.metric("Oportunitat €",        f"€{alert['estimated_revenue_opp']:,.0f}")
        st.metric("Canal",                alert["recommended_channel"])
        st.metric("Confiança",            alert["confidence"])

        if alert["category_type"] == "commodity":
            cr = alert.get("capture_rate")
            st.metric("Capture Rate",     f"{cr*100:.0f}%" if cr is not None else "—")
            st.metric("Classificació",    alert.get("client_classification") or "—")
        else:
            st.metric("Dies sense compra",  str(int(alert.get("days_since") or 0)))
            st.metric("Interval medià",     f"{int(alert.get('median_interpurchase') or 0)} dies")
            st.metric("Nre. compres hist.", str(alert.get("n_purchases") or 0))

    # ── Evolution chart ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📈 Evolució mensual (Expected vs Observed)")

    cid    = alert["client_id"]
    cat_id = alert["cat_id"]

    client_ts = (
        agg_df[(agg_df["client_id"] == cid) & (agg_df["cat_id"] == cat_id)]
        .sort_values("year_month")
    )

    if not client_ts.empty:
        hist_avg = (
            client_ts[client_ts["year_month"].isin(hist_months)]["revenue"].mean()
            if hist_months else 0
        )

        fig_evo = go.Figure()
        bar_colors = [
            URGENCY_BG["high"] if m in ref_months else "#3498db"
            for m in client_ts["year_month"]
        ]
        fig_evo.add_trace(go.Bar(
            x=client_ts["year_month"], y=client_ts["revenue"],
            name="Observat", marker_color=bar_colors,
        ))
        fig_evo.add_trace(go.Scatter(
            x=client_ts["year_month"], y=[hist_avg] * len(client_ts),
            mode="lines", name="Esperat (mitjana hist.)",
            line=dict(color="#f39c12", dash="dash", width=2),
        ))

        # Potential line
        pot_row = potential_df[
            (potential_df["client_id"] == cid) & (potential_df["cat_id"] == cat_id)
        ]
        if not pot_row.empty:
            monthly_pot = pot_row.iloc[0]["monthly_potential"]
            fig_evo.add_trace(go.Scatter(
                x=client_ts["year_month"], y=[monthly_pot] * len(client_ts),
                mode="lines", name="Potencial mensual",
                line=dict(color="#9b59b6", dash="dot", width=2),
            ))

        fig_evo.update_layout(
            xaxis_title="Mes", yaxis_title="Revenue (€)",
            height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
            margin=dict(t=40),
        )
        st.plotly_chart(fig_evo, use_container_width=True)
        st.caption("🟥 Barres vermelles = període de referència · 🟦 Blau = historial")
    else:
        st.info("No hi ha dades d'evolució mensual per a aquesta combinació.")

    # ── Feedback ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 💬 Feedback comercial")

    note = st.text_input("Nota (opcional)", key=f"note_{aid}", placeholder="ex: El client ja ha contactat per correu…")

    fb1, fb2, fb3, fb4 = st.columns(4)

    def _save(status):
        save_feedback(
            alert["alert_id"], cid, alert["clinic_name"], alert["family_name"],
            alert["category_type"], alert["alert_type"], status, note,
        )

    if fb1.button("✅ Contactat",       key=f"c_{aid}"):
        _save("contacted");    st.success("Guardat: Contactat")
    if fb2.button("❌ Fals positiu",   key=f"f_{aid}"):
        _save("false_positive"); st.warning("Guardat: Fals positiu")
    if fb3.button("🔄 Recuperat",      key=f"r_{aid}"):
        _save("recovered");    st.success("Guardat: Recuperat")
    if fb4.button("📝 Nota",           key=f"n_{aid}"):
        _save("noted");        st.info("Nota guardada")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — FEEDBACK LOG
# ══════════════════════════════════════════════════════════════════════════════
elif page == "💬 Feedback":
    st.title("💬 Feedback Log")

    fb_df = load_feedback()

    if fb_df.empty:
        st.info("Encara no hi ha feedback. Ve a **Alert Detail** i registra accions comercials.")
    else:
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Total registres",  len(fb_df))
        r2.metric("Contactats",       int((fb_df["status"] == "contacted").sum()))
        r3.metric("Falsos positius",  int((fb_df["status"] == "false_positive").sum()))
        r4.metric("Recuperats",       int((fb_df["status"] == "recovered").sum()))

        st.dataframe(
            fb_df.sort_values("timestamp", ascending=False).reset_index(drop=True),
            use_container_width=True, height=400,
        )

        csv_fb = fb_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Exportar feedback", csv_fb, "feedback.csv", "text/csv")

    st.markdown("---")
    st.markdown("""
### 🔮 Camí cap a l'aprenentatge continu

El feedback recopilat aquí és la base per a un **sistema d'aprenentatge iteratiu**:

| Estat           | Ús futur                                                        |
|-----------------|------------------------------------------------------------------|
| `false_positive`| Elevar el llindar d'alerta per a aquest perfil client-família   |
| `recovered`     | Validar quins tipus d'alerta generen més conversions            |
| `contacted`     | Correlacionar amb les vendes posteriors per mesurar ROI         |
| `noted`         | Base de coneixement qualitatiu per als delegats                 |

En la propera iteració, aquest feedback alimentaria un model de regressió
logística que recalibraria automàticament els paràmetres de scoring i
els llindars de detecció per família i segment.
""")
