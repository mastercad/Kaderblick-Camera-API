"""
Kaderblick Camera API - Main Application
Provides REST API endpoints for USB camera control via web interface
"""
from flask import Flask, jsonify, request, Response, send_file, render_template_string
from flask_cors import CORS
import logging
import os
from camera_controller import CameraController

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for web interface

# Initialize camera controller
camera = CameraController(camera_id=0)

# HTML template for web interface
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kaderblick Camera Controller</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        
        .header p {
            font-size: 1.1em;
            opacity: 0.9;
        }
        
        .content {
            padding: 30px;
        }
        
        .status-panel {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 30px;
            border-left: 5px solid #667eea;
        }
        
        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #dee2e6;
        }
        
        .status-item:last-child {
            border-bottom: none;
        }
        
        .status-label {
            font-weight: 600;
            color: #495057;
        }
        
        .status-value {
            color: #667eea;
            font-weight: 500;
        }
        
        .status-connected {
            color: #28a745;
        }
        
        .status-disconnected {
            color: #dc3545;
        }
        
        .camera-view {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .camera-preview {
            width: 100%;
            max-width: 640px;
            height: auto;
            border-radius: 10px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            background: #000;
        }
        
        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .btn {
            padding: 15px 25px;
            font-size: 1.1em;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-success {
            background: #28a745;
            color: white;
        }
        
        .btn-danger {
            background: #dc3545;
            color: white;
        }
        
        .btn-info {
            background: #17a2b8;
            color: white;
        }
        
        .settings-panel {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        .settings-panel h3 {
            margin-bottom: 20px;
            color: #495057;
        }
        
        .setting-group {
            margin-bottom: 20px;
        }
        
        .setting-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #495057;
        }
        
        .setting-group input[type="range"] {
            width: 100%;
            height: 6px;
            border-radius: 3px;
            background: #dee2e6;
            outline: none;
        }
        
        .setting-group input[type="range"]::-webkit-slider-thumb {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #667eea;
            cursor: pointer;
        }
        
        .setting-value {
            display: inline-block;
            margin-left: 10px;
            color: #667eea;
            font-weight: 600;
        }
        
        .message {
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            display: none;
        }
        
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }
            
            .controls {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎥 Kaderblick Camera Controller</h1>
            <p>USB Camera Control Interface</p>
        </div>
        
        <div class="content">
            <div class="status-panel">
                <h2 style="margin-bottom: 15px; color: #495057;">Camera Status</h2>
                <div class="status-item">
                    <span class="status-label">Connection Status:</span>
                    <span class="status-value" id="connectionStatus">Checking...</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Camera ID:</span>
                    <span class="status-value" id="cameraId">-</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Resolution:</span>
                    <span class="status-value" id="resolution">-</span>
                </div>
                <div class="status-item">
                    <span class="status-label">FPS:</span>
                    <span class="status-value" id="fps">-</span>
                </div>
            </div>
            
            <div class="camera-view">
                <img id="cameraPreview" class="camera-preview" src="/api/camera/stream" alt="Camera Preview">
            </div>
            
            <div class="controls">
                <button class="btn btn-primary" onclick="connectCamera()">Connect Camera</button>
                <button class="btn btn-success" onclick="captureImage()">Capture Image</button>
                <button class="btn btn-info" onclick="refreshStatus()">Refresh Status</button>
                <button class="btn btn-danger" onclick="disconnectCamera()">Disconnect</button>
            </div>
            
            <div class="settings-panel">
                <h3>Camera Settings</h3>
                
                <div class="setting-group">
                    <label for="width">Width: <span class="setting-value" id="widthValue">640</span></label>
                    <input type="range" id="width" min="320" max="1920" step="160" value="640" 
                           oninput="updateSettingValue('width', this.value)">
                </div>
                
                <div class="setting-group">
                    <label for="height">Height: <span class="setting-value" id="heightValue">480</span></label>
                    <input type="range" id="height" min="240" max="1080" step="120" value="480"
                           oninput="updateSettingValue('height', this.value)">
                </div>
                
                <div class="setting-group">
                    <label for="fps">FPS: <span class="setting-value" id="fpsValue">30</span></label>
                    <input type="range" id="fps" min="10" max="60" step="10" value="30"
                           oninput="updateSettingValue('fps', this.value)">
                </div>
                
                <button class="btn btn-primary" onclick="applySettings()">Apply Settings</button>
            </div>
            
            <div id="message" class="message"></div>
        </div>
    </div>
    
    <script>
        let streamInterval;
        
        function showMessage(text, type) {
            const messageEl = document.getElementById('message');
            messageEl.textContent = text;
            messageEl.className = 'message ' + type;
            messageEl.style.display = 'block';
            setTimeout(() => {
                messageEl.style.display = 'none';
            }, 5000);
        }
        
        async function connectCamera() {
            try {
                const response = await fetch('/api/camera/connect', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showMessage('Camera connected successfully!', 'success');
                    refreshStatus();
                    startStream();
                } else {
                    showMessage('Failed to connect camera: ' + data.message, 'error');
                }
            } catch (error) {
                showMessage('Error connecting camera: ' + error.message, 'error');
            }
        }
        
        async function disconnectCamera() {
            try {
                const response = await fetch('/api/camera/disconnect', { method: 'POST' });
                const data = await response.json();
                if (data.success) {
                    showMessage('Camera disconnected', 'success');
                    refreshStatus();
                    stopStream();
                } else {
                    showMessage('Failed to disconnect camera', 'error');
                }
            } catch (error) {
                showMessage('Error disconnecting camera: ' + error.message, 'error');
            }
        }
        
        async function captureImage() {
            try {
                const response = await fetch('/api/camera/capture');
                const data = await response.json();
                if (data.success) {
                    showMessage('Image captured: ' + data.filepath, 'success');
                } else {
                    showMessage('Failed to capture image: ' + data.message, 'error');
                }
            } catch (error) {
                showMessage('Error capturing image: ' + error.message, 'error');
            }
        }
        
        async function refreshStatus() {
            try {
                const response = await fetch('/api/camera/status');
                const data = await response.json();
                
                const statusEl = document.getElementById('connectionStatus');
                if (data.connected) {
                    statusEl.textContent = 'Connected';
                    statusEl.className = 'status-value status-connected';
                } else {
                    statusEl.textContent = 'Disconnected';
                    statusEl.className = 'status-value status-disconnected';
                }
                
                document.getElementById('cameraId').textContent = data.camera_id;
                
                if (data.actual_width && data.actual_height) {
                    document.getElementById('resolution').textContent = 
                        data.actual_width + 'x' + data.actual_height;
                }
                
                if (data.actual_fps) {
                    document.getElementById('fps').textContent = data.actual_fps;
                }
            } catch (error) {
                showMessage('Error refreshing status: ' + error.message, 'error');
            }
        }
        
        function updateSettingValue(setting, value) {
            document.getElementById(setting + 'Value').textContent = value;
        }
        
        async function applySettings() {
            const settings = {
                width: parseInt(document.getElementById('width').value),
                height: parseInt(document.getElementById('height').value),
                fps: parseInt(document.getElementById('fps').value)
            };
            
            try {
                const response = await fetch('/api/camera/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });
                const data = await response.json();
                if (data.success) {
                    showMessage('Settings applied successfully!', 'success');
                    refreshStatus();
                } else {
                    showMessage('Failed to apply settings: ' + data.message, 'error');
                }
            } catch (error) {
                showMessage('Error applying settings: ' + error.message, 'error');
            }
        }
        
        function startStream() {
            const preview = document.getElementById('cameraPreview');
            streamInterval = setInterval(() => {
                preview.src = '/api/camera/stream?' + new Date().getTime();
            }, 100);  // Update every 100ms for ~10 FPS preview
        }
        
        function stopStream() {
            if (streamInterval) {
                clearInterval(streamInterval);
            }
        }
        
        // Initialize on page load
        window.onload = function() {
            refreshStatus();
        };
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Serve the web interface"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/camera/status', methods=['GET'])
def get_camera_status():
    """Get camera status"""
    try:
        status = camera.get_status()
        return jsonify(status), 200
    except Exception as e:
        logger.error(f"Error getting camera status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/camera/connect', methods=['POST'])
def connect_camera():
    """Connect to the camera"""
    try:
        success = camera.connect()
        if success:
            return jsonify({
                'success': True,
                'message': 'Camera connected successfully',
                'status': camera.get_status()
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to connect to camera'
            }), 500
    except Exception as e:
        logger.error(f"Error connecting camera: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/camera/disconnect', methods=['POST'])
def disconnect_camera():
    """Disconnect from the camera"""
    try:
        camera.disconnect()
        return jsonify({
            'success': True,
            'message': 'Camera disconnected'
        }), 200
    except Exception as e:
        logger.error(f"Error disconnecting camera: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/camera/capture', methods=['GET'])
def capture_image():
    """Capture an image from the camera"""
    try:
        success, filepath = camera.capture_image()
        if success:
            return jsonify({
                'success': True,
                'filepath': filepath,
                'message': 'Image captured successfully'
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to capture image'
            }), 500
    except Exception as e:
        logger.error(f"Error capturing image: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/camera/stream', methods=['GET'])
def stream_camera():
    """Stream a single frame from the camera"""
    try:
        frame_bytes = camera.get_frame_jpeg()
        if frame_bytes:
            return Response(frame_bytes, mimetype='image/jpeg')
        else:
            # Return a placeholder image if camera not available
            return Response(b'', mimetype='image/jpeg', status=503)
    except Exception as e:
        logger.error(f"Error streaming frame: {str(e)}")
        return Response(b'', mimetype='image/jpeg', status=500)


@app.route('/api/camera/settings', methods=['GET'])
def get_settings():
    """Get current camera settings"""
    try:
        status = camera.get_status()
        return jsonify({
            'success': True,
            'settings': status.get('settings', {})
        }), 200
    except Exception as e:
        logger.error(f"Error getting settings: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/camera/settings', methods=['POST'])
def update_settings():
    """Update camera settings"""
    try:
        settings = request.get_json()
        if not settings:
            return jsonify({
                'success': False,
                'message': 'No settings provided'
            }), 400
        
        success = camera.update_settings(settings)
        if success:
            return jsonify({
                'success': True,
                'message': 'Settings updated successfully',
                'settings': camera.get_status().get('settings', {})
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to update settings'
            }), 500
    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


@app.route('/api/cameras/available', methods=['GET'])
def get_available_cameras():
    """Get list of available cameras"""
    try:
        available = camera.get_available_cameras()
        return jsonify({
            'success': True,
            'cameras': available
        }), 200
    except Exception as e:
        logger.error(f"Error getting available cameras: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


if __name__ == '__main__':
    # Try to connect to camera on startup
    logger.info("Starting Kaderblick Camera API...")
    camera.connect()
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
