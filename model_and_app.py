import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime, timedelta

# --- CONSTANTS ---
SQUAMISH_LAT = 49.7016
SQUAMISH_LON = -123.1558
YVR_LAT = 49.1967
YVR_LON = -123.1815

# --- 1. DATA FETCHING (Open-Meteo Free API) ---
def get_weather_data():
    # Fetch Squamish Data
    url_sq = f"https://api.open-meteo.com/v1/forecast?latitude={SQUAMISH_LAT}&longitude={SQUAMISH_LON}&hourly=temperature_2m,pressure_msl,precipitation,windspeed_10m,winddirection_10m&timezone=America%2FVancouver"
    sq = requests.get(url_sq).json()
    
    # Fetch YVR Data (For Pressure Gradient)
    url_yvr = f"https://api.open-meteo.com/v1/forecast?latitude={YVR_LAT}&longitude={YVR_LON}&hourly=pressure_msl&timezone=America%2FVancouver"
    yvr = requests.get(url_yvr).json()

    # Create DataFrame
    df = pd.DataFrame({
        'time': sq['hourly']['time'],
        'temp_sq': sq['hourly']['temperature_2m'],
        'pressure_sq': sq['hourly']['pressure_msl'],
        'rain': sq['hourly']['precipitation'],
        'wind_speed_base': sq['hourly']['windspeed_10m'],
        'wind_dir': sq['hourly']['winddirection_10m'],
        'pressure_yvr': yvr['hourly']['pressure_msl']
    })
    
    # Calculate Gradient (YVR - Squamish)
    df['gradient'] = df['pressure_yvr'] - df['pressure_sq']
    return df

# --- 2. THE LOGIC (Thermal + Storm + Heat Bubble) ---
def predict_kite_wind(row):
    # Kiteable Hours Only (10 AM - 8 PM)
    hour = int(row['time'].split('T')[1].split(':')[0])
    if hour < 10 or hour > 20:
        return 0, "Night"

    # LOGIC GATES
    # 1. Storm Safety (Rain > 2mm AND Low Pressure)
    if row['rain'] > 2.0 and row['pressure_sq'] < 1008:
        return 40, "DANGER: STORM"  # 40kn indicates Danger in chart
    
    # 2. Heat Bubble (Temp > 31C kills thermal)
    if row['temp_sq'] > 31.0:
        return 5, "Heat Bubble (Lull)"
    
    # 3. The Thermal Engine (Gradient Driven)
    predicted_wind = 0
    status = "No Wind"
    
    if row['gradient'] >= 3.5:
        predicted_wind = 20 + (row['gradient'] - 4) * 2  # Base 20kn + bonus
        status = "EXCELLENT"
    elif row['gradient'] >= 2.0:
        predicted_wind = 15 + (row['gradient'] - 2) * 2
        status = "KITEABLE"
    else:
        predicted_wind = row['wind_speed_base'] # Fallback to synoptic wind
        status = "Light"

    # 4. Rain Penalty (Light rain kills thermal)
    if row['rain'] > 0.5 and predicted_wind < 30: # Don't penalize storms
        predicted_wind = predicted_wind * 0.5
        status = "Rain Risk"
        
    return predicted_wind, status

# --- 3. THE APP (Streamlit UI) ---
def main():
    st.set_page_config(page_title="Squamish Kite Bot", page_icon="🪁")
    st.title("🪁 Squamish Wind Predictor")
    
    st.write("Fetching live data from Open-Meteo...")
    try:
        df = get_weather_data()
        
        # Apply Logic
        df[['predicted_wind', 'status']] = df.apply(
            lambda row: pd.Series(predict_kite_wind(row)), axis=1
        )
        
        # Convert Time
        df['datetime'] = pd.to_datetime(df['time'])
        df['day_name'] = df['datetime'].dt.day_name()
        df['hour_only'] = df['datetime'].dt.hour
        
        # FILTER: Show Next 5 Days
        today = pd.Timestamp.now().floor('D')
        df_show = df[df['datetime'] >= today]

        # --- VISUALIZATION ---
        # Color Logic for Bar Chart
        def get_color(wind):
            if wind >= 35: return 'red'     # Danger
            if wind >= 18: return '#00CC00' # Green (Good)
            if wind >= 13: return '#FFAA00' # Yellow (Borderline)
            return 'gray'
            
        df_show['color'] = df_show['predicted_wind'].apply(get_color)

        # Main Chart
        st.subheader("7-Day Forecast (Predicted Knots)")
        fig = px.bar(
            df_show, x='datetime', y='predicted_wind',
            color='predicted_wind',
            color_continuous_scale=['gray', 'orange', 'green', 'red'],
            range_color=[0, 35],
            title="Wind Speed Prediction (Knots)"
        )
        # Add a horizontal line for "Kiteable" threshold
        fig.add_hline(y=15, line_dash="dash", line_color="white", annotation_text="Kiteable (15kn)")
        st.plotly_chart(fig, use_container_width=True)

        # --- BEST TIME OF DAY ANALYSIS ---
        st.subheader("📅 Best Time to Kite")
        
        # Group by Day to find Peak Wind
        days = df_show['datetime'].dt.date.unique()
        
        for day in days[:5]: # Show next 5 days
            day_data = df_show[df_show['datetime'].dt.date == day]
            day_data = day_data[day_data['hour_only'].between(10, 20)] # Kite hours
            
            # Find Best Hour
            peak_row = day_data.loc[day_data['predicted_wind'].idxmax()]
            peak_wind = peak_row['predicted_wind']
            peak_time = peak_row['datetime'].strftime("%I %p")
            
            # Logic for "Verdict"
            verdict = "❌ No Wind"
            icon = "💤"
            if peak_wind >= 30: 
                verdict = "⚠️ DANGER / STORM"
                icon = "⛈️"
            elif peak_wind >= 18: 
                verdict = "✅ GO KITING"
                icon = "🏄"
            elif peak_wind >= 13: 
                verdict = "⚠️ Foil / Big Kite"
                icon = "🪂"

            # Render Card
            with st.container():
                st.markdown(f"### {day.strftime('%A, %b %d')}")
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.metric(label="Peak Wind", value=f"{int(peak_wind)} kn")
                with col2:
                    st.write(f"**Verdict:** {icon} {verdict}")
                    st.write(f"**Best Time:** {peak_time}")
                    st.caption(f"Gradient: {peak_row['gradient']:.1f}mb | Temp: {peak_row['temp_sq']}°C")
                st.divider()

    except Exception as e:
        st.error(f"Error fetching data: {e}")

if __name__ == "__main__":
    main()
  
