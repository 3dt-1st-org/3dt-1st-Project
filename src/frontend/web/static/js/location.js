/**
 * location.js
 * 브라우저 Geolocation API로 위도/경도를 획득하고
 * sessionStorage에 저장한 뒤 /map 으로 이동한다.
 *
 * 권한 거부 또는 오류 시 기본 좌표(수원시청)로 대체하여 서비스 진입을 보장한다.
 */

const DEFAULT_LAT = 37.2636;  // 수원시청
const DEFAULT_LNG = 127.0286;

function requestLocationAndRedirect() {
  if (!navigator.geolocation) {
    _saveAndRedirect(DEFAULT_LAT, DEFAULT_LNG);
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      _saveAndRedirect(pos.coords.latitude, pos.coords.longitude);
    },
    (err) => {
      console.warn('[LALA] 위치 권한 거부 또는 오류:', err.message);
      _saveAndRedirect(DEFAULT_LAT, DEFAULT_LNG);
    },
    { timeout: 8000, maximumAge: 300_000, enableHighAccuracy: false }
  );
}

function _saveAndRedirect(lat, lng) {
  sessionStorage.setItem('user_lat', lat);
  sessionStorage.setItem('user_lng', lng);
  window.location.replace('/map');
}

