import threading
from ctypes import *
import cv2
import sys, os, platform
import time
from reolink import ReolinkAPI
import json
import numpy as np
from collections import deque
import pymysql
import re

# RTSP URL 목록
rtsp_urls = [
    "rtsp://192.168.1.7:554/stream1",
    "rtsp://192.168.1.8:554/stream1",
    "rtsp://192.168.1.9:554/stream1"
    # "http://192.168.1.7/index.html"
    # "rtsp://admin:asiadmin!@192.168.1.5:554/Preview_01_main"
    # "rtsp://camera2_url",
]

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


# Load camera preference
def loadCamPreference(self,cam:str) -> tuple:
    # cam_label = self.CAM_PREFERENCE[cam]['LABEL']
    # ip_address = self.CAM_PREFERENCE[cam]['IP']
    # username = self.CAM_PREFERENCE[cam]['USERNAME']
    # password = self.CAM_PREFERENCE[cam]['PASSWORD']
    # led = self.CAM_PREFERENCE[cam]['LED']
    # irlight = self.CAM_PREFERENCE[cam]['IRLIGHT']
    cam_label = 'camlabel'
    ip_address = '192.168.1.5'
    username = 'admin'
    password = 'asiadmin!'
    led = true
    irlight = false
    return cam_label, ip_address, username, password, led, irlight

def save_image_bytes_as_jpg(image_bytes, file_path):
    # image_bytes를 numpy 배열로 변환
    nparr = np.frombuffer(image_bytes, np.uint8)
    # numpy 배열을 이미지로 디코딩
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    # 이미지를 JPG 파일로 저장
    cv2.imwrite(file_path, img)

def getSnapSingleIpCAM(cam:str) -> bool:

    # create ReolinkAPI instance
    reolink = ReolinkAPI()

    # Load camera preference
    # cam_label,ip_address,username,password,led,irlight = loadCamPreference(cam)
    cam_label = 'camlabel'
    ip_address = '192.168.1.4'
    username = 'admin'
    password = 'asiadmin!'
    led = True
    irlight = False

    # logging.info(f'========= {cam} label: {cam_label} | IP: {ip_address}, USE LED: {led}, USE IRLIGHTS: {irlight}')
    time.sleep(1)

    # Get camera session
    token = reolink._apiLogin(ip_address,username,password)

    # If led is true, turn on led
    if led:
        flag = reolink._apiSetWhiteLedOn(ip_address,token)
        # logging.info(f'{cam} LED ON : {flag}')
        time.sleep(3)
    if irlight:
        flag = reolink._apiSetIRLightOn(ip_address,token)
        # logging.info(f'{cam} IR LIGHT ON : {flag}')
        time.sleep(3)

    # Get image
    image_bytes = reolink._apiGetSnap(ip_address,token)

    if led:
        flag = reolink._apiSetWhiteLedOff(ip_address,token)
        # logging.info(f'{cam} LED OFF : {flag}')
    if irlight:
        flag = reolink._apiSetIRLightOff(ip_address,token)
        # logging.info(f'{cam} IR LIGHT OFF : {flag}')
    # Log out
    flag = reolink._apiLogout(ip_address,token)
    # logging.info(f'{cam} LOGOUT: {flag}')

    return image_bytes

def preprocess_image(image):
    # 이미지 전처리
    pass

def connect_to_db():
    try:
        # MySQL 데이터베이스에 연결
        connection = pymysql.connect(
            host='172.17.0.2',
            user='ev_monitoring_user',
            password='asiadmin@CentralCity',
            database='ev_monitoring_db',
            charset='utf8mb4',
        )
        return connection

    except pymysql.Error as error:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("Failed to connect to MySQL database {}".format(error))
        return None

def close_db_connection(connection):
    if connection.is_connected():
        connection.close()

