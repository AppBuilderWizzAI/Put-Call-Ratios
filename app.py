import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="Smart Money vs. Dumb Money Put/Call Ratio", layout="wide"
)

st.title("Smart Money vs. Dumb Money Indicator")
st.markdown("""
Dieser Indikator vergleicht das Absicherungsverhalten von Großanlegern (**Smart Money** im Index-Markt) 
mit der Spekulation von Kleinanlegern (**Dumb Money** im Einzelaktien-Markt).

* **Smart Money:** CBOE Index Put/Call Ratio (`^CPCI`)
* **Dumb Money:** CBOE Equity Call/Put Ratio ($1 / \text{Equity P/C}$ via `^CPCE`)
* **Formel:** `(Index Put/Call Ratio) - (Equity Call/Put Ratio)`
""")

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("Einstellungen")
days = st.sidebar.slider(
    "Zeitraum (Tage):", min_value=30, max_value=1000, value=252
)


# --- DATEN VON YAHOO FINANCE LADEN ---
@st.cache_data(ttl=14400)
def load_market_data():
  # Einzelner Abruf der Ticker ist auf Cloud-Servern deutlich stabiler
  idx_ticker = yf.Ticker("^CPCI")
  eq_ticker = yf.Ticker("^CPCE")

  df_idx = idx_ticker.history(period="3y")[["Close"]].rename(
      columns={"Close": "INDEX_PC"}
  )
  df_eq = eq_ticker.history(period="3y")[["Close"]].rename(
      columns={"Close": "EQUITY_PC"}
  )

  if df_idx.empty or df_eq.empty:
    raise ValueError(
        "Daten konnten nicht von Yahoo Finance geladen werden. Bitte versuche"
        " es später erneut."
    )

  # Zeitzonen entfernen, um Daten sauber nach Datum zusammenzuführen
  df_idx.index = pd.to_datetime(df_idx.index).tz_localize(None)
  df_eq.index = pd.to_datetime(df_eq.index).tz_localize(None)

  # Merge über das Datum
  df = pd.merge(df_idx, df_eq, left_index=True, right_index=True, how="inner")
  df = df.reset_index().rename(columns={"Date": "DATE", "index": "DATE"})

  # Berechnungen
  df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]  # Dumb Money Sentiment
  df["SPREAD"] = df["INDEX_PC"] - df["EQUITY_CP"]  # Smart - Dumb Spread

  df["SPREAD_SMA10"] = df["SPREAD"].rolling(window=10).mean()
  df["SPREAD_SMA21"] = df["SPREAD"].rolling(window=21).mean()

  return df


# --- HAUPTLOGIK & ANZEIGE ---
try:
  with st.spinner("Lade Daten von Yahoo Finance..."):
    df = load_market_data()

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
  st.error(f"Fehler: {e}")
