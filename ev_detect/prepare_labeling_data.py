#!/usr/bin/env python3
import os
import json
from datetime import datetime
import shutil
import csv
import glob
import re
import sys

# --- 설정 (필요에 따라 경로 수정) ---

# 사용자 홈 디렉토리 경로를 동적으로 가져오기 (예: /home/evmonitoringadmin)
HOME_DIR = os.path.expanduser("~")

# 프로젝트 Workspace 경로 (홈 디렉토리 기준)
WORKSPACE_BASE = os.path.join(HOME_DIR, "Workspace", "ANPR", "python")

# ANPR_IMG 기본 경로 (홈 디렉토리 기준 또는 절대 경로)
ANPR_IMG_BASE = os.path.join(HOME_DIR, "ANPR_IMG")


# 종합 로그 파일 기본 저장 디렉토리 (Workspace 기준)
COMPREHENSIVE_LOG_BASE_DIR = os.path.join(WORKSPACE_BASE, "ev_detect", "logs", "comprehensive_predictions")


# --- 처리할 날짜 결정 (명령행 인자 사용) ---
# 스크립트 실행 시 날짜를 YYYYMMDD 형식으로 명령행 인자로 받습니다.
if len(sys.argv) > 1:
    # 명령행 인자가 제공되면 해당 날짜 사용
    date_to_process_str = sys.argv[1]
    # 날짜 형식 검증 (YYYYMMDD)
    try:
        datetime.strptime(date_to_process_str, '%Y%m%d') # YYYYMMDD 형식인지 확인
        selected_date_str = date_to_process_str
    except ValueError:
        print("오류: 유효하지 않은 날짜 형식입니다. YYYYMMDD 형식으로 입력해주세요.")
        print(f"사용법: python {sys.argv[0]} [YYYYMMDD]")
        sys.exit(1) # 날짜 형식이 잘못되면 스크립트 종료
else:
    # 명령행 인자가 없으면 오늘 날짜 사용 (기본값)
    selected_date_str = datetime.now().strftime('%Y%m%d')
    print(f"날짜가 지정되지 않았습니다. 오늘 날짜 ({selected_date_str}) 데이터로 처리합니다.")

# 종합 로그 파일 경로 (선택된 날짜 기준)
JSONL_FILE_PATH = os.path.join(COMPREHENSIVE_LOG_BASE_DIR, selected_date_str, "predictions.jsonl")


# 이미지 원본 폴더들의 정확한 절대 경로 설정
TEMP_FOLDER = os.path.join(ANPR_IMG_BASE, "TEMP")
MISRECOG_BASE_FOLDER_PATTERN = os.path.join(ANPR_IMG_BASE, "MISRECOG*") # MISRECOG, MISRECOG2 등을 찾기 위한 패턴
EV_FOLDER = os.path.join(ANPR_IMG_BASE, "EV")
ICE_FOLDER = os.path.join(ANPR_IMG_BASE, "ICE")


# 라벨링 데이터셋 기본 저장 폴더 (Workspace 아래에 생성)
LABELING_BASE_FOLDER = os.path.join(WORKSPACE_BASE, "labeling_dataset")

# --- 처리한 날짜별 라벨링 데이터셋 저장 폴더 정의 ---
# 라벨링 기본 저장 폴더 아래에 처리한 날짜 이름으로 폴더 생성
LABELING_OUTPUT_FOLDER = os.path.join(LABELING_BASE_FOLDER, selected_date_str)

# 라벨링 데이터셋 내 이미지 및 CSV 서브폴더 경로 정의
IMAGE_SUBFOLDER = os.path.join(LABELING_OUTPUT_FOLDER, "jpg")
CSV_SUBFOLDER = os.path.join(LABELING_OUTPUT_FOLDER, "csv")


# 결과 CSV 파일 경로 (CSV 서브폴더 안에 저장)
OUTPUT_CSV_FILE = os.path.join(CSV_SUBFOLDER, "labeling_data.csv")

