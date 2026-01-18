"""
Test script for Kaderblick Camera API
Tests basic functionality without requiring actual camera hardware
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing imports...")
    try:
        import flask
        print("  ✓ Flask imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import Flask: {e}")
        return False
    
    try:
        import cv2
        print("  ✓ OpenCV imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import OpenCV: {e}")
        return False
    
    try:
        import numpy
        print("  ✓ NumPy imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import NumPy: {e}")
        return False
    
    try:
        from flask_cors import CORS
        print("  ✓ Flask-CORS imported successfully")
    except ImportError as e:
        print(f"  ✗ Failed to import Flask-CORS: {e}")
        return False
    
    return True


def test_camera_controller():
    """Test camera controller module"""
    print("\nTesting Camera Controller...")
    try:
        from camera_controller import CameraController
        print("  ✓ CameraController imported successfully")
        
        # Create controller instance
        controller = CameraController(camera_id=0)
        print("  ✓ CameraController instantiated")
        
        # Test status method
        status = controller.get_status()
        assert isinstance(status, dict), "Status should return a dictionary"
        assert 'connected' in status, "Status should contain 'connected' field"
        assert 'camera_id' in status, "Status should contain 'camera_id' field"
        print("  ✓ get_status() works correctly")
        
        # Test available cameras method
        available = controller.get_available_cameras()
        assert isinstance(available, list), "available_cameras should return a list"
        print(f"  ✓ get_available_cameras() works correctly (found {len(available)} cameras)")
        
        return True
    except Exception as e:
        print(f"  ✗ Camera controller test failed: {e}")
        return False


def test_flask_app():
    """Test Flask application"""
    print("\nTesting Flask Application...")
    try:
        from app import app
        print("  ✓ Flask app imported successfully")
        
        # Test that app has required routes
        routes = [rule.rule for rule in app.url_map.iter_rules()]
        required_routes = [
            '/',
            '/api/camera/status',
            '/api/camera/connect',
            '/api/camera/disconnect',
            '/api/camera/capture',
            '/api/camera/stream',
            '/api/camera/settings',
            '/api/cameras/available'
        ]
        
        for route in required_routes:
            assert route in routes, f"Required route {route} not found"
            print(f"  ✓ Route {route} exists")
        
        return True
    except Exception as e:
        print(f"  ✗ Flask app test failed: {e}")
        return False


def test_file_structure():
    """Test that required files exist"""
    print("\nTesting File Structure...")
    required_files = [
        'app.py',
        'camera_controller.py',
        'requirements.txt',
        'README.md',
        '.gitignore'
    ]
    
    all_exist = True
    for filename in required_files:
        if os.path.exists(filename):
            print(f"  ✓ {filename} exists")
        else:
            print(f"  ✗ {filename} missing")
            all_exist = False
    
    return all_exist


def main():
    """Run all tests"""
    print("=" * 60)
    print("Kaderblick Camera API - Test Suite")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("File Structure", test_file_structure()))
    results.append(("Imports", test_imports()))
    results.append(("Camera Controller", test_camera_controller()))
    results.append(("Flask Application", test_flask_app()))
    
    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! The API is ready to use.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please check the errors above.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
