"""CLI 스크립트 공통 유틸리티"""

import argparse
from pathlib import Path
from datetime import datetime

# 테스트 기본 좌표
# DEFAULT_TEST_LOCATION = (37.2635, 127.0090)
DEFAULT_TEST_LOCATION = (37.1536, 127.3966)  # 수원역에서 조금 더 북쪽으로 이동한 지점 (명소가 더 잘 나오는 위치)

def build_common_argparser(description: str) -> argparse.ArgumentParser:
    """도슨트 생성 스크립트용 공통 인자 파서 생성"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--language",
        default="English",
        choices=["English", "Korean", "Japanese"],
        help="도슨트 대본 언어 선택 (기본: English)",
    )
    parser.add_argument(
        "--speech",
        action="store_true",
        help="생성된 대본을 mp3 음성 파일로 저장",
    )
    parser.add_argument(
        "--speech-output-dir",
        default=None,
        help="음성 파일 저장 디렉터리 (기본: data/docent/mp3)",
    )
    parser.add_argument(
        "--script-output-dir",
        default=None,
        help="도슨트 스크립트 저장 디렉터리 (기본: data/docent/scripts)",
    )
    return parser


def save_script_text(
    content: str,
    language: str,
    output_dir: str | None = None,
    filename_prefix: str = "script",
    project_root: Path = None,
) -> str:
    """
    도슨트 스크립트를 파일에 저장합니다.
    
    Args:
        content: 저장할 스크립트 내용
        language: 언어
        output_dir: 저장 디렉터리 (None이면 기본값 사용)
        filename_prefix: 파일명 접두사
        project_root: 프로젝트 루트 경로
    
    Returns:
        저장된 파일 경로
    """
    if project_root is None:
        # 이 함수가 src/utils/cli_utils.py에 있으므로 2단계 상위가 프로젝트 루트
        project_root = Path(__file__).resolve().parents[2]
    
    if output_dir:
        target_dir = Path(output_dir)
    else:
        target_dir = project_root / "data" / "docent" / "scripts"
    
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 고정된 이름으로 덮어쓰기 (타임스탬프 제거)
    file_path = target_dir / f"{filename_prefix}_{language.lower()}.txt"
    
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)
