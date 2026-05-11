import requests
import time
import streamlit as st
from datetime import datetime
import pandas as pd
import yaml
from lib.rtdetr_or import load_model
import subprocess, platform
import multiprocessing

# =========================
# SEND TO UNO
# =========================
def compact_ts():
    # YYMMDDHHMMSS (Singapore local time on your PC)
    return datetime.now().strftime("%y%m%d%H%M%S")

def send_to_uno(uno_ip, uno_location, category: str, is_valid: bool) -> bool:
    params = {
        "cat": category,
        "location": uno_location,   # e.g. "location1"
        "ts": compact_ts(),
        "status": "valid" if is_valid else "invalid"
    }

    for attempt in range(2):
        try:
            r = requests.post(f"http://{uno_ip}/setItem", data=params, timeout=2)
            print(f"   -> UNO HTTP {r.status_code} | {r.text[:80]}")
            return r.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"   -> Send attempt {attempt+1} failed: {e}")
            time.sleep(0.2)
    return False

# def send_to_uno(uno_ip, uno_location, category: str, is_valid: bool) -> bool:
#     params = {
#         "cat": category,
#         "location": uno_location,   # e.g. "location1"
#         "ts": compact_ts(),
#         "status": "valid" if is_valid else "invalid"
#     }

#     for attempt in range(2):
#         try:
#             r = requests.get(f"http://{uno_ip}/setItem", params=params, timeout=2)
#             print(f"   -> UNO HTTP {r.status_code} | {r.text[:80]}")
#             return r.status_code == 200
#         except requests.exceptions.RequestException as e:
#             print(f"   -> Send attempt {attempt+1} failed: {e}")
#             time.sleep(0.2)
#     return False

# =========================
# Set Uno Mode
# =========================
# def set_uno_mode(uno_ip, mode: str) -> bool:
#     mode_mapping = {
#         "WRITE": "w",
#         "READ": "r"
#         }
#     m = mode_mapping.get(mode)
#     if m is None:
#         print(f"Invalid mode: {mode}")
#         return False
#     try:
#         r = requests.get(f"http://{uno_ip}/mode", params={"m": m}, timeout=3)
#         return (r.status_code == 200) and ("OK" in r.text)
#     except Exception as e:
#         print("set_uno_mode error:", e)
#         return False
def set_uno(uno_ip, mode: str, loc: str) -> bool:
    mode_mapping = {
        "WRITE": "w",
        "READ": "r"
        }
    m = mode_mapping.get(mode)
    if m is None:
        print(f"Invalid mode: {mode}")
        return False
    try:
        payload = {
            "m": m,
            "loc": loc
        }
        # Now sending as a POST body instead of a URL parameter
        r = requests.post(f"http://{uno_ip}/mode", data=payload, timeout=3)
        return (r.status_code == 200) and ("OK" in r.text)
    except Exception as e:
        print("Error:", e)
        return False


# =========================
# Get Uno Mode
# =========================
def get_uno_mode(uno_ip) -> str | None:
    try:
        r = requests.get(f"http://{uno_ip}/status", timeout=2)
        if r.status_code != 200:
            return None
        txt = r.text.strip()
        # expects "MODE=WRITE"
        if "MODE=" in txt:
            return txt.split("MODE=")[-1].strip()
        return txt
    except Exception as e:
        print("get_uno_mode error:", e)
        return None

# =========================
# read UNO serial logs (wirelessly from /logs endpoint)
# =========================
def read_uno_serial(uno_ip) -> str:
    try:
        # 1) read WITHOUT clearing first
        r = requests.get(f"http://{uno_ip}/logs", timeout=2)
        if r.status_code != 200:
            return ""

        text = r.text  # don't strip
        if text and text.strip():
            # 2) only clear if we actually got something
            requests.post(f"http://{uno_ip}/logs", data={"clear": "1"}, timeout=2)
            return text
        return ""
    except Exception as e:
        print("read_uno_serial error:", e)
        return ""
    
# =============================================
# trigger led
# =============================================
# def trigger_led(uno_ip, colour: str) -> bool:
#     try:
#         r = requests.get(f"http://{uno_ip}/{colour}", timeout=2)
#         # Returns True if successful, False if the Arduino sent an error code (like 404)
#         return r.status_code == 200
#     except requests.exceptions.RequestException as e:
#         print(f"Trigger LED error: {e}")
#         # Returns False if it couldn't connect or timed out
#         return False

