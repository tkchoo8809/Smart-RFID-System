import streamlit as st
from lib.utils import send_to_uno, read_uno_serial, initialize_session_state, ping_ip
from lib.rtdetr_or import stream_and_infer

# Access the config directly from session state
initialize_session_state()

st.set_page_config(page_title="Monitor", layout="wide")
st.title("Live Feed")

# Data display
st.subheader("Device Status")
display_df = st.session_state.df
edited_df = st.data_editor(
    display_df,
    width='stretch',
    hide_index=True,
    num_rows="dynamic",
    disabled=True,  # Enabled Category so new rows can be assigned a type
    key = "live_feed"
)
df = st.session_state.df

# --- FRAGMENT DEFINITION (Define ONCE outside the loop) ---
@st.fragment(run_every="2s")
def render_cam_stream(cam_ip, target_uno):
    # Stream and infer
    rgb_frame, best_class, best_conf = stream_and_infer(cam_ip, st.session_state.model)
    mode = target_uno['Mode'] if target_uno != "None" else "None"
    if rgb_frame is not None:
        if best_class:
            st.image(rgb_frame, caption=f"Live: {best_class} ({best_conf:.2f})", width='content')
            print("target_uno", target_uno)
            # Only send to UNO if there's an actual linked Arduino
            if mode is not None and mode == 'WRITE':
                is_valid = True if best_class in st.session_state.names else False
                if is_valid:
                    st.info(f"Valid object detected {best_class}.")
                else:
                    st.info(f"Invalid object detected {best_class}.")
                    
                # success = send_to_uno(target_uno['IP'], target_uno['Location'], best_class, is_valid)
                # if success:
                #     st.success(f"Successfully sent '{best_class}' to Arduino ({target_uno['IP']})!")    
            else:
                message = f"Warning: No Arduino connected." if mode == "None" else f"Warning: Connected Arduino {target_uno} is in {mode}." 
                st.warning(message)
        else:
            st.image(rgb_frame, caption="Live: No Detection", width='content')

# --- LOOPING THROUGH DEVICES ---
esp32_data = st.session_state.config.get('devices', {}).get('esp32_cam', [])
arduino_data = st.session_state.config.get('devices', {}).get('arduino_uno', [])

def has_valid_tag(device):
    """Checks if a device has a valid, non-empty Tag."""
    tag = device.get("Tag")
    # Returns False if tag is None, "", "None", "null", etc.
    if not tag or str(tag).strip().lower() in ["none", "null", ""]:
        return False
    return True

# --- 1. ESP32 Cams WITH a Tag ---
esp32_with_tag = [dev for dev in esp32_data if has_valid_tag(dev)]
print("esp32_with_tag:", esp32_with_tag)

# --- 2. ESP32 Cams WITHOUT a Tag ---
esp32_no_tag = [dev for dev in esp32_data if not has_valid_tag(dev)]
print("esp32_no_tag", esp32_no_tag)

# --- 3. Arduinos WITHOUT a Tag ---
arduino_no_tag = [dev for dev in arduino_data if not has_valid_tag(dev)]
print("arduino_no_tag", arduino_no_tag)

@st.fragment(run_every="1s")
def log_viewer_fragment(selected_ip):
    # Initialize the dictionary in session state if it doesn't exist
    if "device_logs" not in st.session_state:
        st.session_state.device_logs = {}
    
    # Initialize the specific list for THIS IP if it's new
    if selected_ip not in st.session_state.device_logs:
        st.session_state.device_logs[selected_ip] = []

    # 1. Fetch new data
    new_data = read_uno_serial(selected_ip) 
    
    if new_data:
        for line in new_data.splitlines():
            line = line.strip()
            if line:
                st.session_state.device_logs[selected_ip].append(line)
        
        # Keep only the last 20 lines for this specific device
        st.session_state.device_logs[selected_ip] = st.session_state.device_logs[selected_ip][-20:]
    
    # 2. Render only this device's logs
    log_output = "\n".join(st.session_state.device_logs[selected_ip])
    st.code(log_output, language="text")

# --- 1. LINKED STATIONS (Cam + Tag) ---
if esp32_with_tag:
    st.header("Write Stations")
    for index, dev in enumerate(esp32_with_tag):
        cam_id, cam_ip, cam_mode, cam_tag = dev.get("ID"), dev.get("IP"), dev.get("Mode"), dev.get("Tag")
        
        # Get the linked Arduino safely
        target_id = cam_tag.split(" ")[0]
        # print("target_id:", target_id)
        target_uno = next((uno for uno in arduino_data if uno.get("ID") == target_id), None)
        st.subheader(f"Station {index + 1}:")
        target_mode = target_uno.get("Mode") if target_uno != None else "None"
        # print(f"Mode: {target_mode}")
        col1, col2, col3 = st.columns([5, 1, 5])
        with col1: # Show Stream
            st.markdown(f"**{cam_id} ({cam_ip})**")
            if cam_mode == 'ON':
                if target_mode == "WRITE":
                    render_cam_stream(cam_ip, target_uno)
                else:
                    st.warning(f"Arduino is not in WRITE.")
            else:
                st.info("Camera is offline.")
                
        with col3: # Show Logs
            st.markdown(f"**{cam_tag}**")
            if cam_mode == 'ON':
                if target_uno is not None:
                    log_viewer_fragment(target_uno['IP'])
                else:
                    st.warning("Tagged Arduino not found...")
            else:
                st.info("Camera is offline.")
    st.divider()

# --- 2. UNLINKED CAMERAS (Cam, No Tag) ---
if esp32_no_tag:
    st.header("Cameras")
    for index, dev in enumerate(esp32_no_tag):
        cam_id, cam_ip, cam_mode = dev.get("ID"), dev.get("IP"), dev.get("Mode")
        
        st.subheader(f"Camera {index + 1}:")
        st.markdown(f"{cam_id} ({cam_ip})")
        # We don't need 3 columns here, just show the stream
        if cam_mode == 'ON':
            render = render_cam_stream(cam_ip, target_uno=None)
        else:
            st.info("Camera is offline.")

    st.divider()

# --- 3. UNLINKED ARDUINOS (Arduino, No Tag) ---
if arduino_no_tag:
    st.header("Read Stations")
    for index, uno in enumerate(arduino_no_tag):
        uno_id, uno_ip, uno_mode = uno.get("ID"), uno.get("IP"), uno.get("Mode")
        
        st.subheader(f"Controller {index + 1}:")
        st.markdown(f"{uno_id} ({uno_ip})")

        verify = ping_ip(uno_ip)
        if verify:
            log_viewer_fragment(uno_ip)
        else:
            st.error(f"Device {uno_id} ({uno_ip}) is unreachable.")
    
    st.divider()