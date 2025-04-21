import requests
import sys
import json
import base64
import time
import psutil
import pymssql
from datetime import datetime, timedelta
import numpy as np
import pymysql

# 설정 값
config = {}

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

# Mssql 데이터베이스 연결 설정
mssql_conn = pymssql.connect(
    server='192.168.51.10',
    user='aseman',
    password='aseman123!',
    database='FC_TRNS',
    port=1433
)
mssql_cursor = mssql_conn.cursor()

# MySQL 연결
def connect_to_db():
    try:
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

# 모니터링 리스트에 추가
def add_to_monitoring_list_with_position(cursor, plate_text, powertrainTypeCode, entry_datetime, parking_position):
    # current_time = time.strftime('%Y-%m-%d %H:%M:%S')
    # SQL 쿼리 작성
    print(f'{plate_text}, {powertrainTypeCode}, {entry_datetime}, {parking_position} 데이터를 삽입')
    sql_insert_query = """INSERT IGNORE INTO car_monitoring (plateNumber, powertrainTypeCode, enterTime, parkingPosition) VALUES (%s, %s, %s, %s)"""
    cursor.execute(sql_insert_query, (plate_text, powertrainTypeCode, entry_datetime, parking_position))


# car_info 테이블에서 차량 정보 조회
def check_car_info(cursor, plate_text):
    sql_select_query = """SELECT plateNumber, powertrainTypeCode FROM car_info WHERE plateNumber = %s"""
    cursor.execute(sql_select_query, (plate_text,))
    result = cursor.fetchone()

    if result is None:
        return b"\0x99"
    else:
        plateNumber, powertrainTypeCode = result
        return powertrainTypeCode


# 현재 모니터링 차량 목록 조회
def get_car_list(cursor):
    query = """
    SELECT cm.plateNumber, cm.enterTime, cm.parkingPosition, ci.powerTrainTypeCode
    FROM car_monitoring cm
    JOIN car_info ci ON cm.plateNumber = ci.plateNumber
    """
    cursor.execute(query)
    current_data = cursor.fetchall()
    car_list = {}
    for plateNumber, enterTime, parkingPosition, powerTrainTypeCode in current_data:
        car_list[plateNumber] = {
            'enterTime': enterTime,
            'parkingPosition': parkingPosition,
            'powerTrainTypeCode': powerTrainTypeCode
        }
    return car_list


def process():
    process_start_time = time.time()

    # 유종 기본값 설정
    DEFAULT_POWERTRAIN_TYPE = "Unknown"
    DEFAULT_POWERTRAIN_TYPECODE = b"\0x99"

    # AMANO API 연결
    userid = config['amano_userid']
    userpw = config['amano_userpw']

    # base64 encoding
    string = userid+':'+userpw
    string_bytes = string.encode('UTF-8')
    result = base64.b64encode(string_bytes)
    result_str = result.decode('ascii')

    headers = {
        "Authorization": f"Basic {result_str}"
    }
    url_getParkingLocation = config['amano_url_getParkingLocation']
    carNo = "0000"
    body = {
	"lotAreaNo" : config['amano_lotAreaNo'],
	"carNo4Digit" : carNo
    }

    # 현재 모니터링 리스트 출력
    conn = connect_to_db()
    cursor = conn.cursor()
    current_monitoring_car_list = get_car_list(cursor)
    #print(current_monitoring_car_list)
    #print(len(current_monitoring_car_list))
#    conn.close()

    # 현재 모니터링 리스트 내의 차량번호 unique list 추출
    current_platenumber_list = list(current_monitoring_car_list.keys())
    #print(current_platenumber_list)
    print(len(current_platenumber_list))
    #sys.exit(0)

    # AMANO DB에서 현재시간부터 12시간 전가지의 출차처리되지 않은 입차된 차량 현황 조회 - 주차관제 모니터링 후보군
    datetime_now = datetime.now()
    datetime_start = datetime_now - timedelta(hours=72)
    datetime_start = datetime_start.strftime('%Y-%m-%dT%H:%M:%SZ')
    print(datetime_start)
    query = f"SELECT * FROM V_TotalParkTrns WHERE iInOutStatus=0 and iLotArea=30 and DbTableName='TCKTTRNS' and dtInDate>='{datetime_start}' and dtOutDate IS NULL"
    mssql_cursor.execute(query)
    # 조회 현황 결과 출력
    mssql_db_result = mssql_cursor.fetchall()
    mssql_conn.close()
    # 차량번호 뒷 네자리 추출
    #aaaa = time.time()
    search_target_result = []


    #print(current_platenumber_list)
    #sys.exit(0)

    print(f'original length : {len(mssql_db_result)}')

    for plate_number in range(101,10000):
        plate_number_str = f"{plate_number:04d}"
        #print(plate_number_str)

        api_start = time.time()
        # 네트워크 트래픽 확인
        body["carNo4Digit"] = plate_number_str
        response = requests.post(url=url_getParkingLocation,headers=headers,data=json.dumps(body))
        car_loc = response.json()

