import os
import pickle
import time
from datetime import datetime, timedelta

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
* **Dumb Money:** CBOE Equity Put/Call Ratio (`EQUITY_PC`)
* **Spread / Indikator:** $\\text{Index P/C} - \\text{Equity P/C}$

ℹ️ **Datenquelle:** Die historischen CBOE Put/Call-Ratios werden über die
[Equibles-API](https://equibles.com/docs/api/endpoints/sentiment) bezogen.
Die Daten werden 24 Stunden lokal gecacht, um das Rate-Limit von 100 Requests/Tag zu schonen.
""")

# --- CACHE-KONSTANTEN ---
CACHE_FILE = "cboe_data_cache.pkl"
CACHE_TTL_HOURS = 24
# Immer 10 Jahre anfordern – der Slider schneidet dann lokal zu
MAX_FETCH_DAYS = 3650

# --- SIDEBAR EINSTELLUNGEN ---
st.sidebar.header("⚙️ Einstellungen")

days = st.sidebar.slider(
    "Zeitraum (Anzahl Tage):", min_value=30, max_value=3650, value=252, step=10
)

sma_period = st.sidebar.slider(
    "SMA-Periode (Tage):", min_value=5, max_value=200, value=20
)

st.sidebar.divider()
st.sidebar.subheader("📊 Chart-Fenster")

show_spread = st.sidebar.checkbox("Spread-Chart anzeigen", value=True)
show_components = st.sidebar.checkbox("Einzelkomponenten anzeigen", value=True)
show_index = st.sidebar.checkbox("Aktienindex anzeigen", value=True)

st.sidebar.divider()

INDEX_OPTIONS = {
    "Kein Index": None,
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Russell 2000": "^RUT",
    "DAX 40": "^GDAXI",
    "Euro Stoxx 50": "^STOXX50E",
}
selected_index_name = st.sidebar.selectbox(
    "Aktienindex:", options=list(INDEX_OPTIONS.keys()), index=1
)
selected_index_ticker = INDEX_OPTIONS[selected_index_name]

if st.sidebar.button("🔄 Cache leeren & neu laden"):
    # Datei-Cache UND In-Memory-Cache leeren
    if os.path.exists(CACHE_FILE):
        try:
            os.remove(CACHE_FILE)
        except Exception:
            pass
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

api_key = st.secrets.get("EQUIBLES_API_KEY", "")
if not api_key:
    st.sidebar.subheader("🔑 Equibles API-Key")
    api_key = st.sidebar.text_input("API-Key (beginnt mit 'eq_')", type="password")
else:
    st.sidebar.success("✅ API-Key aus Secrets geladen")


# --- EQUIBLES API ---
EQUIBLES_BASE = "https://api.equibles.com/v1/market/put-call-ratios"


def _fetch_equibles_series(
    series_type: str, api_key: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """Holt eine Put/Call-Ratio-Zeitreihe von der Equibles-API.

    Paginiert robust: läuft so lange, bis eine Seite weniger als page_limit
    Zeilen zurückliefert ODER hasMore explizit False ist.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    all_rows = []
    offset = 0
    page_limit = 500
    max_pages = 30  # Sicherheitsnetz gegen Endlosschleifen

    for _ in range(max_pages):
        params = {
            "type": series_type,
            "limit": page_limit,
            "offset": offset,
            "startDate": start_date,
            "endDate": end_date,
        }
        resp = requests.get(EQUIBLES_BASE, headers=headers, params=params, timeout=30)
        if resp.status_code == 401:
            raise RuntimeError("Equibles-API-Key ungültig oder abgelaufen.")
        if resp.status_code == 429:
            raise RuntimeError("RATE_LIMIT")  # wird oben abgefangen
        resp.raise_for_status()

        payload = resp.json()
        rows = payload.get("data", [])
        if not rows:
            break
        all_rows.extend(rows)

        if len(rows) < page_limit:
            break
        if not payload.get("meta", {}).get("hasMore", True):
            break

        offset += page_limit
        time.sleep(0.25)

    if not all_rows:
        raise RuntimeError(f"Equibles-API lieferte keine Daten für '{series_type}'.")

    df = pd.DataFrame(all_rows)
    df = df.rename(columns={"date": "DATE", "putCallRatio": "RATIO"})
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["RATIO"] = pd.to_numeric(df["RATIO"], errors="coerce")
    return df[["DATE", "RATIO"]].dropna().sort_values("DATE").reset_index(drop=True)


def fetch_equibles_data(api_key: str) -> pd.DataFrame:
    """Lädt immer die volle 10-Jahres-Historie von Index- und Equity-P/C."""
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=MAX_FETCH_DAYS + 300)  # Puffer für SMA

    start_date = start_dt.strftime("%Y-%m-%d")
    end_date = end_dt.strftime("%Y-%m-%d")

    df_index = _fetch_equibles_series("Index", api_key, start_date, end_date)
    df_equity = _fetch_equibles_series("Equity", api_key, start_date, end_date)

    df_index = df_index.rename(columns={"RATIO": "INDEX_PC"})
    df_equity = df_equity.rename(columns={"RATIO": "EQUITY_PC"})

    return pd.merge(df_index, df_equity, on="DATE", how="inner")


