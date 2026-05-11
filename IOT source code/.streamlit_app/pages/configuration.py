import streamlit as st
import subprocess
import platform
import pandas as pd
import time

import yaml
from lib.utils import set_uno, send_to_uno, read_uno_serial, initialize_session_state, ping_ip
from lib.rtdetr_or import stream_and_infer

# Access the config directly from session state
initialize_session_state()

st.set_page_config(page_title="Settings", layout="wide")
st.title("Configuration Settings")
col1, col2 = st.columns([14,1])
with col1:
    st.subheader("Device Status")
with col2:
    refresh = st.button("⟳", help="Refresh Connectivity Status")
# ==========================================
# STATUS SECTION
# ==========================================
# Reference the session state
df = st.session_state.df

# 2. Logic to update status (Initial load or Manual Refresh)
# We check if we need to ping (if Status is still the default circle)
if refresh:
    with st.spinner("Checking connectivity..."):
        if 'IP' in df.columns:
            # Update the session state directly
            st.session_state.df['Status'] = df['IP'].apply(lambda x: "🟢" if x and ping_ip(x) else "🔴")
    if refresh:
        st.rerun()

# 3. The Data Editor
st.info("Refresh to update device connections.")

# We use st.session_state.df directly so edits/updates are reflected
edited_df = st.data_editor(
    st.session_state.df,
    width="stretch",
    hide_index=True,
    num_rows="dynamic",
    disabled=True, 
    key = "configuration"
)

# ==========================================
# UNO SERIAL MONITOR
# ==========================================
# ==========================================
# UNO SERIAL MONITOR & CONFIG
# ==========================================
def save_config_from_dataframe(df):
    new_config = {"devices": {"arduino_uno": [], "esp32_cam": []}}
    
    for _, row in df.iterrows():
        cat = row['Category']
        device_data = {
            "ID": row['ID'],
            "IP": row['IP'],
            "Mode": row['Mode'],
            "Location": row.get('Location', ''),
            "Tag": row.get('Tag', '')
        }
        new_config["devices"][cat].append(device_data)
    
    with open(".streamlit_app/config.yaml", "w") as f:
        yaml.dump(new_config, f, default_flow_style=False, sort_keys=False)
    
    st.session_state.config = new_config
    st.session_state.queue.put(new_config)

@st.fragment(run_every="1s")  # Automatically reruns this function every 1 second
def log_viewer_fragment(selected_ip):
    # 1. Fetch new data
    logs = read_uno_serial(selected_ip) 
    if logs:
        for line in logs.splitlines():
            line = line.strip()
            if line:
                st.session_state.serial_log.append(line)
        # Keep only the last 50
        st.session_state.serial_log = st.session_state.serial_log[-20:]
    log_output = "\n".join(st.session_state.serial_log)
    st.code(log_output, language='text')

