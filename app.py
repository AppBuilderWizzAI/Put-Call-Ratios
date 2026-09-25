from io import StringIO
import re
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(
    page_title="Smart Money vs. Dumb Money Sentiment Dashboard", layout="wide"
)

st.title("Smart & Dumb Money Put/Call Ratio Dashboard")
st.markdown("""
Dieses Dashboard vergleicht die Absicherungsstrategien professioneller Akteure (**Smart Money**) 
mit der Spekulation von Kleinanlegern (**Dumb Money**).

* **Smart Money 1:** OEX Put/Call Ratio (CBOE S&P 100 Optionen via ScraperAPI)
* **Smart Money 2:** Index Put/Call Ratio (`^CPCI` via Yahoo Finance)
* **Dumb Money:** Equity Call/Put Ratio ($1 / \text{Equity P/C}$)
""")

# --- SIDEBAR: EINSTELLUNGEN & API KEY ---
st.sidebar.header("Konfiguration")
scraper_api_key = st.sidebar.text_input(
    "ScraperAPI Key (für CBOE OEX):",
    type="password",
    help="Kostenlos auf scraperapi.com erstellen. Wenn leer, werden nur Yahoo Finance Daten verwendet.",
)
days = st.sidebar.slider(
    "Zeitraum (Tage):", min_value=30, max_value=1000, value=252
)


# --- 1. YAHOO FINANCE DATEN LADEN ---
@st.cache_data(ttl=14400)
def load_yahoo_data():
  try:
    # ^CPCE = CBOE Equity Put/Call Ratio, ^CPCI = CBOE Index Put/Call Ratio
    tickers = yf.Tickers("^CPCE ^CPCI")
    df_eq = tickers.tickers["^CPCE"].history(period="3y")[["Close"]]
    df_idx = tickers.tickers["^CPCI"].history(period="3y")[["Close"]]

    df = pd.merge(
        df_idx,
        df_eq,
        left_index=True,
        right_index=True,
        suffixes=("_INDEX", "_EQUITY"),
    )
    df = df.reset_index()

    # Zeitzoneninformationen vom Datum entfernen
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)

    df.rename(
        columns={
            "Date": "DATE",
            "Close_INDEX": "INDEX_PC",
            "Close_EQUITY": "EQUITY_PC_YF",
        },
        inplace=True,
    )

    return df
  except Exception as e:
    st.error(f"Fehler beim Laden von Yahoo Finance Daten: {e}")
    return pd.DataFrame()


# --- 2. CBOE DATEN VIA SCRAPERAPI LADEN ---
def parse_cboe_text(raw_text):
  lines = raw_text.splitlines()
  header_idx = -1
  for i, line in enumerate(lines):
    if "date" in line.lower():
      header_idx = i
      break

  if header_idx == -1:
    date_pattern = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
    for i, line in enumerate(lines):
      if date_pattern.search(line):
        header_idx = max(0, i - 1)
        break

  if header_idx == -1:
    raise ValueError("Keine Kopfzeile gefunden.")

  csv_data = "\n".join(lines[header_idx:])
  df = pd.read_csv(StringIO(csv_data), on_bad_lines="skip")
  df.columns = [str(c).strip().upper() for c in df.columns]

  date_cols = [c for c in df.columns if "DATE" in c]
  date_col = date_cols[0] if date_cols else df.columns[0]
  df["DATE"] = pd.to_datetime(df[date_col], errors="coerce")
  df = df.dropna(subset=["DATE"])

  pc_cols = [c for c in df.columns if "P/C" in c or "RATIO" in c]
  pc_col = pc_cols[0] if pc_cols else df.columns[-1]
  df["PC_RATIO"] = pd.to_numeric(df[pc_col], errors="coerce")

  return df.dropna(subset=["PC_RATIO"])[["DATE", "PC_RATIO"]]


@st.cache_data(ttl=14400)
def load_cboe_via_scraperapi(api_key):
  if not api_key:
    return pd.DataFrame()

  try:
    oex_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/oexpc.csv"
    proxy_url = (
        f"http://api.scraperapi.com?api_key={api_key}&url={oex_url}"
    )

    res = requests.get(proxy_url, timeout=30)
    res.raise_for_status()

    df_oex = parse_cboe_text(res.text)
    df_oex.rename(columns={"PC_RATIO": "OEX_PC"}, inplace=True)
    return df_oex
  except Exception as e:
    st.warning(
        f"CBOE OEX Daten konnten via ScraperAPI nicht geladen werden: {e}"
    )
    return pd.DataFrame()


