import multiprocessing
from ctypes import *
import cv2
import sys, os, platform
import time
import json
import logging  # Added logging module
import numpy as np
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import pymysql
import re
from datetime import datetime
from ev_detect import ev_detect

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Log to console
        logging.FileHandler("anpr.log", encoding="utf-8")  # Log to file
    ]
)

# 설정 파일 로드
config = {}
def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ANPR 라이브러리 경로 설정
def getLibPath():
    os_name = platform.system().lower()
    arch_name = platform.machine().lower()
    logging.info('os_name=%s, arch_name=%s', os_name, arch_name)

    if os_name == 'windows':
        if arch_name == 'x86_64' or arch_name == 'amd64':
            return os.path.join('..', 'bin', 'windows-x86_64', 'tsanpr.dll')
        elif arch_name == 'x86':
            return os.path.join('..', 'bin', 'windows-x86', 'tsanpr.dll')
    elif os_name == 'linux':
        if arch_name == 'x86_64':
            return os.path.join('..', 'bin', 'linux-x86_64', 'libtsanpr.so')
        elif arch_name == 'aarch64':
            return os.path.join('..', 'bin', 'linux-aarch64', 'libtsanpr.so')

    logging.error('Unsupported target platform')
    sys.exit(-1)


IMG_PATH = '../img/'
LIB_PATH = getLibPath()
logging.info('LIB_PATH=%s', LIB_PATH)
lib = cdll.LoadLibrary(LIB_PATH)

lib.anpr_initialize.argtype = c_char_p
lib.anpr_initialize.restype = c_char_p

lib.anpr_read_file.argtypes = (c_char_p, c_char_p, c_char_p)
lib.anpr_read_file.restype = c_char_p

lib.anpr_read_pixels.argtypes = (c_char_p, c_int32, c_int32, c_int32, c_char_p, c_char_p, c_char_p)
lib.anpr_read_pixels.restype = c_char_p

# ANPR 라이브러리 초기화
def initialize():
    error = lib.anpr_initialize('text')
    return error.decode('utf8') if error else error

# 차량 번호판 이미지 저장
def save_image(image_bytes, save_path):
    with open(save_path, 'wb') as f:
        f.write(image_bytes)

# ROI 영역 적용
def get_frame_roi(frame, roi):
    frame_size = frame.shape[:2]

    # ROI가 설정되어 있을 경우
    if roi:
        y1_ratio, y2_ratio, x1_ratio, x2_ratio = roi
        frame_height, frame_width = frame_size

        y1 = int(y1_ratio * frame_height)
        y2 = int(y2_ratio * frame_height)
        x1 = int(x1_ratio * frame_width)
        x2 = int(x2_ratio * frame_width)

        return frame[y1:y2, x1:x2]
    return frame

# 카메라 영상 처리
def process_camera(rtsp_url):

    # rtsp 스트림에서 캡처 생성
    capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    anpr_option = config['anpr_option']
    plate_count_deque_size = config['plate_count_deque_size']
    plate_count_threshold = config['plate_count_threshold']
    plate_texts = deque(maxlen=plate_count_deque_size)      # 최근 n개의 차량 번호 저장할 deque
    
    max_workers = os.cpu_count() or 2  # CPU 코어 수에 따라 동적 설정
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while True:
            ret, frame = capture.read()

            # RTSP 스트림이 끊어졌을 경우 재연결
            if not ret:
                logging.warning("Stream disconnected. Reconnecting...")
                capture.release()
                time.sleep(5)  # 재연결 대기 시간
                capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                continue
            
            # ROI 설정 적용
            roi = config['roi'].get(rtsp_url, None)
            frame_roi = get_frame_roi(frame, roi)
            height, width = frame_roi.shape[:2]

#===============================


  #===========================              
            # 차량 번호판 인식
            object_result = lib.anpr_read_pixels(bytes(frame_roi), width, height, 0, 'BGR'.encode('utf-8'), 'json'.encode('utf-8'), anpr_option.encode('utf-8'))

            # 번호판 인식 결과가 있을 경우
            if len(object_result) > 0:
                object_result_json = json.loads(object_result.decode('utf8'))
                #logging.info(f"ANPR 결과 (JSON): {object_result_json}") # <-- 바로 이 줄을 추가해 주세요.

            if object_result_json:
                if 'text' in object_result_json[0]:
                    # 차량 번호판 텍스트 추출
                    plate_info = object_result_json[0]
                    plate_text = plate_info['text']
                    
                    # 차량 번호판 패턴과 일치하는지 확인
                    pattern = r'^(\d{2,3}|[가-힣]{2}\d{1,2})[가-힣]\d{4}$'
                    if re.match(pattern, plate_text):
                        powertrainTypeCode = 'ev' if object_result_json[0]['ev'] else 'ice'
                        plate_texts.append(plate_text)

                        # 최근 n개의 plate_text에서 m번 이상 같은 plate_text가 있는지 확인
                        if plate_texts.count(plate_text) >= plate_count_threshold and plate_texts.count(plate_text) < plate_count_threshold+1:
                            logging.info("TS RESULT >> plate number, powerTrainTypeCode :: %s , %s", plate_text, powertrainTypeCode)

                            # ev 판정
                            ev_detect_result = ev_detect(frame_roi, plate_info)
                            if ev_detect_result['ev'] is not None:
                                logging.info("EV DETECT RESULT >> %s", ev_detect_result['ev'])
                                powertrainTypeCode = 'ev' if ev_detect_result['ev'] else 'ice'

