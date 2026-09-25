from io import StringIO
import re
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests
import streamlit as st
import yfinance as yf

# --- SEITEN-KONFIGURATION ---
st.set_page_config(
    page_title="Smart Money vs. Dumb Money Sentiment Dashboard", layout="wide"
)

st.title("Smart & Dumb Money Put/Call Ratio Dashboard")
st.markdown("""
Dieses Dashboard vergleicht das Absicherungsverhalten professioneller Akteure (**Smart Money**) 
mit der Spekulation von Kleinanlegern (**Dumb Money**).

* **Smart Money 1 (CBOE):** OEX Put/Call Ratio (S&P 100 Optionen – *optional via ScraperAPI*)
* **Smart Money 2 (Yahoo):** Index Put/Call Ratio (`^CPCI` – *immer verfügbar*)
* **Dumb Money (Yahoo):** Equity Call/Put Ratio ($1 / \text{Equity P/C}$ via `^CPCE`)
""")

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("Einstellungen")
scraper_api_key = st.sidebar.text_input(
    "ScraperAPI Key (Optional für OEX Daten):",
    type="password",
    help="Falls leer oder ungültig, läuft die App stabil nur mit den Yahoo-Finance-Daten weiter.",
)
days = st.sidebar.slider(
    "Zeitraum (Tage):", min_value=30, max_value=1000, value=252
)


# --- 1. YAHOO FINANCE DATEN LADEN (STABILE BASIS) ---
@st.cache_data(ttl=14400)
def load_yahoo_data():
  try:
    # ^CPCE = CBOE Equity Put/Call, ^CPCI = CBOE Index Put/Call
    tickers = yf.Tickers("^CPCE ^CPCI")
    df_eq = tickers.tickers["^CPCE"].history(period="3y")[["Close"]]
    df_idx = tickers.tickers["^CPCI"].history(period="3y")[["Close"]]

    if df_eq.empty or df_idx.empty:
      return pd.DataFrame()

    df = pd.merge(
        df_idx,
        df_eq,
        left_index=True,
        right_index=True,
        suffixes=("_INDEX", "_EQUITY"),
    )
    df = df.reset_index()

    # Zeitzonen entfernen für sauberen Merge
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)

    df.rename(
        columns={
            "Date": "DATE",
            "Close_INDEX": "INDEX_PC",
            "Close_EQUITY": "EQUITY_PC",
        },
        inplace=True,
    )

    return df
  except Exception as e:
    st.error(f"Fehler beim Laden der Yahoo-Finance-Daten: {e}")
    return pd.DataFrame()


# --- 2. CBOE OEX DATEN VIA SCRAPERAPI LADEN (FEHLERTOLERANT) ---
def parse_cboe_csv(raw_text):
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
    raise ValueError("Keine Kopfzeile im CBOE CSV gefunden.")

  csv_data = "\n".join(lines[header_idx:])
  df = pd.read_csv(StringIO(csv_data), on_bad_lines="skip")
  df.columns = [str(c).strip().upper() for c in df.columns]

  date_cols = [c for c in df.columns if "DATE" in c]
  date_col = date_cols[0] if date_cols else df.columns[0]
  df["DATE"] = pd.to_datetime(df[date_col], errors="coerce")
  df = df.dropna(subset=["DATE"])

  pc_cols = [c for c in df.columns if "P/C" in c or "RATIO" in c]
  pc_col = pc_cols[0] if pc_cols else df.columns[-1]
  df["OEX_PC"] = pd.to_numeric(df[pc_col], errors="coerce")

  return df.dropna(subset=["OEX_PC"])[["DATE", "OEX_PC"]]


@st.cache_data(ttl=14400)
def load_oex_via_scraperapi(api_key):
  if not api_key:
    return pd.DataFrame()

  try:
    oex_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/oexpc.csv"
    # Nutzen von render=true und premium=true zur Umgehung von Cloudflare
    proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={oex_url}&render=true&premium=true"

    res = requests.get(proxy_url, timeout=25)
    res.raise_for_status()

    return parse_cboe_csv(res.text)
  except Exception as e:
    st.sidebar.warning(
        f"CBOE OEX Daten nicht verfügbar ({e}). App läuft im Yahoo-Modus."
    )
    return pd.DataFrame()


# --- HAUPTLOGIK & DATENVERARBEITUNG ---
with st.spinner("Lade Marktdaten..."):
  df_yf = load_yahoo_data()

