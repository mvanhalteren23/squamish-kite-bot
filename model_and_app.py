import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta

# --- CONFIGURATION ---
SQUAMISH_LAT = 49.7016
SQUAMISH_LON = -123.1558
YVR_LAT = 49.1967
YVR_LON = -123.1815
KITE_THRESHOLD = 15
MIN_DURATION = 2

# --- 1. DATA FETCHING ---
@st.cache_data(ttl=3600)
def get_forecast_data():
    url_sq = f"https://api.open-meteo.com/v1/forecast?latitude={SQUAMISH_LAT}&longitude={SQUAMISH_LON}&hourly=temperature_2m,pressure_msl,precipitation,windspeed_10m,winddirection_10m,windgusts_10m&timezone=America%2FVancouver"
    sq = requests.get(url_sq).json()
    url_yvr = f"https://api.open-meteo.com/v1/forecast?latitude={YVR_LAT}&longitude={YVR_LON}&hourly=pressure_msl&timezone=America%2FVancouver"
    yvr = requests.get(url_yvr).json()
    return process_data(sq, yvr)

@st.cache_data(ttl=3600)
def get_historical_data(date_str):
    url_sq = f"https://archive-api.open-meteo.com/v1/archive?latitude={SQUAMISH_LAT}&longitude={SQUAMISH_LON}&start_date={date_str}&end_date={date_str}&hourly=temperature_2m,pressure_msl,precipitation,windspeed_10m,winddirection_10m,windgusts_10m&timezone=America%2FVancouver"
    sq = requests.get(url_sq).json()
    url_yvr = f"https://archive-api.open-meteo.com/v1/archive?latitude={YVR_LAT}&longitude={YVR_LON}&hourly=pressure_msl&timezone=America%2FVancouver"
    yvr = requests.get(url_yvr).json()
    return process_data(sq, yvr)

def process_data(sq, yvr):
    df = pd.DataFrame({
        'time': sq['hourly']['time'],
        'temp_sq': sq['hourly']['temperature_2m'],
        'pressure_sq': sq['hourly']['pressure_msl'],
        'rain': sq['hourly']['precipitation'],
        'wind_base': sq['hourly']['windspeed_10m'],
        'wind_gust_api': sq['hourly']['windgusts_10m'],
        'wind_dir': sq['hourly']['winddirection_10m'],
        'pressure_yvr': yvr['hourly']['pressure_msl']
    })
    df['gradient'] = df['pressure_yvr'] - df['pressure_sq']
    df['datetime'] = pd.to_datetime(df['time'])
    return df

# --- 2. LOGIC ---
def calculate_wind_logic(row):
    if row['rain'] > 2.0 and row['pressure_sq'] < 1008:
        return 0, 0, 45, "DANGER"
    if row['temp_sq'] > 31.0:
        return 5, 8, 12, "Heat Bubble"
    steady = 22 + (row['gradient'] - 4) * 2.5 if row['gradient'] >= 4.0 else (16 + (row['gradient'] - 2.5) * 2 if row['gradient'] >= 2.5 else row['wind_base'])
    gust = max(steady * 1.35, row['wind_gust_api'])
    lull = steady * 0.7
    return lull, steady, gust, "Kiteable" if steady >= 15 else "Light"

# --- 3. GRAPHING HELPER (WIND ARROWS) ---
def add_wind_arrows(fig, df_subset, y_pos):
    """Adds directional arrows to the plot using annotations."""
    # We plot an arrow every 2 hours to keep mobile view clean
    for i, row in df_subset.iloc[::2].iterrows():
        # Open-Meteo wind_dir is degrees (0 is North, 180 is South)
        # We need to rotate the arrow. Plotly uses standard degrees.
        angle = row['wind_dir']
        
        fig.add_annotation(
            x=row['datetime'],
            y=y_pos,
            ax=15 * np.sin(np.radians(angle)),
            ay=-15 * np.cos(np.radians(angle)),
            xref="x", yref="y",
            axref="pixel", ayref="pixel",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.5,
            arrowwidth=2,
            arrowcolor="white" if row['steady'] >= 15 else "gray"
        )

# --- 4. UI: FORECAST ---
def render_forecast():
    st.header("7-Day Forecast")
    df = get_forecast_data()
    df[['lull', 'steady', 'gust', 'status']] = df.apply(lambda row: pd.Series(calculate_wind_logic(row)), axis=1)
    
    today = pd.Timestamp.now().date()
    df['day_date'] = df['datetime'].dt.date
    
    for day in df['day_date'].unique()[:7]:
        if day < today: continue
        day_df = df[(df['day_date'] == day) & (df['datetime'].dt.hour.between(10, 21))]
        if day_df.empty: continue

        with st.expander(f"{day.strftime('%A, %b %d')} (Peak: {int(day_df['steady'].max())}kn)"):
            fig = go.Figure()
            # Area Range
            fig.add_trace(go.Scatter(x=day_df['datetime'], y=day_df['gust'], mode='lines', line_width=0, showlegend=False))
            fig.add_trace(go.Scatter(x=day_df['datetime'], y=day_df['steady'], fill='tonexty', fillcolor='rgba(0,255,0,0.1)', mode='lines', line=dict(color='green', width=3), name='Steady'))
            
            # Add Arrows at the top (Max Y + 5)
            y_arrow_pos = day_df['gust'].max() + 5
            add_wind_arrows(fig, day_df, y_arrow_pos)

            fig.update_layout(height=300, margin=dict(l=10,r=10,t=40,b=10), yaxis_title="Knots", xaxis=dict(tickformat="%I %p"), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

# --- 5. UI: HISTORICALS ---
def render_historicals():
    st.header("Prediction Review")
    selected_date = st.date_input("Select Past Date", value=pd.Timestamp.now().date() - timedelta(days=1))
    
    if st.button("Analyze History"):
        df = get_historical_data(str(selected_date))
        df[['lull', 'steady', 'gust', 'status']] = df.apply(lambda row: pd.Series(calculate_wind_logic(row)), axis=1)
        df = df[df['datetime'].dt.hour.between(10, 21)]
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df['datetime'], y=df['wind_base'], fill='tozeroy', line_color='royalblue', name='Actual'))
        fig.add_trace(go.Scatter(x=df['datetime'], y=df['steady'], mode='lines+markers', line=dict(color='green', width=3), name='Predicted'))
        
        # Add Actual Wind Arrows
        y_arrow_pos = max(df['wind_gust_api'].max(), df['steady'].max()) + 5
        add_wind_arrows(fig, df, y_arrow_pos)
        
        fig.update_layout(height=350, yaxis_title="Knots", xaxis=dict(tickformat="%I %p"), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

def main():
    st.set_page_config(page_title="Squamish Wind Bot", layout="centered")
    tab1, tab2 = st.tabs(["🚀 Forecast", "📜 Historicals"])
    with tab1: render_forecast()
    with tab2: render_historicals()

if __name__ == "__main__":
    main()
    
