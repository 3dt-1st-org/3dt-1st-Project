"""
아침 하루 일정 계획 테스트 스크립트
"""

import sys
from pathlib import Path
import argparse
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.daily_planner import DailyTravelPlanner, print_daily_plan
from src.services.speech_synthesizer import save_text_as_mp3, SpeechSynthesisError


def parse_args():
    parser = argparse.ArgumentParser(description="하루 일정 플래너 실행")
    parser.add_argument(
        "--language",
        default="English",
        choices=["English", "Korean", "Japanese"],
        help="도슨트 대본 언어 선택 (기본: English)",
    )
    parser.add_argument(
        "--speech",
        action="store_true",
        help="생성된 하루 일정 대본을 mp3 음성 파일로 저장",
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
    return parser.parse_args()


def _build_daily_narration_text(plan_result: dict) -> str:
    if not plan_result or not plan_result.get("plan"):
        return ""

    # TTS에는 모델이 생성한 도슨트 스크립트만 포함합니다.
    lines = []
    for item in plan_result.get("plan", []):
        script = item.get("script", "")
        if script:
            lines.append(script)

    return " ".join(lines)


def _save_daily_script_text(plan_result: dict, narration: str, language: str, output_dir: str | None = None) -> str:
    if output_dir:
        target_dir = Path(output_dir)
    else:
        target_dir = PROJECT_ROOT / "data" / "docent" / "scripts"
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = target_dir / f"daily_plan.txt"

    scripts = []
    for item in plan_result.get("plan", []):
        script = (item.get("script", "") or "").strip()
        if script:
            scripts.append(script)

    file_path.write_text("\n\n".join(scripts), encoding="utf-8")
    return str(file_path)


def main():
    """
    아침에 실행하는 하루 일정 계획 기능 테스트
    """
    args = parse_args()

    print("\n🌅 좋은 아침이에요! 오늘 하루 일정을 짜볼게요.\n")
    
    # 테스트 위치
    test_lat, test_lng = 37.2635, 127.0090
    # test_lat, test_lng = 37.26788, 127.11233
    
    # 언어 선택 (기본값: English)
    language = args.language
    print(f"🗣️ 대본 언어: {language}")
    
    # 일정 생성
    planner = DailyTravelPlanner(test_lat, test_lng)
    result = planner.create_daily_plan(language=language)
    
    # 결과 출력
    print_daily_plan(result)
    narration = _build_daily_narration_text(result)

    if narration:
        script_path = _save_daily_script_text(
            plan_result=result,
            narration=narration,
            language=language,
            output_dir=args.script_output_dir,
        )
        print(f"\n📝 스크립트 파일 저장 완료: {script_path}")
    else:
        print("\n⚠️ 저장할 스크립트가 없습니다.")

    if args.speech:
        if narration:
            try:
                file_prefix = f"daily_plan"
                audio_path = save_text_as_mp3(
                    text=narration,
                    language=language,
                    output_dir=args.speech_output_dir,
                    filename_prefix=file_prefix,
                )
                print(f"\n🔊 음성 파일 생성 완료: {audio_path}")
            except SpeechSynthesisError as e:
                print(f"\n⚠️ 음성 변환 실패: {e}")
        else:
            print("\n⚠️ 음성으로 변환할 일정 대본이 없습니다.")
    
    print("\n✨ 즐거운 하루 되세요!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n🔥 에러 발생: {e}")
        print("\n📋 상세 스택 트레이스:")
        traceback.print_exc()
