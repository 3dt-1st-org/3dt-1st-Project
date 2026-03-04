"""
통합 파이프라인: GPS설정 → 근처 명소 추출 → 리뷰 수집 → AI 도슨트 제공
"""

import sys
from pathlib import Path

# src/main에서 직접 실행할 때도 프로젝트 루트를 import 경로에 추가
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from src.collectors.attraction_filter import filter_attractions_by_location
from src.collectors.load_review_pipeline import run_review_pipeline
from src.services.attraction_docent import process_attractions

load_dotenv()

if __name__ == "__main__":
    # ⭐ GPS 좌표 설정
    GPS_LAT = 37.2807
    GPS_LON = 127.0151
    
    print("\n" + "🚀 "*20)
    print("LALA AI GUIDE: 통합 파이프라인 시작")
    print("🚀 "*20)
    
    # ==============================================================================
    # STEP 1: GPS 기반 근처 명소 추출
    # ==============================================================================
    print("\n" + "="*80)
    print("📍 [STEP 1] GPS 기반 근처 명소 추출")
    print("="*80)
    print(f"📍 GPS 좌표: ({GPS_LAT}, {GPS_LON})")
    
    attractions, status = filter_attractions_by_location(radius_m=100, lat=GPS_LAT, lon=GPS_LON)
    
    if not attractions:
        print(f"⚠️ 상태: {status}")
    else:
        # 명소명 추출 (원본 그대로)
        attraction_names = [attr[0] for attr in attractions]
        
        print(f"\n✅ 총 {len(attraction_names)}개의 명소 발견:")
        for i, name in enumerate(attraction_names, 1):
            distance = attractions[i-1][5]
            print(f"   {i}. {name} (거리: {distance:.2f}m)")
        
        # ==============================================================================
        # STEP 2: 리뷰 수집 및 DB 적재
        # ==============================================================================
        print("\n" + "="*80)
        print("📚 [STEP 2] 명소별 리뷰 데이터 수집 및 적재")
        print("="*80)
        
        success_count = 0
        fail_count = 0
        
        for attraction_name in attraction_names:
            try:
                print(f"\n📍 [{attraction_name}] 리뷰 수집 중...")
                run_review_pipeline(attraction_name)
                success_count += 1
            except Exception as e:
                print(f"❌ [{attraction_name}] 실패: {str(e)}")
                fail_count += 1
        
        print(f"\n✅ 리뷰 적재 완료: {success_count}개 성공, {fail_count}개 실패")
        
        # ==============================================================================
        # STEP 3: 도슨트 음성 가이드 생성
        # ==============================================================================
        if success_count > 0:
            print("\n" + "="*80)
            print("🎤 [STEP 3] AI 도슨트 음성 가이드 생성")
            print("="*80)
            
            try:
                process_attractions(attraction_names, language="English")
                print(f"\n✅ 도슨트 생성 완료: {len(attraction_names)}개 명소 처리됨")
                print(f"📁 저장 위치: data/docent/")
            except Exception as e:
                print(f"❌ 도슨트 생성 실패: {str(e)}")
        else:
            print("\n⚠️ 리뷰 적재 실패로 도슨트 생성을 건너뜁니다.")
        
        # 최종 결과 요약
        print("\n" + "="*80)
        print("✨ 파이프라인 완료!")
        print("="*80 + "\n")