st.subheader("Configure Devices")
with st.expander("Arduino Uno", expanded=True):
    # 1. Use the DataFrame as the single source of truth right from the start
    arduinos_df = st.session_state.df[st.session_state.df['Category'] == 'arduino_uno']

    if not arduinos_df.empty:
        # Create a dictionary mapping the "Display String" to the actual "ID"
        arduino_options = {f"{row['ID']} ({row['IP']})": row['ID'] for _, row in arduinos_df.iterrows()}
        esp32_data = st.session_state.config['devices'].get('esp32_cam', [])
        esp32_options = {f"{dev['ID']} ({dev['IP']})": dev for dev in esp32_data}
        esp32_options = {"None": None, **esp32_options} # add none selection
        
        # 2. Dropdown
        selected_display = st.selectbox(
            "Select Arduino to monitor:", 
            options=list(arduino_options.keys()),
            key="serial_monitor_select" 
        )
        
        # Get the clean ID from our dictionary mapping
        target_id = arduino_options[selected_display]
        
        # 3. Safely get the current row data using the clean ID
        matching_rows = arduinos_df[arduinos_df['ID'] == target_id]
        
        if not matching_rows.empty:
            current_row = matching_rows.iloc[0]
            selected_ip = current_row['IP']
            selected_id = current_row['ID']

            # Clear logs if we switched devices
            if st.session_state.current_monitored_ip != selected_ip:
                st.session_state.serial_log = []  
                st.session_state.current_monitored_ip = selected_ip

            # --- 4. The Edit Form ---
            with st.form("edit_device_form", clear_on_submit=False):    
                col1, col2 = st.columns(2)
                with col1:
                    new_ip = st.text_input("IP Address", value=current_row['IP'])
                    new_location = st.text_input("Location", value=current_row.get('Location', ''))
                with col2:
                    new_mode = st.selectbox("Operating Mode", ["READ", "WRITE"], 
                                            index=0 if current_row['Mode'] == "READ" else 1)
                    options = list(esp32_options.keys())
                    new_tag = st.selectbox("Link to ESP32_Cam Tag:", options=options, 
                                           index=options.index(current_row['Tag'])if current_row['Tag'] in options else 0)

                submit_btn = st.form_submit_button("Update & Sync Device")
                if submit_btn:
                    with st.spinner(f"Syncing {new_mode} mode to Arduino..."):
                        # 1. Find the index for our target Camera
                        target_idx = st.session_state.df.index[st.session_state.df['ID'] == target_id].tolist()[0]
                        
                        # Remember the old tag so we can unlink the previous Arduino if needed
                        old_tag = st.session_state.df.at[target_idx, 'Tag']

                        # --- 2. UPDATE TARGET Arduino ---
                        st.session_state.df.at[target_idx, 'IP'] = new_ip
                        st.session_state.df.at[target_idx, 'Location'] = new_location
                        st.session_state.df.at[target_idx, 'Tag'] = new_tag
                        st.session_state.df.at[target_idx, 'Mode'] = new_mode

                        # We always want to save since we updated the arduino's base info
                        save_config = False 

                        # --- 4. LINK THE NEW ARDUINO ---
                        new_esp32_id = str(new_tag).split(" ")[0] if new_tag != "None" else "None"
                        new_esp32_ip = str(new_tag).split(" ")[1].replace("(", "").replace(")", "") if new_tag != "None" else "None"
                        # print(new_arduino_ip)

                        if new_esp32_id != "None" and new_esp32_ip != "None":
                            new_ard_mask = (st.session_state.df['Category'] == 'esp32_cam') & ((st.session_state.df['IP'] == new_esp32_ip) | (st.session_state.df['ID'] == new_esp32_id))
                            
                            if new_ard_mask.any():
                                new_ard_idx = st.session_state.df[new_ard_mask].index[0]
                                # Write the Arduino's IP to the NEW ESP32's Tag column (Fixed uppercase 'Tag')
                                st.session_state.df.at[new_ard_idx, 'Tag'] = f"{target_id} ({new_ip})"
                            else:
                                st.warning(f"Warning: Could not find an ESP32 Cam matching '{new_tag}' to apply the reverse tag.")
                        
                        if not ping_ip(new_esp32_ip) and new_esp32_ip != "None":
                            st.warning(f"Selected ESP32 Cam {new_tag} is offline")
                            print(f"Selected ESP32 Cam {new_tag} is offline")
                        elif not ping_ip(selected_ip):
                            st.warning(f"Selected Arduino {target_id} ({new_ip}) is offline")
                            print(f"Selected Arduino {target_id} ({new_ip}) is offline")
                        else:
                            message = f"Selected Camera {new_tag} is online..." if new_tag != "None" else f"Selected Camera is None..."
                            st.info(message)
                            mode = set_uno(selected_ip, new_mode, new_location)
                            if mode:
                                st.success(f"Arduino {new_tag} mode changed to {new_mode}")
                                save_config = True
                            else:
                                st.warning(f"Warning: Failed to change Arduino {selected_id} ({selected_ip}) to {new_mode} mode.")
                        
                        # --- 5. SAVE AND REFRESH ---
                        if save_config:
                            save_config_from_dataframe(st.session_state.df)
                            st.success(f"Successfully linked {target_id} <---> {new_tag}")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.warning("Failed to save new configuration")

            # --- 5. Serial Monitor Visuals ---
            # Usage in your app:
            log_viewer_fragment(selected_ip)
            
        else:
            st.error("Error: Could not locate device data.")
            
    else:
        st.warning("No Arduinos found in configuration. Add one in the Settings tab.")