# --- DATEN ZUSAMMENFÜHREN ---
with st.spinner("Lade Marktdaten..."):
  df_yf = load_yahoo_data()
  df_oex = (
      load_cboe_via_scraperapi(scraper_api_key)
      if scraper_api_key
      else pd.DataFrame()
  )

if not df_yf.empty:
  # Merge Yahoo mit CBOE OEX (falls vorhanden)
  if not df_oex.empty:
    df = pd.merge(df_yf, df_oex, on="DATE", how="left")
  else:
    df = df_yf.copy()
    df["OEX_PC"] = None  # Platzhalter falls kein API-Key eingegeben wurde

  df = df.sort_values("DATE").reset_index(drop=True)

  # Berechnungen
  # Equity Call/Put Ratio = 1 / Equity Put/Call Ratio
  df["EQUITY_CP"] = 1.0 / df["EQUITY_PC_YF"]

  # Spreads
  df["SPREAD_INDEX"] = df["INDEX_PC"] - df["EQUITY_CP"]
  df["SPREAD_INDEX_SMA10"] = df["SPREAD_INDEX"].rolling(window=10).mean()

  if "OEX_PC" in df.columns and df["OEX_PC"].notna().any():
    df["SPREAD_OEX"] = df["OEX_PC"] - df["EQUITY_CP"]
    df["SPREAD_OEX_SMA10"] = df["SPREAD_OEX"].rolling(window=10).mean()

  df_filtered = df.tail(days)
  latest = df.iloc[-1]

  # --- METRICS ANZEIGEN ---
  col1, col2, col3, col4, col5 = st.columns(5)
  col1.metric("Datum", latest["DATE"].strftime("%Y-%m-%d"))

  oex_val = (
      f"{latest['OEX_PC']:.2f}"
      if "OEX_PC" in latest and pd.notna(latest["OEX_PC"])
      else "N/A"
  )
  col2.metric("OEX P/C (Smart 1)", oex_val)

  col3.metric("Index P/C (Smart 2)", f"{latest['INDEX_PC']:.2f}")
  col4.metric("Equity C/P (Dumb)", f"{latest['EQUITY_CP']:.2f}")

  spread_val = (
      f"{latest['SPREAD_OEX']:.2f}"
      if "SPREAD_OEX" in latest and pd.notna(latest["SPREAD_OEX"])
      else f"{latest['SPREAD_INDEX']:.2f}"
  )
  col5.metric("Spread (Smart - Dumb)", spread_val)

  # --- CHARTS ERSTELLEN ---
  fig = make_subplots(
      rows=2,
      cols=1,
      shared_xaxes=True,
      vertical_spacing=0.08,
      subplot_titles=(
          "Smart vs. Dumb Money Spread Index",
          "Die 3 Put/Call Ratios im Vergleich",
      ),
  )

  # Upper Plot: Spreads
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD_INDEX_SMA10"],
          name="Index vs Equity Spread (10-Tage SMA)",
          line=dict(color="blue", width=2),
      ),
      row=1,
      col=1,
  )

  if "SPREAD_OEX_SMA10" in df_filtered.columns:
    fig.add_trace(
        plt.Scatter(
            x=df_filtered["DATE"],
            y=df_filtered["SPREAD_OEX_SMA10"],
            name="OEX vs Equity Spread (10-Tage SMA)",
            line=dict(color="purple", width=2),
        ),
        row=1,
        col=1,
    )

  # Lower Plot: Alle 3 Put/Call Ratios
  # 1. OEX Put/Call Ratio (Smart Money 1)
  if "OEX_PC" in df_filtered.columns and df_filtered["OEX_PC"].notna().any():
    fig.add_trace(
        plt.Scatter(
            x=df_filtered["DATE"],
            y=df_filtered["OEX_PC"],
            name="OEX P/C (Smart Money 1)",
            line=dict(color="green", width=1.5),
        ),
        row=2,
        col=1,
    )

  # 2. Index Put/Call Ratio (Smart Money 2)
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["INDEX_PC"],
          name="Index P/C (Smart Money 2)",
          line=dict(color="darkcyan", width=1.5),
      ),
      row=2,
      col=1,
  )

  # 3. Equity Call/Put Ratio (Dumb Money)
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

  fig.update_layout(height=750, template="plotly_white", hovermode="x unified")
  fig.update_yaxes(title_text="Spread", row=1, col=1)
  fig.update_yaxes(title_text="Ratio", row=2, col=1)

  st.plotly_chart(fig, use_container_width=True)

  # Rohdaten-Tab
  with st.expander("Rohdaten anzeigen"):
    st.dataframe(df_filtered.sort_values("DATE", ascending=False))
