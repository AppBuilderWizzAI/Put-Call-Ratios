import streamlit as st
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests

st.set_page_config(
    page_title="Smart Money vs. Dumb Money Put/Call Ratio",
    layout="wide"
)

st.title("Smart Money vs. Dumb Money Indicator")
st.markdown("""
Dieser Indikator vergleicht das Absicherungsverhalten von Großanlegern (**Smart Money** im S&P 100 / OEX) 
mit der Spekulation von Kleinanlegern (**Dumb Money** im CBOE Equity Markt).

**Formel:** `(OEX Put/Call Ratio) - (Equity Call/Put Ratio)`
""")

@st.cache_data(ttl=14400)
def fetch_cboe_data(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    }
    res = requests.get(url, headers=headers, timeout=15)
    
    # Filtere Metadaten-Zeilen aus CBOE-Dateien
    lines = [line for line in res.text.splitlines() if line and not line.startswith('#') and 'CBOE' not in line]
    
    # In DataFrame umwandeln
    from io import StringIO
    df = pd.read_csv(StringIO('\n'.join(lines)))
    return df

@st.cache_data(ttl=14400)
def load_and_process_ratios():
    try:
        # Offizielle CBOE Endpunkte
        equity_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv"
        oex_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/oexpc.csv"
        
        df_eq = fetch_cboe_data(equity_url)
        df_oex = fetch_cboe_data(oex_url)
        
        # Spaltennamen bereinigen
        df_eq.columns = [c.strip().upper() for c in df_eq.columns]
        df_oex.columns = [c.strip().upper() for c in df_oex.columns]
        
        # Datum parsen
        df_eq['DATE'] = pd.to_datetime(df_eq['DATE'], errors='coerce')
        df_oex['DATE'] = pd.to_datetime(df_oex['DATE'], errors='coerce')
        
        df_eq = df_eq.dropna(subset=['DATE'])
        df_oex = df_oex.dropna(subset=['DATE'])
        
        # Spalte 'P/C' oder 'P/C RATIO' identifizieren
        pc_col_eq = [c for c in df_eq.columns if 'P/C' in c or 'RATIO' in c][0]
        pc_col_oex = [c for c in df_oex.columns if 'P/C' in c or 'RATIO' in c][0]
        
        # Merge der beiden Datensätze
        df = pd.merge(
            df_oex[['DATE', pc_col_oex]], 
            df_eq[['DATE', pc_col_eq]], 
            on='DATE', 
            suffixes=('_OEX', '_EQUITY')
        )
        
        df['OEX_PC'] = pd.to_numeric(df[pc_col_oex + '_OEX'], errors='coerce')
        df['EQUITY_PC'] = pd.to_numeric(df[pc_col_eq + '_EQUITY'], errors='coerce')
        
        df = df.dropna(subset=['OEX_PC', 'EQUITY_PC'])
        df = df.sort_values('DATE').reset_index(drop=True)
        
        # Berechnungen nach deiner Formel:
        # Equity C/P = 1 / Equity P/C
        df['EQUITY_CP'] = 1.0 / df['EQUITY_PC']
        
        # Spread = (OEX P/C) - (Equity C/P)
        df['SPREAD'] = df['OEX_PC'] - df['EQUITY_CP']
        
        # Gleitende Durchschnitte
        df['SPREAD_SMA10'] = df['SPREAD'].rolling(window=10).mean()
        df['SPREAD_SMA21'] = df['SPREAD'].rolling(window=21).mean()
        
        return df

    except Exception as e:
        st.error(f"Fehler beim Laden der CBOE-Daten: {e}")
        return pd.DataFrame()

with st.spinner("Lade CBOE-Daten..."):
    df = load_and_process_ratios()

if not df.empty:
    st.sidebar.header("Einstellungen")
    days = st.sidebar.slider("Zeitraum (Tage):", min_value=30, max_value=1000, value=252)
    
    df_filtered = df.tail(days)
    latest = df.iloc[-1]
    
    # Kennzahlen anzeigen
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Datum", latest['DATE'].strftime('%Y-%m-%d'))
    col2.metric("OEX Put/Call (Smart)", f"{latest['OEX_PC']:.2f}")
    col3.metric("Equity Call/Put (Dumb)", f"{latest['EQUITY_CP']:.2f}")
    col4.metric("Spread (Smart - Dumb)", f"{latest['SPREAD']:.2f}")

    # Charts erstellen
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.08,
        subplot_titles=("Smart vs. Dumb Money Spread", "Einzelkomponenten (OEX P/C vs. Equity C/P)")
    )

    # Upper chart: Spread
    fig.add_trace(
        plt.Scatter(x=df_filtered['DATE'], y=df_filtered['SPREAD'], name="Spread (Täglich)", line=dict(color='lightgray', width=1)),
        row=1, col=1
    )
    fig.add_trace(
        plt.Scatter(x=df_filtered['DATE'], y=df_filtered['SPREAD_SMA10'], name="Spread (10-Tage SMA)", line=dict(color='blue', width=2)),
        row=1, col=1
    )
    fig.add_trace(
        plt.Scatter(x=df_filtered['DATE'], y=df_filtered['SPREAD_SMA21'], name="Spread (21-Tage SMA)", line=dict(color='orange', width=2)),
        row=1, col=1
    )

    # Lower chart: Individual components
    fig.add_trace(
        plt.Scatter(x=df_filtered['DATE'], y=df_filtered['OEX_PC'], name="OEX P/C (Smart Money)", line=dict(color='green', width=1.5)),
        row=2, col=1
    )
    fig.add_trace(
        plt.Scatter(x=df_filtered['DATE'], y=df_filtered['EQUITY_CP'], name="Equity C/P (Dumb Money)", line=dict(color='red', width=1.5)),
        row=2, col=1
    )

    fig.update_layout(height=700, template="plotly_white", hovermode="x unified")
    fig.update_yaxes(title_text="Spread Index", row=1, col=1)
    fig.update_yaxes(title_text="Ratio", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Rohdaten anzeigen"):
        st.dataframe(df_filtered[['DATE', 'OEX_PC', 'EQUITY_PC', 'EQUITY_CP', 'SPREAD', 'SPREAD_SMA10']].sort_values('DATE', ascending=False))
