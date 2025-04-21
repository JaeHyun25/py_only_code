#!/usr/bin/env python3
import os
import json

target_dir = "/home/evmonitoringadmin/Workspace/ANPR/python/ev_detect/uncertain_cases/20250417"
count = 0

if os.path.isdir(target_dir):
    for filename in os.listdir(target_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(target_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    detection_result = data.get("detection_result")
                    if detection_result:
                        ev_value = detection_result.get("ev")
                        if ev_value is True or ev_value == "true" or ev_value =="True":
                            count += 1
            except FileNotFoundError:
                print(f"파일을 찾을 수 없습니다: {filepath}")
            except json.JSONDecodeError:
                print(f"JSON 디코딩 오류: {filepath}")
            except Exception as e:
                print(f"기타 오류 발생: {filepath} - {e}")

print(f"20250417 폴더 내에서 detection_result.ev 값이 True인 JSON 파일 개수: {count}")
