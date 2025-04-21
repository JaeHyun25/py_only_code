import cv2
import numpy as np
from typing import Tuple, Dict
import logging

logger = logging.getLogger(__name__) # 모듈 레벨 로거 (필요시 함수 내에서 getLogger)

def preprocess_image(image: np.ndarray, crop_box: Tuple[int, int, int, int],
                     angle: float, target_size: Tuple[int, int] = (320, 180)) -> np.ndarray:
    """이미지 전처리 (크롭, 리사이즈, 회전, HSV 변환)"""
    try: # 이미지 처리 중 예외 발생 가능성 대비
        img_h, img_w = image.shape[:2]
        x, y, w, h = map(int, crop_box) # 혹시 float으로 올 경우 대비해 int 변환

        # --- 좌표 검증 및 조정 로직 추가 ---
        x1_c = max(0, x)
        y1_c = max(0, y)
        # x2, y2 계산 시 원본 이미지 경계를 넘지 않도록 min 사용
        x2_c = min(img_w, x + w) 
        y2_c = min(img_h, y + h)

        # 조정된 좌표로 너비/높이 계산
        eff_w = x2_c - x1_c
        eff_h = y2_c - y1_c

        # 조정 후 너비 또는 높이가 0 이하이면 에러 처리
        if eff_w <= 0 or eff_h <= 0:
            logger.error(f"Invalid crop dimensions after clamping: Box={crop_box}, Clamped=[{x1_c}:{x2_c}, {y1_c}:{y2_c}], ImgShape=({img_h},{img_w})")
            # 여기서 에러를 발생시키거나, None을 반환하는 등 처리 방식 결정 필요
            # 에러 발생시키면 상위 except에서 잡힘
            raise ValueError(f"Invalid effective crop size ({eff_w}x{eff_h}) after clamping")
            # 또는 return None (호출하는 쪽에서 None 처리 필요)
        # --- 로직 추가 끝 ---

        # 조정된 좌표(clamped coordinates)를 사용하여 이미지 자르기
        cropped = image[y1_c:y2_c, x1_c:x2_c]

        # 만약을 위해 crop 결과가 비었는지 한 번 더 확인 (이론상 위에서 걸러져야 함)
        if cropped.size == 0:
             logger.error(f"Cropped image is unexpectedly empty! Box={crop_box}, Clamped=[{x1_c}:{x2_c}, {y1_c}:{y2_c}], ImgShape=({img_h},{img_w})")
             raise ValueError("Cropped image is empty despite valid clamped dimensions")

        # 이미지 리사이즈
        resized = cv2.resize(cropped, target_size)

        # 회전 처리
        if angle != 0:
            center = (resized.shape[1]//2, resized.shape[0]//2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            resized = cv2.warpAffine(resized, matrix, (resized.shape[1], resized.shape[0]))

        # HSV 변환
        return cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

    except Exception as e:
        logger.error(f"Error during preprocess_image: {e}. Input crop_box: {crop_box}, Image shape: {image.shape if image is not None else 'None'}")
        # 오류를 다시 발생시켜 상위에서 처리하도록 함
        raise

# def preprocess_image(image: np.ndarray, crop_box: Tuple[int, int, int, int], 
#                     angle: float, target_size: Tuple[int, int] = (320, 180)) -> np.ndarray:
#     """이미지 전처리 (크롭, 리사이즈, 회전, HSV 변환)"""
#     x, y, w, h = crop_box
#     cropped = image[y:y+h, x:x+w]   # 250403 14:59 오류 발생 
#     resized = cv2.resize(cropped, target_size)  #  250403 14:59 오류 발생
    
#     if angle != 0:
#         center = (resized.shape[1]//2, resized.shape[0]//2)
#         matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
#         resized = cv2.warpAffine(resized, matrix, (resized.shape[1], resized.shape[0]))
    
#     return cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)

def extract_features(hsv_image: np.ndarray) -> np.ndarray:
    """HSV 히스토그램 특징 추출"""
    h, s, v = cv2.split(hsv_image)
    hist_h = cv2.calcHist([h], [0], None, [256], [0, 256])
    hist_s = cv2.calcHist([s], [0], None, [256], [0, 256])
    hist_v = cv2.calcHist([v], [0], None, [256], [0, 256])
    
    return np.r_[hist_h, hist_s, hist_v].squeeze()

def validate_plate_info(plate_info: Dict) -> bool:
    """
    번호판 정보 유효성 검사.
    area가 [x, y, width, height] 형태의 리스트로 들어올 경우,
    딕셔너리로 변환하여 처리를 시도합니다. (팀 요청 반영)
    """
    logger = logging.getLogger(__name__) # 로거 가져오기

    if not isinstance(plate_info, dict):
        logger.warning("입력된 plate_info가 딕셔너리 타입이 아닙니다.") # print 대신 logging 사용
        return False

    area = plate_info.get('area') # 기본값 {} 대신 None을 받아 명시적 처리

    # area 정보가 없는 경우
    if area is None:
        logger.warning("plate_info에 'area' 키가 없습니다.")
        return False

    # --- 
    # area가 특정 형태의 리스트인 경우 dict로 변환 시도
    # 주의: 리스트 순서가 [x, y, width, height] 라고 가정합니다.
    if isinstance(area, list):
        if len(area) == 4:
            logger.info("area 정보가 리스트 형태(len=4)로 입력되어 dict로 변환을 시도합니다.")
            try:
                # 모든 요소가 숫자인지 간단히 확인 (더 엄격한 타입 체크 가능)
                if all(isinstance(n, (int, float)) for n in area):
                     area = {'x': int(area[0]), 'y': int(area[1]), 'width': int(area[2]), 'height': int(area[3])}
                     # 변환된 area를 원래 plate_info에도 반영할지 결정해야 하지만,
                     # 여기서는 validate 함수 내 지역 변수 area만 변경합니다.
                     # 원본 plate_info 변경이 필요하면 이 함수 외부 또는 호출부에서 처리해야 합니다.
                else:
                    logger.warning(f"area 리스트에 숫자가 아닌 요소가 포함되어 변환 불가: {area}")
                    return False
            except Exception as e:
                logger.warning(f"area 리스트를 dict로 변환 중 오류 발생: {e} - 입력: {area}")
                return False
        else:
            logger.warning(f"area 정보가 리스트 형태이지만 길이가 4가 아님: {area}")
            return False
    # --- 

    # 이제 area는 딕셔너리 형태여야 함 (변환되었거나 원래 dict였거나)
    if not isinstance(area, dict):
         logger.warning(f"area 정보가 딕셔너리 형태가 아님 (변환 실패 또는 다른 타입): {type(area)}")
         return False

    # area 딕셔너리가 비어있는 경우 (변환 실패 등)
    if not area:
        logger.warning("area 정보가 비어있습니다.")
        return False

    # 필수 필드 검사
    required_fields = ['x', 'y', 'width', 'height']
    missing_fields = [field for field in required_fields if field not in area]

    if missing_fields:
        logger.warning(f"area 정보에 필수 필드가 누락되었습니다: {missing_fields}. Area: {area}")
        return False

    # 모든 필드의 값이 유효한지 추가 검사 (선택 사항)
    # 예: 너비와 높이가 0보다 큰지 등
    if not (area['width'] > 0 and area['height'] > 0):
        logger.warning(f"area의 width 또는 height 값이 유효하지 않습니다. Area: {area}")
        return False

    return True