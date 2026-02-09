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
KITE_THRESHOLD = 15  # Knots required to kite

# --- 1. DATA FETCHING ---
@st.cache_data(ttl=3600) # Cache data for 1 hour to speed up mobile loading
def get_weather_data():
    # Fetch Squamish (Include Gusts)
    url_sq = f"https://api.open-meteo.com/v1/forecast?latitude={SQUAMISH_LAT}&longitude={SQUAMISH_LON}&hourly=temperature_2m,pressure_msl,precipitation,windspeed_10m,winddirection_10m,windgusts_10m&timezone=America%2FVancouver"
    sq = requests.get(url_sq).json()
    
    # Fetch YVR (For Pressure Gradient)
    url_yvr = f"https://api.open-meteo.com/v1/forecast?latitude={YVR_LAT}&longitude={YVR_LON}&hourly=pressure_msl&timezone=America%2FVancouver"
    yvr = requests.get(url_yvr).json()

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
    return df

# --- 2. PREDICTION ENGINE ---
def calculate_wind_logic(row):
    # Hour Filter (Night is rarely kiteable, but we calculate it anyway for 24h view)
    hour = int(row['time'].split('T')[1].split(':')[0])
    
    # 1. Storm Check (Safety First)
    if row['rain'] > 2.0 and row['pressure_sq'] < 1008:
        return 0, 0, 45, "DANGER: STORM" # 45kn gust flag
    
    # 2. Heat Bubble (Temp > 31C)
    if row['temp_sq'] > 31.0:
        return 5, 8, 12, "Heat Bubble"

    # 3. Thermal Calculation
    steady = 0
    status = "Light"
    
    if row['gradient'] >= 4.0:
        steady = 22 + (row['gradient'] - 4) * 2.5
        status = "Excellent"
    elif row['gradient'] >= 2.5:
        steady = 16 + (row['gradient'] - 2.5) * 2
        status = "Good"
    else:
        steady = row['wind_base'] # No thermal, use forecast base
        status = "Light"

    # 4. Gusts & Lulls
    # Squamish Factor: Gusts are usually 30-40% higher than steady thermal
    gust = max(steady * 1.35, row['wind_gust_api'])
    lull = steady * 0.7 # Lulls are 70% of steady

    # Rain Dampener
    if row['rain'] > 0.5 and status != "Light":
        steady *= 0.6
        gust *= 0.8
        status = "Rain Risk"

    return lull, steady, gust, status

# --- 3. UI RENDERING ---
def main():
    st.set_page_config(page_title="Squamish Wind Planner", page_icon="🪁", layout="centered")
    
    # Header
    st.title("🪁 Squamish Wind Planner")
    st.write(f"**Last Update:** {datetime.now().strftime('%I:%M %p')}")

    try:
        df = get_weather_data()
        
        # Apply Logic
        df[['lull', 'steady', 'gust', 'status']] = df.apply(
            lambda row: pd.Series(calculate_wind_logic(row)), axis=1
        )
        
        # Format Time
        df['datetime'] = pd.to_datetime(df['time'])
        now = pd.Timestamp.now()
        
        # --- SECTION 1: NEXT 24 HOURS (HOURLY) ---
        st.divider()
        st.subheader("⏱️ Next 24 Hours")
        
        # Filter: Now to Now + 24h
        df_24h = df[(df['datetime'] >= now) & (df['datetime'] < now + timedelta(hours=24))]
        
        # Plotly Chart for 24h
        fig_24 = go.Figure()
        
        # Gust Area (Light Red)
        fig_24.add_trace(go.Scatter(
            x=df_24h['datetime'], y=df_24h['gust'],
            fill=None, mode='lines', line_color='rgba(255,0,0,0.1)', showlegend=False
        ))
        fig_24.add_trace(go.Scatter(
            x=df_24h['datetime'], y=df_24h['lull'],
            fill='tonexty', mode='lines', line_color='rgba(255,0,0,0.1)', fillcolor='rgba(255, 100, 100, 0.2)', name='Gust Range'
        ))
        
        # Steady Line (Green/Red based on value)
        fig_24.add_trace(go.Scatter(
            x=df_24h['datetime'], y=df_24h['steady'],
            mode='lines+markers', line=dict(color='#00CC96', width=3), name='Steady Wind'
        ))

        # 15kn Threshold Line
        fig_24.add_hline(y=15, line_dash="dash", line_color="white", annotation_text="Kiteable")

        fig_24.update_layout(
            height=250, margin=dict(l=10, r=10, t=30, b=10),
            yaxis_title="Knots",
            xaxis=dict(tickformat="%I %p"), # Show 1 PM, 2 PM...
            showlegend=False
        )
        st.plotly_chart(fig_24, use_container_width=True)

        # --- SECTION 2: WEEKLY WINDOWS (START / END TIMES) ---
        st.divider()
        st.subheader("📅 Weekly Kite Windows")
        st.caption("Times when wind > 15 knots.")

        # Filter: Next 7 Days
        df_week = df[df['datetime'] >= now.floor('D')]
        days = df_week['datetime'].dt.date.unique()

        for day in days[:7]:
            day_df = df_week[df_week['datetime'].dt.date == day]
            
            # Find Kiteable Hours (Steady > 15)
            kite_hours = day_df[day_df['steady'] >= 15]
            
            day_name = day.strftime("%A, %b %d")
            
            if kite_hours.empty:
                # CARD: NO WIND
                with st.container():
                    col1, col2 = st.columns([1, 3])
                    col1.write(f"**{day.strftime('%a')}**")
                    col2.markdown("💤 No Wind")
            else:
                # Find Start and End
                start_time = kite_hours['datetime'].iloc[0].strftime("%I %p").lstrip("0")
                end_time = kite_hours['datetime'].iloc[-1].strftime("%I %p").lstrip("0")
                peak_wind = int(kite_hours['steady'].max())
                
                # Check for Storm Flag in this day
                is_storm = "DANGER" in day_df['status'].values
                
                # CARD: WINDY
                with st.container():
                    col1, col2, col3 = st.columns([1, 2, 1])
                    
                    # Day
                    col1.write(f"**{day.strftime('%a')}**")
                    
                    # Window
                    if is_storm:
                        col2.markdown(f"🚫 **STORM RISK**")
                    else:
                        col2.markdown(f"🏄 **{start_time} - {end_time}**")
                    
                    # Peak Strength
                    color = "red" if peak_wind > 30 else "green"
                    col3.markdown(f":{color}[**Max {peak_wind} kn**]")
            
            st.markdown("---") # Thin divider

    except Exception as e:
        st.error(f"Error loading forecast: {e}")

if __name__ == "__main__":
    main()
