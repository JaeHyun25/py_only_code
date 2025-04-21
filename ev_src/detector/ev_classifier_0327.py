import cv2
import numpy as np
import joblib
import logging
from typing import Dict, Tuple, List
import time
from dataclasses import dataclass
from ..utils.image_processing import preprocess_image, extract_features, validate_plate_info

@dataclass
class ProcessingMetrics:
    """처리 메트릭 데이터 클래스"""
    elapsed_time: float     # 처리 시간
    confidence_score: float # 신뢰도 점수
    model_used: str        # 'xgb' or 'lgbm'
    error_occurred: bool = False
    error_message: str = None

class EVClassifier:
    def __init__(self, 
                 xgb_model_path: str, 
                 lgbm_model_path: str,
                 confidence_threshold: float = 0.45,
                 max_processing_time: float = 1.0):
        self.metrics_history:List[ProcessingMetrics] = []
        """전기차 판별 모델 로드
        
        Args:
            xgb_model_path (str): XGBoost 모델 경로
            lgbm_model_path (str): LightGBM 모델 경로
            confidence_threshold (float): 예측 신뢰도 임계값
            max_processing_time (float): 최대 처리 시간 (초)
        """
        self.logger = logging.getLogger(__name__)
        try:
            self.xgb_model = joblib.load(xgb_model_path)
            self.lgbm_model = joblib.load(lgbm_model_path)
            self.confidence_threshold = confidence_threshold
            self.max_processing_time = max_processing_time
            self.metrics_history: List[ProcessingMetrics] = []  # 메트릭 히스토리 저장
        except Exception as e:
            self.logger.error(f"모델 로드 실패: {str(e)}")
            raise

    def process_frame(self, frame: np.ndarray, plate_info: Dict) -> Tuple[bool, ProcessingMetrics]:
        """단일 프레임 처리 및 예측
        
        Args:
            frame (np.ndarray): 입력 이미지
            plate_info (Dict): 번호판 정보
        Returns:
            Tuple[bool, ProcessingMetrics]: (예측 결과, 처리 메트릭)
        """
        try:
            start_time = time.time()
            
            # 입력 검증
            if not isinstance(frame, np.ndarray):
                raise TypeError("frame은 numpy array여야 합니다.")
            if not validate_plate_info(plate_info):
                raise ValueError("유효하지 않은 번호판 정보입니다.")
            
            # 번호판 정보 추출
            area = plate_info['area']
            crop_box = (area['x'], area['y'], area['width'], area['height'])
            
            # 이미지 전처리
            hsv_image = preprocess_image(frame, crop_box, area.get('angle', 0))
            
            # 특징 추출
            features = extract_features(hsv_image)
            
            # 예측
            xgb_pred = self.xgb_model.predict([features])[0]
            xgb_prob = self.xgb_model.predict_proba([features])[0][1]
            
            # 신뢰도 기반 앙상블
            if xgb_prob < self.confidence_threshold:
                prediction = self.lgbm_model.predict([features])[0]
                model_used = 'lgbm'
                # LightGBM add 0417 am 10:04 modified
                lgbm_prob = self.lgbm_model.predict_proba([features])[0][1] if hasattr(self.lgbm_model, 'predict_proba') else xgb_prob	# 0417 predict_proba X-> xgb_prob use 
                confidence_score = lgbm_prob	# 0417
            else:
                prediction = xgb_pred
                model_used = 'xgb'
                
                confidence_score = xgb_prob	# 0417 am 10:04 modified
            	
            elapsed_time = time.time() - start_time
            metrics = ProcessingMetrics(
                elapsed_time=elapsed_time,
                confidence_score=xgb_prob,
                model_used=model_used
            )
            
            if elapsed_time > self.max_processing_time:
                self.logger.warning(f"처리 시간 초과: {elapsed_time:.2f}초")
            
            self.metrics_history.append(metrics)
            return bool(prediction), metrics
            
        except Exception as e:
            self.logger.error(f"프레임 처리 중 오류 발생: {str(e)}")    
            metrics = ProcessingMetrics(
                elapsed_time=time.time() - start_time,       # 오류 발생해도도 처리 시간 저장  
                confidence_score=0.0,                        # 오류 발생으로 예측 신뢰도 0.0
                model_used='none',                           # 사용된 모델 없음
                error_occurred=True,                         # 오류 발생 표시
                error_message=str(e)                         # 오류 상세 내용 str(e)로 저장
            )
            raise

    def get_metrics_summary(self) -> Dict:
        """처리 메트릭 요약 정보 반환"""
        if not self.metrics_history:
            return {}
            
        return {
            'total_processed': len(self.metrics_history),
            'avg_processing_time': np.mean([m.elapsed_time for m in self.metrics_history]), # 평균 처리 시간간
            'avg_confidence': np.mean([m.confidence_score for m in self.metrics_history]),  # 신뢰도
            'error_rate': sum(1 for m in self.metrics_history if m.error_occurred) / len(self.metrics_history),
            'model_usage': {
                'xgb': sum(1 for m in self.metrics_history if m.model_used == 'xgb'),
                'lgbm': sum(1 for m in self.metrics_history if m.model_used == 'lgbm')
            }
        } 
