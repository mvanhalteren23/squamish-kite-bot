import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- CONFIGURATION ---
SQUAMISH_LAT = 49.7016
SQUAMISH_LON = -123.1558
YVR_LAT = 49.1967
YVR_LON = -123.1815
KITE_THRESHOLD = 15
MIN_DURATION = 2

# --- 1. DATA FETCHING (FORECAST & HISTORICAL) ---
@st.cache_data(ttl=3600)
def get_forecast_data():
    # Forecast API (Next 7 Days)
    url_sq = f"https://api.open-meteo.com/v1/forecast?latitude={SQUAMISH_LAT}&longitude={SQUAMISH_LON}&hourly=temperature_2m,pressure_msl,precipitation,windspeed_10m,winddirection_10m,windgusts_10m&timezone=America%2FVancouver"
    sq = requests.get(url_sq).json()
    
    url_yvr = f"https://api.open-meteo.com/v1/forecast?latitude={YVR_LAT}&longitude={YVR_LON}&hourly=pressure_msl&timezone=America%2FVancouver"
    yvr = requests.get(url_yvr).json()

    return process_data(sq, yvr)

@st.cache_data(ttl=3600)
def get_historical_data(date_str):
    # Historical API (Past Dates)
    # Open-Meteo Archive API
    start_date = date_str
    end_date = date_str
    
    url_sq = f"https://archive-api.open-meteo.com/v1/archive?latitude={SQUAMISH_LAT}&longitude={SQUAMISH_LON}&start_date={start_date}&end_date={end_date}&hourly=temperature_2m,pressure_msl,precipitation,windspeed_10m,winddirection_10m,windgusts_10m&timezone=America%2FVancouver"
    sq = requests.get(url_sq).json()
    
    url_yvr = f"https://archive-api.open-meteo.com/v1/archive?latitude={YVR_LAT}&longitude={YVR_LON}&start_date={start_date}&end_date={end_date}&hourly=pressure_msl&timezone=America%2FVancouver"
    yvr = requests.get(url_yvr).json()

    return process_data(sq, yvr)

def process_data(sq, yvr):
    # Shared processing for both Forecast and History
    try:
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
    except Exception as e:
        st.error(f"Error processing data: {e}")
        return pd.DataFrame()

# --- 2. PREDICTION ENGINE (THE LOGIC) ---
def calculate_wind_logic(row):
    # 1. Storm Check
    if row['rain'] > 2.0 and row['pressure_sq'] < 1008:
        return 0, 0, 45, "DANGER: STORM"
    
    # 2. Heat Bubble
    if row['temp_sq'] > 31.0:
        return 5, 8, 12, "Heat Bubble"

    # 3. Thermal Model
    steady = 0
    if row['gradient'] >= 4.0:
        steady = 22 + (row['gradient'] - 4) * 2.5
        status = "Excellent"
    elif row['gradient'] >= 2.5:
        steady = 16 + (row['gradient'] - 2.5) * 2
        status = "Good"
    else:
        steady = row['wind_base']
        status = "Light"

    # 4. Gusts & Lulls
    gust = max(steady * 1.35, row['wind_gust_api'])
    lull = steady * 0.7

    # Rain Dampener
    if row['rain'] > 0.5 and status != "Light":
        steady *= 0.6
        gust *= 0.8
        status = "Rain Risk"

    return lull, steady, gust, status

# --- 3. HELPER: FIND WINDOWS ---
def find_kite_window(day_df):
    windy_hours = day_df[day_df['steady'] >= KITE_THRESHOLD]
    if len(windy_hours) < MIN_DURATION:
        return None, None, "No Solid Session"
    start = windy_hours['datetime'].iloc[0].strftime("%I %p").lstrip("0")
    end = windy_hours['datetime'].iloc[-1].strftime("%I %p").lstrip("0")
    return start, end, f"{start} - {end}"

