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

ℹ️ **Datenquelle:** Die historischen CBOE Put/Call-Ratios werden über die
[Equibles-API](https://equibles.com/docs/api/endpoints/sentiment) bezogen.
Die kostenlose Stufe erlaubt 100 Requests/Tag.
""")

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("⚙️ Einstellungen")

# Zeitraum
days = st.sidebar.slider(
    "Zeitraum (Anzahl Tage):", min_value=30, max_value=1000, value=252
)

# SMA-Periode (eine Einstellung für beide Berechnungen)
sma_period = st.sidebar.slider(
    "SMA-Periode (Tage):", min_value=5, max_value=100, value=10
)

# Aktienindex-Auswahl
INDEX_OPTIONS = {
    "Kein Index": None,
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Russell 2000": "^RUT",
    "DAX 40": "^GDAXI",
    "Euro Stoxx 50": "^STOXX50E",
}
selected_index_name = st.sidebar.selectbox(
    "Aktienindex anzeigen:",
    options=list(INDEX_OPTIONS.keys()),
    index=1,  # Standard: S&P 500
)
selected_index_ticker = INDEX_OPTIONS[selected_index_name]

if st.sidebar.button("🔄 Live-Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

# API-Key bevorzugt aus Secrets lesen, sonst manuell abfragen
api_key = st.secrets.get("EQUIBLES_API_KEY", "")

if not api_key:
    st.sidebar.subheader("🔑 Equibles API-Key")
    api_key = st.sidebar.text_input(
        "API-Key (beginnt mit 'eq_')",
        type="password",
        help=(
            "Kostenlos erhältlich unter https://equibles.com – "
            "Registrierung dauert unter einer Minute."
        ),
    )
else:
    st.sidebar.success("✅ API-Key aus Secrets geladen")

st.sidebar.divider()
st.sidebar.subheader("🆘 Fallback-Datenquelle")
use_csv_fallback = st.sidebar.toggle(
    "Eigene CSV statt Live-Abruf verwenden",
    help=(
        "Falls der Live-Abruf blockiert wird oder kein API-Key vorliegt, "
        "kannst du hier eine eigene CSV mit den Spalten DATE, INDEX_PC, EQUITY_PC hochladen."
    ),
)
uploaded_csv = None
if use_csv_fallback:
    uploaded_csv = st.sidebar.file_uploader(
        "CSV hochladen (Spalten: DATE, INDEX_PC, EQUITY_PC)", type=["csv"]
    )


# --- EQUIBLES API ---
EQUIBLES_BASE = "https://api.equibles.com/v1/market/put-call-ratios"


def _fetch_equibles_series(
    series_type: str, api_key: str, start_date: str | None = None
) -> pd.DataFrame:
    """Holt eine Put/Call-Ratio-Zeitreihe von der Equibles-API.

    Lädt ALLE Seiten bis meta.hasMore False ist.
    series_type: 'Index' oder 'Equity' (auch 'Total', 'Vix', 'Etp').
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    all_rows = []
    offset = 0
    page_limit = 500  # Maximum laut API-Doku[reference:4]

    while True:
        params = {
            "type": series_type,
            "limit": page_limit,
            "offset": offset,
        }
        if start_date:
            params["startDate"] = start_date

        resp = requests.get(EQUIBLES_BASE, headers=headers, params=params, timeout=30)
        if resp.status_code == 401:
            raise RuntimeError("Equibles-API-Key ungültig oder abgelaufen.")
        if resp.status_code == 429:
            raise RuntimeError("Equibles-API-Rate-Limit erreicht (100 Requests/Tag).")
        resp.raise_for_status()

        payload = resp.json()
        rows = payload.get("data", [])
        if not rows:
            break
        all_rows.extend(rows)

        meta = payload.get("meta", {})
        if not meta.get("hasMore", False):
            break
        offset += page_limit
        time.sleep(0.25)  # sanfte Drosselung gegen Rate-Limit

    if not all_rows:
        raise RuntimeError(f"Equibles-API lieferte keine Daten für '{series_type}'.")

    df = pd.DataFrame(all_rows)
    df = df.rename(columns={"date": "DATE", "putCallRatio": "RATIO"})
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["RATIO"] = pd.to_numeric(df["RATIO"], errors="coerce")
    return df[["DATE", "RATIO"]].dropna().sort_values("DATE").reset_index(drop=True)


def fetch_equibles_data(api_key: str) -> pd.DataFrame:
    """Lädt Index- und Equity-Put/Call-Ratio und führt sie zusammen."""
    df_index = _fetch_equibles_series("Index", api_key)
    df_equity = _fetch_equibles_series("Equity", api_key)

    df_index = df_index.rename(columns={"RATIO": "INDEX_PC"})
    df_equity = df_equity.rename(columns={"RATIO": "EQUITY_PC"})

    df = pd.merge(df_index, df_equity, on="DATE", how="inner")
    return df


# --- AKTIENINDEX VIA YFINANCE ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_index_data(ticker: str, period: str = "5y") -> pd.DataFrame:
    """Holt historische Schlusskurse eines Index über yfinance."""
    if not YFINANCE_AVAILABLE:
        raise RuntimeError("yfinance ist nicht installiert – bitte requirements.txt prüfen.")

    hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"yfinance lieferte keine Daten für '{ticker}'.")

    out = hist[["Close"]].reset_index()
    out.rename(columns={out.columns[0]: "DATE", "Close": "CLOSE"}, inplace=True)
    out["DATE"] = pd.to_datetime(out["DATE"]).dt.tz_localize(None)
    return out.dropna().sort_values("DATE").reset_index(drop=True)


