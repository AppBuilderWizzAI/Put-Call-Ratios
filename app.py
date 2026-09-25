from io import StringIO
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests
import streamlit as st

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="Smart Money vs. Dumb Money Put/Call Ratio (FRED)",
    layout="wide",
)

st.title("Smart Money vs. Dumb Money Indicator")
st.markdown("""
Dieser Indikator vergleicht das Absicherungsverhalten von Großanlegern (**Smart Money** im Index-Markt) 
mit der Spekulation von Kleinanlegern (**Dumb Money** im Einzelaktien-Markt) über Daten der **Federal Reserve Bank of St. Louis (FRED)**.

* **Smart Money:** CBOE Index Put/Call Ratio (`PCINDEX`)
* **Dumb Money:** CBOE Equity Call/Put Ratio ($1 / \text{Equity P/C}$ via `PCEQUITY`)
* **Formel:** `(Index Put/Call Ratio) - (Equity Call/Put Ratio)`
""")

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("Einstellungen")
fred_api_key = st.sidebar.text_input(
    "FRED API Key (Optional):",
    type="password",
    help="Kostenlos auf fred.stlouisfed.org erstellen. Wenn leer, wird der direkte CSV-Download genutzt.",
)

equity_series_id = st.sidebar.text_input(
    "Equity P/C Series ID:",
    value="PCEQUITY",
    help="FRED Ticker für Equity Put/Call Ratio",
)

index_series_id = st.sidebar.text_input(
    "Index P/C Series ID:",
    value="PCINDEX",
    help="FRED Ticker für Index Put/Call Ratio",
)

days = st.sidebar.slider(
    "Zeitraum (Tage):", min_value=30, max_value=1000, value=252
)


# --- FRED DATEN LADEN ---
def fetch_fred_series(series_id, api_key=None):
  """Lädt eine Zeitreihe von FRED per API-Key oder per direktem CSV-Download."""
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      )
  }

  if api_key:
    # 1. Option: Offizielle FRED JSON API
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"
    res = requests.get(url, headers=headers, timeout=15)
    res.raise_for_status()
    data = res.json().get("observations", [])
    df = pd.DataFrame(data)[["date", "value"]]
    df.columns = ["DATE", "VALUE"]
  else:
    # 2. Option: Direkter CSV-Download von FRED
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    res = requests.get(url, headers=headers, timeout=15)
    res.raise_for_status()
    df = pd.read_csv(StringIO(res.text))
    df.columns = ["DATE", "VALUE"]

  # Datenbereinigung
  df["VALUE"] = pd.to_numeric(df["VALUE"], errors="coerce")
  df["DATE"] = pd.to_datetime(df["DATE"], errors="coerce")
  return df.dropna(subset=["DATE", "VALUE"])


@st.cache_data(ttl=14400)
def load_market_data_from_fred(api_key, eq_id, idx_id):
  df_eq = fetch_fred_series(eq_id, api_key)
  df_idx = fetch_fred_series(idx_id, api_key)

  if df_eq.empty or df_idx.empty:
    raise ValueError(
        "Es konnten keine Daten für eine oder beide FRED-Serien geladen werden."
    )

  df_eq.rename(columns={"VALUE": "EQUITY_PC"}, inplace=True)
  df_idx.rename(columns={"VALUE": "INDEX_PC"}, inplace=True)

  # Merge über das Datum
  df = pd.merge(df_idx, df_eq, on="DATE", how="inner")
  df = df.sort_values("DATE").reset_index(drop=True)

  # Berechnungen
  df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]  # Dumb Money Sentiment
  df["SPREAD"] = df["INDEX_PC"] - df["EQUITY_CP"]  # Smart - Dumb Spread

  df["SPREAD_SMA10"] = df["SPREAD"].rolling(window=10).mean()
  df["SPREAD_SMA21"] = df["SPREAD"].rolling(window=21).mean()

  return df


# --- HAUPTLOGIK & ANZEIGE ---
try:
  with st.spinner("Lade Daten von FRED..."):
    df = load_market_data_from_fred(
        fred_api_key, equity_series_id, index_series_id
    )

  df_filtered = df.tail(days)
  latest = df.iloc[-1]

  # --- METRICS ANZEIGEN ---
  col1, col2, col3, col4 = st.columns(4)
  col1.metric("Datum", latest["DATE"].strftime("%Y-%m-%d"))
  col2.metric("Index P/C (Smart)", f"{latest['INDEX_PC']:.2f}")
  col3.metric("Equity C/P (Dumb)", f"{latest['EQUITY_CP']:.2f}")
  col4.metric("Spread (Smart - Dumb)", f"{latest['SPREAD']:.2f}")

  # --- CHARTS ERSTELLEN ---
  fig = make_subplots(
      rows=2,
      cols=1,
      shared_xaxes=True,
      vertical_spacing=0.08,
      subplot_titles=(
          "Smart vs. Dumb Money Spread Index",
          "Einzelkomponenten (Index P/C vs. Equity C/P)",
      ),
  )

  # Subplot 1: Spread & SMAs
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD"],
          name="Spread (Täglich)",
          line=dict(color="lightgray", width=1),
      ),
      row=1,
      col=1,
  )
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD_SMA10"],
          name="Spread (10-Tage SMA)",
          line=dict(color="blue", width=2),
      ),
      row=1,
      col=1,
  )
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD_SMA21"],
          name="Spread (21-Tage SMA)",
          line=dict(color="orange", width=2),
      ),
      row=1,
      col=1,
  )

  # Subplot 2: Ratios
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["INDEX_PC"],
          name="Index P/C (Smart Money)",
          line=dict(color="darkcyan", width=1.5),
      ),
      row=2,
      col=1,
  )
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["EQUITY_CP"],
          name="Equity C/P (Dumb Money)",
          line=dict(color="red", width=1.5),
      ),
      row=2,
      col=1,
  )

  fig.update_layout(height=700, template="plotly_white", hovermode="x unified")
  fig.update_yaxes(title_text="Spread Index", row=1, col=1)
  fig.update_yaxes(title_text="Ratio", row=2, col=1)

  st.plotly_chart(fig, use_container_width=True)

  # --- ROHDATEN ---
  with st.expander("Rohdaten anzeigen"):
    st.dataframe(
        df_filtered[[
            "DATE",
            "INDEX_PC",
            "EQUITY_PC",
            "EQUITY_CP",
            "SPREAD",
            "SPREAD_SMA10",
        ]].sort_values("DATE", ascending=False)
    )

except Exception as e:
  st.error(f"Fehler beim Laden der FRED-Daten: {e}")
  st.info(
      "Hinweis: Falls die Standard-IDs keine Daten liefern, erstelle einen"
      " kostenlosen API-Key auf https://fred.stlouisfed.org/ und trage ihn in"
      " der Seitenleiste ein."
  )
