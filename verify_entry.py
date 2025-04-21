# 필요한 모듈 import (기존 파일에 있다면 중복 제거)
import requests
import sys, os
import time
import numpy as np
import base64
import pymysql
import re
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import shutil
import logging # 로깅 모듈 import

# 로깅 설정 (verify_entry 스크립트용 로거 설정)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # 이 모듈의 로거 객체 생성

# 설정 값 (전역 변수 config 사용)
config = {}

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_all_filenames_from_directory(directory_path):
    try:
        # .jpg 파일만 가져오도록 수정 (혹시 다른 파일이 있다면)
        filenames = [f for f in os.listdir(directory_path) if f.lower().endswith('.jpg')]
        return filenames
    except Exception as e:
        logger.error(f"디렉토리 파일 목록 가져오기 오류 {directory_path}: {e}")
        return []

# 파일 이름 파싱
def parse_filename(filename):
    parts = filename.split('_')
    # 파일 이름 형식: plate_text_powertrain_entry_date_entry_time.jpg
    if len(parts) != 4:
        # 파일명 형식이 잘못된 경우 ValueError 발생
        raise ValueError(f"파일명 형식 오류: {filename}")

    plate_text = parts[0]
    powertrain_from_filename = parts[1] # 파일명에서 파워트레인 추출
    entry_date_str = parts[2]
    entry_time_str = parts[3].split('.')[0]  # 파일 확장자 제거

    # 날짜 및 시간 형식 검증
    try:
        entry_datetime_str = f"{entry_date_str} {entry_time_str}"
        entry_datetime = datetime.strptime(entry_datetime_str, "%Y%m%d %H%M%S")
    except ValueError:
        raise ValueError(f"파일명 날짜/시간 형식 오류: {filename}")

    return plate_text, powertrain_from_filename, entry_datetime

# 차량 번호로 주차 위치 조회 (AMANO API)
def get_parking_status(carNo):
    userid = config['amano_userid']
    userpw = config['amano_userpw']

    # base64 encoding
    string = userid+':'+userpw
    string_bytes = string.encode('UTF-8')
    result = base64.b64encode(string_bytes)
    result_str = result.decode('ascii')

    headers = {
        "Authorization": f"Basic {result_str}",
        "Content-Type": "application/json" # Content-Type 헤더 추가
    }
    url_getParkingLocation = config['amano_url_getParkingLocation']

    body = {
        "lotAreaNo" : config['amano_lotAreaNo'],
        "carNo4Digit" : carNo # AMANO API는 보통 차량 번호 4자리를 사용
    }

    try:
        # API 호출 시 timeout 설정 권장
        response = requests.post(url=url_getParkingLocation, headers=headers, data=json.dumps(body), timeout=10) # timeout 10초 설정
        response.raise_for_status() # HTTP 오류가 발생하면 예외 발생
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"AMANO API 호출 오류: {e}")
        # API 호출 실패 시 오류 응답 반환
        return {"status": "API_ERROR", "message": str(e)}
    except json.JSONDecodeError:
        logger.error("AMANO API 응답 JSON 디코딩 오류")
        return {"status": "JSON_ERROR", "message": "Invalid JSON response"}


def connect_to_db():
    try:
        # MySQL 데이터베이스에 연결
        connection = pymysql.connect(
            host = config['db_host'],
            user = config['db_user'],
            password = config['db_password'],
            database = config['db_name'],
            charset = 'utf8mb4',
            cursorclass=pymysql.cursors.DictCursor # 결과를 딕셔너리로 받도록 설정
        )
        logger.info("MySQL 데이터베이스 연결 성공")
        return connection

    except pymysql.Error as error:
        logger.error(f"MySQL 데이터베이스 연결 실패: {error}")
        return None

# car_info 테이블에서 차량 정보 조회
def check_car_info(cursor, plate_text):
    sql_select_query = """SELECT plateNumber, powertrainTypeCode FROM car_info WHERE plateNumber = %s"""
    try:
        cursor.execute(sql_select_query, (plate_text,))
        result = cursor.fetchone()

        if result is None:
            return "NODATA"
        else:
            # 데이터베이스에서 가져온 powertrainTypeCode는 byte일 수 있으므로 문자열로 변환
            return result['powertrainTypeCode'].decode('utf-8') if isinstance(result['powertrainTypeCode'], bytes) else str(result['powertrainTypeCode'])

    except pymysql.Error as e:
        logger.error(f"데이터베이스 조회 오류 (car_info): {e}")
        return "DB_ERROR" # 데이터베이스 오류 시 "DB_ERROR" 반환

