-- ================================================================================
-- NULL 값만 존재할 것 같은 의심되는 컬럼명 데이터 조사
-- ================================================================================
-- NULL 값 밖에 없는 컬럼명 확인 및 삭제
SELECT * FROM locallink.gg_restaurants WHERE suspnbiz_begin_de IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN suspnbiz_begin_de;

SELECT * FROM locallink.gg_restaurants WHERE suspnbiz_end_de IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN suspnbiz_end_de;

SELECT * FROM locallink.gg_restaurants WHERE reopenbiz_de IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN reopenbiz_de;

SELECT * FROM locallink.gg_restaurants WHERE locplc_faclt_telno IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN locplc_faclt_telno;

SELECT * FROM locallink.gg_restaurants WHERE locplc_ar_info IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN locplc_ar_info;

SELECT * FROM locallink.gg_restaurants WHERE bizcond_div_nm_info IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN bizcond_div_nm_info;

SELECT * FROM locallink.gg_restaurants WHERE x_crdnt_vl IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN x_crdnt_vl;

SELECT * FROM locallink.gg_restaurants WHERE y_crdnt_vl IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN y_crdnt_vl;

SELECT * FROM locallink.gg_restaurants WHERE headofc_emply_cnt IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN headofc_emply_cnt;

SELECT * FROM locallink.gg_restaurants WHERE factry_ofcrk_dut_emply_cnt IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN factry_ofcrk_dut_emply_cnt;

SELECT * FROM locallink.gg_restaurants WHERE factry_sale_dut_emply_cnt IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN factry_sale_dut_emply_cnt;

SELECT * FROM locallink.gg_restaurants WHERE factry_prodctn_dut_emply_cnt IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN factry_prodctn_dut_emply_cnt;

SELECT * FROM locallink.gg_restaurants WHERE buldng_posesn_div_nm IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN buldng_posesn_div_nm;

SELECT * FROM locallink.gg_restaurants WHERE assurnc_amt IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN assurnc_amt;

SELECT * FROM locallink.gg_restaurants WHERE mtrent_amt IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN mtrent_amt;

SELECT * FROM locallink.gg_restaurants WHERE faclt_tot_scale_info IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN faclt_tot_scale_info;

SELECT * FROM locallink.gg_restaurants WHERE traditn_bizestbl_appont_no IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN traditn_bizestbl_appont_no;

SELECT * FROM locallink.gg_restaurants WHERE traditn_bizestbl_chief_food_nm IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN traditn_bizestbl_chief_food_nm;

SELECT * FROM locallink.gg_restaurants WHERE hmpg_url IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN hmpg_url;

SELECT * FROM locallink.gg_restaurants WHERE licensg_cancl_de IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN licensg_cancl_de;

SELECT * FROM locallink.gg_restaurants WHERE bsn_state_div_cd IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN bsn_state_div_cd;

SELECT * FROM locallink.gg_restaurants WHERE unity_bsn_state_div_cd IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN unity_bsn_state_div_cd;

SELECT * FROM locallink.gg_restaurants WHERE unity_bsn_state_nm IS NOT NULL;
ALTER TABLE locallink.gg_restaurants DROP COLUMN unity_bsn_state_nm;


-- 조사 결과, NOT NULL 값 존재
SELECT * FROM locallink.gg_restaurants WHERE male_enflpsn_cnt IS NOT NULL;
SELECT * FROM locallink.gg_restaurants WHERE tot_emply_cnt IS NOT NULL;

