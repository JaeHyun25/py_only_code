import requests
import sys
import json
import base64
import time
import psutil

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



# car_info 테이블에서 차량 정보 조회
def check_car_info(cursor, plate_text):

    sql_select_query = """SELECT plateNumber, powertrainTypeCode FROM car_info WHERE plateNumber = %s"""
    cursor.execute(sql_select_query, (plate_text,))
    result = cursor.fetchone()

    if result is None:
        return "NODATA"
    else:
        plateNumber, powertrainTypeCode = result
        return powertrainTypeCode


# 네트워크 트래픽 모니터링 함수
def get_network_usage():
    net_io = psutil.net_io_counters()
    return net_io.bytes_sent + net_io.bytes_recv

def process():

    # 유종 기본값 설정
    DEFAULT_POWERTRAIN_TYPE = "Unknown"

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


    # 차량 번호를 0000부터 9999까지 조회10000
    for plate_number in range(100):
        plate_number_str = f"{plate_number:04d}"

        api_start = time.time()

        # 네트워크 트래픽 확인

        body["carNo4Digit"] = plate_number_str
        initial_usage = get_network_usage()
        response = requests.post(url=url_getParkingLocation,headers=headers,data=json.dumps(body))
        final_usage = get_network_usage()
        network_usage = final_usage - initial_usage
        car_loc = response.json()

        print(f"Network usage: {network_usage} bytes.")
        api_end = time.time()
        print(f"API 호출 시간: {api_end - api_start}초")

        print(car_loc)
        time.sleep(0.1)
        """
        if car_loc["status"] == "200" and car_loc["data"]["success"]:

            # carList에 차량이 없으면 다음 차량 번호로 이동
            if len(car_loc["data"]["carList"]) == 0:
                continue

            for car in car_loc["data"]["carList"]:

                # 차량 위치, 층 정보 저장
                location = car["location"]
                # level = car["levelNo"]
                parkingTime = car["parkingTime"]
                carNo = car["carNo"]
                # carnum = [plate_number[:-5], plate_number[-5], plate_number[-4:]]
                
                # 주차관제 DB에서 차량 정보 조회
                db_result = 주차관제_db_차량정보조회(carNo)

                if not db_result:
                    # 조회 결과가 없으면 기본값 사용
                    result = {
                        "plateNumber": carNo,
                        "parkingPosition": location,
                        "enterTime": parkingTime,
                        "powertrainType": DEFAULT_POWERTRAIN_TYPE
                    }
                else:
                    # 조회 결과가 있으면 유종 정보 사용
                    powertrainTypeCode = db_result["powertrainTypeCode"]
                    # 유종 정보를 파악하는 로직 추가~~
                    powertrainType = "EV" if powertrainTypeCode == "EV" else "ICE"
                    result = {
                        "plateNumber": carNo,
                        "parkingPosition": location,
                        "enterTime": parkingTime,
                        "powertrainType": powertrainType
                    }
                
                overall_result.append(result)
                """

    # 전체 결과 출력
    # for res in overall_result:
        # print(res)

    # 프로그램 종료
    sys.exit(0)


if __name__ == "__main__":
    config_path = 'config.json'
    config = load_config(config_path)
    # 전체 결과를 저장할 리스트
    overall_result = []
    overall_result = process()
