import streamlit as st
from lib.utils import initialize_session_state

if __name__ == "__main__":

    initialize_session_state()

    dashboard_page = st.Page("pages/dashboard.py", title="Dashboard", icon=":material/visibility:")
    config_page = st.Page("pages/configuration.py", title="Settings", icon=":material/add_circle:")
    monitor_page = st.Page("pages/monitor.py", title="Live Feed", icon=":material/fit_screen:")

    pg = st.navigation([ 
        dashboard_page,
        monitor_page,
        config_page

        ])
    pg.run()