import cv2
import numpy as np
import logging
from typing import Dict
from dataclasses import dataclass
from datetime import datetime
import time
import json
from .ev_classifier_0327 import EVClassifier, ProcessingMetrics

@dataclass
class DetectionResult:
    """검출 결과 데이터 클래스"""
    plate_number: str   # 번호판 번호
    is_ev: bool         # 전기차 여부
    confidence: float   # 신뢰도
    timestamp: datetime # 검출 시간
    processing_time: float  # 처리 시간
    plate_area: Dict    # 번호판 위치 정보
    metrics: ProcessingMetrics  # 처리 메트릭

class EVDetector:
    def __init__(self, xgb_model_path: str, lgbm_model_path: str, **kwargs):
        """초기화
        
        Args:
            xgb_model_path (str): XGBoost 모델 경로
            lgbm_model_path (str): LightGBM 모델 경로
            **kwargs: EVClassifier에 전달할 추가 파라미터
        """
        self.logger = logging.getLogger(__name__)
        try:
            self.classifier = EVClassifier(xgb_model_path, lgbm_model_path, **kwargs)
            self.logger.info("EVDetector 초기화 완료")
        except Exception as e:
            self.logger.error(f"EVDetector 초기화 중 오류 발생: {str(e)}")
            raise

    def process_frame(self, frame: np.ndarray, plate_info: Dict) -> DetectionResult:
        """단일 프레임 처리"""
        try:
            start_time = time.time()
            
            # plate_info 구조 로깅
            self.logger.info(f"입력된 plate_info 구조: {json.dumps(plate_info, indent=2, ensure_ascii=False)}")
            
            # 번호판 정보 추출
            if isinstance(plate_info, list) :
                if not plate_info:
                    raise ValueError("빈 plate_info 리스트입니다.")
                plate_info = plate_info[0]
            
            # area 정보 추출
            area = plate_info.get('area', {})
            if not area:
                raise ValueError("번호판 영역 정보를 찾을 수 없습니다.")
            
            # 이미지 처리 및 예측
            is_ev, metrics = self.classifier.process_frame(frame, plate_info)
            
            # 결과 생성
            return DetectionResult(
                plate_number=plate_info.get('text', ''),
                is_ev=is_ev,
                confidence=metrics.confidence_score,
                timestamp=datetime.now(),
                processing_time=metrics.elapsed_time,
                plate_area=area,
                metrics=metrics
            )
            
        except Exception as e:
            self.logger.error(f"프레임 처리 중 오류 발생: {str(e)}")
            raise

    def convert_numpy_types(obj):
        """딕셔너리/리스트 내의 numpy 타입을 파이썬 기본 타입으로 변환"""
        if isinstance(obj, dict):
            return {k: convert_numpy_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy_types(i) for i in obj]
        elif isinstance(obj, (np.int_, np.intc, np.intp, np.int8,
                            np.int16, np.int32, np.int64, np.uint8,
                            np.uint16, np.uint32, np.uint64)):
            return int(obj)
        elif isinstance(obj, (np.float_, np.float16, np.float32, 
                            np.float64)):
            return float(obj)
        elif isinstance(obj, (np.ndarray,)): # ndarray를 리스트로 변환 (필요시)
            return obj.tolist()
        elif isinstance(obj, (np.bool_)):
            return bool(obj)
        elif isinstance(obj, (np.void)): # void 타입 처리 (필요시)
            return None
        return obj

    def save_results(self, results: list[DetectionResult], output_path: str):
        """결과 저장"""
        try:
            # 결과를 딕셔너리 리스트로 변환
            results_dict = [
                {
                    'plate_number': r.plate_number,
                    'is_ev': r.is_ev,
                    'confidence': r.confidence,
                    'processing_time': r.processing_time,
                    'timestamp': r.timestamp.isoformat(),
                    'plate_area': r.plate_area,
                    'metrics': {
                        'elapsed_time': r.metrics.elapsed_time,
                        'confidence_score': r.metrics.confidence_score,
                        'model_used': r.metrics.model_used,
                        'error_occurred': r.metrics.error_occurred,
                        'error_message': r.metrics.error_message
                    }
                }
                for r in results
            ]
                
            # JSON 파일로 저장
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results_dict, f, indent=4, ensure_ascii=False)
                
            self.logger.info(f"결과가 {output_path}에 저장되었습니다.")
                
        except Exception as e:
            self.logger.error(f"결과 저장 중 오류 발생: {str(e)}")
            raise

    def get_metrics_summary(self) -> Dict:
        """처리 메트릭 요약 정보 반환"""
        return self.classifier.get_metrics_summary() 