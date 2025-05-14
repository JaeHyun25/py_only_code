import os
import json
import base64
import requests
import pymysql
from datetime import datetime
from tqdm import tqdm
import csv
from collections import defaultdict

# --- 설정 경로 ---
CONFIG_PATH = "/home/evmonitoringadmin/Workspace/ANPR/python/config.json"

# --- config.json 불러오기 ---
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

# --- AMANO 인증 정보 ---
AMANO_USER = config["amano_userid"]
AMANO_PASS = config["amano_userpw"]
LOT_AREA_NO = config["amano_lotAreaNo"]
URL_API1 = config["amano_url_getParkingLocation"]
URL_API3 = config["amano_url_getParkingLocationStatusList"]

# --- DB 설정 ---
DB_HOST = config["db_host"]
DB_USER = config["db_user"]
DB_PASSWORD = config["db_password"]
DB_NAME = config["db_name"]

# --- 인증 헤더 ---
HEADERS = {
    "Authorization": "Basic " + base64.b64encode(f"{AMANO_USER}:{AMANO_PASS}".encode()).decode(),
    "Content-Type": "application/json"
}

# --- API1: 4자리 차량번호 순회 조회 ---
def get_api1_locations():
    result = defaultdict(list)
    for i in tqdm(range(100, 10000), desc="API1 조회 중", dynamic_ncols=True):
        plate = f"{i:04d}"
        try:
            res = requests.post(
                URL_API1,
                headers=HEADERS,
                json={"lotAreaNo": LOT_AREA_NO, "carNo4Digit": plate},
                timeout=2
            )
            data = res.json()
            if data.get("status") == "200" and data["data"].get("success"):
                for car in data["data"].get("carList", []):
                    loc = car.get("location")
                    if loc and loc != "타워":
                        result[loc].append({
                            "plate": car.get("carNo"),
                            "time": datetime.strptime(car.get("parkingTime", ""), "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S"),
                            "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
        except:
            continue
    return result

# --- API3: 현재 점유중인 주차위치 ---
def get_api3_locations():
    try:
        res = requests.post(
            URL_API3,
            headers=HEADERS,
            json={"lotAreaNo": LOT_AREA_NO},
            timeout=5
        )
        data = res.json()
        if data.get("status") == "200" and data["data"].get("success"):
            return {
                loc["location"]: loc
                for loc in data["data"].get("locList", [])
                if loc.get("currentStatus")
            }
    except:
        pass
    return {}

# --- 메인 실행 ---
def main():
    print("[INFO] API1 / API3 / DB_SQL 수집 시작")

    api1 = get_api1_locations()
    print(f"[✔] API1 완료: {len(api1)}건")

    api3 = get_api3_locations()
    print(f"[✔] API3 완료: {len(api3)}건")

    # 병합 대상 위치 키
    all_keys = sorted(set(api1.keys()) | set(api3.keys()))

    # CSV 저장 경로
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    fname = f"/home/evmonitoringadmin/Workspace/ANPR/python/compare_api1_api3_db_sql_{date_str}.csv"

    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Location",
            "API1_CarPlate", "API1_ParkingTime", "API1_QueryTime",
            "API3_Occupied",
            "DB_CarPlate_SQL", "DB_EnterTime_SQL"
        ])

        for loc in tqdm(all_keys, desc="CSV 작성 중", dynamic_ncols=True):
            api1_plate = "\n".join([entry["plate"] for entry in api1.get(loc, [])])
            api1_time = "\n".join([entry["time"] for entry in api1.get(loc, [])])
            api1_query_time = "\n".join([entry["query_time"] for entry in api1.get(loc, [])])
            occupied = "TRUE" if loc in api3 else ""

            db_plate_sql = ""
            db_time_sql = ""

            try:
                conn = pymysql.connect(
                    host=DB_HOST, user=DB_USER,
                    password=DB_PASSWORD, database=DB_NAME
                )
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT plateNumber, enterTime FROM car_monitoring WHERE parkingPosition = %s",
                    (loc,)
                )
                rows = cursor.fetchall()
                if rows:
                    plates = [r[0] for r in rows]
                    times = [
                        r[1].strftime("%Y-%m-%d %H:%M:%S") if isinstance(r[1], datetime) else str(r[1])
                        for r in rows
                    ]
                    db_plate_sql = "\n".join(plates)
                    db_time_sql = "\n".join(times)
                cursor.close()
                conn.close()
            except Exception as e:
                print(f"[ERROR] SQL 직접조회 실패 ({loc}): {e}")

            writer.writerow([
                loc,
                api1_plate, api1_time, api1_query_time,
                occupied,
                db_plate_sql, db_time_sql
            ])

    print(f"[완료] CSV 저장됨: {fname}")

if __name__ == "__main__":
    main()