#        print(car_loc)
        time.sleep(0.01)

        if car_loc["status"] == "200" and car_loc["data"]["success"]:

            # carList에 차량이 없으면 다음 차량 번호로 이동
            if len(car_loc["data"]["carList"]) == 0:
                print(f'{plate_number:04d} Cannot Find. pass')
                continue

            for car in car_loc["data"]["carList"]:
                # 차량 위치, 층 정보 저장
                location = car["location"]
                if location=="타워":
                    print("타워 주차위치는 pass!")
                    continue
                # level = car["levelNo"]
                parkingTime = car["parkingTime"]
                carNo = car["carNo"]
                if carNo in current_platenumber_list:
                    print(f'{carNo}는 이미 모니터링 대상이야.')
                    continue
                # carnum = [plate_number[:-5], plate_number[-5], plate_number[-4:]]
                print(f'{plate_number}  /  {location}')

                # 주차관제 DB에서 차량 정보 조회
                powertrainTypeCode = check_car_info(cursor,carNo)

                if not powertrainTypeCode:
                    # 조회 결과가 없으면 기본값 사용
                    result = {
                        "plateNumber": carNo,
                        "parkingPosition": location,
                        "enterTime": parkingTime,
                        "powertrainTypeCode": DEFAULT_POWERTRAIN_TYPECODE
                    }
                else:
                    # 조회 결과가 있으면 유종 정보 사용
#                    if powertrainTypeCode == b'\x00':
#                        vehicle_type = "EV"
#                    elif powertrainTypeCode == b'\x10':
#                        vehicle_type = "ICE"
#                    else:
#                        vehicle_type = "Unknown"
                    result = {
                        "plateNumber": carNo,
                        "parkingPosition": location,
                        "enterTime": parkingTime,
                        "powertrainTypeCode": powertrainTypeCode
                    }
                print(result)
                overall_result.append(result)

    print('------------')
    for data in overall_result:
        #print(data)
        plate_text = data['plateNumber']
        powertrainTypeCode = data['powertrainTypeCode']
        entry_datetime = data['enterTime']
        parking_position = data['parkingPosition']

        add_to_monitoring_list_with_position(cursor, plate_text, powertrainTypeCode, entry_datetime, parking_position)
        #conn.close()
        #sys.exit(0)
        
        # 0420 add
        
    while True:
        try:
            conn.commit()
            print("commit success") # 기존에 print("commit success") 같은 메시지가 있었다면
            # --- 최종 차량 대수 조회 및 출력 코드 시작 ---
            try:
                # 기존 커서 (cursor)를 재사용해도 되지만, 안전하게 새로운 커서 사용 권장
                with conn.cursor() as final_count_cursor: # conn 대신 db_connection 변수 사용 (process 함수 안에서는 conn)
                    sql_count_query = "SELECT COUNT(*) FROM car_monitoring"
                    final_count_cursor.execute(sql_count_query)
                    final_count_result = final_count_cursor.fetchone()

                    if final_count_result:
                        # 결과에서 COUNT(*) 값 추출 (커서 종류에 따라 다름)
                        # 이 코드에서는 기본 cursor를 사용하는 것으로 보이므로 튜플 형태일 가능성 높음
                        count_value = final_count_result[0] if isinstance(final_count_result, (list, tuple)) else final_count_result # 안전하게 값 추출
                        print(f"로컬 DB car_monitoring 테이블 최종 차량 대수: {count_value}") # print 대신 logger 사용 가능
                    else:
                        print("로컬 DB car_monitoring 테이블 대수 조회 결과 없음.") # print 대신 logger 사용 가능
            except Exception as count_error:
                print(f"로컬 DB car_monitoring 테이블 대수 조회 오류: {count_error}") # print 대신 logger 사용 가능
            # --- 최종 차량 대수 조회 및 출력 코드 끝 ---

            break # 커밋 성공 시 재시도 루프 종료
        except Exception as e:
            # ... (오류 처리 및 재시도 로직) ...
            print(e)
            print('Wait 5 seconds...')
            time.sleep(5)
    # conn.close() # 연결 종료는 루프 밖에서 이루어짐)

    # 프로그램 종료
    process_end_time = time.time()
    print(f'Overall elapsed time : {process_end_time - process_start_time} sec')
    sys.exit(0)


if __name__ == "__main__":
    # config_path = 'config.json' # 기존 상대 경로

    # --- config.json 파일의 절대 경로 사용 ---
    # 현재 실행 중인 스크립트 파일의 절대 경로를 가져와서 config.json 경로를 구성
    script_directory = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_directory, 'config.json')
    # --- 절대 경로 사용 끝 ---

    # config 파일 로드
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        print(f"오류: 설정 파일 '{config_path}'를 찾을 수 없습니다. 프로그램 종료.") # logger 대신 print
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"오류: 설정 파일 '{config_path}' JSON 디코딩 오류.") # logger 대신 print
        sys.exit(1)
    except Exception as e:
        print(f"오류: 설정 파일 로드 중 예상치 못한 오류: {e}") # logger 대신 print
        sys.exit(1)


    # 전체 결과를 저장할 리스트
    overall_result = []
    overall_result = process() # process 함수는 위에서 정의됨