# --- ESP32 Cam Section ---
with st.expander("ESP32 Camera", expanded=True):
    # 1. Setup Data Sources
    arduino_data = st.session_state.config['devices'].get('arduino_uno', [])
    arduino_options = {f"{dev['ID']} ({dev['IP']})": dev for dev in arduino_data}
    arduino_options = {"None": None, **arduino_options} # add none selection
    
    esp32_df = st.session_state.df[st.session_state.df['Category'] == 'esp32_cam']

    if not esp32_df.empty:
        esp32_mapping = {f"{row['ID']} ({row['IP']})": row for _, row in esp32_df.iterrows()}
        
        selected_display = st.selectbox("Select ESP32 Cam:", 
                                        options=list(esp32_mapping.keys()), 
                                        key="cam_select")
        
        current_row = esp32_mapping[selected_display]
        # print(current_row)
        target_id = current_row['ID']
        selected_ip = current_row['IP']
        
        # --- UPDATE SECTION ---
        with st.form("update_form", clear_on_submit=False):
            col1, col2 = st.columns(2)
            with col1:
                new_ip = st.text_input("IP Address", value=current_row['IP'])
                new_location = st.text_input("Location", value=current_row.get('Location', ''))
            with col2:
                new_mode = st.selectbox("Operating Mode", ["ON", "OFF"], 
                                            index=0 if current_row['Mode'] == "On" else 1)
                # Use index to match existing tag if possible
                options = list(arduino_options.keys())
                current_tag = current_row.get('Tag', options[0])
                new_tag = st.selectbox("Link to Arduino Tag:", options=list(arduino_options.keys()),
                                        index=options.index(current_tag) if current_tag in options else 0)
            
            submit_btn = st.form_submit_button("Update & Sync Device")

            if submit_btn:
                # 1. Find the index for our target Camera
                target_idx = st.session_state.df.index[st.session_state.df['ID'] == target_id].tolist()[0]
                
                # Remember the old tag so we can unlink the previous Arduino if needed
                old_tag = st.session_state.df.at[target_idx, 'Tag']

                # --- 2. UPDATE TARGET CAMERA ---
                st.session_state.df.at[target_idx, 'IP'] = new_ip
                st.session_state.df.at[target_idx, 'Location'] = new_location
                st.session_state.df.at[target_idx, 'Tag'] = new_tag
                st.session_state.df.at[target_idx, 'Mode'] = new_mode

                # We always want to save since we updated the camera's base info
                save_config = False 

                # --- 4. LINK THE NEW ARDUINO ---
                new_arduino_id = str(new_tag).split(" ")[0] if new_tag != "None" else "None"
                new_arduino_ip = str(new_tag).split(" ")[1].replace("(", "").replace(")", "") if new_tag != "None" else "None"
                # print(new_arduino_ip)
                if new_arduino_id != "None" and new_arduino_ip != "None":
                    new_ard_mask = (st.session_state.df['Category'] == 'arduino_uno') & ((st.session_state.df['IP'] == new_arduino_ip) | (st.session_state.df['ID'] == new_arduino_id))
                    
                    if new_ard_mask.any():
                        new_ard_idx = st.session_state.df[new_ard_mask].index[0]
                        # Write the Camera's IP to the NEW Arduino's Tag column (Fixed uppercase 'Tag')
                        st.session_state.df.at[new_ard_idx, 'Tag'] = f"{target_id} ({new_ip})"
                    else:
                        st.warning(f"Warning: Could not find an Arduino matching '{new_tag}' to apply the reverse tag.")

                if not ping_ip(new_arduino_ip) and new_arduino_ip != "None":
                    st.warning(f"Selected Arduino {new_tag} is offline") 
                elif not ping_ip(selected_ip):
                    st.warning(f"Selected ESP32 Cam {target_id} ({selected_ip}) is offline")
                
                else:
                    message = f"Selected Arduino {new_tag} is online..." if new_tag != "None" else f"Selected Arduino set as None..."
                    st.info(message)
                    save_config = True
                
                # --- 5. SAVE AND REFRESH ---
                if save_config:
                    save_config_from_dataframe(st.session_state.df)
                    st.success(f"Successfully linked {target_id} <---> {new_tag}")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Failed to save new configuration")

        # --- STREAMING & INFERENCE SECTION ---
        current_row = esp32_mapping[selected_display]
        target_id = current_row['ID']
        if st.session_state.active_cam_id != target_id:
            st.session_state.last_frame = None
            st.session_state.last_detection = (None, None)
            st.session_state.active_cam_id = target_id


        col1, col2 = st.columns([15,3])
        with col1:
            is_streaming = st.toggle("Stream Camera (Live Inference)", value=False)
        with col2:
            test_tag = st.button("Tag Object")
        
        frame_box = st.empty()
        status_box = st.empty() 

        if st.session_state.last_frame is not None:
            det_name, det_conf = st.session_state.last_detection
            caption = f"Live: {det_name} ({det_conf:.2f})" if det_name else "Live: No Detection"
            frame_box.image(st.session_state.last_frame, caption=caption, width="content")

        if is_streaming:
            # Retrieve desired class names
            valid_items_list = sorted(list(st.session_state.names))

            # Get the Arduino associated with the currently selected ESP32's tag
            current_tag = current_row.get('Tag')
            if current_tag in arduino_options:
                target_uno = arduino_options[current_tag]
                
                # Use the ESP32's own IP to get the frame
                rgb_frame, best_class_name, best_confidence = stream_and_infer(current_row['IP'], st.session_state.model)
                
                if rgb_frame is not None:
                    st.session_state.last_frame = rgb_frame
                    st.session_state.last_detection = (best_class_name, best_confidence)

                    if best_class_name is None:
                        frame_box.image(rgb_frame, caption=f"Live: No Detection", width='content')
                    else:
                        frame_box.image(rgb_frame, caption=f"Live: {best_class_name} ({best_confidence:.2f})", width="content")
                        if best_class_name in valid_items_list:
                            is_valid = True
                            status_box.info("Valid class detected...")
                            if test_tag:
                                success = send_to_uno(target_uno['IP'], target_uno['Location'], best_class_name, is_valid)
                                if success:
                                    status_box.success(f"Sucessfully sent '{best_class_name}' to Arduino ({target_uno['IP']})!")
                        else:
                            status_box.warning(f"Invalid class detected...")
                else:
                    status_box.error("Failed to reach ESP32-CAM. Check IP/Connection.")
                
                # Rerun logic for the loop
                time.sleep(0.1)
                st.rerun()
            else:
                st.warning("Please link this camera to an Arduino Tag first.")