# car_info 테이블에 차량 정보 저장 (새로운 차량)
def insert_car_info(db_connection, cursor, plate_text, powertrain_from_filename):
    sql_insert_query = """INSERT INTO car_info (plateNumber, powertrainTypeCode) VALUES (%s, %s)"""
    try:
        # 파일 이름에서 온 문자열 파워트레인을 데이터베이스 형식 (byte 또는 문자열)에 맞게 변환
        db_powertrain_type = powertrain_from_filename.encode('utf-8') if isinstance(powertrain_from_filename, str) else powertrain_from_filename # DB 스키마에 맞게 조정 필요
        cursor.execute(sql_insert_query, (plate_text, db_powertrain_type))
        # db_connection.commit() # commit은 main 함수에서 일괄적으로 수행
        logger.info(f"새 차량 정보 삽입: {plate_text} - {powertrain_from_filename}")
    except pymysql.Error as e:
        logger.error(f"데이터베이스 삽입 오류 (car_info): {e}")
        # 오류 발생 시 rollback은 main 함수에서 처리

# car_monitoring 테이블에 추가 (입차 시간 업데이트)
def add_to_monitoring_list(db_connection, cursor, plate_text, powertrain_from_db, entry_datetime):
    # INSERT IGNORE: 이미 존재하면 무시하고, 없으면 삽입
    sql_insert_query = """INSERT IGNORE INTO car_monitoring (plateNumber, powertrainTypeCode, enterTime) VALUES (%s, %s, %s)"""
    try:
        # 데이터베이스에서 온 파워트레인 정보를 그대로 사용
        cursor.execute(sql_insert_query, (plate_text, powertrain_from_db, entry_datetime))
        # db_connection.commit() # commit은 main 함수에서 일괄적으로 수행
        logger.info(f"차량 모니터링 목록 추가/업데이트: {plate_text}")
    except pymysql.Error as e:
        logger.error(f"데이터베이스 삽입/업데이트 오류 (car_monitoring): {e}")
        # 오류 발생 시 rollback은 main 함수에서 처리


