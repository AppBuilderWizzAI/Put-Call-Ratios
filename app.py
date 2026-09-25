import streamlit as st
import pandas as pd
import plotly.graph_objects as plt
from plotly.subplots import make_subplots
import requests
import io

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

@st.cache_data(ttl=14400)  # Caches data for 4 hours
def load_cboe_data():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    # Official CBOE Data Endpoints
    equity_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv"
    oex_url = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/oexpc.csv"
    
    try:
        req_eq = requests.get(equity_url, headers=headers, timeout=10)
        req_oex = requests.get(oex_url, headers=headers, timeout=10)
        
        # Read CSV skipping initial CBOE header rows
        df_eq = pd.read_csv(io.StringIO(req_eq.text), skiprows=2)
        df_oex = pd.read_csv(io.StringIO(req_oex.text), skiprows=2)
        
        # Standardize column names
        df_eq.columns = [c.strip().upper() for c in df_eq.columns]
        df_oex.columns = [c.strip().upper() for c in df_oex.columns]
        
        df_eq['DATE'] = pd.to_datetime(df_eq['DATE'], errors='coerce')
        df_oex['DATE'] = pd.to_datetime(df_oex['DATE'], errors='coerce')
        
        df_eq = df_eq.dropna(subset=['DATE'])
        df_oex = df_oex.dropna(subset=['DATE'])
        
        # Merge on Date
        df = pd.merge(df_oex[['DATE', 'P/C', 'CALLS', 'PUTS']], 
                      df_eq[['DATE', 'P/C', 'CALLS', 'PUTS']], 
                      on='DATE', 
                      suffixes=('_OEX', '_EQUITY'))
        
        # Convert numeric values
        for col in ['P/C_OEX', 'P/C_EQUITY', 'CALLS_OEX', 'PUTS_OEX', 'CALLS_EQUITY', 'PUTS_EQUITY']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        df = df.sort_values('DATE').reset_index(drop=True)
        
        # Calculate Ratios
        # 1. OEX Put/Call Ratio
        df['OEX_PC'] = df['P/C_OEX']
        
        # 2. Equity Call/Put Ratio = 1 / (Equity Put/Call Ratio)
        df['EQUITY_CP'] = 1.0 / df['P/C_EQUITY']
        
        # 3. Exact Formula Spread: (OEX P/C) - (Equity C/P)
        df['SPREAD'] = df['OEX_PC'] - df['EQUITY_CP']
        
        # Moving Averages for smoother analysis
        df['SPREAD_SMA10'] = df['SPREAD'].rolling(window=10).mean()
        df['SPREAD_SMA21'] = df['SPREAD'].rolling(window=21).mean()
        
        return df

    except Exception as e:
        st.error(f"Fehler beim Laden der CBOE-Daten: {e}")
        return pd.DataFrame()

with st.spinner("Lade echte CBOE-Daten..."):
    df = load_cboe_data()

if not df.empty:
    # Timeframe selection
    st.sidebar.header("Einstellungen")
    days = st.sidebar.slider("Zeitraum (Tage):", min_value=30, max_value=1000, value=252)
    
    df_filtered = df.tail(days)
    latest = df.iloc[-1]
    
    # Display Current Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Datum", latest['DATE'].strftime('%Y-%m-%d'))
    col2.metric("OEX Put/Call (Smart)", f"{latest['OEX_PC']:.2f}")
    col3.metric("Equity Call/Put (Dumb)", f"{latest['EQUITY_CP']:.2f}")
    col4.metric("Spread (Smart - Dumb)", f"{latest['SPREAD']:.2f}")

    # Plot Chart
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.08,
        subplot_titles=("Smart vs. Dumb Money Spread", "Einzelkomponenten (OEX P/C vs. Equity C/P)")
    )

    # Top Plot: Spread
    fig.add_trace(
        plt.Scatter(x=df_filtered['DATE'], y=df_filtered['SPREAD'], name="Spread (Täglich)", line=dict(color='gray', width=1), opacity=0.5),
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

    # Bottom Plot: Components
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
        st.dataframe(df_filtered[['DATE', 'OEX_PC', 'EQUITY_CP', 'SPREAD', 'SPREAD_SMA10']].sort_values('DATE', ascending=False))
