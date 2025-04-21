import requests
from collections import defaultdict
import pymysql
import json
import base64
import time
import datetime
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

# 설정 값
config = {}

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

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

# 특정 시간 모니터링 차량 조회
def count_cars_by_time(cursor, target_time):
    # target_time의 분까지만 비교하도록 포맷팅
    target_time_str = target_time.strftime('%Y-%m-%d %H:%M')
    
    query = """
    SELECT COUNT(cm.plateNumber)
    FROM car_monitoring cm
    WHERE DATE_FORMAT(cm.enterTime, '%%Y-%%m-%%d %%H:%%i') = %s
    """
    cursor.execute(query, (target_time_str,))
    result = cursor.fetchone()
    print('~~~~~~~~~~', result)
    
    return result[0] if result else 0

# 차량 위치 업데이트
def update_car_location(cursor, plateNumber, location):
    cursor.execute("UPDATE car_monitoring SET parkingPosition = %s WHERE plateNumber = %s", (location, plateNumber))
    return location

# 차량 출차 처리
def process_car_exit(cursor, plateNumber):
    cursor.execute("DELETE FROM car_monitoring WHERE plateNumber = %s", (plateNumber,))

# 차량 번호로 주차 위치 조회
def get_parking_status(carNo):

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
    
    body = {
	"lotAreaNo" : config['amano_lotAreaNo'],
	"carNo4Digit" : carNo
    }
    
    response = requests.post(url=url_getParkingLocation,headers=headers,data=json.dumps(body))

    return response.json()

def  get_parking_current_status():

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
    # url_getParkingLocationStatusList = config['amano_url_getParkingLocationStatusList']
    url_getParkingCurrentStatus = config['amano_url_getParkingCurrentStatus']
    body = {
	"lotAreaNo" : config['amano_lotAreaNo']
    }
    
    response = requests.post(url=url_getParkingCurrentStatus,headers=headers,data=json.dumps(body))

    return response.json()

def post_parking_current_status():
    timestamp_msec = int(time.time() * 1000)

    # Thingsboard post data format
    post_data = {}
    post_data['ts'] = timestamp_msec
    post_data['values'] = {'totalParkingSpace':0, 'totalOccupancy':0}

    result = get_parking_current_status()

    post_data['values']['totalParkingSpace'] = result["data"]["totalParkingSpace"]
    post_data['values']['totalOccupancy'] = result["data"]["totalOccupancy"]

    for section in result["data"]["sections"]:
        levelNo = section['levelNo']
        post_data['values'][levelNo] = section

    tb_url = config['tb_url']
    parking_status_token = config['parking_status_token']
    parking_status_url = tb_url.format(parking_status_token)
    httpPostDataToThingboard(parking_status_url, post_data)