def check_car_info(plate_text):
    connection = None
    cursor = None

    connection = connect_to_db()
    cursor = connection.cursor()

    # SQL 쿼리 작성
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

        print("Plate info saved to database successfully :: car_info & car_monitoring")

    except pymysql.Error as error:
        print("Failed to insert record into MySQL table {}".format(error))
        connection.rollback()
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

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

        print("Plate info saved to database successfully :: car_monitoring")

    except pymysql.Error as error:
        print("Failed to insert record into MySQL table {}".format(error))

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def process_camera(rtsp_url):
    capture = cv2.VideoCapture(rtsp_url)
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    fps = capture.get(cv2.CAP_PROP_FPS)
    delayDefault = 1000 / fps if fps > 0 else 30

    plate_texts = deque(maxlen=20)
    delay = delayDefault
    while True:
      ret, frame = capture.read()
      start = time.time()
      height = frame.shape[0]
      width = frame.shape[1]
      
      # 객체 인식(ds	단일 객체, 360° 서라운드 인식 (차량 번호 인식 안함))
      # 번호판 인식(dsr	단일 객체, 360° 서라운드, 차량 번호 인식)
      object_result = lib.anpr_read_pixels(bytes(frame), width, height, 0, 'BGR'.encode('utf-8'), 'json'.encode('utf-8'), 'dsr'.encode('utf-8'))
      if len(object_result) > 0:
        object_result_json = json.loads(object_result.decode('utf8'))
      if object_result_json:
        # print("object result::")
        # print(object_result_json)
        # print(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        # if object_result_json[0]['area']['width'] > width * 0.3 and object_result_json[0]['area']['height'] > height * 0.3:
        if 'licensePlate' in object_result_json[0] and object_result_json[0]['licensePlate'][0]['area']['width'] > 90:    
            # 차량 번호판 패턴
            pattern = r'^\d{2,3}[가-힣]\d{4}$'
            plate_text = object_result_json[0]['licensePlate'][0]['text']
            if re.match(pattern, plate_text):
                # if object_result_json[0]['licensePlate'][0]['text'] != '':
                # plate_text = object_result_json[0]['licensePlate'][0]['text']
                powertrainTypeCode = b'\x00' if object_result_json[0]['licensePlate'][0]['attrs']['ev'] else b'\x10'

                
                plate_texts.append(plate_text)

                # 최근 5개의 plate_text에서 3번 이상 같은 plate_text가 있는지 확인
                if plate_texts.count(plate_text) >= 10 and plate_texts.count(plate_text) < 11:

                    print("plate number >> ", plate_text)
                    print("powertrainTypeCode >> ", powertrainTypeCode)

                    #   차량 번호가 car_info 테이블에 존재하는지 확인
                    powertrain = check_car_info(plate_text)

                    if powertrain == "NODATA":
                        save_plate_info_to_db(plate_text, powertrainTypeCode)
                    else:
                        add_to_monitoring_list(plate_text, powertrain)

                    # plate_text 분할
                    match = re.match(r'^(\d{2,3})([가-힣])(\d{4})$', plate_text)
                    if match:
                        part1 = match.group(1)
                        part2 = match.group(2)
                        part3 = match.group(3)

                        # 경로 설정
                        root = os.getenv('ROOT', '/home/evmonitoringadmin/ANPR_IMG')
                        vehicle_type = 'ICE' if powertrainTypeCode == b'\x10' else 'EV'
                        base_path = os.path.join(root, vehicle_type, part1, part2, part3)
                        os.makedirs(base_path, exist_ok=True)

                        # 파일 이름 순서대로 증가
                        # existing_files = [f for f in os.listdir(base_path) if f.startswith('image_') and f.endswith('.png')]
                        # next_index = len(existing_files) + 1

                        
                        current_time = time.strftime('%Y%m%d_%H%M%S')
                        save_path = os.path.join(base_path, f'{plate_text}_{current_time}.jpg')

                        # 이미지 저장
                        ret, buffer = cv2.imencode('.jpg', frame)
                        if ret:
                            image_bytes = buffer.tobytes()
                            save_image_bytes_as_jpg(image_bytes, save_path)


    #   cv2.imshow("ANPR Demo", frame)
      spent = time.time() - start
      delay = delayDefault - spent

    capture.release()
    cv2.destroyAllWindows()


def main():
    error = initialize()
    if error:
        print(error)
        sys.exit(1)

    # process_camera("rtsp://192.168.1.8:554/stream1")
    print(rtsp_urls)
    threads = []
    for rtsp_url in rtsp_urls:
        thread = threading.Thread(target=process_camera, args=(rtsp_url,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

if __name__ == '__main__':
  main()
