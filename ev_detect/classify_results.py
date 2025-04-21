#!/usr/bin/env python3
import os
import json
import shutil

base_dir = "/home/evmonitoringadmin/Workspace/ANPR/python/ev_detect/uncertain_cases/"
output_base_dir = "/home/evmonitoringadmin/Workspace/ANPR/python/ev_detect/" # 결과 폴더를 현재 실행 폴더 아래 생성

target_date_dir = os.path.join(base_dir, "20250417")
ts_ev_my_ice_dir = os.path.join(base_dir, "TS_EV_My_ICE")
ts_ice_my_ev_dir = os.path.join(base_dir, "TS_ICE_My_EV")
ts_ev_my_ev_dir = os.path.join(base_dir, "TS_EV_My_EV")

# 결과 폴더 생성 (이미 존재하면 무시)
os.makedirs(ts_ev_my_ice_dir, exist_ok=True)
os.makedirs(ts_ice_my_ev_dir, exist_ok=True)
os.makedirs(ts_ev_my_ev_dir, exist_ok=True)

if os.path.isdir(target_date_dir):
    for filename in os.listdir(target_date_dir):
        if filename.endswith(".json"):
            json_filepath = os.path.join(target_date_dir, filename)
            image_filename = filename.replace(".json", ".jpg")
            image_filepath = os.path.join(target_date_dir, image_filename)

            try:
                with open(json_filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    ts_ev = data.get("input_plate_info", {}).get("attrs", {}).get("ev")
                    # 사용자님 모델 결과는 "detection_result" 아래 "ev"에 있습니다.
                    my_ev = data.get("detection_result", {}).get("ev")

                    if ts_ev is not None and my_ev is not None:
                        target_dir = None
                        if ts_ev and not my_ev:
                            target_dir = ts_ev_my_ice_dir
                        elif not ts_ev and my_ev:
                            target_dir = ts_ice_my_ev_dir
                        elif ts_ev and my_ev:
                            target_dir = ts_ev_my_ev_dir

                        if target_dir:
                            try:
                                shutil.move(json_filepath, os.path.join(target_dir, filename))
                                if os.path.exists(image_filepath):
                                    shutil.move(image_filepath, os.path.join(target_dir, image_filename))
                                else:
                                    print(f"이미지 파일 {image_filepath}를 찾을 수 없습니다.")
                            except Exception as e:
                                print(f"파일 이동 오류: {e}")
                    else:
                        print(f"file: {filename}, TS EV OR My EV is nothinh.")
            except Exception as e:
                print(f"JSON 파일 처리 오류: {json_filepath} - {e}")
else:
    print(f"{target_date_dir} 폴더를 찾을 수 없습니다.")

print("분류 작업 완료.")