# --- DATEI-CACHE ---
def _load_cache_from_disk() -> pd.DataFrame | None:
    """Lädt die gecachten Rohdaten (ohne SMA) von der Festplatte."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "rb") as f:
            payload = pickle.load(f)
        df = payload["df"]
        timestamp = payload["timestamp"]
        age_hours = (datetime.now() - timestamp).total_seconds() / 3600
        df.attrs["cache_age_hours"] = age_hours
        return df
    except Exception:
        return None


def _save_cache_to_disk(df: pd.DataFrame) -> None:
    """Speichert die Rohdaten (ohne SMA) mit Zeitstempel."""
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump({"df": df, "timestamp": datetime.now()}, f)
    except Exception:
        pass  # Cache-Fehler sind nicht kritisch


# --- AKTIENINDEX VIA YFINANCE ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_index_data(ticker: str, days: int) -> pd.DataFrame:
    """Holt historische Schlusskurse eines Index über yfinance."""
    if not YFINANCE_AVAILABLE:
        raise RuntimeError("yfinance ist nicht installiert.")

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days + 200)

    hist = yf.Ticker(ticker).history(
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        interval="1d",
        auto_adjust=False,
    )
    if hist is None or hist.empty:
        raise RuntimeError(f"yfinance lieferte keine Daten für '{ticker}'.")

    out = hist[["Close"]].reset_index()
    out.rename(columns={out.columns[0]: "DATE", "Close": "CLOSE"}, inplace=True)
    out["DATE"] = pd.to_datetime(out["DATE"]).dt.tz_localize(None)
    return out.dropna().sort_values("DATE").reset_index(drop=True)


# --- HILFSFUNKTIONEN ---
def _add_derived_columns(df: pd.DataFrame, sma_period: int) -> pd.DataFrame:
    """Berechnet Spread und SMAs. Spread = INDEX_PC - EQUITY_PC."""
    df = df.copy()
    df["DATE"] = pd.to_datetime(df["DATE"])
    df["INDEX_PC"] = pd.to_numeric(df["INDEX_PC"], errors="coerce")
    df["EQUITY_PC"] = pd.to_numeric(df["EQUITY_PC"], errors="coerce")
    df = df.dropna().sort_values("DATE").reset_index(drop=True)

    df["SPREAD"] = df["INDEX_PC"] - df["EQUITY_PC"]
    df["SPREAD_SMA"] = df["SPREAD"].rolling(window=sma_period).mean()
    df["INDEX_PC_SMA"] = df["INDEX_PC"].rolling(window=sma_period).mean()
    df["EQUITY_PC_SMA"] = df["EQUITY_PC"].rolling(window=sma_period).mean()
    return df


def _fetch_or_load_raw_data(api_key: str) -> tuple[pd.DataFrame, str]:
    """Liefert (Rohdaten, Status) – Status ist 'cache' oder 'api' oder 'stale_cache'."""
    cached = _load_cache_from_disk()
    if cached is not None:
        age = cached.attrs.get("cache_age_hours", 999)
        if age <= CACHE_TTL_HOURS:
            return cached, "cache"

    # Cache fehlt oder ist abgelaufen → API fragen
    try:
        fresh = fetch_equibles_data(api_key)
        _save_cache_to_disk(fresh)
        return fresh, "api"
    except RuntimeError as e:
        if str(e) == "RATE_LIMIT" and cached is not None:
            # Rate-Limit erreicht, aber abgelaufener Cache vorhanden → den nutzen
            return cached, "stale_cache"
        raise


@st.cache_data(ttl=CACHE_TTL_HOURS * 3600, show_spinner=False)
def load_data(api_key: str, sma_period: int) -> tuple[pd.DataFrame, str]:
    """In-Memory-Cache (pro Session). Lädt Rohdaten und berechnet SMAs."""
    raw, status = _fetch_or_load_raw_data(api_key)
    return _add_derived_columns(raw, sma_period), status


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
data_status = None

if not api_key:
    st.info(
        "⬅️ Bitte in der Seitenleiste einen Equibles-API-Key eingeben. "
        "Kostenlos erhältlich unter https://equibles.com"
    )
    st.stop()

try:
    with st.spinner("Lade Put/Call-Ratio-Daten..."):
        df, data_status = load_data(api_key, sma_period)
except Exception as e:
    load_error = e

if selected_index_ticker and show_index:
    try:
        with st.spinner(f"Lade {selected_index_name}-Daten..."):
            df_index = fetch_index_data(selected_index_ticker, days)
    except Exception as e:
        st.warning(f"⚠️ Indexdaten für {selected_index_name} konnten nicht geladen werden: {e}")

if load_error is not None:
    st.error("❌ Der automatische Live-Abruf ist fehlgeschlagen.")
    with st.expander("🔍 Technische Details zum Fehler", expanded=True):
        st.code(str(load_error))
    st.info(
        "**Hinweis:** Wenn das Rate-Limit erreicht ist, wird beim nächsten Aufruf "
        "automatisch der letzte Cache-Stand verwendet, sofern vorhanden. "
        "Der Cache wird alle 24 Stunden aktualisiert."
    )
    st.stop()

# --- STATUS-HINWEIS ---
if data_status == "cache":
    st.success("✅ Daten aus lokalem Cache (max. 24 h alt) – kein API-Request nötig.")
elif data_status == "api":
    st.info("🔄 Daten frisch von der Equibles-API geladen und für 24 h gecacht.")
elif data_status == "stale_cache":
    st.warning(
        "⚠️ Rate-Limit erreicht – zeige Daten aus dem letzten Cache-Stand. "
        "Der Cache wird automatisch erneuert, sobald das Limit zurückgesetzt ist."
    )

# --- DATEN FILTERN ---
df_filtered = df.tail(days).copy()

if df_index is not None and not df_index.empty:
    df_index_filtered = df_index.tail(days).copy()
    df_index_filtered["INDEX_SMA"] = (
        df_index_filtered["CLOSE"].rolling(window=sma_period).mean()
    )
else:
    df_index_filtered = None

latest = df_filtered.iloc[-1]

# --- KENNZAHLEN ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Datum", latest["DATE"].strftime("%Y-%m-%d"))
col2.metric("Index P/C (Smart)", f"{latest['INDEX_PC']:.2f}")
col3.metric("Equity P/C (Dumb)", f"{latest['EQUITY_PC']:.2f}")
col4.metric("Spread (Smart − Dumb)", f"{latest['SPREAD']:.2f}")

# --- CHARTS ERSTELLEN ---
active_panels = []
if show_spread:
    active_panels.append("spread")
if show_components:
    active_panels.append("components")
if show_index and df_index_filtered is not None and not df_index_filtered.empty:
    active_panels.append("index")

if not active_panels:
    st.info("ℹ️ Bitte mindestens ein Chart-Fenster in der Seitenleiste aktivieren.")
    st.stop()

n_rows = len(active_panels)
panel_titles = {
    "spread": "Smart vs. Dumb Money Spread Index",
    "components": "Einzelkomponenten (Index P/C vs. Equity P/C)",
    "index": f"{selected_index_name} (Tageskurs + SMA {sma_period})",
}

fig = make_subplots(
    rows=n_rows,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.07,
    subplot_titles=tuple(panel_titles[p] for p in active_panels),
)

row = 1
for panel in active_panels:
    if panel == "spread":
        fig.add_trace(
            go.Scatter(
                x=df_filtered["DATE"], y=df_filtered["SPREAD"],
                name="Spread (Täglich)",
                line=dict(color="rgba(160,160,160,0.6)", width=1),
            ), row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df_filtered["DATE"], y=df_filtered["SPREAD_SMA"],
                name=f"Spread SMA {sma_period}",
                line=dict(color="#1f77b4", width=2.2),
            ), row=row, col=1,
        )
        fig.update_yaxes(title_text="Spread Index", row=row, col=1)

    elif panel == "components":
        fig.add_trace(
            go.Scatter(
                x=df_filtered["DATE"], y=df_filtered["INDEX_PC"],
                name="Index P/C",
                line=dict(color="#00BFC4", width=1.5),
            ), row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df_filtered["DATE"], y=df_filtered["INDEX_PC_SMA"],
                name=f"Index P/C SMA {sma_period}",
                line=dict(color="#00BFC4", width=2.2, dash="dot"),
            ), row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df_filtered["DATE"], y=df_filtered["EQUITY_PC"],
                name="Equity P/C",
                line=dict(color="#F8766D", width=1.5),
            ), row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df_filtered["DATE"], y=df_filtered["EQUITY_PC_SMA"],
                name=f"Equity P/C SMA {sma_period}",
                line=dict(color="#F8766D", width=2.2, dash="dot"),
            ), row=row, col=1,
        )
        fig.update_yaxes(title_text="Ratio", row=row, col=1)

    elif panel == "index":
        fig.add_trace(
            go.Scatter(
                x=df_index_filtered["DATE"], y=df_index_filtered["CLOSE"],
                name=f"{selected_index_name} (Tageskurs)",
                line=dict(color="#4FC3F7", width=1.6),
                hovertemplate="%{y:,.0f}<extra></extra>",
            ), row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df_index_filtered["DATE"], y=df_index_filtered["INDEX_SMA"],
                name=f"{selected_index_name} SMA {sma_period}",
                line=dict(color="#FFA726", width=2.4),
                hovertemplate="%{y:,.0f}<extra></extra>",
            ), row=row, col=1,
        )
        fig.update_yaxes(title_text="Index-Stand", row=row, col=1)

    row += 1

fig.update_layout(
    height=320 * n_rows,
    template="plotly_white",
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=40, r=20, t=60, b=40),
)

st.plotly_chart(fig, use_container_width=True)

# --- ROHDATEN ---
with st.expander("📊 Live-Rohdaten anzeigen"):
    st.dataframe(
        df_filtered[[
            "DATE", "INDEX_PC", "EQUITY_PC", "SPREAD", "SPREAD_SMA",
        ]].sort_values("DATE", ascending=False),
        use_container_width=True,
    )

# --- PLAUSIBILITÄTS-CHECK ---
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