# --- 라벨링 데이터셋 기본 저장 폴더 및 날짜별 서브폴더, 이미지/CSV 서브폴더 생성 ---
os.makedirs(LABELING_BASE_FOLDER, exist_ok=True) # 기본 라벨링 폴더
os.makedirs(LABELING_OUTPUT_FOLDER, exist_ok=True) # 날짜별 라벨링 폴더
os.makedirs(IMAGE_SUBFOLDER, exist_ok=True) # 이미지 서브폴더
os.makedirs(CSV_SUBFOLDER, exist_ok=True) # CSV 서브폴더


# --- CSV 헤더 정의 ---
csv_header = [
    'jsonl_timestamp',
    'plate_number',
    'ts_ev_prediction',
    'my_model_ev_prediction',
    'my_model_confidence',
    'model_used',
    'processing_time',
    'saved_in_uncertain',
    'image_source_folder', # 이미지가 발견된 원본 폴더 (TEMP, MISRECOG, MISRECOG2, EV, ICE 등)
    'copied_image_filename' # 라벨링 폴더(날짜별/jpg 서브폴더)로 복사된 이미지의 파일 이름 (csv 파일 기준 상대 경로)
]

# --- 이미지 정보 및 CSV 데이터 저장 리스트 ---
csv_data = []
csv_data.append(csv_header) # 헤더 추가

# --- 번호판 파싱 함수 ---
def parse_plate_for_folder(plate_text: str) -> tuple[str, str, str] | None:
    """번호판 텍스트를 폴더 구조에 사용할 부분으로 파싱"""
    match = re.match(r'^(\d{2,3}|[가-힣]{2}\d{1,2})([가-힣])(\d{4})$', plate_text)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return None

# --- EV 또는 ICE 폴더 구조 내에서 이미지 검색 함수 ---
def find_image_in_ev_ice(base_ev_ice_folder: str, plate_number: str, formatted_timestamp: str, predicted_powertrain_tag: str) -> str | None:
    """
    EV 또는 ICE 폴더 구조 (/BASE_FOLDER/part1/part2/part3/) 내에서 이미지를 검색합니다.
    """
    # 번호판 파싱하여 폴더 구조에 사용할 부분 추출
    plate_parts = parse_plate_for_folder(plate_number)
    if not plate_parts:
        return None # 파싱 실패 시 검색 불가

    part1, part2, part3 = plate_parts

    # 예상되는 하위 폴더 경로 구성
    plate_subfolder_path = os.path.join(base_ev_ice_folder, part1, part2, part3)

    # 해당 하위 폴더가 존재하는지 확인
    if not os.path.isdir(plate_subfolder_path):
        return None # 폴더 없으면 이미지도 없음

    # 예상되는 이미지 파일 이름 재구성 (TEMP, MISRECOG* 형식과 동일)
    expected_filename = f"{plate_number}_{predicted_powertrain_tag}_{formatted_timestamp}.jpg"

    # 구성한 하위 폴더 내에서 해당 파일 이름 검색
    full_expected_path = os.path.join(plate_subfolder_path, expected_filename)

    # 파일이 존재하는지 확인
    if os.path.exists(full_expected_path):
        return full_expected_path # 찾았으면 전체 경로 반환
    else:
        return None # 파일 없음

# --- JSONL 파일 읽기 및 처리 ---
processed_count = 0
found_image_count = 0
filtered_count = 0 # 필터링된 항목 개수 카운트

