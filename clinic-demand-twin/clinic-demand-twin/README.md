# Clinic Demand Twin
### Smart Demand Signals — Inibsa · Interhack 2026

---

## Què fa

**Clinic Demand Twin** transforma l'historial de compra de les clíniques dentals d'Inibsa en **alertes comercials accionables**.

Per a cada parella *client × família de producte*, el sistema:
1. Calcula el comportament de compra esperat (basat en l'historial i el potencial declarat)
2. El compara amb el comportament observat recentment
3. Genera una alerta quan hi ha una desviació rellevant
4. Prioritza, explica i recomana el canal comercial adequat

---

## Com instal·lar

```bash
cd clinic-demand-twin
pip install -r requirements.txt
```

## Com executar

```bash
streamlit run app.py
```

El sistema detecta automàticament la font de dades:
- **Excel real** (`interhack2026/Inibsa challenge/Datasets.xlsx`) → s'usa si existeix
- **CSVs generats** (`data/*.csv`) → s'usa si existeixen
- **Dades sintètiques** → es generen automàticament si no hi ha cap altra font

---

## Estructura del projecte

```
clinic-demand-twin/
├── app.py                  # Dashboard Streamlit (4 pàgines)
├── requirements.txt
├── README.md
├── data/                   # CSVs (generats o extrets del Excel)
│   ├── sales.csv
│   ├── clients.csv
│   ├── products.csv
│   ├── potential.csv
│   └── campaigns.csv
├── src/
│   ├── mock_data.py        # Generador de dades sintètiques
│   ├── data_loader.py      # Càrrega multi-font (Excel → CSV → mock)
│   ├── preprocessing.py    # Agregació mensual + estadístiques
│   ├── signal_engine.py    # Lògica d'alertes (commodity + technical)
│   ├── scoring.py          # Priority score, urgència, canal
│   ├── explanations.py     # Textos sense LLM (plantilles)
│   └── feedback.py         # Persistència de feedback en CSV
└── storage/
    └── feedback.csv        # Historial d'accions comercials
```

---

## Estructura de dades

### Dataset real (Datasets.xlsx)
| Full       | Camps clau                                                    |
|------------|---------------------------------------------------------------|
| Ventas     | Fecha, Id.Cliente, Id.Producto, Unidades, Valores_H (€)       |
| Clientes   | Id.Cliente, Provincia                                         |
| Productos  | Id.Prod, Bloque analítico, Categoria_H, Familia_H             |
| Potencial  | Id.Cliente, Familia, Categoria Productos, Potencial_H (€/any) |
| Campañas   | Campaña, Fecha inicio, Fecha fin                              |

### Categories de producte
| Cat ID | Nom comercial  | Tipus     | Famílies de producte |
|--------|----------------|-----------|----------------------|
| C1     | Anestesia      | commodity | Familia C1           |
| C2     | Biomateriales  | commodity | Familia C2           |
| T1     | Bioseguridad   | technical | Familia T1, T2       |

---

## Lògica d'alertes

### Commodities (C1, C2)
1. Agrega vendes mensuals per (client, categoria)
2. Calcula `capture_rate = historical_avg_revenue / (Potencial_H / 12)`
3. Classifica el client:
   - **loyal**: capture_rate ≥ 0.70
   - **promiscuous**: 0.15 ≤ capture_rate < 0.70
   - **marginal**: capture_rate < 0.15
4. Compara el comportament recent (últims 2 mesos) amb l'esperat
5. Genera alertes:
   - `anomalous_drop` → client loyal amb caiguda > 60%
   - `churn_risk` → client loyal amb caiguda > 40%
   - `capture_window` → client promiscuous/marginal amb potencial no capturat
   - `replenishment_expected` → qualsevol client amb caiguda > 50%

### Productes tècnics (T1)
1. Calcula intervals entre compres per client
2. Calcula `median_interpurchase_days`
3. Si `days_since > median * 1.5` → genera alerta
4. No alerta si < 3 compres históriques (confiança insuficient)
5. Nivells: `replenishment_expected` (1.5×), `churn_risk` (2×), `anomalous_drop` (3×)

### Context de campanya
Les campanyes d'Inibsa (festejos comercials globals) s'identifiquen als períodes
de referència. Quan una alerta coincideix amb una campanya, s'afegeix una nota
explicativa perquè el comercial la tingui en compte.

### Priority score
```
priority_score = 40% × severity_gap
               + 30% × revenue_opportunity_normalised
               + 20% × urgency_score
               + 10% × confidence_score
```

---

## 5 casos de demo dissenyats

| # | Client | Família | Cas                                          | Alerta esperada    |
|---|--------|---------|----------------------------------------------|--------------------|
| 1 | 001    | C1      | Client loyal amb caiguda recent del 80%      | `anomalous_drop`   |
| 2 | 002    | C2      | Client promiscuous, captura del 30%          | `capture_window`   |
| 3 | 003    | T1      | Pausa normal (55 dies, mediana 90)           | **sense alerta**   |
| 4 | 004    | T1      | Deteriorament sostingut (160 dies, med. 40)  | `anomalous_drop`   |
| 5 | 005    | C1      | Pic durant campanya, contextualitzat          | nota de campanya   |

---

## Limitacions actuals

- El **potencial declarat** (`Potencial_H`) s'interpreta com a anual; si és mensual, el capture_rate s'ha d'ajustar manualment.
- Els **retorns** (Unidades < 0) s'exclouen del còmput; en una versió productiva caldria analitzar-los per detectar insatisfacció.
- Les **campanyes** no estan vinculades a famílies de producte específiques; el context és global.
- El **feedback** no recalibra el model en aquesta versió — és la base per a futures iteracions.

---

## Evolució futura

```
v1 (actual)  → Detecció d'anomalies basada en regles + scoring estàtic
v2           → Recalibració automàtica dels llindars via feedback (regresió logística)
v3           → Integració CRM: push d'alertes a Salesforce / HubSpot
v4           → Predicció de demanda futura (ARIMA / Prophet per client-família)
v5           → Recomanació de producte substitutiu quan hi ha stockout
```

---

## Com encaixa amb el repte Smart Demand Signals

El repte d'Inibsa demana **convertir dades de vendes en senyals comercials intel·ligents**.
Clinic Demand Twin respon directament:

- **Signal detection**: identifica automàticament quins clients s'allunyen del seu patró
- **Prioritisation**: el priority_score combina magnitud, urgència i oportunitat econòmica
- **Actionability**: cada alerta inclou explicació en llenguatge natural i canal recomanat
- **Feedback loop**: el sistema aprèn de les accions comercials per millorar la precisió
- **Scalability**: l'arquitectura basada en categories permet afegir nous productes sense canviar la lògica

---

*Construït per al hackathon Interhack 2026 · Equip [nom de l'equip]*
