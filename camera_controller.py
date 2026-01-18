"""
Camera Controller Module for Kaderblick Camera API
Handles USB camera detection, capture, and settings management
"""
import cv2
import numpy as np
from typing import Optional, Dict, List, Tuple
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CameraController:
    """Controller for USB camera operations"""
    
    def __init__(self, camera_id: int = 0):
        """
        Initialize camera controller
        
        Args:
            camera_id: Camera device ID (default: 0 for first camera)
        """
        self.camera_id = camera_id
        self.camera: Optional[cv2.VideoCapture] = None
        self.is_connected = False
        self.current_settings = {
            'width': 640,
            'height': 480,
            'fps': 30,
            'brightness': 128,
            'contrast': 128,
            'saturation': 128
        }
        
    def connect(self) -> bool:
        """
        Connect to the USB camera
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.camera = cv2.VideoCapture(self.camera_id)
            if not self.camera.isOpened():
                logger.error(f"Failed to open camera {self.camera_id}")
                return False
            
            # Apply default settings
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.current_settings['width'])
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.current_settings['height'])
            self.camera.set(cv2.CAP_PROP_FPS, self.current_settings['fps'])
            
            self.is_connected = True
            logger.info(f"Camera {self.camera_id} connected successfully")
            return True
        except Exception as e:
            logger.error(f"Error connecting to camera: {str(e)}")
            return False
    
    def disconnect(self):
        """Disconnect from the camera"""
        if self.camera is not None:
            self.camera.release()
            self.camera = None
            self.is_connected = False
            logger.info("Camera disconnected")
    
    def get_status(self) -> Dict:
        """
        Get camera status information
        
        Returns:
            dict: Camera status information
        """
        status = {
            'connected': self.is_connected,
            'camera_id': self.camera_id,
            'settings': self.current_settings.copy()
        }
        
        if self.is_connected and self.camera is not None:
            status['actual_width'] = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
            status['actual_height'] = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
            status['actual_fps'] = int(self.camera.get(cv2.CAP_PROP_FPS))
        
        return status
    
    def capture_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Capture a single frame from the camera
        
        Returns:
            tuple: (success, frame) where frame is numpy array or None
        """
        if not self.is_connected or self.camera is None:
            logger.error("Camera not connected")
            return False, None
        
        try:
            ret, frame = self.camera.read()
            if not ret:
                logger.error("Failed to capture frame")
                return False, None
            return True, frame
        except Exception as e:
            logger.error(f"Error capturing frame: {str(e)}")
            return False, None
    
    def capture_image(self, output_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Capture and save an image
        
        Args:
            output_path: Path to save the image (optional)
            
        Returns:
            tuple: (success, filepath) where filepath is the saved image path
        """
        success, frame = self.capture_frame()
        if not success or frame is None:
            return False, None
        
        try:
            if output_path is None:
                # Create captured_images directory if it doesn't exist
                os.makedirs('captured_images', exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_path = f'captured_images/capture_{timestamp}.jpg'
            
            cv2.imwrite(output_path, frame)
            logger.info(f"Image saved to {output_path}")
            return True, output_path
        except Exception as e:
            logger.error(f"Error saving image: {str(e)}")
            return False, None
    
    def get_frame_jpeg(self) -> Optional[bytes]:
        """
        Capture frame and encode as JPEG bytes
        
        Returns:
            bytes: JPEG encoded frame or None
        """
        success, frame = self.capture_frame()
        if not success or frame is None:
            return None
        
        try:
            _, buffer = cv2.imencode('.jpg', frame)
            return buffer.tobytes()
        except Exception as e:
            logger.error(f"Error encoding frame: {str(e)}")
            return None
    
    def update_settings(self, settings: Dict) -> bool:
        """
        Update camera settings
        
        Args:
            settings: Dictionary of settings to update
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected or self.camera is None:
            logger.error("Camera not connected")
            return False
        
        try:
            if 'width' in settings:
                self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, settings['width'])
                self.current_settings['width'] = settings['width']
            
            if 'height' in settings:
                self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, settings['height'])
                self.current_settings['height'] = settings['height']
            
            if 'fps' in settings:
                self.camera.set(cv2.CAP_PROP_FPS, settings['fps'])
                self.current_settings['fps'] = settings['fps']
            
            if 'brightness' in settings:
                self.camera.set(cv2.CAP_PROP_BRIGHTNESS, settings['brightness'])
                self.current_settings['brightness'] = settings['brightness']
            
            if 'contrast' in settings:
                self.camera.set(cv2.CAP_PROP_CONTRAST, settings['contrast'])
                self.current_settings['contrast'] = settings['contrast']
            
            if 'saturation' in settings:
                self.camera.set(cv2.CAP_PROP_SATURATION, settings['saturation'])
                self.current_settings['saturation'] = settings['saturation']
            
            logger.info("Camera settings updated")
            return True
        except Exception as e:
            logger.error(f"Error updating settings: {str(e)}")
            return False
    
    def get_available_cameras(self) -> List[int]:
        """
        Get list of available camera devices
        
        Returns:
            list: List of available camera IDs
        """
        available = []
        for i in range(10):  # Check first 10 camera indices
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        return available