try:
    with open(JSONL_FILE_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            processed_count += 1
            try:
                log_entry = json.loads(line)

                # 필요한 정보 추출
                jsonl_timestamp_str = log_entry.get('timestamp')
                plate_number = log_entry.get('plate_number')
                my_model_ev_prediction = log_entry.get('my_model_ev_prediction')
                ts_ev_prediction = log_entry.get('ts_ev_prediction')
                my_model_confidence = log_entry.get('my_model_confidence')
                model_used = log_entry.get('model_used')
                processing_time = log_entry.get('processing_time')
                saved_in_uncertain = log_entry.get('saved_in_uncertain')

                # 필수 정보 누락 시 건너뛰기
                if not plate_number or not jsonl_timestamp_str or my_model_ev_prediction is None or ts_ev_prediction is None:
                    # TS 결과도 필수 정보로 추가
                    continue

                # --- 특정 판정 조합에 해당하는지 필터링 ---
                # {false, true}, {true, false}, {true, true} 조합만 포함
                include_in_csv = False
                if (ts_ev_prediction is False and my_model_ev_prediction is True): # TS:ICE, My:EV
                    include_in_csv = True
                elif (ts_ev_prediction is True and my_model_ev_prediction is False): # TS:EV, My:ICE
                    include_in_csv = True
                elif (ts_ev_prediction is True and my_model_ev_prediction is True): # TS:EV, My:EV (일치하는 EV 판정)
                    include_in_csv = True

                # 만약 {false, false}인 경우도 CSV에 포함하고 싶다면 아래 조건 추가:
                # elif (ts_ev_prediction is False and my_model_ev_prediction is False): # TS:ICE, My:ICE (일치하는 ICE 판정)
                #    include_in_csv = True


                if not include_in_csv:
                    continue # 필터링 조건 불만족 시 건너뛰기

                filtered_count += 1 # 필터링 통과 항목 카운트

                # JSONL 타임스탬프를 이미지 파일 이름 형식으로 변환 (YYYYMMDD_HHMMSS)
                try:
                    timestamp_obj = datetime.fromisoformat(jsonl_timestamp_str)
                    formatted_timestamp = timestamp_obj.strftime('%Y%m%d_%H%M%S')
                except ValueError:
                    print(f"오류: 로그 항목 건너뛰기 (잘못된 타임스탬프 형식): {line.strip()}")
                    continue

                # 사용자 모델 판정 결과에 따른 파워트레인 태그 (파일명에 사용될 것으로 예상되는 값)
                predicted_powertrain_tag = 'ev' if my_model_ev_prediction else 'ice'

                # --- 해당 이미지를 모든 예상 저장 폴더들에서 검색 ---
                found_image_path = None
                image_source_folder = None

                # 예상되는 이미지 파일 이름 재구성 (TEMP 및 MISRECOG* 형식)
                expected_filename_base = f"{plate_number}_{predicted_powertrain_tag}_{formatted_timestamp}.jpg"

                # 1. TEMP 폴더 검색
                temp_image_path = os.path.join(TEMP_FOLDER, expected_filename_base)
                if os.path.exists(temp_image_path):
                    found_image_path = temp_image_path
                    image_source_folder = "TEMP"

                # 2. MISRECOG* 폴더 검색
                if not found_image_path:
                    misrecog_folders = glob.glob(MISRECOG_BASE_FOLDER_PATTERN)
                    for misrecog_folder in misrecog_folders:
                         if os.path.isdir(misrecog_folder):
                            misrecog_image_path = os.path.join(misrecog_folder, expected_filename_base)
                            if os.path.exists(misrecog_image_path):
                                found_image_path = misrecog_image_path
                                image_source_folder = os.path.basename(misrecog_folder)
                                break # 찾았으면 더 이상 검색하지 않음


                # 3. EV 폴더 검색
                if not found_image_path:
                    found_image_path = find_image_in_ev_ice(EV_FOLDER, plate_number, formatted_timestamp, predicted_powertrain_tag)
                    if found_image_path:
                         image_source_folder = "EV"

                # 4. ICE 폴더 검색
                if not found_image_path:
                    found_image_path = find_image_in_ev_ice(ICE_FOLDER, plate_number, formatted_timestamp, predicted_powertrain_tag)
                    if found_image_path:
                         image_source_folder = "ICE"


                # --- 이미지를 찾았다면 라벨링 폴더(날짜별/jpg 서브폴더)로 복사하고 CSV 데이터 추가 ---
                if found_image_path:
                    found_image_count += 1
                    # 복사될 이미지 파일 이름 생성 (원본 출처 폴더와 원본 파일 이름 사용)
                    original_image_filename = os.path.basename(found_image_path)
                    copied_image_filename = f"{image_source_folder}_{original_image_filename}" # 예: EV_23바1234_ev_20250418_123456.jpg

                    # 이미지를 JPG 서브폴더에 저장
                    copied_image_full_path = os.path.join(IMAGE_SUBFOLDER, copied_image_filename)

                    try:
                        # 원본 파일을 JPG 서브폴더로 복사 (원본 보존)
                        shutil.copy(found_image_path, copied_image_full_path)

                        # CSV 데이터 리스트에 추가
                        # CSV에는 라벨링 폴더 기준 상대 경로를 기록 (날짜별 폴더/jpg 서브폴더 기준)
                        relative_copied_image_path_for_csv = os.path.join("jpg", copied_image_filename)


                        csv_data.append([
                            jsonl_timestamp_str,
                            plate_number,
                            ts_ev_prediction,
                            my_model_ev_prediction,
                            my_model_confidence,
                            model_used,
                            processing_time,
                            saved_in_uncertain,
                            image_source_folder,
                            relative_copied_image_path_for_csv # 복사된 이미지 파일 이름 (csv 파일 기준 상대 경로) 기록
                        ])
                    except Exception as e:
                        print(f"오류: 이미지 파일 '{found_image_path}' 라벨링 폴더로 복사 실패: {e}")

                # else:
                    # 필터링 조건은 만족했지만 이미지를 찾지 못한 경우
                    # print(f"경고: 이미지 파일 '{expected_filename_base}' 필터링 조건 만족했으나 모든 예상 폴더에서 찾을 수 없습니다.")


            except json.JSONDecodeError:
                print(f"오류: JSONL 파일 처리 중 JSON 디코딩 오류 발생 - 라인 건너뛰기: {line.strip()}")
            except Exception as e:
                print(f"오류: JSONL 파일 라인 처리 중 예상치 못한 오류 발생 - 라인 건너뛰기: {line.strip()} - {e}")

except FileNotFoundError:
    print(f"오류: JSONL 파일을 찾을 수 없습니다: {JSONL_FILE_PATH}")
except Exception as e:
    print(f"오류: JSONL 파일 읽기 중 오류 발생: {JSONL_FILE_PATH} - {e}")

# --- 추출된 데이터를 CSV 파일로 저장 ---
if len(csv_data) > 1: # 헤더 제외 데이터가 1개 이상인 경우
    try:
        # CSV 파일을 CSV 서브폴더에 저장
        with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerows(csv_data)
        print(f"\n작업 완료.")
        print(f"총 로그 항목 처리: {processed_count}")
        print(f"필터링 조건 만족 로그 항목 수: {filtered_count}") # 필터링된 항목 개수 출력
        print(f"총 찾은 이미지 개수 (필터링 조건 만족 + 이미지 찾음): {found_image_count}") # 필터링 통과 항목 중 이미지 찾은 개수
        print(f"데이터 CSV 파일 저장 완료: {OUTPUT_CSV_FILE}")
        print(f"라벨링할 이미지 저장 폴더: {IMAGE_SUBFOLDER}") # JPG 서브폴더를 가리킴

    except Exception as e:
        print(f"오류: CSV 파일 '{OUTPUT_CSV_FILE}' 저장 실패: {e}")
else:
    print(f"\n작업 완료.")
    print(f"총 로그 항목 처리: {processed_count}")
    print(f"필터링 조건 만족 로그 항목 수: {filtered_count}")
    print("필터링 조건을 만족하는 로그 항목이 없거나, 해당 이미지를 찾지 못했습니다.")