# 입차 확정 처리 (파일 이동 및 DB 업데이트) - 하이브리드 로직 적용
def entry_confirm(db_connection, cursor, car_filename, plate_text, powertrain_from_filename, entry_datetime, config):
    logger.info(f"차량 {plate_text} 입차 확정 처리 시작. 파일명 파워트레인: '{powertrain_from_filename}'")

    # 차량 번호가 car_info 테이블에 존재하는지 확인
    powertrain_from_db = check_car_info(cursor, plate_text) # 데이터베이스 조회

    # 폴더 결정을 위해 사용할 파워트레인 정보 (기본값: 파일명 기반 사용자 모델 결과)
    powertrain_to_use_for_folder = powertrain_from_filename

    if powertrain_from_db == "NODATA":
        # 1. 데이터베이스에 차량 정보가 없는 경우:
        # 파일 이름에서 온 파워트레인 정보로 데이터베이스에 신규 삽입
        logger.info(f"차량 {plate_text} 데이터베이스에 없음. 파일명 기반 '{powertrain_from_filename}'으로 신규 추가.")
        insert_car_info(db_connection, cursor, plate_text, powertrain_from_filename)
        # 폴더 결정은 파일명 기반 값 사용 (powertrain_to_use_for_folder는 이미 powertrain_from_filename)

    elif powertrain_from_db == "DB_ERROR":
        # 데이터베이스 조회 중 오류 발생 시: 로그 남기고 파일명 기반 값 사용 (안전 장치)
        logger.error(f"차량 {plate_text} 데이터베이스 조회 중 오류 발생. 파일명 기반 '{powertrain_from_filename}'으로 폴더 결정.")
        # powertrain_to_use_for_folder는 이미 powertrain_from_filename

    else:
        # 2. 데이터베이스에 차량 정보가 있는 경우:
        # 모니터링 리스트 업데이트 (데이터베이스에서 온 파워트레인 정보 사용)
        add_to_monitoring_list(db_connection, cursor, plate_text, powertrain_from_db, entry_datetime)

        # 데이터베이스와 파일명의 파워트레인 정보가 다를 경우 (불일치)
        if powertrain_from_filename != powertrain_from_db:
            # 불일치 경고 로깅: 어떤 값이 다르고 어떤 값을 따를지 명시
            logger.warning(f"파워트레인 불일치! 차량: {plate_text}. 파일명: '{powertrain_from_filename}', DB: '{powertrain_from_db}'. 폴더 결정은 파일명 기준 따름.")
            # 폴더 결정은 파일명 기반 값 사용 (powertrain_to_use_for_folder는 이미 powertrain_from_filename)
        else:
            # 데이터베이스와 파일명의 파워트레인 정보가 일치하는 경우
            logger.info(f"파워트레인 일치. 차량: {plate_text}, '{powertrain_from_filename}'. 폴더 결정은 파일명 기준 따름.")
            # 폴더 결정은 파일명 기반 값 사용 (powertrain_to_use_for_folder는 이미 powertrain_from_filename)


    # --- 폴더 결정을 위해 powertrain_to_use_for_folder 사용 ---
    # 폴더 이름에 사용할 파워트레인 코드 결정 (bytes 형태)
    if powertrain_to_use_for_folder == "ev":
        powertrainCode_for_folder = b"\x00" # 또는 DB 스키마에 맞는 다른 값
    elif powertrain_to_use_for_folder == "ice":
        powertrainCode_for_folder = b"\x10" # 또는 DB 스키마에 맞는 다른 값
    else:
        # 파일명 파워트레인이 'ev' 또는 'ice'가 아닌 경우 (예: 'Unknown' 또는 잘못 파싱된 값)
        logger.warning(f"알 수 없는 파워트레인 타입: '{powertrain_to_use_for_folder}' for car {plate_text}. 기본값 ICE로 처리.")
        powertrainCode_for_folder = b"\x10" # 알 수 없는 경우 기본값 ICE로 처리 (또는 별도 Unknown 폴더 고려)


    # 최종 폴더 이름 결정 ('EV', 'ICE', 'Unknown')
    if powertrainCode_for_folder == b'\x00':
        vehicle_type = "EV"
    elif powertrainCode_for_folder == b'\x10':
        vehicle_type = "ICE"
    else:
        vehicle_type = "Unknown" # 위에서 처리했으므로 여기에 올 일은 거의 없음

    # 차량 번호 파싱하여 폴더 구조에 사용할 부분 추출
    match = re.match(r'^(\d{2,3}|[가-힣]{2}\d{1,2})([가-힣])(\d{4})$', plate_text)
    part1, part2, part3 = 'Unknown', 'Unknown', 'Unknown' # 기본값 설정
    if match:
        part1 = match.group(1)
        part2 = match.group(2)
        part3 = match.group(3)
    else:
        logger.warning(f"번호판 형식 오류: {plate_text}. 폴더 구조에 기본값 'Unknown' 사용.")


    # 이미지 저장 경로 설정
    root = config['car_image_save_path']
    base_path = os.path.join(root, vehicle_type, part1, part2, part3)
    os.makedirs(base_path, exist_ok=True) # 대상 폴더 생성

    # 원본 파일 이름을 사용하여 이동할 파일 경로 설정
    temp_car_image_save_path = config['temp_car_image_save_path']
    temp_file_path = os.path.join(temp_car_image_save_path, car_filename) # car_filename은 verify_entry에서 넘어온 원본 파일 이름

    # 최종 저장 경로 (원본 파일 이름을 유지)
    final_save_path = os.path.join(base_path, car_filename)

    # 파일 이동
    if os.path.isfile(temp_file_path):
        try:
            shutil.move(temp_file_path, final_save_path)
            logger.info(f"차량 {plate_text} ('{powertrain_to_use_for_folder}') 입차 확인. '{vehicle_type}' 폴더로 이동 완료.")
        except Exception as e:
            logger.error(f"차량 {plate_text} 파일 이동 오류: {e}")
    else:
        logger.warning(f"차량 {plate_text} 입차 확인. TEMP 폴더에서 원본 파일 '{car_filename}' 찾을 수 없음.")


