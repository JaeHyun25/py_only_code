import cv2
import subprocess

# RTSP URL 목록
rtsp_urls = [
    "rtsp://192.168.1.7:554/stream1?tcp",
    "rtsp://192.168.1.8:554/stream1",
    "rtsp://192.168.1.9:554/stream1"
]

def check_tcp_support(rtsp_url):
    cap = cv2.VideoCapture(rtsp_url)
    if cap.isOpened():
        print(f"Successfully opened RTSP stream: {rtsp_url}")
        cap.release()
    else:
        print(f"Failed to open RTSP stream: {rtsp_url}")
import subprocess

# 원래 RTSP URL
rtsp_url = "rtsp://192.168.1.7:554/stream1"

def check_rtsp_transport(rtsp_url):
    command = [
        'ffmpeg',
        '-i', rtsp_url,
        '-v', 'verbose',
        '-t', '5',  # Run for 5 seconds
        '-f', 'null',
        '-'
    ]
    result = subprocess.run(command, stderr=subprocess.PIPE, text=True)
    if "Using tcp" in result.stderr:
        print("The RTSP stream is using TCP.")
    elif "Using udp" in result.stderr:
        print("The RTSP stream is using UDP.")
    else:
        print("Could not determine the transport protocol.")

if __name__ == "__main__":
    for url in rtsp_urls:
        # check_rtsp_transport(rtsp_url)
        check_tcp_support(url)