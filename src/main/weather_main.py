import sys
from pathlib import Path

# 프로젝트 루트 경로 추가 (src 임포트용)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.weather_planner import WeatherTravelPlanner
from src.services.speech_synthesizer import save_text_as_mp3, SpeechSynthesisError
from src.utils.cli_utils import build_common_argparser, save_script_text, DEFAULT_TEST_LOCATION


def parse_args():
    parser = build_common_argparser("WeatherTravelPlanner 통합 테스트")
    return parser.parse_args()


def run_integration_test(language="English", speech=False, speech_output_dir=None, script_output_dir=None):
    # 테스트용 GPS: 수원역 인근
    # 실제 DB에 '수원' 관련 날씨와 명소가 있어야 결과가 나옵니다.
    test_lat, test_lng = DEFAULT_TEST_LOCATION
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
        outdoor_status = weather.get('outdoor_status') or '정보 없음'
        print(f"🌦️ [STEP 2] 현재 날씨: {weather['location']} / {outdoor_status} / 강수형태:{weather['precipitation_type']}")
    else:
        print("❌ 날씨 데이터를 가져오지 못했습니다. DB를 확인하세요.")
        return

    # STEP 3: 선제시(Intervention) 로직 및 장소 추출 테스트
    # *테스트 팁: DB의 날씨를 강제로 '비'로 바꾸거나 코드를 수정해서 상황을 연출해보세요.
    # radius_m: 날씨 조건에 맞는 장소를 찾은 후 이 거리 내 장소들을 추천
    intervention = planner.check_and_propose_intervention(radius_m=10000)
    if not intervention:
        print("\nℹ️ 현재 날씨 변동이 없거나 조건에 맞는 장소가 주변에 없습니다.")
        return

    recommendations, alert_type = intervention
    
    if recommendations:
        print(f"\n✅ [STEP 3] 감지된 상황: {alert_type}")
        if planner.last_alert_reasons:
            reason_labels = {
                'rain_alert': '비/눈',
                'pm_alert': '미세먼지',
                'cold_alert': '한파/강풍',
                'heat_alert': '폭염',
            }
            reasons = [reason_labels.get(r, r) for r in planner.last_alert_reasons]
            print(f"🧭 야외활동 불가 원인: {', '.join(reasons)}")
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

            script_path = save_script_text(
                content=combined_result['script'],
                language=script_language,
                output_dir=script_output_dir,
                filename_prefix="weather_combined",
                project_root=PROJECT_ROOT,
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