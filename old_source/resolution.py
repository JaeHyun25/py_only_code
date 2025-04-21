import cv2

rtsp_url = "rtsp://admin:asiadmin!@192.168.0.104:554/Preview_01_main"
capture = cv2.VideoCapture(rtsp_url)
ret, frame = capture.read()
height = frame.shape[0]
width = frame.shape[1]
print(f"Frame resolution: {width}x{height}")