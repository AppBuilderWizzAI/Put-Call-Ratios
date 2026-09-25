import streamlit as st
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests
from io import StringIO

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

def parse_cboe_csv(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    res = requests.get(url, headers=headers, timeout=15)
    lines = res.text.splitlines()
    
    # Suche die Zeile, in der die Spaltenüberschrift 'Date' vorkommt
    header_idx = -1
    for i, line in enumerate(lines):
        if 'date' in line.lower():
            header_idx = i
            break
            
    if header_idx == -1:
        raise ValueError("Keine Datums-Kopfzeile in der CBOE-Datei gefunden.")
        
    # Lese CSV ab der gefundenen Kopfzeile
    csv_data = "\n".join(lines[header_idx:])
    df = pd.read_csv(StringIO(csv_data))
    
    # Spaltennamen säubern
    df.columns = [str(c).strip().upper() for c in df.columns]
    
    # Finde die Datumsspalte (egal ob DATE, Date etc.)
    date_col = [c for c in df.columns if 'DATE' in c][0]
    df['DATE'] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=['DATE'])
    
    # Finde die P/C-Spalte (z. B. P/C, P/C RATIO, RATIO)
    pc_cols = [c for c in df.columns if 'P/C' in c or 'RATIO' in c]
    if not pc_cols:
        raise ValueError("Keine P/C Ratio Spalte gefunden.")
    
    pc_col = pc_cols[0]
    df['PC_RATIO'] = pd.to_numeric(df[pc_col], errors='coerce')
    df = df.dropna(subset=['PC_RATIO'])
    
    return df[['DATE', 'PC_RATIO']]

@st.cache_data(ttl=14400)
def load_and_process_ratios():
    try:
        equity_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv"
        oex_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/oexpc.csv"
        
        df_eq = parse_cboe_csv(equity_url)
        df_oex = parse_cboe_csv(oex_url)
        
        # Merge der beiden Datensätze über das Datum
        df = pd.merge(
            df_oex, 
            df_eq, 
            on='DATE', 
            suffixes=('_OEX', '_EQUITY')
        )
        
        df = df.sort_values('DATE').reset_index(drop=True)
        
        # 1. OEX Put/Call Ratio
        df['OEX_PC'] = df['PC_RATIO_OEX']
        
        # 2. Equity Put/Call Ratio
        df['EQUITY_PC'] = df['PC_RATIO_EQUITY']
        
        # 3. Equity Call/Put Ratio = 1 / Equity Put/Call Ratio
        df['EQUITY_CP'] = 1.0 / df['EQUITY_PC']
        
        # 4. Exakte Formel: (OEX P/C) - (Equity C/P)
        df['SPREAD'] = df['OEX_PC'] - df['EQUITY_CP']
        
        # Gleitende Durchschnitte
        df['SPREAD_SMA10'] = df['SPREAD'].rolling(window=10).mean()
        df['SPREAD_SMA21'] = df['SPREAD'].rolling(window=21).mean()
        
        return df

    except Exception as e:
        st.error(f"Fehler beim Laden der CBOE-Daten: {e}")
        return pd.DataFrame()

with st.spinner("Lade echte CBOE-Daten..."):
    df = load_and_process_ratios()

if not df.empty:
    st.sidebar.header("Einstellungen")
    days = st.sidebar.slider("Zeitraum (Tage):", min_value=30, max_value=1000, value=252)
    
    df_filtered = df.tail(days)
    latest = df.iloc[-1]
    
    # Kennzahlen
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Datum", latest['DATE'].strftime('%Y-%m-%d'))
    col2.metric("OEX Put/Call (Smart)", f"{latest['OEX_PC']:.2f}")
    col3.metric("Equity Call/Put (Dumb)", f"{latest['EQUITY_CP']:.2f}")
    col4.metric("Spread (Smart - Dumb)", f"{latest['SPREAD']:.2f}")

    # Charts
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.08,
        subplot_titles=("Smart vs. Dumb Money Spread", "Einzelkomponenten (OEX P/C vs. Equity C/P)")
    )

    # Upper Plot
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

    # Lower Plot
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
