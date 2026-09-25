import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="Smart & Dumb Money Put/Call Ratio", page_icon="📈", layout="wide"
)

st.title("Smart & Dumb Money Put/Call Ratio Dashboard")

st.markdown("""
Dieses Dashboard vergleicht das Absicherungsverhalten professioneller Akteure (**Smart Money** im Index-Markt) 
mit der Spekulation von Kleinanlegern (**Dumb Money** im Einzelaktien-Markt).

* **Smart Money:** CBOE Index Put/Call Ratio (`INDEX_PC`)
* **Dumb Money:** CBOE Equity Call/Put Ratio ($1 / \\text{EQUITY\\_PC}$)
* **Spread / Indikator:** $\\text{Index P/C} - \\left(\\frac{1}{\\text{Equity P/C}}\\right)$
""")

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("⚙️ Einstellungen")

days = st.sidebar.slider(
    "Zeitraum (Anzahl Tage):", min_value=30, max_value=1000, value=252
)

# Button zum manuellen Aktualisieren des Caches
if st.sidebar.button("🔄 Live-Daten neu laden"):
  st.cache_data.clear()
  st.rerun()


# --- VOLLAUTOMATISCHER DATEN-DOWNLOAD ---
def fetch_yahoo_data(ticker: str, range_str: str = "2y") -> pd.DataFrame:
  """Holt historische Daten direkt aus der Yahoo Finance Chart-Schnittstelle."""
  url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_str}&interval=1d"

  # Browser-Header vortäuschen, um Cloud-Sperren zu umgehen
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
      )
  }

  response = requests.get(url, headers=headers, timeout=10)
  if response.status_code != 200:
    raise RuntimeError(
        f"Fehler beim Abrufen von {ticker} (HTTP {response.status_code})"
    )

  data = response.json()
  result = data["chart"]["result"][0]
  timestamps = result["timestamp"]
  closes = result["indicators"]["quote"][0]["close"]

  df = pd.DataFrame({
      "DATE": pd.to_datetime(timestamps, unit="s").dt.strftime("%Y-%m-%d"),
      ticker: closes,
  })
  return df.dropna()


# Cache für 1 Stunde (3600 Sekunden)
@st.cache_data(ttl=3600)
def load_live_data():
  # Daten für Index (Smart Money) und Equity (Dumb Money) abrufen
  df_cpci = fetch_yahoo_data("^CPCI", "2y")
  df_cpce = fetch_yahoo_data("^CPCE", "2y")

  # Zusammenführen über das Datum
  df = pd.merge(df_cpci, df_cpce, on="DATE")
  df.rename(
      columns={"^CPCI": "INDEX_PC", "^CPCE": "EQUITY_PC"}, inplace=True
  )

  df["DATE"] = pd.to_datetime(df["DATE"])
  df["INDEX_PC"] = pd.to_numeric(df["INDEX_PC"], errors="coerce")
  df["EQUITY_PC"] = pd.to_numeric(df["EQUITY_PC"], errors="coerce")

  df = df.dropna().sort_values("DATE")

  # Berechnungen
  df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]  # Dumb Money Call/Put Ratio
  df["SPREAD"] = df["INDEX_PC"] - df["EQUITY_CP"]  # Smart - Dumb Spread

  # Gleitende Durchschnitte
  df["SPREAD_SMA10"] = df["SPREAD"].rolling(window=10).mean()
  df["SPREAD_SMA21"] = df["SPREAD"].rolling(window=21).mean()

  return df


# --- HAUPTLOGIK & ANZEIGE ---
try:
  with st.spinner("Lade neuste Marktdaten von Yahoo Finance..."):
    df = load_live_data()

  df_filtered = df.tail(days)
  latest = df.iloc[-1]

  # --- KENNZAHLEN (METRICS) ---
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
      go.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD"],
          name="Spread (Täglich)",
          line=dict(color="lightgray", width=1),
      ),
      row=1,
      col=1,
  )
  fig.add_trace(
      go.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD_SMA10"],
          name="Spread (10-Tage SMA)",
          line=dict(color="#1f77b4", width=2),
      ),
      row=1,
      col=1,
  )
  fig.add_trace(
      go.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD_SMA21"],
          name="Spread (21-Tage SMA)",
          line=dict(color="#ff7f0e", width=2),
      ),
      row=1,
      col=1,
  )

  # Subplot 2: Ratios
  fig.add_trace(
      go.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["INDEX_PC"],
          name="Index P/C (Smart Money)",
          line=dict(color="darkcyan", width=1.5),
      ),
      row=2,
      col=1,
  )
  fig.add_trace(
      go.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["EQUITY_CP"],
          name="Equity C/P (Dumb Money)",
          line=dict(color="crimson", width=1.5),
      ),
      row=2,
      col=1,
  )

  fig.update_layout(height=700, template="plotly_white", hovermode="x unified")
  fig.update_yaxes(title_text="Spread Index", row=1, col=1)
  fig.update_yaxes(title_text="Ratio", row=2, col=1)

  st.plotly_chart(fig, use_container_width=True)

  # --- ROHDATEN TABELLE ---
  with st.expander("📊 Live-Rohdaten anzeigen"):
    st.dataframe(
        df_filtered[[
            "DATE",
            "INDEX_PC",
            "EQUITY_PC",
            "EQUITY_CP",
            "SPREAD",
            "SPREAD_SMA10",
        ]].sort_values("DATE", ascending=False),
        use_container_width=True,
    )

except Exception as e:
  st.error(f"❌ Fehler beim automatischen Abrufen der Live-Daten: {e}")
  st.info(
      "Klicke in der Seitenleiste auf 'Live-Daten neu laden' oder versuche es"
      " in einigen Minuten erneut."
  )
