import io
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Smart Money vs. Dumb Money Indicator", layout="wide"
)

st.title("Smart Money vs. Dumb Money Indicator")

st.markdown("""
Dieser Indikator vergleicht das Absicherungsverhalten von Großanlegern (**Smart Money** im Index-Markt) mit der Spekulation von Kleinanlegern (**Dumb Money** im Einzelaktien-Markt) über Daten der Federal Reserve Bank of St. Louis (FRED).

* **Smart Money:** CBOE Index Put/Call Ratio (`PCINDEX`)
* **Dumb Money:** CBOE Equity Call/Put Ratio ($1 / \\text{PCEQUITY}$)
* **Formel:** $\\text{Smart Money Indicator} = \\text{Index Put/Call Ratio} - \\text{Equity Call/Put Ratio}$
""")

# Seitenleiste für Optionen & API-Key
st.sidebar.header("Einstellungen")
api_key = st.sidebar.text_input(
    "FRED API-Key (optional, dringend empfohlen):",
    type="password",
    help="Falls der Direkt-Download blockiert wird: Kostenlosen Key auf https://fred.stlouisfed.org/ erstellen und hier eintragen.",
)
days_to_show = st.sidebar.slider("Anzahl Tage anzeigen:", 30, 1000, 365)

# Browser-Header vortäuschen, um Timeout / Blockaden zu vermeiden
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


@st.cache_data(ttl=3600)
def fetch_fred_series(series_id, api_key=None):
    # Methode 1: Offizielle FRED API (beste & stabilste Methode)
    if api_key and api_key.strip():
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key.strip()}&file_type=json"
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
        data = res.json()
        obs = data.get("observations", [])
        df = pd.DataFrame(obs)[["date", "value"]]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        df = df.dropna().set_index("date")
        return df["value"]

    # Methode 2: Direkt-Download mit angepasst-stabilem Header & Timeout
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        res = requests.get(url, headers=HEADERS, timeout=25)
        res.raise_for_status()
        df = pd.read_csv(io.StringIO(res.text))

        df.columns = [c.strip() for c in df.columns]
        date_col, val_col = df.columns[0], df.columns[1]

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
        df = df.dropna(subset=[date_col, val_col]).set_index(date_col)
        return df[val_col]


# Daten abrufen und anzeigen
try:
    with st.spinner("Lade FRED-Daten..."):
        pcindex = fetch_fred_series("PCINDEX", api_key)
        pcequity = fetch_fred_series("PCEQUITY", api_key)

    df = pd.DataFrame({"PCINDEX": pcindex, "PCEQUITY": pcequity}).dropna()

    if df.empty:
        st.warning("Keine Daten gefunden.")
    else:
        # Berechnung: Call/Put ist der Kehrwert der Put/Call Ratio
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

except Exception as e:
    st.error(f"Fehler beim Laden der Daten: {e}")
    st.info("""
    **Tipp:** Falls Streamlit Cloud den Direktzugriff weiterhin drosselt:
    1. Registriere dich kostenlos auf [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html).
    2. Erstelle unter *My Account -> API Keys* einen Key.
    3. Trage diesen Key in der Seitenleiste der App ein.
    """)
