import sys
from pathlib import Path
import argparse
from datetime import datetime

# 프로젝트 루트 경로 추가 (src 임포트용)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.weather_planner import WeatherTravelPlanner
from src.services.speech_synthesizer import save_text_as_mp3, SpeechSynthesisError


def parse_args():
    parser = argparse.ArgumentParser(description="WeatherTravelPlanner 통합 테스트")
    parser.add_argument(
        "--language",
        default="English",
        choices=["English", "Korean", "Japanese"],
        help="도슨트 멘트 생성 언어 (기본: English)",
    )
    parser.add_argument(
        "--speech",
        action="store_true",
        help="생성된 통합 도슨트 멘트를 mp3 음성 파일로 저장",
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

def _save_weather_script_text(combined_result: dict, language: str, output_dir: str | None = None) -> str:
    if output_dir:
        target_dir = Path(output_dir)
    else:
        target_dir = PROJECT_ROOT / "data" / "docent" / "scripts"
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = target_dir / f"weather_combined_{language.lower()}_{timestamp}.txt"

    script_text = (combined_result.get("script", "") or "").strip()
    file_path.write_text(script_text, encoding="utf-8")
    return str(file_path)


def run_integration_test(language="English", speech=False, speech_output_dir=None, script_output_dir=None):
    # 1. 초기화 (테스트용 GPS: 수원역 인근)
    # 실제 DB에 '수원' 관련 날씨와 명소가 있어야 결과가 나옵니다.
    test_lat, test_lng = 37.2635, 127.0090
    # test_lat, test_lng = 37.26788, 127.11233
    script_language = language
    planner = WeatherTravelPlanner(test_lat, test_lng)
    
    print("\n" + "="*50)
    print("🚀 WeatherTravelPlanner 통합 테스트 시작")
    print("="*50)
    print(f"🌐 도슨트 언어: {script_language}")

    # STEP 1: 위치 기반 시군구 추출 테스트
    sigun = planner.get_user_sigun_nm()
    print(f"\n📍 [STEP 1] 위치 분석 결과: {sigun}")
    if not sigun:
        print("❌ 근처 명소를 찾을 수 없어 시군구 추출에 실패했습니다.")
        return

    # STEP 2: 실시간 날씨 조회 테스트
    weather = planner.get_current_location_weather()
    if weather:
        print(f"🌦️ [STEP 2] 현재 날씨: {weather['location']} / {weather['outdoor_status']} / 강수형태:{weather['precipitation_type']}")
    else:
        print("❌ 날씨 데이터를 가져오지 못했습니다. DB를 확인하세요.")
        return

    # STEP 3: 선제시(Intervention) 로직 및 장소 추출 테스트
    # *테스트 팁: DB의 날씨를 강제로 '비'로 바꾸거나 코드를 수정해서 상황을 연출해보세요.
    # radius_m: 날씨 조건에 맞는 장소를 찾은 후 이 거리 내 장소들을 추천
    recommendations, alert_type = planner.check_and_propose_intervention(radius_m=10000)
    
    if recommendations:
        print(f"\n✅ [STEP 3] 감지된 상황: {alert_type}")
        print(f"🔎 추천된 장소 (TOP 3):")
        for i, res in enumerate(recommendations[:3], 1):
            print(f"   {i}. {res['name']} (거리: {res['dist']:.1f}m)")
            
        # STEP 4 & 5: 3개 장소를 하나의 통합 도슨트 멘트로 생성
        print(f"\n{'='*50}")
        print(f"📝 [STEP 4 & 5] 통합 도슨트 멘트 생성")
        print(f"🌐 생성 언어: {script_language}")
        print(f"{'='*50}")
        
        combined_result = planner.create_combined_docent_script(
            recommendations, 
            alert_type, 
            language=script_language, 
            max_count=3
        )
        
        if combined_result and combined_result.get('script'):
            print(f"\n🤖 생성된 통합 도슨트 멘트:")
            print(f"{'─'*70}")
            print(combined_result['script'])
            print(f"{'─'*70}")

            script_path = _save_weather_script_text(
                combined_result=combined_result,
                language=script_language,
                output_dir=script_output_dir,
            )
            print(f"\n📝 스크립트 파일 저장 완료: {script_path}")

            if speech:
                try:
                    file_prefix = f"weather_combined"
                    audio_path = save_text_as_mp3(
                        text=combined_result['script'],
                        language=script_language,
                        output_dir=speech_output_dir,
                        filename_prefix=file_prefix,
                    )
                    print(f"\n🔊 음성 파일 생성 완료: {audio_path}")
                except SpeechSynthesisError as e:
                    print(f"\n⚠️ 음성 변환 실패: {e}")
            
            print(f"\n📍 포함된 장소:")
            for i, place in enumerate(combined_result.get('places', []), 1):
                distance_km = place['distance'] / 1000
                print(f"   {i}. {place['name']} ({distance_km:.1f}km) - {place['type']}")
        else:
            print("❌ 도슨트 멘트 생성에 실패했습니다.")
        
        print(f"\n{'='*50}")
        print(f"✅ 통합 도슨트 멘트 생성 완료!")
        print(f"{'='*50}")
    else:
        print("\nℹ️ 현재 날씨 변동이 없거나 조건에 맞는 장소가 주변에 없습니다.")

if __name__ == "__main__":
    try:
        args = parse_args()
        run_integration_test(
            language=args.language,
            speech=args.speech,
            speech_output_dir=args.speech_output_dir,
            script_output_dir=args.script_output_dir,
        )
    except Exception as e:
        import traceback
        print(f"\n🔥 테스트 중 에러 발생: {e}")
        print("\n📋 상세 스택 트레이스:")
        traceback.print_exc()