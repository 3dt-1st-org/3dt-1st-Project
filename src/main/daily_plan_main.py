"""
아침 하루 일정 계획 테스트 스크립트
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.daily_planner import DailyTravelPlanner, print_daily_plan
from src.services.speech_synthesizer import save_text_as_mp3, SpeechSynthesisError
from src.utils.cli_utils import build_common_argparser, save_script_text, DEFAULT_TEST_LOCATION


def parse_args():
    parser = build_common_argparser("하루 일정 플래너 실행")
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


def main():
    """
    아침에 실행하는 하루 일정 계획 기능 테스트
    """
    args = parse_args()

    print("\n🌅 좋은 아침이에요! 오늘 하루 일정을 짜볼게요.\n")
    
    # 테스트 위치
    test_lat, test_lng = DEFAULT_TEST_LOCATION
    
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
        script_content = "\n\n".join([
            (item.get("script", "") or "").strip()
            for item in result.get("plan", [])
            if (item.get("script", "") or "").strip()
        ])
        
        script_path = save_script_text(
            content=script_content,
            language=language,
            output_dir=args.script_output_dir,
            filename_prefix="daily_plan",
            project_root=PROJECT_ROOT,
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