def make_post_data(cursor, car_list):
    
    timestamp_msec = int(time.time() * 1000)

    # Thingsboard post data format
    post_data = {}
    post_data['ts'] = timestamp_msec
    post_data['values'] = {'ev': {}, 'general': {}}

    count_post_data = {}
    count_post_data['ts'] = timestamp_msec
    count_post_data['values'] = {
        'all_total': 0,
        'all_general': 0,
        'all_ev': 0,
        'B2_total': 0,
        'B2_general': 0,
        'B2_ev': 0,
        'B3_total': 0,
        'B3_general': 0,
        'B3_ev': 0,
        'B4_total': 0,
        'B4_general': 0,
        'B4_ev': 0,
        'QF_total': 0,
        'QF_general': 0,
        'QF_ev': 0
    }
    auto_exited_cars = []
    waiting_for_parking_cars = []
    exited_cars = []
    location_counter = {}
    
    for plate_number, car_info in car_list.items():
        four_digits = plate_number[-4:]

        # 차량 위치 정보 조회
        car_loc = get_parking_status(four_digits)
        enterTs = car_info['enterTime'].strftime("%Y-%m-%d %H:%M:%S")
        
        if car_loc["status"] == "200" and car_loc["data"]["success"]:
            car_found = False
            for car in car_loc["data"]["carList"]:
                # 차량 번호 4자리 포함 완전히 일치하는 경우
                if car["carNo"] == plate_number:
                    car_found = True
                    
                    # 차량 위치, 층 정보, 차량 번호 분리
                    location = car["location"]
                    level = car["levelNo"]
                    carnum = [plate_number[:-5], plate_number[-5], plate_number[-4:]]

                    # 차량 위치 업데이트
                    if car_info['parkingPosition'] != location or car_info['parkingPosition'] is None:
                        update_car_location(cursor, plate_number, location)

                    # 차종 코드에 따른 차종 분류
                    powerTrainTypeCode = car_info['powerTrainTypeCode']
                    if powerTrainTypeCode == b'\x00':
                        powerTrainType = "BEV"
                    elif powerTrainTypeCode == b'\x01':
                        powerTrainType = "PHEV"
                    elif powerTrainTypeCode == b'\x02':
                        powerTrainType = "HEV"
                    elif powerTrainTypeCode == b'\x03':
                        powerTrainType = "FCEV"
                    elif powerTrainTypeCode == b'\x04':
                        powerTrainType = "EREV"
                    elif powerTrainTypeCode == b'\x10':
                        powerTrainType = "ICE"
                    else:
                        continue  # Unknown powerTrainTypeCode, skip this car
                    
                    # 주차 위치 기둥별 번호 부여
                    if location not in location_counter:
                        location_counter[location] = 1
                    else:
                        location_counter[location] += 1
                    
                    numbered_location = f"{location}-{location_counter[location]}"
                    
                    car_data = {
                        "carnum": carnum,
                        "powerTrainType": powerTrainType,
                        "enterTs": enterTs
                    }

                    # 해당 층이 없을 경우 추가
                    if f'{level}_total' not in count_post_data['values']:
                        count_post_data['values'][f'{level}_total'] = 0
                        count_post_data['values'][f'{level}_ev'] = 0
                        count_post_data['values'][f'{level}_general'] = 0

                    # 차량 종류별 카운트, post data에 추가
                    count_post_data['values']['all_total'] += 1
                    count_post_data['values'][f'{level}_total'] += 1

                    if powerTrainType in ["BEV", "PHEV", "HEV", "FCEV", "EREV"]:
                        post_data['values']['ev'][numbered_location] = car_data
                        count_post_data['values']['all_ev'] += 1
                        count_post_data['values'][f'{level}_ev'] += 1
                    elif powerTrainType == "ICE":
                        post_data['values']['general'][numbered_location] = car_data
                        count_post_data['values']['all_general'] += 1
                        count_post_data['values'][f'{level}_general'] += 1

            # 차량 정보가 조회되지 않은 경우
            if not car_found:
                if car_info['parkingPosition'] is None:
                    enter_time = datetime.strptime(enterTs, "%Y-%m-%d %H:%M:%S")
                    auto_exit_minutes = config['auto_exit_minutes']
                    auto_exit_time = enter_time + timedelta(minutes=auto_exit_minutes)
                    current_time = datetime.now()

                    # 입차로부터 n분 지난 경우 자동 출차 처리
                    if current_time > auto_exit_time:
                        process_car_exit(cursor, plate_number)
                        auto_exited_cars.append(plate_number)
                    # 입차 대기
                    waiting_for_parking_cars.append(plate_number)
                else:
                    # 차량 출차 처리
                    process_car_exit(cursor, plate_number)
                    exited_cars.append(plate_number)

    if auto_exited_cars:
        print(f"1H has passed. Cars exited the parking lot: {', '.join(auto_exited_cars)}")
    if waiting_for_parking_cars:
        print(f"Cars waiting for parking: {', '.join(waiting_for_parking_cars)}")
    if exited_cars:
        print(f"Cars exited the parking lot: {', '.join(exited_cars)}")

    return post_data, count_post_data

# Post data to Thingsboard
def httpPostDataToThingboard(url_host:str,post_data:dict) -> requests.models.Response:
    header = {
            "accept": "application/json",
            "Content-Type": "application/json"
    }
    response = requests.post(url_host, data=json.dumps(post_data), headers=header)
    return response

# 분당 입차하는 차량 대수 카운트
def count_new_entries():
    
    now = datetime.now()
    target_time = now - timedelta(minutes=1)
    target_time_msec = int(target_time.timestamp() * 1000)

    # 데이터베이스 연결 및 커서 생성
    db_connection = connect_to_db()
    cursor = db_connection.cursor()

    count = 0

    # 해당 시간(1분간격)에 입차한 차량 대수 조회
    count = count_cars_by_time(cursor, target_time)

    # Thingsboard post data format
    post_data = {}
    post_data['ts'] = target_time_msec
    post_data['values'] = {'count_1min': count}
    
    # tb post data 전송
    tb_url = config['tb_url']
    count_new_entries_token = config['count_new_entries_token']

    count_new_entries_url = tb_url.format(count_new_entries_token)

    httpPostDataToThingboard(count_new_entries_url, post_data)

    # db 연결 종료
    db_connection.commit()
    cursor.close()
    db_connection.close()




def main():
    global config

    # 데이터베이스 연결 및 커서 생성
    db_connection = connect_to_db()
    cursor = db_connection.cursor()

    car_list = {}

    # 모니터링 대상 차량 목록 조회
    car_list = get_car_list(cursor)

    # tb post data 생성
    post_data, count_post_data = make_post_data(cursor, car_list)
    
    # tb post data 전송
    tb_url = config['tb_url']
    parking_data_test_token = config['parking_data_test_token']
    ev_monitoring_token = config['ev_monitoring_token']

    parking_data_url = tb_url.format(parking_data_test_token)
    ev_monitoring_url = tb_url.format(ev_monitoring_token)

    httpPostDataToThingboard(parking_data_url, post_data)
    httpPostDataToThingboard(ev_monitoring_url, count_post_data)

    # db 연결 종료
    db_connection.commit()
    cursor.close()
    db_connection.close()


if __name__ == "__main__":
    config_path = 'config.json'
    config = load_config(config_path)
    monitoring_cron_minute = config['monitoring_cron_minute']

    scheduler = BackgroundScheduler()
    scheduler.add_job(main, 'cron', minute = monitoring_cron_minute)
    scheduler.add_job(post_parking_current_status, 'cron', minute='*')
    scheduler.add_job(count_new_entries, 'cron', minute='*')

    scheduler.start()

    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()