import streamlit as st
import requests
import pandas as pd
from dateutil import parser
from zoneinfo import ZoneInfo
import altair as alt
from lib.utils import initialize_session_state

# --- Helper Functions ---
def to_sg(ts):
    if not ts: return ts
    try:
        dt = parser.isoparse(ts)
        dt_sg = dt.astimezone(ZoneInfo("Asia/Singapore"))
        return dt_sg.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts

# --- Config & State ---
st.set_page_config(page_title="IoT Dashboard", layout="wide")
st.title("Dashboard")

initialize_session_state()

APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbzJuX7P3OQ25ZBMqRZwnyI56U78QSnx3IW13OY7W2T9jaTQ2Wa2pJZ2JSrDXJ5pCdmR/exec"

# Sidebar Controls
SHEET_REFRESH = st.sidebar.number_input("Sheet refresh (seconds)", 2, 60, 10)

# --- The Fragment (The "Loop") ---
@st.fragment(run_every=SHEET_REFRESH)
def auto_refresh_sheet():
    st.subheader("Google Sheet (Live)")
    
    try:
        # Fetch Data
        r = requests.get(APPS_SCRIPT_URL, params={"op": "list"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        rows = data.get("rows", [])

        if rows:
            # Process Data
            for row in rows:
                ts = row.get("Timestamp")
                row["Timestamp (SGT)"] = to_sg(ts)
                row.pop("Timestamp", None) # Hide original

            df = pd.DataFrame(rows)
            
            # Sort
            if "Timestamp (SGT)" in df.columns:
                df = df.sort_values("Timestamp (SGT)", ascending=False)

            st.dataframe(df, width='stretch', height=250)
        else:
            st.info("Sheet returned 0 rows.")
            
    except Exception as e:
        st.error(f"Failed to load sheet: {e}")
    
    return df

# Call the fragment
df = auto_refresh_sheet()
st.divider()

# ==============================================
# Charts
# ==============================================
# 1. Ensure Timestamp is datetime for the line chart
df['Timestamp (SGT)'] = pd.to_datetime(df['Timestamp (SGT)'])

# --- 1. Create Slicers (Filters) ---
st.subheader("Filters")

# Create three columns for filters
f1, f2 = st.columns(2)

with f1:
    all_locations = sorted(df['Location'].dropna().unique())
    selected_locations = st.multiselect("Filter by Location", all_locations, default=all_locations)

with f2:
    all_items = sorted(df['Item Category'].dropna().unique())
    selected_items = st.multiselect("Filter by Item", all_items, default=all_items)

    # Get min and max dates from the dataframe
    min_date = df['Timestamp (SGT)'].min().date()
    max_date = df['Timestamp (SGT)'].max().date()
    
    # Date Input (Slider)
    selected_date_range = st.date_input(
        "Filter by Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )

# --- 2. Apply Filters to Data ---
# Logic to handle if the user only clicks one date or a range
if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
    start_date, end_date = selected_date_range
else:
    start_date = end_date = selected_date_range[0]

# Combine all filters
mask = (
    (df['Location'].isin(selected_locations)) & 
    (df['Item Category'].isin(selected_items)) &
    (df['Timestamp (SGT)'].dt.date >= start_date) &
    (df['Timestamp (SGT)'].dt.date <= end_date)
)

plot_df = df.loc[mask]

# --- 2. Apply Filters to Data ---
# Filter the dataframe where the Location AND Item Category match the selections
plot_df = df[
    (df['Location'].isin(selected_locations)) & 
    (df['Item Category'].isin(selected_items))
]

st.divider()

# 2. Set up the columns
col1, mid, col2 = st.columns([10, 1, 10])

with col1:
    st.subheader("Items by Location")
    # Group by Location and count
    loc_counts = plot_df.groupby('Location').size().reset_index(name='Quantity')
    
    # Safely plot the Bar Chart
    if not loc_counts.empty:
        # 1. Build the chart object in Altair
        chart = alt.Chart(loc_counts).mark_bar().encode(
            x=alt.X('Location', axis=alt.Axis(labelAngle=-45)), # Rotate the labels
            y='Quantity',
            color=alt.Color('Location', legend=None)
        )
        
        # 2. Render it using st.altair_chart (NOT st.bar_chart)
        st.altair_chart(chart, width='stretch')
    else:
        st.info("No data to display.")

with mid:
    # --- FIXED: True Vertical Divider ---
    st.container()

with col2:
    st.subheader("Inventory over Time")
    
    # Sort and Group by Timestamp
    df_time = plot_df.sort_values('Timestamp (SGT)')
    time_counts = df_time.groupby('Timestamp (SGT)').size().reset_index(name='New Items')
    
    # Safely plot the Line Chart
    if not time_counts.empty:
        # Calculate the running total
        time_counts['Total Quantity'] = time_counts['New Items'].cumsum()
        st.line_chart(time_counts, x='Timestamp (SGT)', y='Total Quantity')
    else:
        st.info("No data to display.")

st.divider()


st.subheader("Location Summary")
# Ensure timestamps are actual datetime objects
plot_df['Timestamp (SGT)'] = pd.to_datetime(plot_df['Timestamp (SGT)'])

# Step 1 & 2: Sort by latest timestamp, group by item, get the first entry
latest_df = (
    plot_df.sort_values('Timestamp (SGT)', ascending=False)
    .groupby('Tag ID')
    .head(1)
)

# Group the cleaned, latest dataframe by Location
for location, items_at_location in latest_df.groupby('Location'):
    
    # Header for the location with item count
    st.subheader(f"{location} ({len(items_at_location)} items)")
    
    # Create a clean layout with 3 columns for the cards
    cols = st.columns(3)
    
    # Loop through the items and build the UI cards
    for index, (_, row) in enumerate(items_at_location.iterrows()):
        col = cols[index % 3] # Distribute cards evenly across columns
        
        with col:
            # Use an info box to act as a "card"
            st.info(
                f"**Tag ID:** {row['Tag ID']}\n\n"
                f"**Category:** {row['Item Category']}\n\n"
                f"**Last Seen:** {row['Timestamp (SGT)'].strftime('%H:%M:%S')}"
            )
            
    st.divider() # Visual break before the next location