device_categories = st.session_state.config.get('devices', [])
with st.expander("Add New Devices", expanded=True):
    st.info("Register a new device to the system. Required fields are ID and IP address.")
    with st.container(border=True):
        st.selectbox(
            "Category", 
            options=list(device_categories.keys()),
            key ="cat_selection"
        )
        new_category = st.session_state.cat_selection

    with st.form("add_device_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            new_id = st.text_input("ID (e.g. camera_002)", placeholder="Optional")
            # new_category = st.selectbox("Category", options=list(device_categories.keys()))
            new_ip = st.text_input("IP Address (e.g. 192.168.1.100)", placeholder="Required")
            new_location = st.text_input("Location (e.g. Hub, Sorting)", placeholder="Required")
        with col2:
            new_tag = st.text_input("Tag (IP address of receiver)", value=None, placeholder="Optional")
            mode_options = ["READ", "WRITE"] if new_category == 'arduino_uno' else ["ON", "OFF"]
            new_mode = st.selectbox("Mode",
                                    options=mode_options, 
                                    index=0,
                                    key=f"mode_select_{new_category}"
                                    )
        
        add_btn = st.form_submit_button("Register Device")
        if add_btn:
            is_valid = True  # Assume valid until proven otherwise
            
            # --- 1. Validation Logic ---
            if new_category == 'arduino_uno':
                if not new_id or not new_ip or not new_location:
                    st.error("Arduino Uno: ID, IP Address and Location are required!")
                    is_valid = False
            elif new_category == 'esp32_cam':
                if not new_id or not new_ip or not new_location:
                    st.error("ESP32 Camera: ID, IP Address and Location are required!")
                    is_valid = False

            # --- 2. Saving Logic (Runs for ALL categories if valid) ---
            if is_valid:
                new_data = {
                    'Status': "⚪",
                    'ID': new_id,
                    'Category': new_category,
                    'IP': new_ip,
                    'Location': new_location,
                    'Tag': new_tag if new_tag else "None",
                    'Mode': new_mode
                }

                # Update DataFrame
                new_row_df = pd.DataFrame([new_data])
                st.session_state.df = pd.concat([st.session_state.df, new_row_df], ignore_index=True)
                
                # Save to YAML
                try:
                    save_config_from_dataframe(st.session_state.df)
                    st.success(f"Successfully registered {new_id} ({new_category})!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save configuration: {e}")

# --- Streamlit UI for Deletion ---
with st.expander("Remove Devices", expanded=False):
    if 'df' in st.session_state and not st.session_state.df.empty:
        # Create a mapping dictionary for the selectbox
        delete_options = {f"{row['ID']} ({row['Category']} - {row['IP']})": row['ID'] 
                          for _, row in st.session_state.df.iterrows()}
        
        device_to_delete_label = st.selectbox("Select Device to Remove:", 
                                              options=list(delete_options.keys()))
        
        target_delete_id = delete_options[device_to_delete_label]

        st.info(f"This will permanently remove {target_delete_id} from your configuration.")
        
        if st.button("Confirm Deletion", type="primary"):
            # 1. Filter out the target ID from the DataFrame
            st.session_state.df = st.session_state.df[st.session_state.df['ID'] != target_delete_id]
            st.session_state.df.reset_index(drop=True, inplace=True)
            
            # 2. Rebuild and save the YAML file
            try:
                save_config_from_dataframe(st.session_state.df)
                st.success(f"Device {target_delete_id} has been removed.")
                
                # Small delay so the user sees the success message before reload
                import time
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update configuration file: {e}")
    else:
        st.info("No devices currently registered in the system.")