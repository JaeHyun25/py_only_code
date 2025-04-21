import logging
import logging.handlers     # handlers import 추가가
import os
from datetime import datetime

def setup_logging(log_dir: str = "logs", config: dict = None):
    
    """로깅 설정"""
    # 로그 디렉토리 생성
    os.makedirs(log_dir, exist_ok=True)    
    
    # 로그 파일명 설정 (날짜 포함)
    log_file = os.path.join(log_dir, f"ev_prediction_{datetime.now().strftime('%Y%m%d')}.log")
    
    # 로그 로테이션 설정 추가
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config['logging']['file_rotation']['max_bytes'] if config else 10485760,
        backupCount=config['logging']['file_rotation']['backup_count'] if config else 5
    )

    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,    # 로깅레벨 INFO이상 기록 - 일반적인 정보, 시스템의 정상적인 동작 기록 이상 동작시 기록
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            file_handler,    # RotatingFileHandler 사용용
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger(__name__) 
