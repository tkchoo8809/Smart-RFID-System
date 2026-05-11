import threading
import cv2
from ultralytics import RTDETR
import supervision as sv
import torch
import threading

# --- Threaded Stream Handler ---
class CameraStream:
    def __init__(self, url, name):
        self.cap = cv2.VideoCapture(url)
        self.name = name
        self.frame = None
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        
    def start(self):
        self.thread.start()
        return self

    def _update(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                self.frame = frame
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0) # Restart if stream drops

    def read(self):
        return self.frame

    def stop(self):
        self.running = False
        self.cap.release()

def infer(image, model):
    # 1. Run inference
    results = model.predict(image)[0]
    
    # 2. Convert to Supervision Detections
    detections = sv.Detections.from_ultralytics(results)
    
    if len(detections) == 0:
        return image, None, None

    # --- Logic to find the highest confidence detection ---
    # Find the index of the maximum confidence score
    max_idx = detections.confidence.argmax()
    detections = detections[[max_idx]]  # Keep only the best detection

    # Extract the class ID and the actual name
    best_class_id = detections.class_id[max_idx]
    best_class_name = results.names[best_class_id]
    best_confidence = detections.confidence[max_idx]
    # ------------------------------------------------------

    # 3. Create Annotators
    box_annotator = sv.BoxAnnotator()
    label_annotator = sv.LabelAnnotator()

    # 4. Generate labels
    labels = [
        f"{results.names[class_id]} {confidence:.2f}"
        for class_id, confidence in zip(detections.class_id, detections.confidence)
    ]

    # 5. Annotate
    annotated_image = box_annotator.annotate(
        scene=image.copy(), 
        detections=detections
    )
    annotated_image = label_annotator.annotate(
        scene=annotated_image, 
        detections=detections, 
        labels=labels
    )
    # 6. Plot
    # sv.plot_image(annotated_image)

    return annotated_image, best_class_name, best_confidence

def train(model, dataset_dir, output_dir='train_logs', model_path='finetuned_rfdetr.pt'):
    # Parameters: https://docs.ultralytics.com/usage/cfg/#train-settings
    model.train(
        data = dataset_dir,  # Path to your dataset in YOLO format
        epochs = 50, 
        imgsz = 1024, 
        batch = 8,
        device = 0 if torch.cuda.is_available() else 'cpu',
        project = output_dir,
        amp = True  # Use Automatic Mixed Precision for faster training on compatible hardware
    )
    model.save(model_path)
    print(f"Training complete! Model saved to {model_path}")
    
def stream_and_infer(target_ip, model):
    # ESP32-CAM usually serves stream at :81/stream or :80/capture
    # Note: :81/stream is a multipart MJPEG, :80/capture is a single JPG.
    # For a single frame inference, /capture is often more stable.
    stream_url = f"http://{target_ip}:81/stream"
    
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        return None, None, 0
        
    ret, frame = cap.read()
    cap.release() 

    if not ret or frame is None:
        return None, None, 0

    # Perform Inference
    annotated_image, best_class_name, best_confidence = infer(frame, model)

    if annotated_image is not None:
        rgb_frame = cv2.cvtColor(annotated_image, cv2.COLOR_BGR2RGB)
    else:
        rgb_frame = None
        
    return rgb_frame, best_class_name, best_confidence

def load_model():
    return RTDETR(".rtdetr_model/finetuned_augmented_latest_rfdetr.pt")