# MISRECOG 이동 처리
def get_misrecog_target_path(misrecog_base_path, file_limit=10000):
    """ANPR_IMG 폴더에 MISRECOG 및 하위 폴더 경로를 결정"""
    # ... (기존 코드 유지) ...
    parent_path = os.path.dirname(misrecog_base_path) # misrecog_base_path의 부모 디렉토리
    base_name = os.path.basename(misrecog_base_path) # MISRECOG 기본 이름

    # 기본 MISRECOG 폴더 확인
    try:
        # 폴더가 없으면 빈 리스트 반환하도록 예외 처리 추가
        file_count_original = len(os.listdir(misrecog_base_path)) if os.path.exists(misrecog_base_path) else 0
        # logger.info(f"기본 {base_name} 폴더 파일 수: {file_count_original}") # 너무 많은 로그 방지
        if file_count_original < file_limit:
            # logger.info(f"대상 폴더: {misrecog_base_path}") # 너무 많은 로그 방지
            return misrecog_base_path
        else:
            subfolder_index = 2
            while True:
                subfolder_name = f"{base_name}{subfolder_index}"
                subfolder_path = os.path.join(parent_path, subfolder_name)
                os.makedirs(subfolder_path, exist_ok=True) # 하위 폴더 생성
                subfolder_file_count = len(os.listdir(subfolder_path)) if os.path.exists(subfolder_path) else 0 # 폴더 존재 여부 확인
                # logger.info(f"{subfolder_name} 폴더 파일 수: {subfolder_file_count}") # 너무 많은 로그 방지
                if subfolder_file_count < file_limit:
                    # logger.info(f"대상 폴더: {subfolder_path}") # 너무 많은 로그 방지
                    return subfolder_path
                subfolder_index += 1
    except Exception as e:
        logger.error(f"MISRECOG 대상 경로 결정 오류: {e}")
        # 오류 발생 시 기본 MISRECOG 경로 반환 (안전 장치)
        return misrecog_base_path


def entry_cancel(car_filename, config): # config 인자 추가
    """주차 미확인 및 시간 초과 시 TEMP > MISRECOG로 이미지 이동"""
    logger.info(f"입차 취소 처리: 파일 '{car_filename}'")
    temp_car_image_save_path = config['temp_car_image_save_path']
    misrecog_base_path = config['misrecog_car_image_save_path']
    temp_file_path = os.path.join(temp_car_image_save_path, car_filename)

    target_misrecog_path = get_misrecog_target_path(misrecog_base_path)
    misrecog_file_path = os.path.join(target_misrecog_path, car_filename) # 원본 파일 이름 유지

    # 대상 폴더는 get_misrecog_target_path에서 생성하므로 여기서 또 생성할 필요는 없지만, 안전을 위해 그대로 둡니다.
    # os.makedirs(target_misrecog_path, exist_ok=True)

    if os.path.isfile(temp_file_path):
        try:
            shutil.move(temp_file_path, misrecog_file_path)
            logger.info(f"파일 '{car_filename}' MISRECOG으로 이동 완료: {misrecog_file_path}")
        except Exception as e:
            logger.error(f"파일 '{car_filename}' MISRECOG 이동 오류: {e}")
    else:
        logger.warning(f"MISRECOG 이동 대상 파일 '{car_filename}' TEMP 폴더에서 찾을 수 없음.")


