-- 테이블 생성
CREATE TABLE IF NOT EXISTS locallink.gg_restaurants (
    id                          bigserial PRIMARY KEY,

    sigun_cd                    text,
    bizplc_nm                   text,
    licensg_de                  date,

    refine_roadnm_addr          text,
    refine_lotno_addr           text,
    refine_zip_cd               text,

    refine_wgs84_lat            double precision,
    refine_wgs84_logt           double precision,

    licensg_cancl_de            date,

    bsn_state_div_cd            text,
    unity_bsn_state_div_cd      text,
    unity_bsn_state_nm          text,
    bsn_state_nm                text,

    clsbiz_de                   date,
    suspnbiz_begin_de           date,
    suspnbiz_end_de             date,
    reopenbiz_de                date,

    locplc_faclt_telno          text,
    locplc_ar_info              text,
    bizcond_div_nm_info         text,

    x_crdnt_vl                  double precision,
    y_crdnt_vl                  double precision,

    sanittn_bizcond_nm          text,
    male_enflpsn_cnt            integer,
    female_enflpsn_cnt          integer,

    bsnsited_circumfr_div_nm    text,
    grad_div_nm                 text,
    grad_faclt_div_nm           text,

    tot_emply_cnt               integer,
    headofc_emply_cnt           integer,
    factry_ofcrk_dut_emply_cnt  integer,
    factry_sale_dut_emply_cnt   integer,
    factry_prodctn_dut_emply_cnt integer,

    buldng_posesn_div_nm        text,
    assurnc_amt                 numeric,
    mtrent_amt                  numeric,

    multi_use_bizestbl_yn       text,
    faclt_tot_scale_info        text,
    traditn_bizestbl_appont_no  text,
    traditn_bizestbl_chief_food_nm text,
    hmpg_url                    text,

    sigun_nm                    text,

    loaded_at                   timestamptz DEFAULT now()
);


--
COMMENT ON COLUMN locallink.gg_restaurants.sigun_cd IS '시군코드';
COMMENT ON COLUMN locallink.gg_restaurants.bizplc_nm IS '사업장명';
COMMENT ON COLUMN locallink.gg_restaurants.licensg_de IS '인허가일자';

COMMENT ON COLUMN locallink.gg_restaurants.refine_roadnm_addr IS '소재지도로명주소';
COMMENT ON COLUMN locallink.gg_restaurants.refine_lotno_addr IS '소재지지번주소';
COMMENT ON COLUMN locallink.gg_restaurants.refine_zip_cd IS '소재지우편번호';

COMMENT ON COLUMN locallink.gg_restaurants.refine_wgs84_lat IS '위도';
COMMENT ON COLUMN locallink.gg_restaurants.refine_wgs84_logt IS '경도';

COMMENT ON COLUMN locallink.gg_restaurants.licensg_cancl_de IS '인허가취소일자';

COMMENT ON COLUMN locallink.gg_restaurants.bsn_state_div_cd IS '영업상태구분코드';
COMMENT ON COLUMN locallink.gg_restaurants.unity_bsn_state_div_cd IS '통합영업상태구분코드';
COMMENT ON COLUMN locallink.gg_restaurants.unity_bsn_state_nm IS '통합영업상태명';
COMMENT ON COLUMN locallink.gg_restaurants.bsn_state_nm IS '영업상태명';

COMMENT ON COLUMN locallink.gg_restaurants.clsbiz_de IS '폐업일자';
COMMENT ON COLUMN locallink.gg_restaurants.suspnbiz_begin_de IS '휴업시작일자';
COMMENT ON COLUMN locallink.gg_restaurants.suspnbiz_end_de IS '휴업종료일자';
COMMENT ON COLUMN locallink.gg_restaurants.reopenbiz_de IS '재개업일자';

COMMENT ON COLUMN locallink.gg_restaurants.locplc_faclt_telno IS '소재지시설전화번호';
COMMENT ON COLUMN locallink.gg_restaurants.locplc_ar_info IS '소재지면적정보';
COMMENT ON COLUMN locallink.gg_restaurants.bizcond_div_nm_info IS '업태구분명정보';

COMMENT ON COLUMN locallink.gg_restaurants.x_crdnt_vl IS 'X좌표값';
COMMENT ON COLUMN locallink.gg_restaurants.y_crdnt_vl IS 'Y좌표값';

COMMENT ON COLUMN locallink.gg_restaurants.sanittn_bizcond_nm IS '위생업태명';
COMMENT ON COLUMN locallink.gg_restaurants.male_enflpsn_cnt IS '남성종사자수';
COMMENT ON COLUMN locallink.gg_restaurants.female_enflpsn_cnt IS '여성종사자수';

COMMENT ON COLUMN locallink.gg_restaurants.bsnsited_circumfr_div_nm IS '영업장주변구분명';
COMMENT ON COLUMN locallink.gg_restaurants.grad_div_nm IS '등급구분명';
COMMENT ON COLUMN locallink.gg_restaurants.grad_faclt_div_nm IS '급수시설구분명';

COMMENT ON COLUMN locallink.gg_restaurants.tot_emply_cnt IS '총종업원수';
COMMENT ON COLUMN locallink.gg_restaurants.headofc_emply_cnt IS '본사종업원수';
COMMENT ON COLUMN locallink.gg_restaurants.factry_ofcrk_dut_emply_cnt IS '공장사무직종업원수';
COMMENT ON COLUMN locallink.gg_restaurants.factry_sale_dut_emply_cnt IS '공장판매직종업원수';
COMMENT ON COLUMN locallink.gg_restaurants.factry_prodctn_dut_emply_cnt IS '공장생산직종업원수';

COMMENT ON COLUMN locallink.gg_restaurants.buldng_posesn_div_nm IS '건물소유구분명';
COMMENT ON COLUMN locallink.gg_restaurants.assurnc_amt IS '보증액';
COMMENT ON COLUMN locallink.gg_restaurants.mtrent_amt IS '월세액';

COMMENT ON COLUMN locallink.gg_restaurants.multi_use_bizestbl_yn IS '다중이용업소여부';
COMMENT ON COLUMN locallink.gg_restaurants.faclt_tot_scale_info IS '시설총규모정보';
COMMENT ON COLUMN locallink.gg_restaurants.traditn_bizestbl_appont_no IS '전통업소지정번호';
COMMENT ON COLUMN locallink.gg_restaurants.traditn_bizestbl_chief_food_nm IS '전통업소주된음식';
COMMENT ON COLUMN locallink.gg_restaurants.hmpg_url IS '홈페이지URL';

COMMENT ON COLUMN locallink.gg_restaurants.sigun_nm IS '시군명';
COMMENT ON COLUMN locallink.gg_restaurants.loaded_at IS 'DB 적재일시';


----
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_rest_sigun_nm ON locallink.gg_restaurants (sigun_nm);
CREATE INDEX idx_rest_bizplc_nm_trgm ON locallink.gg_restaurants USING gin (bizplc_nm gin_trgm_ops);
CREATE INDEX idx_rest_unity_state ON locallink.gg_restaurants (unity_bsn_state_nm);
CREATE INDEX idx_rest_addr_trgm ON locallink.gg_restaurants USING gin (refine_roadnm_addr gin_trgm_ops);


