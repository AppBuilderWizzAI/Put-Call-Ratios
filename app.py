from io import StringIO
import re
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests
import streamlit as st

st.set_page_config(
    page_title="Smart Money vs. Dumb Money Put/Call Ratio", layout="wide"
)

st.title("Smart Money vs. Dumb Money Indicator")
st.markdown("""
Dieser Indikator vergleicht das Absicherungsverhalten von Großanlegern (**Smart Money** im S&P 100 / OEX) 
mit der Spekulation von Kleinanlegern (**Dumb Money** im CBOE Equity Markt).

**Formel:** `(OEX Put/Call Ratio) - (Equity Call/Put Ratio)`
""")


def fetch_cboe_url(url):
  """Ruft CBOE-Daten mit vollständigen Browser-Headern und Fallback auf cloudscraper ab."""
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
      ),
      "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
      "Referer": "https://www.cboe.com/",
      "Sec-Ch-Ua": (
          '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"'
      ),
      "Sec-Ch-Ua-Mobile": "?0",
      "Sec-Ch-Ua-Platform": '"Windows"',
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
      "Sec-Fetch-Site": "cross-site",
      "Sec-Fetch-User": "?1",
      "Upgrade-Insecure-Requests": "1",
  }

  # Versuche cloudscraper zu nutzen, falls installiert (umgeht Cloudflare)
  try:
    import cloudscraper

    scraper = cloudscraper.create_scraper()
    res = scraper.get(url, headers=headers, timeout=15)
  except ImportError:
    # Fallback auf standardmäßigem requests.Session()
    session = requests.Session()
    res = session.get(url, headers=headers, timeout=15)

  if res.status_code == 403:
    raise PermissionError(
        "CBOE blockiert Anfragen von Cloud-Servern (HTTP 403 / Cloudflare"
        " Bot-Schutz)."
    )

  res.raise_for_status()
  return res.text


def parse_cboe_csv(url):
  raw_text = fetch_cboe_url(url)

  if "<html" in raw_text.lower() or "<doctype" in raw_text.lower():
    raise ValueError(
        "CBOE hat eine HTML-Sperrseite anstelle einer CSV-Datei zurückgegeben."
    )

  lines = raw_text.splitlines()

  # Suche nach Kopfzeile 'date'
  header_idx = -1
  for i, line in enumerate(lines):
    if "date" in line.lower():
      header_idx = i
      break

  # Fallback: Suche nach Datumsmuster MM/DD/YYYY
  if header_idx == -1:
    date_pattern = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
    for i, line in enumerate(lines):
      if date_pattern.search(line):
        header_idx = max(0, i - 1)
        break

  if header_idx == -1:
    raise ValueError("Keine Datums-Kopfzeile in der CBOE-Datei gefunden.")

  csv_data = "\n".join(lines[header_idx:])
  try:
    df = pd.read_csv(StringIO(csv_data), on_bad_lines="skip")
  except Exception:
    df = pd.read_csv(StringIO(csv_data), header=None, on_bad_lines="skip")

  df.columns = [str(c).strip().upper() for c in df.columns]

  date_cols = [c for c in df.columns if "DATE" in c]
  date_col = date_cols[0] if date_cols else df.columns[0]

  df["DATE"] = pd.to_datetime(df[date_col], errors="coerce")
  df = df.dropna(subset=["DATE"])

  pc_cols = [c for c in df.columns if "P/C" in c or "RATIO" in c]
  pc_col = pc_cols[0] if pc_cols else df.columns[-1]

  df["PC_RATIO"] = pd.to_numeric(df[pc_col], errors="coerce")
  df = df.dropna(subset=["PC_RATIO"])

  return df[["DATE", "PC_RATIO"]]


@st.cache_data(ttl=14400)
def load_and_process_ratios():
  try:
    equity_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv"
    oex_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/oexpc.csv"

    df_eq = parse_cboe_csv(equity_url)
    df_oex = parse_cboe_csv(oex_url)

    df = pd.merge(
        df_oex, df_eq, on="DATE", suffixes=("_OEX", "_EQUITY")
    )
    df = df.sort_values("DATE").reset_index(drop=True)

    df["OEX_PC"] = df["PC_RATIO_OEX"]
    df["EQUITY_PC"] = df["PC_RATIO_EQUITY"]
    df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]
    df["SPREAD"] = df["OEX_PC"] - df["EQUITY_CP"]

    df["SPREAD_SMA10"] = df["SPREAD"].rolling(window=10).mean()
    df["SPREAD_SMA21"] = df["SPREAD"].rolling(window=21).mean()

    return df

  except Exception as e:
    st.error(f"Fehler beim Laden der CBOE-Daten: {e}")
    return pd.DataFrame()


with st.spinner("Lade CBOE-Daten..."):
  df = load_and_process_ratios()

if not df.empty:
  st.sidebar.header("Einstellungen")
  days = st.sidebar.slider(
      "Zeitraum (Tage):", min_value=30, max_value=1000, value=252
  )

  df_filtered = df.tail(days)
  latest = df.iloc[-1]

  col1, col2, col3, col4 = st.columns(4)
  col1.metric("Datum", latest["DATE"].strftime("%Y-%m-%d"))
  col2.metric("OEX Put/Call (Smart)", f"{latest['OEX_PC']:.2f}")
  col3.metric("Equity Call/Put (Dumb)", f"{latest['EQUITY_CP']:.2f}")
  col4.metric("Spread (Smart - Dumb)", f"{latest['SPREAD']:.2f}")

  fig = make_subplots(
      rows=2,
      cols=1,
      shared_xaxes=True,
      vertical_spacing=0.08,
      subplot_titles=(
          "Smart vs. Dumb Money Spread",
          "Einzelkomponenten (OEX P/C vs. Equity C/P)",
      ),
  )

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

  fig.add_trace(
      plt.Scatter(
          x=df_filtered["DATE"],
          y=df_filtered["OEX_PC"],
          name="OEX P/C (Smart Money)",
          line=dict(color="green", width=1.5),
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

  with st.expander("Rohdaten anzeigen"):
    st.dataframe(
        df_filtered[[
            "DATE",
            "OEX_PC",
            "EQUITY_PC",
            "EQUITY_CP",
            "SPREAD",
            "SPREAD_SMA10",
        ]].sort_values("DATE", ascending=False)
    )
