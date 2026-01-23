import cv2
cap = cv2.VideoCapture('/dev/video0')
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
cap.set(cv2.CAP_PROP_FPS, 30)
ret, frame = cap.read()
print('Frame:', ret, frame.shape if ret else None)
cap.release()