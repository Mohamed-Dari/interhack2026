# Clinic Demand Twin

Smart Demand Signals per al repte d'Inibsa a Interhack 2026.

## Què fa

Clinic Demand Twin transforma històrics de compra de clíniques dentals en alertes comercials accionables.

Per cada parella `client_id + family_id`, l'app calcula un comportament esperat amb regles explicables basades en l'històric i el compara amb el comportament observat recent. Quan hi ha una desviació rellevant, genera una alerta amb motiu, prioritat, urgència, valor potencial, canal recomanat i una explicació.

## Instal·lació

```bash
cd interhack2026/clinic-demand-twin
pip install -r requirements.txt
```

## Execució

```bash
streamlit run app.py
```

Per forçar dades sintètiques:

```bash
CLINIC_TWIN_DATA_SOURCE=mock streamlit run app.py
```

Per reprocessar explícitament l'Excel original encara que ja existeixin CSV:

```bash
CLINIC_TWIN_DATA_SOURCE=excel streamlit run app.py
```

Fonts de dades suportades:

- `../Inibsa challenge/Datasets.xlsx`: és la font principal en mode automàtic. Es normalitza i es desa a `data/`.
- `data/*.csv`: fallback/cache local si l'Excel no està disponible.
- Mock data: si no hi ha CSV ni Excel, es generen dades sintètiques.

El dataset original del repte és l'Excel `Datasets.xlsx`. Els CSV no són el format original lliurat per Inibsa: són una capa normalitzada que genera l'app perquè la lògica analítica sigui més simple, ràpida i estable durant la demo.

## Estructura

```text
clinic-demand-twin/
  app.py
  requirements.txt
  README.md
  data/
    sales.csv
    clients.csv
    products.csv
    potential.csv
    campaigns.csv
  src/
    data_loader.py
    preprocessing.py
    signal_engine.py
    scoring.py
    explanations.py
    feedback.py
    mock_data.py
  storage/
    feedback.csv
```

## Dataset original: `Datasets.xlsx`

El fitxer adjunt d'Inibsa té aquests fulls:

`Ventas`

- `Num.Fact`
- `Fecha`
- `Id. Cliente`
- `Id. Producto`
- `Unidades`
- `Valores_H`

`Clientes`

- `Id. Cliente`
- `Provincia`

`Productos`

- `Id.Prod`
- `Bloque analítico`
- `Categoria_H`
- `Familia_H`

`Potencial`

- `Id.Cliente`
- `Familia`
- `Categoria Productos`
- `Potencial_H`

`Campañas`

- `Campaña`
- `Fecha inicio`
- `Fecha fin`

## Contracte normalitzat intern

L'app converteix `Datasets.xlsx` a aquests CSV interns a `data/`. Aquest és el contracte que consumeixen `preprocessing.py`, `signal_engine.py` i el dashboard.

`sales.csv`

- `date`
- `client_id`
- `product_id`
- `units`
- `revenue`

`clients.csv`

- `client_id`
- `clinic_name`
- `city`
- `region`
- `clinic_segment`

`products.csv`

- `product_id`
- `product_name`
- `family_id`
- `family_name`
- `category_type`: `commodity` o `technical`

`potential.csv`

- `client_id`
- `family_id`
- `monthly_potential_units`

`campaigns.csv`

- `campaign_id`
- `family_id`
- `start_date`
- `end_date`
- `campaign_name`

## Lògica d'alertes

Commodities:

- Agrega vendes mensuals per client i família.
- Calcula `capture_rate = historical_avg_units / monthly_potential_units`.
- Classifica internament clients com `loyal`, `promiscuous` o `marginal`; a la UI es mostra com alta captura, captura parcial o captura baixa.
- Genera `capture_window`, `churn_risk`, `anomalous_drop` o `replenishment_expected` segons desviació recent, potencial i perfil.

Productes tècnics:

- Calcula intervals entre compres per client i família.
- Usa `median_interpurchase_days` i `days_since_last_purchase`.
- Evita alertar combinacions amb menys de 3 compres històriques.
- Detecta reposició esperada, risc de churn o caiguda anòmala quan el client supera significativament el seu patró.

Campanyes:

- Si una alerta coincideix amb una campanya de la mateixa família, s'afegeix context.
- Els pics de campanya no es presenten com demanda estructural sense avís.

Scoring:

```text
priority_score =
  40% severity_gap +
  30% revenue_opportunity_normalized +
  20% urgency_score +
  10% confidence_score
```

## Dashboard

Pantalles incloses:

- `Overview`: KPIs, alertes per tipus, categoria, família i urgència.
- `Alert Ranking`: taula prioritzada amb filtres per categoria, urgència, canal, regió i tipus.
- `Alert Detail`: explicació, recomanació, expected vs observed, potencial i variables clau.
- `Feedback`: registre d'accions comercials.

El detall d'alerta mostra la data màxima del dataset com a data del model, una banda històrica P10-P90 quan hi ha prou historial i oculta el potencial quan la font real no aporta una estimació útil.

El feedback es desa a:

```text
storage/feedback.csv
```

## Dades sintètiques

El generador crea:

- 100 clíniques
- 5 famílies de producte
- 25 productes
- 24 mesos d'històric
- commodities recurrents i tècnics irregulars
- 5 casos controlats: loyal amb caiguda, promiscuous amb demanda no capturada, tècnic sense alerta, tècnic amb deteriorament i campanya recent contextualitzada.

## Limitacions

- És un MVP de hackathon basat en regles, no un model predictiu entrenat.
- El potencial de l'Excel real es normalitza a unitats aproximades dividint euros per preu mitjà.
- Les campanyes de l'Excel real no venen lligades a família, així que es repliquen per família durant la normalització.
- El feedback encara no recalibra el model.
