import time

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

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

ℹ️ *Hinweis:* FRED führt in seiner "CBOE Market Statistics"-Reihe nur Volatilitätsindizes (VIX & Co.),
**keine** Put/Call-Ratios – das ist also keine Alternative. Cboe selbst veröffentlicht die Ratios frei nur
als Tageswert, nicht als historische Zeitreihe. Dieses Dashboard nutzt daher weiterhin die inoffiziellen
Yahoo-Finance-Ticker `^CPCI` / `^CPCE`, jetzt über die robustere `yfinance`-Bibliothek mit
Wiederholungsversuchen und einem CSV-Fallback für den Fall, dass Yahoo den Zugriff verweigert.
""")

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("⚙️ Einstellungen")

days = st.sidebar.slider(
    "Zeitraum (Anzahl Tage):", min_value=30, max_value=1000, value=252
)

if st.sidebar.button("🔄 Live-Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("🆘 Fallback-Datenquelle")
use_csv_fallback = st.sidebar.toggle(
    "Eigene CSV statt Live-Abruf verwenden",
    help=(
        "Falls der Live-Abruf von Yahoo Finance blockiert wird (z.B. auf Streamlit "
        "Community Cloud), kannst du hier eine eigene CSV mit den Spalten "
        "DATE, INDEX_PC, EQUITY_PC hochladen."
    ),
)
uploaded_csv = None
if use_csv_fallback:
    uploaded_csv = st.sidebar.file_uploader(
        "CSV hochladen (Spalten: DATE, INDEX_PC, EQUITY_PC)", type=["csv"]
    )


# --- METHODE 1: DATEN ÜBER yfinance (empfohlen) ---
def _fetch_via_yfinance(ticker: str, period: str = "5y") -> pd.DataFrame:
    hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError("yfinance lieferte einen leeren Datensatz zurück.")
    out = hist[["Close"]].reset_index()
    out.rename(columns={out.columns[0]: "DATE", "Close": ticker}, inplace=True)
    out["DATE"] = pd.to_datetime(out["DATE"]).dt.tz_localize(None)
    return out.dropna()


# --- METHODE 2: DIREKTER AUFRUF DER INOFFIZIELLEN CHART-API (Fallback) ---
def _fetch_via_raw_api(ticker: str, range_str: str = "5y") -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_str}&interval=1d"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    response = requests.get(url, headers=headers, timeout=15)
    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code} beim Abrufen von {ticker}. "
            f"Antwort (Auszug): {response.text[:200]!r}"
        )
    data = response.json()
    chart = data.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo-API-Fehler für {ticker}: {chart['error']}")
    results = chart.get("result")
    if not results:
        raise RuntimeError(f"Keine Ergebnisse für {ticker} (Symbol evtl. nicht mehr verfügbar).")
    result = results[0]
    timestamps = result.get("timestamp")
    quote = result.get("indicators", {}).get("quote", [{}])
    closes = quote[0].get("close") if quote else None
    if not timestamps or not closes:
        raise RuntimeError(f"Unvollständige Daten für {ticker} in der API-Antwort.")
    df = pd.DataFrame({
        "DATE": pd.to_datetime(timestamps, unit="s").normalize(),
        ticker: closes,
    })
    return df.dropna()


def fetch_yahoo_data(ticker: str, max_retries: int = 3) -> pd.DataFrame:
    """Holt historische Daten zu einem Ticker robust über zwei Methoden mit Retries.

    Wichtig: Fehler werden NICHT verschluckt, sondern gesammelt und am Ende
    komplett zurückgegeben, damit man in der App sieht, woran es wirklich lag
    (Netzwerk, Rate-Limit, ungültiges Symbol, ...) statt nur "irgendein Fehler".
    """
    errors = []

    if YFINANCE_AVAILABLE:
        for attempt in range(1, max_retries + 1):
            try:
                return _fetch_via_yfinance(ticker)
            except Exception as e:
                errors.append(f"[yfinance, Versuch {attempt}/{max_retries}] {e}")
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)
    else:
        errors.append("[yfinance] Bibliothek nicht installiert (siehe requirements.txt).")

    for attempt in range(1, max_retries + 1):
        try:
            return _fetch_via_raw_api(ticker)
        except Exception as e:
            errors.append(f"[Raw-API, Versuch {attempt}/{max_retries}] {e}")
            if attempt < max_retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(
        f"Alle Abrufversuche für '{ticker}' sind fehlgeschlagen:\n- " + "\n- ".join(errors)
    )


def _add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["INDEX_PC"] = pd.to_numeric(df["INDEX_PC"], errors="coerce")
    df["EQUITY_PC"] = pd.to_numeric(df["EQUITY_PC"], errors="coerce")
    df = df.dropna().sort_values("DATE")
    df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]
    df["SPREAD"] = df["INDEX_PC"] - df["EQUITY_CP"]
    df["SPREAD_SMA10"] = df["SPREAD"].rolling(window=10).mean()
    df["SPREAD_SMA21"] = df["SPREAD"].rolling(window=21).mean()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_live_data() -> pd.DataFrame:
    df_cpci = fetch_yahoo_data("^CPCI")
    df_cpce = fetch_yahoo_data("^CPCE")
    df = pd.merge(df_cpci, df_cpce, on="DATE")
    df.rename(columns={"^CPCI": "INDEX_PC", "^CPCE": "EQUITY_PC"}, inplace=True)
    return _add_derived_columns(df)


def load_csv_data(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)
    required = {"DATE", "INDEX_PC", "EQUITY_PC"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Der CSV fehlen die Spalten: {', '.join(sorted(missing))}")
    return _add_derived_columns(df)


# --- OPTIONALER LIVE-CHECK GEGEN DIE OFFIZIELLE CBOE-QUELLE (nur Tageswert) ---
def fetch_cboe_snapshot() -> dict:
    url = "https://www.cboe.com/us/options/market_statistics/daily/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    tables = pd.read_html(resp.text)
    ratio_table = None
    for t in tables:
        cols = [str(c).strip().lower() for c in t.columns]
        if "ratios" in cols and "value" in cols:
            ratio_table = t
            break
    if ratio_table is None:
        raise RuntimeError("Ratio-Tabelle auf der Cboe-Seite nicht gefunden (Layout evtl. geändert).")
    ratio_table = ratio_table.set_index(ratio_table.columns[0])

    def get_val(label):
        matches = [i for i in ratio_table.index if label.lower() in str(i).lower()]
        return float(ratio_table.loc[matches[0]].iloc[0]) if matches else None

    return {
        "TOTAL": get_val("TOTAL PUT/CALL RATIO"),
        "INDEX": get_val("INDEX PUT/CALL RATIO"),
        "EQUITY": get_val("EQUITY PUT/CALL RATIO"),
    }


# --- HAUPTLOGIK & ANZEIGE ---
df = None
load_error = None

if use_csv_fallback:
    if uploaded_csv is not None:
        try:
            df = load_csv_data(uploaded_csv)
        except Exception as e:
            load_error = e
    else:
        st.info("⬅️ Bitte in der Seitenleiste eine CSV-Datei hochladen.")
        st.stop()
else:
    try:
        with st.spinner("Lade neuste Marktdaten von Yahoo Finance..."):
            df = load_live_data()
    except Exception as e:
        load_error = e

if load_error is not None:
    st.error("❌ Der automatische Live-Abruf ist fehlgeschlagen.")
    with st.expander("🔍 Technische Details zum Fehler", expanded=True):
        st.code(str(load_error))
    st.warning(
        "**Häufigste Ursache:** Yahoo Finance blockiert Anfragen von geteilten Cloud-IPs "
        "(z. B. Streamlit Community Cloud) – unabhängig vom User-Agent-Header. "
        "FRED ist hier übrigens **keine** Alternative (führt keine Put/Call-Ratios), "
        "und Cboe selbst gibt frei nur den heutigen Tageswert heraus.\n\n"
        "**Optionen:**\n"
        "- Auf **'🔄 Live-Daten neu laden'** klicken und es in ein paar Minuten erneut versuchen.\n"
        "- Links auf **'Eigene CSV statt Live-Abruf verwenden'** umschalten.\n"
        "- Lokal (nicht auf Streamlit Cloud) testen, ob es dort ebenfalls fehlschlägt."
    )
    st.stop()

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

fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["SPREAD"],
        name="Spread (Täglich)", line=dict(color="lightgray", width=1),
    ), row=1, col=1,
)
fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["SPREAD_SMA10"],
        name="Spread (10-Tage SMA)", line=dict(color="#1f77b4", width=2),
    ), row=1, col=1,
)
fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["SPREAD_SMA21"],
        name="Spread (21-Tage SMA)", line=dict(color="#ff7f0e", width=2),
    ), row=1, col=1,
)
fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["INDEX_PC"],
        name="Index P/C (Smart Money)", line=dict(color="darkcyan", width=1.5),
    ), row=2, col=1,
)
fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["EQUITY_CP"],
        name="Equity C/P (Dumb Money)", line=dict(color="crimson", width=1.5),
    ), row=2, col=1,
)

fig.update_layout(height=700, template="plotly_white", hovermode="x unified")
fig.update_yaxes(title_text="Spread Index", row=1, col=1)
fig.update_yaxes(title_text="Ratio", row=2, col=1)

st.plotly_chart(fig, use_container_width=True)

# --- ROHDATEN TABELLE ---
with st.expander("📊 Live-Rohdaten anzeigen"):
    st.dataframe(
        df_filtered[[
            "DATE", "INDEX_PC", "EQUITY_PC", "EQUITY_CP", "SPREAD", "SPREAD_SMA10",
        ]].sort_values("DATE", ascending=False),
        use_container_width=True,
    )

# --- OPTIONALER PLAUSIBILITÄTS-CHECK GEGEN DIE OFFIZIELLE CBOE-QUELLE ---
st.divider()
with st.expander("🔎 Live-Abgleich mit der offiziellen Cboe-Quelle (heutiger Wert)"):
    st.caption(
        "Cboe veröffentlicht frei nur den aktuellen Tageswert, keine historische Zeitreihe – "
        "dient hier nur als Plausibilitätscheck für die Yahoo-Daten oben."
    )
    try:
        snap = fetch_cboe_snapshot()
        c1, c2, c3 = st.columns(3)
        c1.metric("Cboe Total P/C", f"{snap['TOTAL']:.2f}" if snap["TOTAL"] is not None else "n/a")
        c2.metric("Cboe Index P/C", f"{snap['INDEX']:.2f}" if snap["INDEX"] is not None else "n/a")
        c3.metric("Cboe Equity P/C", f"{snap['EQUITY']:.2f}" if snap["EQUITY"] is not None else "n/a")
    except Exception as e:
        st.info(f"Live-Check aktuell nicht verfügbar: {e}")
