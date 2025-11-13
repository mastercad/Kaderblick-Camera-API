from fastapi import FastAPI, Response, Header, HTTPException
from starlette.responses import StreamingResponse
import zmq
import threading
import time
import signal
import sys

API_KEY = "mein_sicherer_key"  # Beispiel, ändere auf dein sicheres Key
app = FastAPI()

# ZMQ Setup
context = zmq.Context()
req_socket = context.socket(zmq.REQ)
req_socket.connect("tcp://127.0.0.1:5556")

sub_socket = context.socket(zmq.SUB)
sub_socket.connect("tcp://127.0.0.1:5555")
sub_socket.setsockopt_string(zmq.SUBSCRIBE, "")
sub_socket.RCVTIMEO = 100  # Millisekunden, damit recv nicht ewig blockiert

latest_frame = None
stop_event = threading.Event()

def frame_listener():
    global latest_frame
    while not stop_event.is_set():
        try:
            latest_frame = sub_socket.recv(flags=zmq.NOBLOCK)
            print("Frame received:", len(latest_frame))
        except zmq.Again:
            time.sleep(0.01)

listener_thread = threading.Thread(target=frame_listener, daemon=True)
listener_thread.start()

def verify_api_key(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.get("/start_record")
def start_record():
#def start_record(x_api_key: str = Header(...)):
#    verify_api_key(x_api_key)
    req_socket.send_string("START")
    return {"status": req_socket.recv_string()}

@app.get("/stop_record")
def stop_record():
#def stop_record(x_api_key: str = Header(...)):
#    verify_api_key(x_api_key)
    req_socket.send_string("STOP")
    return {"status": req_socket.recv_string()}

@app.get("/preview")
#def preview(x_api_key: str = Header(...)):
def preview():
#    verify_api_key(x_api_key)
    def generate():
        try:
            while not stop_event.is_set():
                if latest_frame:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" +
                           latest_frame + b"\r\n")
                time.sleep(0.05)
        except GeneratorExit:
            # Client hat Verbindung getrennt
            pass
    return StreamingResponse(generate(), media_type='multipart/x-mixed-replace; boundary=frame')

@app.on_event("shutdown")
def shutdown_event():
    print("Shutdown event triggered, stopping listener...")
    stop_event.set()
    listener_thread.join(timeout=2)
    print("Listener stopped, shutdown complete")