#========================================
			     # plate_info 
#			     if 'area' in plate_info:
#			         x = int(plate_info['area']['x'])
#			         y = int(plate_info['area']['y'])
#			         width = int(plate_info['area']['width'])
#			         height = int(plate_info['area']['height'])
#			         roi_marked_image_save_path = config['roi_marked_image_save_path']
#			         os.makedirs(roi_marked_image_save_path, exist_ok=True)



#=========================================
                            # 차량 후면 이미지 저장
                            temp_car_image_save_path = config['temp_car_image_save_path']
                            current_time = time.strftime('%Y%m%d_%H%M%S')
                            current_date = time.strftime('%Y%m%d')
                            img_save_path = os.path.join(temp_car_image_save_path, f'{plate_text}_{powertrainTypeCode}_{current_time}.jpg')
                            ret, buffer = cv2.imencode('.jpg', frame)
                            if ret:
                                image_bytes = buffer.tobytes()
                                executor.submit(save_image, image_bytes, img_save_path)
#----------------------------------------------------------------------------------
# 크롭 영역 표시된 차량 후면 이미지 저장
#                            if object_result_json and len(object_result_json) > 0 and 'area' in object_result_json[0]:
#                                plate_info = object_result_json[0]
#                                x = int(plate_info['area']['x'])
#                                y = int(plate_info['area']['y'])
#                                width = int(plate_info['area']['width'])
#                                height = int(plate_info['area']['height'])##

#                                frame_with_roi = frame.copy() # 원본 프레임 복사
#                                cv2.rectangle(frame_with_roi, (x, y), (x + width, y - height), (0, 255, 0), 2) # 녹색 사각형
#
#                                roi_marked_img_save_path = os.path.join(config['roi_marked_image_save_path'], f'{plate_text}_roi_marked_{powertrainTypeCode}_{current_time}.jpg') # 새로운 경로 사용
#                                ret_roi_marked, buffer_roi_marked = cv2.imencode('.jpg', frame_with_roi)
#                                if ret_roi_marked:
#                                    image_bytes_roi_marked = buffer_roi_marked.tobytes()
#                                    executor.submit(save_image, image_bytes_roi_marked, roi_marked_img_save_path)
#
#                                # 실제 크롭된 번호판 이미지 저장 (추가된 부분)
#                                cropped_plate = frame[y:y + height, x:x + width]
#                                cropped_plate_save_path = os.path.join(config['roi_marked_image_save_path'], f'{plate_text}_cropped_{powertrainTypeCode}_{current_time}.jpg') # 파일명 변경
#                                ret_cropped, buffer_cropped = cv2.imencode('.jpg', cropped_plate)
#                                if ret_cropped:
#                                    image_bytes_cropped = buffer_cropped.tobytes()
#                                    executor.submit(save_image, image_bytes_cropped, cropped_plate_save_path)
 #-----------------------------------------------------------------------------------------
                            # result_json 저장
                            result_json_save_path = config['result_json_save_path']
                            json_save_path = os.path.join(result_json_save_path, current_date,f'{plate_text}_{powertrainTypeCode}_{current_time}.json')
                            os.makedirs(os.path.dirname(json_save_path), exist_ok=True)
                            with open(json_save_path, 'w', encoding='utf-8') as json_file:
                                json.dump(object_result_json, json_file, ensure_ascii=False, indent=4)
    capture.release()
    cv2.destroyAllWindows()


def main():
    global config
    config_path = 'config.json'
    config = load_config(config_path)

    error = initialize()
    if error:
        logging.error(error)
        sys.exit(1)

    # RTSP URL 목록 로드
    rtsp_urls = config['rtsp_urls']
    logging.info("RTSP URLs: %s", rtsp_urls)

    # 프로세스 생성 및 시작
    processes = []
    for rtsp_url in rtsp_urls:
        process = multiprocessing.Process(target=process_camera, args=(rtsp_url,))
        processes.append(process)
        process.start()

    for process in processes:
        process.join()

if __name__ == '__main__':
    main()
