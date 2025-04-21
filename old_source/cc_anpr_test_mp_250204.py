import multiprocessing
from ctypes import *
import cv2
import sys, os, platform
import time
import json
import numpy as np
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import pymysql
import re
import json

# 설정 값
config = {}

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def getLibPath():
  os_name = platform.system().lower()
  arch_name = platform.machine().lower()
  print('os_name=%s, arch_name=%s' % (os_name, arch_name))

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

  print('Unsupported target platform')
  sys.exit(-1)


IMG_PATH = '../img/'
LIB_PATH = getLibPath()
print('LIB_PATH=', LIB_PATH)
lib = cdll.LoadLibrary(LIB_PATH)

lib.anpr_initialize.argtype = c_char_p
lib.anpr_initialize.restype = c_char_p

lib.anpr_read_file.argtypes = (c_char_p, c_char_p, c_char_p)
lib.anpr_read_file.restype = c_char_p

lib.anpr_read_pixels.argtypes = (c_char_p, c_int32, c_int32, c_int32, c_char_p, c_char_p, c_char_p)
lib.anpr_read_pixels.restype = c_char_p


def initialize():
  error = lib.anpr_initialize('text')
  return error.decode('utf8') if error else error

def save_image_async(image_bytes, save_path):
    with open(save_path, 'wb') as f:
        f.write(image_bytes)

def connect_to_db():
    try:
        # MySQL 데이터베이스에 연결
        connection = pymysql.connect(
            host = config['db_host'],
            user = config['db_user'],
            password = config['db_password'],
            database = config['db_name'],
            charset = 'utf8mb4',
        )
        return connection

    except pymysql.Error as error:
        print("Failed to connect to MySQL database {}".format(error))
        return None

# car_info 테이블에서 차량 정보 조회
def check_car_info(plate_text):
    connection = None
    cursor = None

    connection = connect_to_db()
    cursor = connection.cursor()

    sql_select_query = """SELECT plateNumber, powertrainTypeCode FROM car_info WHERE plateNumber = %s"""
    cursor.execute(sql_select_query, (plate_text,))
    result = cursor.fetchone()

    cursor.close()
    connection.close()

    if result is None:
        return "NODATA"
    else:
        plateNumber, powertrainTypeCode = result
        return powertrainTypeCode

# 차량 정보 저장
def save_plate_info_to_db(plate_text, powertrainTypeCode):
    connection = None
    cursor = None

    try:
        connection = connect_to_db()
        cursor = connection.cursor()
        current_time = time.strftime('%Y-%m-%d %H:%M:%S')

        # car_info 테이블
        sql_insert_query = """INSERT INTO car_info (plateNumber, powertrainTypeCode) VALUES (%s, %s)"""
        cursor.execute(sql_insert_query, (plate_text, powertrainTypeCode))

        # car_monitoring 테이블
        sql_insert_query = """INSERT INTO car_monitoring (plateNumber, powertrainTypeCode, enterTime) VALUES (%s, %s, %s)"""
        cursor.execute(sql_insert_query, (plate_text, powertrainTypeCode, current_time))

        # 변경사항 커밋
        connection.commit()

        # print("Plate info saved to database successfully :: car_info & car_monitoring")

    except pymysql.Error as error:
        # print("Failed to insert record into MySQL table {}".format(error))
        connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# 모니터링 리스트에 추가 & 차량 정보 저장
