# Kaderblick-Camera-API

A REST API for controlling USB cameras via web interface. This software provides an API for the Kaderblick-CameraController, allowing direct USB camera control through a modern web interface.

## Features

- 🎥 USB Camera Integration - Direct connection to USB cameras
- 🌐 RESTful API - Clean and simple API endpoints
- 🖥️ Web Interface - Beautiful, responsive web UI for camera control
- 📸 Image Capture - Capture and save images from the camera
- 🎬 Live Streaming - Real-time camera preview in the browser
- ⚙️ Camera Settings - Adjust resolution, FPS, and other camera parameters
- 🔌 Auto-detection - Automatically detect available cameras

## Requirements

- Python 3.8 or higher
- USB Camera connected to the device
- Linux, Windows, or macOS

## Installation

1. Clone the repository:
```bash
git clone https://github.com/mastercad/Kaderblick-Camera-API.git
cd Kaderblick-Camera-API
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Starting the Server

Run the application:
```bash
python app.py
```

The server will start on `http://0.0.0.0:5000`

### Accessing the Web Interface

Open your web browser and navigate to:
```
http://localhost:5000
```

The web interface provides:
- Real-time camera preview
- Capture button to take photos
- Camera status display
- Settings panel for adjusting camera parameters
- Connect/Disconnect controls

## API Endpoints

### Camera Status
```
GET /api/camera/status
```
Returns the current camera status and settings.

**Response:**
```json
{
  "connected": true,
  "camera_id": 0,
  "settings": {
    "width": 640,
    "height": 480,
    "fps": 30,
    "brightness": 128,
    "contrast": 128,
    "saturation": 128
  },
  "actual_width": 640,
  "actual_height": 480,
  "actual_fps": 30
}
```

### Connect Camera
```
POST /api/camera/connect
```
Connects to the USB camera.

**Response:**
```json
{
  "success": true,
  "message": "Camera connected successfully",
  "status": { ... }
}
```

### Disconnect Camera
```
POST /api/camera/disconnect
```
Disconnects from the camera.

**Response:**
```json
{
  "success": true,
  "message": "Camera disconnected"
}
```

### Capture Image
```
GET /api/camera/capture
```
Captures and saves an image from the camera.

**Response:**
```json
{
  "success": true,
  "filepath": "captured_images/capture_20260118_103000.jpg",
  "message": "Image captured successfully"
}
```

### Stream Frame
```
GET /api/camera/stream
```
Returns a single JPEG frame from the camera. Used for live preview.

**Response:** JPEG image data

### Get Settings
```
GET /api/camera/settings
```
Returns current camera settings.

**Response:**
```json
{
  "success": true,
  "settings": {
    "width": 640,
    "height": 480,
    "fps": 30,
    "brightness": 128,
    "contrast": 128,
    "saturation": 128
  }
}
```

### Update Settings
```
POST /api/camera/settings
Content-Type: application/json
```

Updates camera settings.

**Request Body:**
```json
{
  "width": 1280,
  "height": 720,
  "fps": 30
}
```

**Response:**
```json
{
  "success": true,
  "message": "Settings updated successfully",
  "settings": { ... }
}
```

### Get Available Cameras
```
GET /api/cameras/available
```
Lists all available camera devices.

**Response:**
```json
{
  "success": true,
  "cameras": [0, 1]
}
```

## Project Structure

```
Kaderblick-Camera-API/
├── app.py                  # Main Flask application
├── camera_controller.py    # Camera control logic
├── requirements.txt        # Python dependencies
├── README.md              # This file
├── .gitignore             # Git ignore patterns
└── captured_images/       # Directory for captured images (auto-created)
```

## Configuration

### Environment Variables

The application can be configured using environment variables:

- `FLASK_DEBUG` - Enable debug mode (default: `False`)
  ```bash
  export FLASK_DEBUG=True
  ```

- `FLASK_HOST` - Host to bind to (default: `0.0.0.0`)
  ```bash
  export FLASK_HOST=127.0.0.1
  ```

- `FLASK_PORT` - Port to listen on (default: `5000`)
  ```bash
  export FLASK_PORT=8080
  ```

- `ALLOWED_ORIGINS` - Comma-separated list of allowed CORS origins (default: `http://localhost:5000,http://127.0.0.1:5000`)
  ```bash
  export ALLOWED_ORIGINS=http://localhost:5000,http://example.com
  ```

### Camera Settings

The default camera settings can be modified in `camera_controller.py`:

```python
self.current_settings = {
    'width': 640,
    'height': 480,
    'fps': 30,
    'brightness': 128,
    'contrast': 128,
    'saturation': 128
}
```

To use a different camera device, modify the camera_id parameter when initializing the CameraController in `app.py`:

```python
camera = CameraController(camera_id=0)  # Change 0 to your camera ID
```

## Troubleshooting

### Camera not detected
- Ensure your USB camera is properly connected
- Check that the camera is not being used by another application
- Try running with different camera IDs (0, 1, 2, etc.)
- On Linux, check permissions: `sudo usermod -a -G video $USER`

### Dependencies issues
- Make sure OpenCV is properly installed: `pip install opencv-python`
- On Linux, you may need: `sudo apt-get install python3-opencv`

### Permission errors
- Captured images are saved to `captured_images/` directory
- Ensure the application has write permissions

## Development

### Running in Development Mode

The application runs in debug mode by default:
```bash
python app.py
```

### Running in Production

For production deployment, use a WSGI server like Gunicorn:
```bash
pip install gunicorn
export FLASK_DEBUG=False
export ALLOWED_ORIGINS=https://your-domain.com
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

**Security Recommendations for Production:**
- Set `FLASK_DEBUG=False`
- Configure `ALLOWED_ORIGINS` to specific domains
- Use HTTPS with a reverse proxy (nginx, Apache)
- Run behind a firewall
- Use authentication middleware if needed

## License

This project is open source and available under the MIT License.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

Created for the Kaderblick-CameraController project.