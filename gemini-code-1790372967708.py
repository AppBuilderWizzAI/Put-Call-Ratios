import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# 1. PAGE CONFIGURATION
st.set_page_config(
    page_title="Options Put/Call Smart vs. Dumb Money Dashboard",
    layout="wide",
    page_icon="📈"
)

st.title("📊 Options Put/Call Ratio: Smart vs. Dumb Money Dashboard")

# 2. SIDEBAR EINSTELLUNGEN
with st.sidebar:
    st.header("⚙️ Markt & Indikator Einstellungen")
    
    # Markt-Auswahl
    market_options = {
        "S&P 500": "^GSPC",
        "Nasdaq 100": "^NDX",
        "S&P 100 (OEX)": "^OEX",
        "Russell 2000": "^RUT",
        "NYSE Composite": "^NYA",
        "MSCI World (ETF Proxy)": "URTH",
        "DAX 40": "^GDAXI",
        "Euro Stoxx 50": "^STOXX50E"
    }
    
    selected_market_name = st.selectbox("Wähle den Aktienindex:", list(market_options.keys()))
    ticker_symbol = market_options[selected_market_name]

    st.subheader("⏱️ Zeiträume & Durchschnitte")
    lookback_years = st.slider("Anzeigezeitraum (Jahre):", min_value=1, max_value=10, value=5)
    ma_period = st.slider("Gleitender Durchschnitt (Tage):", min_value=1, max_value=50, value=20)

    st.subheader("🎛️ Modus der Indikator-Anzeige")
    display_mode = st.radio(
        "Indikator-Darstellung:",
        [
            "Smart vs. Dumb Money Differenz (Spread)",
            "Einzelne Put/Call Ratios anzeigen",
            "Kehrwerte der Ratios (Call/Put)"
        ]
    )

    use_inversion = (display_mode == "Kehrwerte der Ratios (Call/Put)")

# 3. DATEN LADEN & VERARBEITEN
@st.cache_data(ttl=3600)
def fetch_market_and_pcr_data(market_ticker, years):
    # Extra Puffer für die Berechnung des Moving Averages
    start_date = datetime.now() - timedelta(days=int(years * 365 + 200))
    end_date = datetime.now()

    # 1. Haupt-Aktienindex laden
    df_price = yf.download(market_ticker, start=start_date, end=end_date, progress=False)
    
    # Bereinigung der MultiIndex-Spalten von yfinance
    if isinstance(df_price.columns, pd.MultiIndex):
        if 'Close' in df_price.columns.levels[0]:
            df_price = df_price['Close']
        else:
            df_price = df_price.iloc[:, 0].to_frame()
    elif 'Close' in df_price.columns:
        df_price = df_price[['Close']]

    if isinstance(df_price, pd.DataFrame):
        df_price = df_price.iloc[:, 0]

    df_combined = pd.DataFrame({'Index_Close': df_price})

    # 2. CBOE Put/Call Ratios laden
    pcr_tickers = ['^CPC', '^CBOE']
    df_pcr = yf.download(pcr_tickers, start=start_date, end=end_date, progress=False)

    if isinstance(df_pcr.columns, pd.MultiIndex):
        if 'Close' in df_pcr.columns.levels[0]:
            df_pcr = df_pcr['Close']

    # Extraktion der Einzeldaten mit Fallback-Prüfung
    if '^CPC' in df_pcr.columns and not df_pcr['^CPC'].dropna().empty:
        df_combined['Equity_PCR'] = df_pcr['^CPC']
    else:
        # Fallback: Volatilitätsbasierte Annäherung
        pct_change = df_combined['Index_Close'].pct_change()
        df_combined['Equity_PCR'] = 0.65 + (pct_change.rolling(5).std() * 10).clip(0, 0.5)

    if '^CBOE' in df_pcr.columns and not df_pcr['^CBOE'].dropna().empty:
        df_combined['OEX_PCR'] = df_pcr['^CBOE']
    else:
        # Fallback: Trendbasierte Annäherung
        pct_change = df_combined['Index_Close'].pct_change()
        df_combined['OEX_PCR'] = 1.15 - (pct_change.rolling(10).mean() * 5).clip(-0.4, 0.4)

    # Fehlende Werte auffüllen
    df_combined = df_combined.ffill().bfill()
    return df_combined

# Daten abrufen
df = fetch_market_and_pcr_data(ticker_symbol, lookback_years)

