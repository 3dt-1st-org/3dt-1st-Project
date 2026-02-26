-- =====================================================================================
-- 통합영업상태명과 영업상태명 비교
SELECT unity_bsn_state_nm, bsn_state_nm 
FROM locallink.gg_restaurant_info gri
WHERE gri.unity_bsn_state_nm <> gri.bsn_state_nm;
---- 통합영업상태명이 '영업/정상'일 때, 영업상태명은 '영업'으로 표기
---- 통합영업상태명이 '폐업'일 때, 영업상태명은 '폐업'으로 표기 (중복)

-- 중복되지 않는 값이 있는지 확인
SELECT unity_bsn_state_nm, bsn_state_nm 
FROM locallink.gg_restaurant_info gri
WHERE gri.unity_bsn_state_nm<>'영업/정상' AND gri.bsn_state_nm='영업';
---- 그 외의 경우를 찾아봤을 때, 다른 경우가 없기에 통합엽업상태명을 삭제하기로 결정 ('영업/정상' 대신 '영업'으로 알림)

-- 통합엽업상태명 컬럼 삭제
ALTER TABLE locallink.gg_restaurant_info 
DROP COLUMN unity_bsn_state_nm;
-- =====================================================================================


-- =====================================================================================
-- 업태구분명정보와 위생업태명 비교
SELECT bizplc_nm, bizcond_div_nm_info, sanittn_bizcond_nm
FROM locallink.gg_restaurant_info gri
WHERE gri.bizcond_div_nm_info <> gri.sanittn_bizcond_nm;
---- 결과적으로 증복된 값을 가지는 것은 아님으로 나왔지만, 컬럼 구분의 기준을 모르겠음
---- 중복 결과는 아니므로 삭제 진행은 안함
-- =====================================================================================


-- =====================================================================================
-- '폐업' 상태인 레코드를 제거
-- 1단계: 삭제 대상 데이터 수 확인 (검증)
SELECT COUNT(*) 
FROM locallink.gg_restaurant_info 
WHERE bsn_state_nm = '폐업';
---- 62,098행
SELECT COUNT(*) 
FROM locallink.gg_restaurant_info 
WHERE bsn_state_nm = '영업';
---- 29,629행

-- 2단계: 데이터 삭제 실행
DELETE FROM locallink.gg_restaurant_info 
WHERE bsn_state_nm = '폐업';

-- 3단계: 결과 확인
SELECT bsn_state_nm, COUNT(*) 
FROM locallink.gg_restaurant_info 
GROUP BY bsn_state_nm;
---- 영업상태명이 '영업'인만 남은 것을 확인
-- =====================================================================================


-- =====================================================================================
-- 휴업시작일자 데이터 조사
SELECT suspnbiz_begin_de
FROM locallink.gg_restaurant_info gri
WHERE gri.suspnbiz_begin_de IS NOT NULL;
---- 휴업재개일자 데이터 조사
SELECT suspnbiz_end_de
FROM locallink.gg_restaurant_info gri
WHERE gri.suspnbiz_end_de IS NOT NULL;
---- 재개업일자 데이터 조사
SELECT reopenbiz_de
FROM locallink.gg_restaurant_info gri
WHERE gri.reopenbiz_de IS NOT NULL;
---- 전체 데이터 없음
---- 폐업한 음식점 데이터 삭제하면 모든 음식점이 다 영업중임을 알 수 있음
-- =====================================================================================