# 카메라 영상 처리 (주차 입차 검증 및 파일 분류) - 메인 로직
def verify_entry(db_connection, cursor, car_list, config): # config 인자 추가
    execution_times = []
    processed_count = 0

    for car_filename in car_list: # 변수명 변경
        processed_count += 1
        logger.info(f"처리 중 파일 ({processed_count}/{len(car_list)}): '{car_filename}'")
        
        try:
            # 파일 이름 파싱하여 차량 번호, 파워트레인(파일명 기반), 입차시간 추출
            plate_text, powertrain_from_filename, entry_datetime = parse_filename(car_filename)

            four_digits = plate_text[-4:]
            # 차량 번호 4자리를 사용하여 AMANO API 조회
            api_start_time = time.time()
            car_loc = get_parking_status(four_digits)
            api_end_time = time.time()
            execution_time = api_end_time - api_start_time
            execution_times.append(execution_time)

            car_found_in_amano = False
            # AMANO API 응답 처리
            if car_loc and car_loc.get("status") == "200" and car_loc.get("data") and car_loc["data"].get("success"):
                # AMANO API가 성공적으로 응답하고 데이터가 있는 경우
                if car_loc["data"].get("carList"): # carList가 비어있지 않은지 확인
                    for amano_car_info in car_loc["data"]["carList"]:
                        # AMANO 응답의 차량 번호와 파일명에서 파싱한 전체 차량 번호 일치 확인
                        if amano_car_info.get("carNo") == plate_text: # .get()으로 안전하게 접근
                            car_found_in_amano = True
                            # 입차 확정 처리 (entry_confirm 함수 호출)
                            entry_confirm(db_connection, cursor, car_filename, plate_text, powertrain_from_filename, entry_datetime, config) # config 전달
                            break # 차량을 찾았으므로 루프 종료
                else:
                    logger.info(f"차량 {plate_text} AMANO API 응답에 carList 비어있음.")
            elif car_loc and car_loc.get("status") != "200":
                logger.warning(f"차량 {plate_text} AMANO API 응답 상태 오류: {car_loc.get('status')} - {car_loc.get('message')}")
            elif car_loc is None:
                logger.error(f"차량 {plate_text} AMANO API 호출 결과 None 반환.")
            else: # 기타 AMANO API 응답 실패 (e.g., "success": false)
                logger.warning(f"차량 {plate_text} AMANO API 응답 실패: {car_loc.get('message')}")


            # 차량 위치가 AMANO에서 확인되지 않은 경우
            if not car_found_in_amano:
                # 입차 시간으로부터 자동 출차 대기 시간 경과 확인
                auto_exit_minutes = config['auto_exit_minutes']
                # 파일명 입차 시간과 현재 시간 비교
                time_since_entry = datetime.now() - entry_datetime
                if time_since_entry >= timedelta(minutes=auto_exit_minutes):
                    # 입차 취소 (MISRECOG으로 이동)
                    logger.info(f"차량 {plate_text} 주차 미확인 및 시간 초과 ({time_since_entry}). MISRECOG 이동.")
                    entry_cancel(car_filename, config) # config 전달
                # else: 차량이 주차되지 않았지만 아직 대기 시간 내이므로 TEMP에 그대로 둡니다.


        except ValueError as ve:
            # 파일명 파싱 오류 발생 시 에러 로그 남기고 해당 파일 건너뛰기
            logger.error(f"파일명 파싱 오류: '{car_filename}' - {ve}. 이 파일 건너뜁니다.")
            # 필요시 잘못된 형식의 파일을 별도의 에러 폴더로 이동시키는 로직 추가
            # try:
            #   error_dir = os.path.join(config['temp_car_image_save_path'], 'MALFORMED')
            #   os.makedirs(error_dir, exist_ok=True)
            #   shutil.move(os.path.join(config['temp_car_image_save_path'], car_filename), os.path.join(error_dir, car_filename))
            # except Exception as move_e:
            #   logger.error(f"잘못된 파일 '{car_filename}' 이동 오류: {move_e}")

        except Exception as e:
            # 기타 예상치 못한 오류 발생 시 로깅
            logger.error(f"'{car_filename}' 처리 중 예상치 못한 오류: {e}. 이 파일 건너뜁니다.")

    # API 호출 시간 평균 계산 및 로깅
    if execution_times:
        average_execution_time = sum(execution_times) / len(execution_times)
        logger.info(f"AMANO API 호출 평균 소요시간: {average_execution_time:.4f} seconds")
    else:
        logger.info("처리된 파일 중 AMANO API 호출 대상 없음.")


