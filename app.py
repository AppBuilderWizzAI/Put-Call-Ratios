import io
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Smart Money vs. Dumb Money Indicator",
    page_icon="📈",
    layout="wide",
)

st.title("Smart Money vs. Dumb Money Indicator")

st.markdown("""
Dieser Indikator vergleicht das Absicherungsverhalten von Großanlegern (**Smart Money** im Index-Markt) mit der Spekulation von Kleinanlegern (**Dumb Money** im Einzelaktien-Markt) über Daten der Federal Reserve Bank of St. Louis (FRED).

* **Smart Money:** CBOE Index Put/Call Ratio (`PCINDEX`)
* **Dumb Money:** CBOE Equity Call/Put Ratio ($1 / \\text{PCEQUITY}$)
* **Formel:** $\\text{Smart Money Indicator} = \\text{Index Put/Call Ratio} - \\text{Equity Call/Put Ratio}$
""")

st.sidebar.header("⚙️ Einstellungen")

# Key automatisch aus Streamlit Secrets laden (falls hinterlegt)
secret_key = st.secrets.get("FRED_API_KEY", "")

# Formular für Mobilgeräte (verhindert unvollständige Eingaben)
with st.sidebar.form(key="fred_form"):
  api_key_input = st.text_input(
      "FRED API-Key:",
      value=secret_key,
      type="password",
      help="Kostenlos erstellen auf https://fred.stlouisfed.org/docs/api/api_key.html",
  )
  days_to_show = st.slider("Anzahl Tage anzeigen:", 30, 1000, 365)
  submit_button = st.form_submit_button(label="🔄 Daten laden")

# Welcher Key soll genutzt werden?
active_api_key = (
    api_key_input.strip() if api_key_input.strip() else secret_key.strip()
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_via_api(series_id, key):
  """Offizielle FRED JSON API (funktioniert zuverlässig mit Key)."""
  url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={key}&file_type=json"
  res = requests.get(url, headers=HEADERS, timeout=15)
  res.raise_for_status()
  data = res.json()
  obs = data.get("observations", [])
  if not obs:
    raise ValueError(f"Keine Daten für {series_id} erhalten.")
  df = pd.DataFrame(obs)[["date", "value"]]
  df["value"] = pd.to_numeric(df["value"], errors="coerce")
  df["date"] = pd.to_datetime(df["date"])
  return df.dropna().set_index("date")["value"]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_via_csv(series_id):
  """Fallback-Direktdownload."""
  url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
  res = requests.get(url, headers=HEADERS, timeout=15)
  res.raise_for_status()
  df = pd.read_csv(io.StringIO(res.text))
  df.columns = [c.strip() for c in df.columns]
  date_col, val_col = df.columns[0], df.columns[1]
  df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
  df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
  return df.dropna(subset=[date_col, val_col]).set_index(date_col)[val_col]


pcindex, pcequity, err_details = None, None, None

# Abrufversuch 1: Über API-Key
if active_api_key:
  try:
    with st.spinner("Lade Daten über FRED API..."):
      pcindex = fetch_via_api("PCINDEX", active_api_key)
      pcequity = fetch_via_api("PCEQUITY", active_api_key)
  except Exception as e:
    err_details = f"API-Fehler: {e}"

# Abrufversuch 2: Ohne Key über Direkt-CSV (falls Versuch 1 fehlschlug oder kein Key da ist)
if pcindex is None or pcequity is None:
  try:
    with st.spinner("Versuche Direkt-Download von FRED..."):
      pcindex = fetch_via_csv("PCINDEX")
      pcequity = fetch_via_csv("PCEQUITY")
      err_details = None
  except Exception as e:
    if not err_details:
      err_details = (
          "Direkt-Download von Streamlit Cloud blockiert (Timeout). API-Key"
          " erforderlich."
      )

# Darstellung
if pcindex is not None and pcequity is not None:
  df = pd.DataFrame({"PCINDEX": pcindex, "PCEQUITY": pcequity}).dropna()

  if not df.empty:
    df["Equity_Call_Put"] = 1 / df["PCEQUITY"]
    df["Indicator"] = df["PCINDEX"] - df["Equity_Call_Put"]

    df_display = df.tail(days_to_show)

    st.subheader("Smart Money vs. Dumb Money Indikator")
    st.line_chart(df_display[["Indicator", "PCINDEX", "Equity_Call_Put"]])

    st.subheader("Aktuelle Werte")
    c1, c2, c3 = st.columns(3)
    c1.metric("Indikator-Wert", f"{df_display['Indicator'].iloc[-1]:.2f}")
    c2.metric("Smart Money (PCINDEX)", f"{df_display['PCINDEX'].iloc[-1]:.2f}")
    c3.metric(
        "Dumb Money (1/PCEQUITY)", f"{df_display['Equity_Call_Put'].iloc[-1]:.2f}"
    )
  else:
    st.warning("Keine Daten im gewählten Zeitraum verfügbar.")
else:
  st.error("⚠️ Daten konnten nicht geladen werden.")
  if err_details:
    st.info(f"**Hinweis:** {err_details}")
  st.warning(
    "Bitte trage deinen FRED API-Key in den **Secrets** der Streamlit Cloud ein"
    " oder gib ihn in der Seitenleiste ein und klicke auf **'🔄 Daten"
    " laden'**."
  )
