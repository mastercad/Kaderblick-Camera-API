import zmq
import cv2
import numpy as np

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://camera-host:5555")
socket.setsockopt_string(zmq.SUBSCRIBE, "")

while True:
    jpg_bytes = socket.recv()
    jpg = np.frombuffer(jpg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(jpg, cv2.IMREAD_COLOR)
    cv2.imshow("Preview", frame)
    if cv2.waitKey(1) == 27:
        break
cv2.destroyAllWindows()