# 메인 함수 (기존 코드에서 복사하여 필요에 맞게 수정)
def main():
    logger.info("verify_entry 프로그램 실행 시작")
    main_start = time.time()

    global config
    config_path = 'config.json' # config.json 파일 경로
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        logger.error(f"설정 파일 '{config_path}'를 찾을 수 없습니다.")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"설정 파일 '{config_path}' JSON 디코딩 오류.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"설정 파일 로드 오류: {e}")
        sys.exit(1)


    # 데이터베이스 연결 및 커서 생성
    db_connection = connect_to_db()
    if db_connection is None:
        logger.error("데이터베이스 연결 실패. 프로그램 종료.")
        sys.exit(1)

    try:
        with db_connection.cursor() as cursor: # with 문을 사용하여 커서 자동 관리
            # 임시 폴더에서 차량 리스트 가져오기
            temp_car_image_save_path = config.get('temp_car_image_save_path')
            if not temp_car_image_save_path:
                logger.error("설정 파일에 'temp_car_image_save_path'가 지정되지 않았습니다.")
                sys.exit(1)

            if not os.path.isdir(temp_car_image_save_path):
                logger.warning(f"임시 폴더 '{temp_car_image_save_path}'를 찾을 수 없거나 디렉토리가 아닙니다.")
                car_list = [] # 폴더가 없으면 처리할 파일 목록은 비어있음
            else:
                car_list = get_all_filenames_from_directory(temp_car_image_save_path)

            logger.info(f"TEMP 폴더에서 찾은 파일 개수: {len(car_list)}")

            # 입차 검증 및 파일 분류 처리
            if car_list: # 처리할 파일이 있을 경우에만 verify_entry 호출
                verify_entry(db_connection, cursor, car_list, config) # config 전달


        # 데이터베이스 커밋 (오류 발생 시 롤백)
        logger.info("데이터베이스 커밋 시도")
        MAX_RETRIES = 5
        commit_retry_count = 0
        wait_time = 1

        while commit_retry_count < MAX_RETRIES:
            try:
                db_connection.commit()
                logger.info("데이터베이스 커밋 성공")
                break # 커밋 성공 시 루프 종료
            except pymysql.err.OperationalError as e:
                if e.args[0] == 1213: # deadlock error 발생 시 재시도
                    logger.warning(f'데이터베이스 커밋 실패 (데드락). 잠시 후 재시도 ({commit_retry_count+1}/{MAX_RETRIES}) - {e}')
                    db_connection.rollback() # 데드락 발생 시 롤백 후 재시도
                    time.sleep(wait_time)
                    commit_retry_count += 1
                    wait_time *= 2 # 대기 시간 증가
                else:
                    # 데드락 외 다른 OperationalError 발생 시 예외 다시 발생
                    logger.error(f"데이터베이스 커밋 실패 (OperationalError): {e}")
                    db_connection.rollback() # 오류 발생 시 롤백
                    raise # 예외 다시 발생

        if commit_retry_count == MAX_RETRIES:
            logger.error("데이터베이스 커밋 실패. 최대 재시도 횟수 초과.")
            db_connection.rollback() # 최종 실패 시 롤백

    except Exception as e:
        logger.error(f"verify_entry 메인 처리 중 오류 발생: {e}")
        # 예상치 못한 오류 발생 시 롤백
        if db_connection:
            db_connection.rollback()
            logger.info("데이터베이스 롤백 완료 (오류 발생).")

    finally:
        # 데이터베이스 연결 닫기
        if db_connection and db_connection.open: # 연결이 열려있는지 확인 후 닫기
            db_connection.close()
            logger.info("데이터베이스 연결 종료")

    main_end = time.time()
    logger.info(f"verify_entry 프로그램 실행 완료. 소요 시간: {main_end - main_start:.4f}초")


if __name__ == '__main__':
    # APScheduler 설정 (기존 코드 유지)
    # config 로드는 main 함수에서 수행
    try:
        temp_config_path = 'config.json' # 임시로 설정 파일 경로 지정 (main에서 다시 로드)
        # scheduler 설정 전에 최소한의 config 정보 로드 (cron 설정을 위해)
        if os.path.exists(temp_config_path):
            with open(temp_config_path, 'r', encoding='utf-8') as f:
                temp_config = json.load(f)
                verify_entry_cron_minute = temp_config.get('verify_entry_cron_minute', '3-59/5') # 기본값 설정
        else:
            logger.error(f"임시 설정 파일 '{temp_config_path}'를 찾을 수 없습니다. 스케줄러를 기본 설정으로 시작합니다.")
            verify_entry_cron_minute = '3-59/5' # 기본값

        scheduler = BackgroundScheduler()
        # main 함수 호출 시 config는 main 함수 내에서 다시 로드
        scheduler.add_job(main, 'cron', minute=verify_entry_cron_minute)

        scheduler.start()
        logger.info("APScheduler 시작됨.")

        # 프로그램 종료 방지
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        logger.info("프로그램 종료 요청됨.")
        scheduler.shutdown()
        logger.info("APScheduler 종료됨.")