def add_to_monitoring_list(plate_text, powertrainTypeCode):
    connection = None
    cursor = None

    try:
        connection = connect_to_db()
        cursor = connection.cursor()

        current_time = time.strftime('%Y-%m-%d %H:%M:%S')
        # SQL 쿼리 작성
        sql_insert_query = """INSERT INTO car_monitoring (plateNumber, powertrainTypeCode, enterTime) VALUES (%s, %s, %s)"""
        cursor.execute(sql_insert_query, (plate_text, powertrainTypeCode, current_time))

        # 변경사항 커밋
        connection.commit()

        # print("Plate info saved to database successfully :: car_monitoring")

    except pymysql.Error as error:
        print("Failed to insert record into MySQL table {}".format(error))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

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

    with ThreadPoolExecutor(max_workers=2) as executor:
        while True:
            ret, frame = capture.read()
            start = time.time()
            height = frame.shape[0]
            width = frame.shape[1]
            
            # 객체 인식(ds	단일 객체, 360° 서라운드 인식 (차량 번호 인식 안함))
            # 번호판 인식(dsr	단일 객체, 360° 서라운드, 차량 번호 인식)
            object_result = lib.anpr_read_pixels(bytes(frame), width, height, 0, 'BGR'.encode('utf-8'), 'json'.encode('utf-8'), anpr_option.encode('utf-8'))
        
            # 번호판 인식 결과가 있을 경우
            if len(object_result) > 0:
                object_result_json = json.loads(object_result.decode('utf8'))

            if object_result_json:
                # 번호판 가로 길이가 90 이상일 경우
                if 'licensePlate' in object_result_json[0] and object_result_json[0]['licensePlate'][0]['area']['width'] > 50:
                    # 차량 번호판 패턴
                    pattern = r'^\d{2,3}[가-힣]\d{4}$'
                    pattern = r'^(\d{2,3}|[가-힣]{2}\d{1,2})[가-힣]\d{4}$'
                    plate_text = object_result_json[0]['licensePlate'][0]['text']
                    if '1.7' in rtsp_url:
                        print('result: ', plate_text)    

                    if re.match(pattern, plate_text):

                        powertrainTypeCode = b'\x00' if object_result_json[0]['licensePlate'][0]['attrs']['ev'] else b'\x10'
                        plate_texts.append(plate_text)

                        # 최근 n개의 plate_text에서 m번 이상 같은 plate_text가 있는지 확인
                        if plate_texts.count(plate_text) >= plate_count_threshold and plate_texts.count(plate_text) < plate_count_threshold+1:
                            if '1.7' in rtsp_url:
                                print("plate number, powerTrainTypeCode >> ", plate_text, " :: ", powertrainTypeCode)

                            #   차량 번호가 car_info 테이블에 존재하는지 확인
                            powertrain = check_car_info(plate_text)

                            if powertrain == "NODATA":
                                # car_info 테이블에 차량 정보가 없는 경우 차량 정보 INSERT, 모니터링 리스트에 추가
                                save_plate_info_to_db(plate_text, powertrainTypeCode)
                            else:
                                # 차량 정보가 있는 경우 모니터링 리스트에 추가
                                add_to_monitoring_list(plate_text, powertrain)


                            # 차량 후면 이미지 저장
                            match = re.match(r'^(\d{2,3}|[가-힣]{2}\d{1,2})([가-힣])(\d{4})$', plate_text)

                            # plate_text 분할
                            if match:
                                part1 = match.group(1)
                                part2 = match.group(2)
                                part3 = match.group(3)

                                # 경로 설정
                                root = config['car_image_save_path']
                                vehicle_type = 'ICE' if powertrainTypeCode == b'\x10' else 'EV'
                                base_path = os.path.join(root, vehicle_type, part1, part2, part3)
                                os.makedirs(base_path, exist_ok=True)
                                
                                current_time = time.strftime('%Y%m%d_%H%M%S')
                                save_path = os.path.join(base_path, f'{plate_text}_{current_time}.jpg')

                                # 이미지 저장
                                ret, buffer = cv2.imencode('.jpg', frame)
                                if ret:
                                    image_bytes = buffer.tobytes()
                                    executor.submit(save_image_async, image_bytes, save_path)

    capture.release()
    cv2.destroyAllWindows()


def main():
    global config
    config_path = 'config.json'
    config = load_config(config_path)

    error = initialize()
    if error:
        print(error)
        sys.exit(1)

    rtsp_urls = config['rtsp_urls']
    print(rtsp_urls)

    processes = []
    for rtsp_url in rtsp_urls:
        process = multiprocessing.Process(target=process_camera, args=(rtsp_url,))
        processes.append(process)
        process.start()

    for process in processes:
        process.join()

if __name__ == '__main__':
  main()
