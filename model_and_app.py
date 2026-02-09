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
    yvr = requests