# --- 4. UI: FORECAST TAB ---
def render_forecast():
    st.header("7-Day Forecast")
    df = get_forecast_data()
    if df.empty: return
    
    # Apply Logic
    df[['lull', 'steady', 'gust', 'status']] = df.apply(lambda row: pd.Series(calculate_wind_logic(row)), axis=1)
    
    # Filter Next 7 Days
    today = pd.Timestamp.now().date()
    df['day_date'] = df['datetime'].dt.date
    days = df['day_date'].unique()

    for day in days[:7]:
        if day < today: continue
        day_df = df[(df['day_date'] == day) & (df['datetime'].dt.hour.between(10, 21))]
        if day_df.empty: continue

        start, end, window = find_kite_window(day_df)
        
        # Header Logic
        icon, title = "💤", f"**{day.strftime('%A')}** | No Wind"
        if "DANGER" in day_df['status'].values: icon, title = "⛈️", f"**{day.strftime('%A')}** | 🚫 **STORM**"
        elif start: icon, title = "🏄", f"**{day.strftime('%A')}** | ✅ **{window}**"

        with st.expander(f"{icon} {title}", expanded=(day == today)):
            fig = go.Figure()
            # Gust Range (Red)
            fig.add_trace(go.Scatter(x=day_df['datetime'], y=day_df['gust'], mode='lines', line=dict(width=0), showlegend=False))
            fig.add_trace(go.Scatter(x=day_df['datetime'], y=day_df['steady'], mode='lines', fill='tonexty', fillcolor='rgba(255,80,80,0.2)', line=dict(color='green', width=3), name='Steady'))
            # Lull Range (Green)
            fig.add_trace(go.Scatter(x=day_df['datetime'], y=day_df['lull'], mode='lines', fill='tonexty', fillcolor='rgba(0,200,0,0.1)', line=dict(width=0), name='Lull'))
            fig.add_hline(y=15, line_dash="dash", line_color="white", opacity=0.5)
            fig.update_layout(height=250, margin=dict(l=10,r=10,t=10,b=10), yaxis_title="Knots", xaxis=dict(tickformat="%I %p"), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

# --- 5. UI: HISTORICALS TAB ---
def render_historicals():
    st.header("Prediction Review")
    st.caption("Compare the Model's logic vs. What actually happened.")
    
    # Date Picker
    default_date = pd.Timestamp.now().date() - timedelta(days=1)
    selected_date = st.date_input("Select Past Date", value=default_date)
    
    if st.button("Analyze History"):
        with st.spinner("Fetching historical archives..."):
            df = get_historical_data(str(selected_date))
            
            if not df.empty:
                # 1. Run the Model on Historical Conditions
                df[['lull', 'steady', 'gust', 'status']] = df.apply(lambda row: pd.Series(calculate_wind_logic(row)), axis=1)
                
                # Filter for Kite Hours
                df = df[df['datetime'].dt.hour.between(10, 21)]
                
                # 2. Calculate Accuracy (Error)
                df['error'] = df['steady'] - df['wind_base'] # Model Steady vs Actual Avg
                mae = df['error'].abs().mean()
                
                # Verdict
                verdict_color = "green" if mae < 5 else "red"
                verdict_text = "✅ Accurate Logic" if mae < 5 else "❌ Model Missed"
                
                col1, col2 = st.columns(2)
                col1.metric("Model Error (MAE)", f"{mae:.1f} kn")
                col2.markdown(f":{verdict_color}[**{verdict_text}**]")
                
                # 3. Visualization (Comparison Chart)
                fig = go.Figure()
                
                # Actual Wind (Blue Area)
                fig.add_trace(go.Scatter(
                    x=df['datetime'], y=df['wind_base'], 
                    mode='lines', fill='tozeroy', 
                    line=dict(color='royalblue', width=2),
                    fillcolor='rgba(65, 105, 225, 0.2)',
                    name='Actual Wind'
                ))
                
                # Actual Gusts (Blue Dotted)
                fig.add_trace(go.Scatter(
                    x=df['datetime'], y=df['wind_gust_api'],
                    mode='lines', line=dict(color='royalblue', dash='dot', width=1),
                    name='Actual Gusts'
                ))
                
                # Model Prediction (Green Line)
                fig.add_trace(go.Scatter(
                    x=df['datetime'], y=df['steady'],
                    mode='lines+markers', line=dict(color='green', width=3),
                    name='Model Predicted'
                ))
                
                fig.update_layout(
                    title="Model (Green) vs Actuals (Blue)",
                    height=350,
                    yaxis_title="Knots",
                    xaxis=dict(tickformat="%I %p"),
                    legend=dict(orientation="h", y=1.1)
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Debug Data
                with st.expander("View Raw Data"):
                    st.dataframe(df[['datetime', 'pressure_sq', 'pressure_yvr', 'gradient', 'steady', 'wind_base']])

# --- MAIN APP STRUCTURE ---
def main():
    st.set_page_config(page_title="Squamish Wind Bot", page_icon="🪁", layout="centered")
    
    tab1, tab2 = st.tabs(["🚀 Forecast", "📜 Historicals"])
    
    with tab1:
        render_forecast()
    
    with tab2:
        render_historicals()

if __name__ == "__main__":
    main()
    