if df_yf.empty:
  st.error(
      "Es konnten keine Marktdaten geladen werden. Bitte versuche es später"
      " erneut."
  )
else:
  # Versuche OEX-Daten zu laden (falls API-Key vorhanden)
  df_oex = (
      load_oex_via_scraperapi(scraper_api_key)
      if scraper_api_key
      else pd.DataFrame()
  )

  # Zusammenführung (Left Join auf Yahoo-Daten)
  if not df_oex.empty:
    df = pd.merge(df_yf, df_oex, on="DATE", how="left")
    has_oex = df["OEX_PC"].notna().any()
  else:
    df = df_yf.copy()
    has_oex = False

  df = df.sort_values("DATE").reset_index(drop=True)

  # Berechnungen
  df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]  # Dumb Money Sentiment
  df["SPREAD_INDEX"] = (
      df["INDEX_PC"] - df["EQUITY_CP"]
  )  # Smart (Index) - Dumb (Equity)
  df["SPREAD_INDEX_SMA10"] = df["SPREAD_INDEX"].rolling(window=10).mean()

  if has_oex:
    df["SPREAD_OEX"] = (
        df["OEX_PC"] - df["EQUITY_CP"]
    )  # Smart (OEX) - Dumb (Equity)
    df["SPREAD_OEX_SMA10"] = df["SPREAD_OEX"].rolling(window=10).mean()

  df_filtered = df.tail(days)
  latest = df.iloc[-1]

  # --- METRICS ANZEIGEN ---
  col1, col2, col3, col4, col5 = st.columns(5)
  col1.metric("Datum", latest["DATE"].strftime("%Y-%m-%d"))

  oex_metric = f"{latest['OEX_PC']:.2f}" if has_oex and pd.notna(latest.get("OEX_PC")) else "N/A"
  col2.metric("OEX P/C (Smart 1)", oex_metric)

  col3.metric("Index P/C (Smart 2)", f"{latest['INDEX_PC']:.2f}")
  col4.metric("Equity C/P (Dumb)", f"{latest['EQUITY_CP']:.2f}")

  spread_metric = f"{latest['SPREAD_OEX']:.2f}" if has_oex and pd.notna(latest.get("SPREAD_OEX")) else f"{latest['SPREAD_INDEX']:.2f}"
  col5.metric(
      "Spread (Smart - Dumb)",
      spread_metric,
      help="Nutzt OEX-Spread wenn verfügbar, sonst Index-Spread.",
  )

  # --- CHARTS ERSTELLEN ---
  fig = make_subplots(
      rows=2,
      cols=1,
      shared_xaxes=True,
      vertical_spacing=0.08,
      subplot_titles=(
          "Smart vs. Dumb Money Spread Index",
          "Die Put/Call Ratios im Verlauf",
      ),
  )

  # Chart 1: Spreads
  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["SPREAD_INDEX_SMA10"],
          name="Index vs Equity Spread (10d SMA)",
          line=dict(color="blue", width=2),
      ),
      row=1,
      col=1,
  )

  if has_oex:
    fig.add_trace(
        plt.Scatter(
            x=df_filtered["DATE"],
            y=df_filtered["SPREAD_OEX_SMA10"],
            name="OEX vs Equity Spread (10d SMA)",
            line=dict(color="purple", width=2),
        ),
        row=1,
        col=1,
    )

  # Chart 2: Ratios
  if has_oex:
    fig.add_trace(
        plt.Scatter(
            x=df_filtered["DATE"],
            y=df_filtered["OEX_PC"],
            name="OEX P/C (Smart Money 1)",
            line=dict(color="purple", width=1.5),
        ),
        row=2,
        col=1,
    )

  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["INDEX_PC"],
          name="Index P/C (Smart Money 2)",
          line=dict(color="blue", width=1.5),
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

  fig.update_layout(height=750, template="plotly_white", hovermode="x unified")
  fig.update_yaxes(title_text="Spread Index", row=1, col=1)
  fig.update_yaxes(title_text="Ratio", row=2, col=1)

  st.plotly_chart(fig, use_container_width=True)

  # --- ROHDATEN ANZEIGEN ---
  with st.expander("Rohdaten anzeigen"):
    cols_to_show = ["DATE", "INDEX_PC", "EQUITY_PC", "EQUITY_CP", "SPREAD_INDEX"]
    if has_oex:
      cols_to_show.insert(1, "OEX_PC")
      cols_to_show.append("SPREAD_OEX")

    st.dataframe(
        df_filtered[cols_to_show].sort_values("DATE", ascending=False)
    )