# --- HILFSFUNKTIONEN ---
def _add_derived_columns(df: pd.DataFrame, sma_period: int) -> pd.DataFrame:
    """Berechnet abgeleitete Spalten mit dynamischer SMA-Periode."""
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["INDEX_PC"] = pd.to_numeric(df["INDEX_PC"], errors="coerce")
    df["EQUITY_PC"] = pd.to_numeric(df["EQUITY_PC"], errors="coerce")
    df = df.dropna().sort_values("DATE")
    df["EQUITY_CP"] = 1.0 / df["EQUITY_PC"]
    df["SPREAD"] = df["INDEX_PC"] - df["EQUITY_CP"]
    df["SPREAD_SMA"] = df["SPREAD"].rolling(window=sma_period).mean()
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_live_data(api_key: str, sma_period: int) -> pd.DataFrame:
    df = fetch_equibles_data(api_key)
    return _add_derived_columns(df, sma_period)


def load_csv_data(uploaded_file, sma_period: int) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)
    required = {"DATE", "INDEX_PC", "EQUITY_PC"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Der CSV fehlen die Spalten: {', '.join(sorted(missing))}")
    return _add_derived_columns(df, sma_period)


# --- OPTIONALER LIVE-CHECK GEGEN DIE OFFIZIELLE CBOE-QUELLE ---
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
        raise RuntimeError("Ratio-Tabelle auf der Cboe-Seite nicht gefunden.")
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
df_index = None
load_error = None

if use_csv_fallback:
    if uploaded_csv is not None:
        try:
            df = load_csv_data(uploaded_csv, sma_period)
        except Exception as e:
            load_error = e
    else:
        st.info("⬅️ Bitte in der Seitenleiste eine CSV-Datei hochladen.")
        st.stop()
else:
    if not api_key:
        st.info(
            "⬅️ Bitte in der Seitenleiste einen Equibles-API-Key eingeben. "
            "Kostenlos erhältlich unter https://equibles.com"
        )
        st.stop()

    try:
        with st.spinner("Lade Put/Call-Ratio-Daten von Equibles..."):
            df = load_live_data(api_key, sma_period)
    except Exception as e:
        load_error = e

# Index separat laden (Fehler hier blockiert das Dashboard nicht)
if selected_index_ticker:
    try:
        with st.spinner(f"Lade {selected_index_name}-Daten..."):
            df_index = fetch_index_data(selected_index_ticker)
    except Exception as e:
        st.warning(f"⚠️ Indexdaten für {selected_index_name} konnten nicht geladen werden: {e}")

if load_error is not None:
    st.error("❌ Der automatische Live-Abruf ist fehlgeschlagen.")
    with st.expander("🔍 Technische Details zum Fehler", expanded=True):
        st.code(str(load_error))
    st.warning(
        "**Häufigste Ursachen:**\n"
        "- Der Equibles-API-Key fehlt oder ist ungültig (beginnt mit `eq_`).\n"
        "- Das tägliche Rate-Limit von 100 Requests ist erreicht.\n\n"
        "**Optionen:**\n"
        "- API-Key unter https://equibles.com prüfen.\n"
        "- Auf **'🔄 Live-Daten neu laden'** klicken.\n"
        "- Links auf **'Eigene CSV statt Live-Abruf verwenden'** umschalten."
    )
    st.stop()

# --- DATEN FILTERN ---
df_filtered = df.tail(days).copy()

# Index auf denselben Zeitraum filtern
if df_index is not None:
    min_date = df_filtered["DATE"].min()
    max_date = df_filtered["DATE"].max()
    df_index_filtered = df_index[
        (df_index["DATE"] >= min_date) & (df_index["DATE"] <= max_date)
    ].copy()
    # Index-SMA mit derselben Periode berechnen
    df_index_filtered["INDEX_SMA"] = (
        df_index_filtered["CLOSE"].rolling(window=sma_period).mean()
    )
else:
    df_index_filtered = None

latest = df.iloc[-1]

# --- KENNZAHLEN (METRICS) ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Datum", latest["DATE"].strftime("%Y-%m-%d"))
col2.metric("Index P/C (Smart)", f"{latest['INDEX_PC']:.2f}")
col3.metric("Equity C/P (Dumb)", f"{latest['EQUITY_CP']:.2f}")
col4.metric("Spread (Smart - Dumb)", f"{latest['SPREAD']:.2f}")

# --- CHARTS ERSTELLEN ---
has_index = df_index_filtered is not None and not df_index_filtered.empty
n_rows = 3 if has_index else 2

fig = make_subplots(
    rows=n_rows,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.06,
    subplot_titles=(
        "Smart vs. Dumb Money Spread Index",
        "Einzelkomponenten (Index P/C vs. Equity C/P)",
        f"{selected_index_name} (Schlusskurs + SMA {sma_period})" if has_index else "",
    )[:n_rows],
)

# --- Subplot 1: Spread ---
fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["SPREAD"],
        name="Spread (Täglich)", line=dict(color="lightgray", width=1),
    ), row=1, col=1,
)
fig.add_trace(
    go.Scatter(
        x=df_filtered["DATE"], y=df_filtered["SPREAD_SMA"],
        name=f"Spread SMA {sma_period}", line=dict(color="#1f77b4", width=2),
    ), row=1, col=1,
)

