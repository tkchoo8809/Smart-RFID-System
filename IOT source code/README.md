# Smart Digital Supply Chain with IoT

A comprehensive IoT monitoring system that combines Arduino Uno with RC522 RFID models, ESP32-Cam MB with OV2640 camera and real-time smart object tagging with RT-DETR (Real-Time DETR) via a locally hosted Streamlit-based dashboard.

## Project Overview

This system enables:
- **Real-time video monitoring** from ESP32 camera modules
- **AI-powered object detection** using RT-DETR model
- **Device management** of multiple Arduino and ESP32 IoT devices
- **Interactive dashboard** for monitoring and configuration
- **Data logging** integration with Google Sheets serving as database
- **Live feed visualization** with detection overlays and serial monitor outputs

## Project Structure

```
IoT project/
├── .streamlit_app/                              # Main Streamlit web application
│   ├── app.py                                   # Entry point
│   ├── config.yaml                              # Device configuration
│   ├── lib/
│   │   ├── rtdetr_or.py                         # Object detection model integration
│   │   ├── utils.py                             # Utility functions
│   │   └── __pycache__/
│   └── pages/
│       ├── dashboard.py                         # Main dashboard page
│       ├── configuration.py                     # Device configuration page
│       ├── monitor.py                           # Live feed monitoring
│       └── __pycache__/
├── .arduino_sourcecode/                         # Arduino/ESP32 firmware
│   ├── CameraWebServer/                         # ESP32 camera server firmware
│   │   └── CameraWebServer.ino
│   └── project_group_arduino/                   # Arduino device firmware
│       └── project_group_arduino.ino
├── .rtdetr_model/                               # Pre-trained RT-DETR models
│   ├── finetuned_rfdetr.pt
│   ├── finetuned_augmented_latest_rfdetr.pt
│   ├── coco_dataset.yaml                        # Yaml of COCO names
│   └── dataset.yaml                             # Yaml of valid names
├── requirements.txt                             # Python dependencies
└── README.md                                    # Readme information
```

## Features

### Dashboard Pages

1. **Dashboard** - Main monitoring interface
   - Real-time device status
   - Detection history and statistics
   - Google Sheets data logging
   - Event visualization with Altair charts

2. **Live Feed** - Real-time video monitoring
   - Live stream from ESP32 camera
   - Object detection overlay
   - Confidence score display

3. **Settings** - Device configuration
   - Device IP
   - Device ID
   - Location
   - Mode configuration (READ/WRITE | ON/OFF)
   - Device tagging (Arduino Uno <---> ESP32 Camera)

## Hardware Requirements

- **ESP32-Cam-MB** - For video capture and streaming (OV640)
- **Arduino Uno WiFi Rev 2** - For sensor reading/control (RFID)
- **Network Connection** - Same WiFi access for device communication

## Software Requirements

- Python 3.9 or higher
- See `requirements.txt` for Python dependencies

## Installation

### 1. Clone/Setup the Project

```bash
cd "IoT project"
```

### 2. Create Virtual Environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Devices

Edit `.streamlit_app/config.yaml` to add your device IPs and locations:
Devices can be added via the Settings page which updates the `config.yaml` file.

```yaml
devices:
  arduino_uno:
    - ID: arduino_uno_001
      IP: 192.168.x.x
      Mode: WRITE
      Location: Location 1
  esp32_cam:
    - ID: esp32_cam_001
      IP: 192.168.x.x
      Mode: 'ON'
      Location: Location 1
```

### 5. Run the Application

```bash
cd .streamlit_app
streamlit run app.py
```

The dashboard will be available at `http://localhost:8501`

## Configuration

### Device Configuration (config.yaml)

- **IP**: Device network IP address
- **Mode**: 
  - Arduino: `WRITE` (send data), `READ` (receive data)
  - ESP32: `ON` (streaming enabled), `OFF` (disabled)
- **Location**: Physical location identifier
- **Tag**: Associated device (e.g., camera linked to sensor)

### Model Configuration

The system supports RT-DETR object detection models:
- Default models in `.rtdetr_model/`
- Models are loaded dynamically in `lib/rtdetr_or.py`
- Supports COCO dataset format

## API Endpoints

### Arduino Endpoints

- `GET /setItem` - Send detection result to Arduino
  - Parameters: `cat`, `location`, `ts`, `status`
- `GET /mode` - Set device mode (READ/WRITE)
  - Parameters: `m` (r/w)

### ESP32 Camera

Change the image quality via `http://<ESP32_IP>`.
- Stream available at: `http://<ESP32_IP>:81/stream`

## Key Libraries

| Library | Purpose |
|---------|---------|
| **streamlit** | Web dashboard framework |
| **ultralytics** | RT-DETR object detection |
| **opencv-python** | Image/video processing |
| **supervision** | Detection visualization |
| **torch** | Deep learning framework |
| **pandas** | Data manipulation |
| **requests** | HTTP communication |
| **pyyaml** | Configuration file handling |

## Usage

### Access Dashboard Features

1. **Dashboard Tab**: View detection history and real-time stats
2. **Live Feed Tab**: Monitor active camera streams
3. **Settings Tab**: Configure devices and model parameters

### Monitor Live Stream

The system captures video from the ESP32 camera, runs RT-DETR object detection in real-time, and displays results with confidence scores.

### Data Logging

Detections are logged to Google Sheets for historical tracking and analysis. Configuration in `pages/dashboard.py`.

## Troubleshooting

### Camera Connection Issues
- Verify ESP32 IP address in `config.yaml`
- Ensure ESP32 is powered and on the same network
- Check camera firmware is flashed correctly

### Detection Not Working
- Verify RT-DETR model files exist in `.rtdetr_model/`
- Check CUDA/GPU availability for faster inference
- Ensure input image format matches model requirements

### Arduino Connection Issues
- Verify Arduino IP address and network connectivity
- Check serial/HTTP communication protocol compatibility
- Ensure correct mode (READ/WRITE) is configured

## Performance Optimization

- **GPU Acceleration**: CUDA enabled models for faster inference
- **Threading**: Asynchronous camera stream handling
- **Caching**: Session state management in Streamlit

## Future Enhancements

- Hosting on cloud server
- Custom model training
- Advanced data analytics
- Mobile app integration
- Cloud backup for detection logs

## License

[Specify your license here]

## Support

For issues or questions, please refer to the project documentation or contact the development team.

---

**Last Updated**: February 2026