# =============================================
# Streamlit utilities
# =============================================
# 1. Initialize the Session State DataFrame
def initialize_session_state():
    """Ensures all required keys exist in session state."""
    if 'config' not in st.session_state:
        with open(".streamlit_app/config.yaml", "r") as f:
            st.session_state.config = yaml.safe_load(f)

    if 'names' not in st.session_state:
        try:
            with open(".rtdetr_model/dataset.yaml", "r") as f:
                data = yaml.safe_load(f)
                raw_names = data.get('names', [])
                
                # Catch both dictionary and list formats
                if isinstance(raw_names, dict):
                    st.session_state.names = set(raw_names.values())
                else:
                    st.session_state.names = set(raw_names)
                    
        except FileNotFoundError:
            st.error("Class names file not found, check path.")
            st.session_state.names = set() # Safe fallback so the app doesn't crash

    if 'df' not in st.session_state:
        # Build your initial DataFrame from config
        data = []
        cfg = st.session_state.config
        for cat, devices in cfg.get('devices', {}).items():
            for dev in devices:
                data.append({**dev, "Category": cat})
        
        df = pd.DataFrame(data)
        if 'Status' not in df.columns:
            df.insert(0, 'Status', "⚪")
        st.session_state.df = df
        st.session_state.df['Status'] = df['IP'].apply(lambda x: "🟢" if x and ping_ip(x) else "🔴")

    if 'model' not in st.session_state:
        st.session_state.model = load_model()
        
    if "last_frame" not in st.session_state:
            st.session_state.last_frame = None
    if "last_detection" not in st.session_state:
        st.session_state.last_detection = (None, None) # (class_name, confidence)
    if "active_cam_id" not in st.session_state:
        st.session_state.active_cam_id = None
    
    if "serial_log" not in st.session_state:
        st.session_state.serial_log = []
    if "current_monitored_ip" not in st.session_state:
        st.session_state.current_monitored_ip = None

    if "cat_selection" not in st.session_state:
        st.session_state.cat_selection = None
    
    if "queue" not in st.session_state:
        st.session_state.queue = multiprocessing.Queue()
    
    if "logic_worker" not in st.session_state:
        # We pass the config and names explicitly because 
        # the background process can't see st.session_state
        config_data = st.session_state.config
        names_list = st.session_state.names
        model = st.session_state.model
        queue = st.session_state.queue
        # Create a separate process
        p = multiprocessing.Process(
            target=run_background_loop, 
            args=(config_data, names_list, model, queue), # Pass data here
            daemon=True # This kills the worker if the Streamlit server stops
        )
        p.start()
        st.session_state.logic_worker = p
        print("Background Logic Worker Started!")

def ping_ip(ip_address):
    """
    Pings an IP address and returns True only if a successful reply is received.
    """
    if not ip_address or ip_address == "None":
        return False

    # Determine command based on OS
    if platform.system().lower() == "windows":
        command = ["ping", "-n", "1", "-w", "1000", ip_address] # -w 1000 is a 1-second timeout
    else:
        command = ["ping", "-c", "1", "-W", "1", ip_address]

    try:
        # We don't use check=True because we want to manually inspect the output string
        result = subprocess.run(command, capture_output=True, text=True, timeout=2)
        
        output = result.stdout.lower()

        # --- THE CRITICAL FIX ---
        # 1. A real successful ping MUST have a "ttl=" value from the target.
        # 2. It MUST NOT contain the word "unreachable" (which comes from your local gateway).
        if "ttl=" in output and "unreachable" not in output:
            return True
        else:
            return False

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Catches timeouts or command execution failures
        return False

import yaml
import time
from lib.rtdetr_or import stream_and_infer
# Load your settings

def run_background_loop(config, valid_list, model, queue):
    print("Background Logic Engine Started. Press Ctrl+C to stop.")
    # Load model once
    while True:
        while not queue.empty():
            config = queue.get() # Update the local config with new data
            print("Worker: Config updated!")
        # Loop through your config to find linked devices
        for dev in config['devices']['esp32_cam']:
            if dev.get("Mode") == "ON" and dev.get("Tag"):
                # Run Inference
                _, best_class, _ = stream_and_infer(dev['IP'], model)
                
                # Find the linked Arduino
                target_id = dev["Tag"].split(" ")[0]
                target_uno = next((u for u in config['devices']['arduino_uno'] if u["ID"] == target_id), None)
                
                if target_uno and target_uno.get("Mode") == "WRITE" and best_class:
                    is_valid = best_class in valid_list
                    send_to_uno(target_uno['IP'], target_uno['Location'], best_class, is_valid)
        
        time.sleep(1) # Frequency of background check