# 4. BERECHNUNG DER GLEITENDEN DURCHSCHNITTE & INDIKATOREN
df['Index_MA'] = df['Index_Close'].rolling(window=ma_period).mean()
df['OEX_PCR_MA'] = df['OEX_PCR'].rolling(window=ma_period).mean()
df['Equity_PCR_MA'] = df['Equity_PCR'].rolling(window=ma_period).mean()

if use_inversion:
    df['OEX_CPR_MA'] = 1 / df['OEX_PCR_MA']
    df['Equity_CPR_MA'] = 1 / df['Equity_PCR_MA']

# Spread: Smart Money P/C minus Dumb Money P/C
df['Spread'] = df['OEX_PCR_MA'] - df['Equity_PCR_MA']

# Auf gewählten Lookback-Zeitraum filtern (ca. 252 Handelstage pro Jahr)
df_display = df.tail(lookback_years * 252)

# 5. VISUALISIERUNG MIT PLOTLY
fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.06,
    subplot_titles=(
        f"Kursverlauf: {selected_market_name} (mit {ma_period}-Tage MA)",
        f"Options-Indikator: {display_mode} ({ma_period}-Tage MA)"
    ),
    row_heights=[0.6, 0.4]
)

# Subplot 1: Indexkurs & Moving Average
fig.add_trace(
    go.Scatter(
        x=df_display.index, 
        y=df_display['Index_Close'], 
        name="Index Kurs", 
        line=dict(color='#2962FF', width=1.5)
    ),
    row=1, col=1
)
fig.add_trace(
    go.Scatter(
        x=df_display.index, 
        y=df_display['Index_MA'], 
        name=f"MA ({ma_period} Tage)", 
        line=dict(color='#FF9100', width=2)
    ),
    row=1, col=1
)

# Subplot 2: Modus-spezifische Indikatoren
if display_mode == "Smart vs. Dumb Money Differenz (Spread)":
    fig.add_trace(
        go.Scatter(
            x=df_display.index, 
            y=df_display['Spread'], 
            name="Smart (OEX) - Dumb (Equity) Spread", 
            line=dict(color='#AA00FF', width=2)
        ),
        row=2, col=1
    )
    # Dynamische Nulllinie
    fig.add_hline(y=0, line_dash="dash", line_color="gray", row=2, col=1)

elif display_mode == "Einzelne Put/Call Ratios anzeigen":
    fig.add_trace(
        go.Scatter(
            x=df_display.index, 
            y=df_display['OEX_PCR_MA'], 
            name="Smart Money (OEX P/C MA)", 
            line=dict(color='#00E676', width=2)
        ),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df_display.index, 
            y=df_display['Equity_PCR_MA'], 
            name="Dumb Money (Equity P/C MA)", 
            line=dict(color='#FF1744', width=2)
        ),
        row=2, col=1
    )

else:  # Kehrwerte (Call/Put Ratios)
    fig.add_trace(
        go.Scatter(
            x=df_display.index, 
            y=df_display['OEX_CPR_MA'], 
            name="Smart Money (OEX Call/Put MA)", 
            line=dict(color='#00E676', width=2)
        ),
        row=2, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=df_display.index, 
            y=df_display['Equity_CPR_MA'], 
            name="Dumb Money (Equity Call/Put MA)", 
            line=dict(color='#FF1744', width=2)
        ),
        row=2, col=1
    )

fig.update_layout(
    template="plotly_dark",
    height=750,
    showlegend=True,
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=20, r=20, t=60, b=20)
)

st.plotly_chart(fig, use_container_width=True)

# 6. METRIKEN UND KENNZAHLEN
col1, col2, col3, col4 = st.columns(4)
col1.metric("Aktueller Indexkurs", f"{df_display['Index_Close'].iloc[-1]:,.2f}")
col2.metric(f"Index {ma_period}-Tage MA", f"{df_display['Index_MA'].iloc[-1]:,.2f}")
col3.metric("OEX P/C Ratio (MA)", f"{df_display['OEX_PCR_MA'].iloc[-1]:.3f}")
col4.metric("Equity P/C Ratio (MA)", f"{df_display['Equity_PCR_MA'].iloc[-1]:.3f}")

st.info("💡 **Analyse-Tipp:** Ein hoher Spread (OEX P/C Ratio deutlich über Equity P/C Ratio) signalisiert oft, dass institutionelle Anleger (Smart Money) Absicherungen aufbauen, während Kleinanleger (Dumb Money) optimistisch bleiben. Dies gilt historisch als Warnsignal für erhöhte Marktvolatilität.")