# --- Subplot 2: Einzelkomponenten ---
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

# --- Subplot 3: Aktienindex (optional) ---
if has_index:
    fig.add_trace(
        go.Scatter(
            x=df_index_filtered["DATE"], y=df_index_filtered["CLOSE"],
            name=f"{selected_index_name} (Close)",
            line=dict(color="black", width=1.5),
        ), row=3, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_index_filtered["DATE"], y=df_index_filtered["INDEX_SMA"],
            name=f"{selected_index_name} SMA {sma_period}",
            line=dict(color="orange", width=2),
        ), row=3, col=1,
    )

fig.update_layout(
    height=350 * n_rows,
    template="plotly_white",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
fig.update_yaxes(title_text="Spread Index", row=1, col=1)
fig.update_yaxes(title_text="Ratio", row=2, col=1)
if has_index:
    fig.update_yaxes(title_text="Index-Stand", row=3, col=1)

st.plotly_chart(fig, use_container_width=True)

# --- ROHDATEN TABELLE ---
with st.expander("📊 Live-Rohdaten anzeigen"):
    st.dataframe(
        df_filtered[[
            "DATE", "INDEX_PC", "EQUITY_PC", "EQUITY_CP", "SPREAD", "SPREAD_SMA",
        ]].sort_values("DATE", ascending=False),
        use_container_width=True,
    )

# --- OPTIONALER PLAUSIBILITÄTS-CHECK ---
st.divider()
with st.expander("🔎 Live-Abgleich mit der offiziellen Cboe-Quelle (heutiger Wert)"):
    st.caption(
        "Cboe veröffentlicht frei nur den aktuellen Tageswert, keine historische Zeitreihe."
    )
    try:
        snap = fetch_cboe_snapshot()
        c1, c2, c3 = st.columns(3)
        c1.metric("Cboe Total P/C", f"{snap['TOTAL']:.2f}" if snap["TOTAL"] is not None else "n/a")
        c2.metric("Cboe Index P/C", f"{snap['INDEX']:.2f}" if snap["INDEX"] is not None else "n/a")
        c3.metric("Cboe Equity P/C", f"{snap['EQUITY']:.2f}" if snap["EQUITY"] is not None else "n/a")
    except Exception as e:
        st.info(f"Live-Check aktuell nicht verfügbar: {e}")
