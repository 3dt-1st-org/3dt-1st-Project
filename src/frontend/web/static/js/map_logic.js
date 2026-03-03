/**
 * map_logic.js  — Step 4
 * · 카카오맵 초기화 + /api/places 호출
 * · 카테고리별 커스텀 마커 (선택 시 크기·글로우 변경)
 * · 마커 ↔ Swiper 카드 완전 양방향 동기화 (_syncing 플래그로 루프 방지)
 * · 현재 위치 FAB 버튼
 */

// ── 전역 상태 ──────────────────────────────────────────────────
let _map       = null;
let _markers   = [];     // { marker, overlay, place, idx }
let _swiper    = null;
let _places    = [];
let _activeIdx = -1;
let _syncing   = false;  // 마커→카드, 카드→마커 이벤트 루프 방지

// ── 카테고리 설정 ──────────────────────────────────────────────
const CAT_CONFIG = {
  attraction: { label: '🏛 명소',   color: '#2B6CB0', badgeClass: 'badge-attraction' },
  restaurant:  { label: '🍽 음식점', color: '#C53030', badgeClass: 'badge-restaurant' },
};

// ══════════════════════════════════════════════════════════════
// 1. 지도 초기화
// ══════════════════════════════════════════════════════════════
function initMap(lat, lng) {
  const container = document.getElementById('map-container');
  _showLoading(true); // 초기 로딩 표시
  _map = new kakao.maps.Map(container, {
    center: new kakao.maps.LatLng(lat, lng),
    level: 5,
  });

  _map.addControl(new kakao.maps.ZoomControl(),    kakao.maps.ControlPosition.RIGHT);
  _map.addControl(new kakao.maps.MapTypeControl(), kakao.maps.ControlPosition.TOPRIGHT);

  // 현재 위치 FAB
  _addLocateMeFAB();

  // 최초 로드
  _fetchPlaces(lat, lng, 'all');

  // 필터 버튼 이벤트
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const c = _map.getCenter();
      _fetchPlaces(c.getLat(), c.getLng(), btn.dataset.cat);
    });
  });

  // 드래그 종료 → 현재 뷰 재로드
  kakao.maps.event.addListener(_map, 'dragend', () => {
    const c   = _map.getCenter();
    const cat = document.querySelector('.filter-btn.active')?.dataset.cat || 'all';
    _fetchPlaces(c.getLat(), c.getLng(), cat);
  });
}

// ── 현재 위치 FAB ────────────────────────────────────────────
function _addLocateMeFAB() {
  const fab = document.createElement('button');
  fab.id        = 'locate-btn';
  fab.className = 'fab-locate';
  fab.title     = '현재 위치로 이동';
  fab.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38
             0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
  </svg>`;
  document.body.appendChild(fab);

  fab.addEventListener('click', () => {
    if (!navigator.geolocation) return;
    fab.classList.add('loading');
    navigator.geolocation.getCurrentPosition(
      pos => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        sessionStorage.setItem('user_lat', lat);
        sessionStorage.setItem('user_lng', lng);
        _map.setCenter(new kakao.maps.LatLng(lat, lng));
        const cat = document.querySelector('.filter-btn.active')?.dataset.cat || 'all';
        _fetchPlaces(lat, lng, cat);
        fab.classList.remove('loading');
      },
      () => fab.classList.remove('loading'),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });
}

// ══════════════════════════════════════════════════════════════
// 2. /api/places 호출
// ══════════════════════════════════════════════════════════════
async function _fetchPlaces(lat, lng, category = 'all', radius = 3000) {
  _showLoading(true);
  _activeIdx = -1;
  try {
    const res  = await fetch(`/api/places?lat=${lat}&lng=${lng}&radius=${radius}&category=${category}`);
    const data = await res.json();
    if (data.error) { console.error('[LALA API]', data.error); return; }
    _places = data.places || [];
    _renderMarkers(_places);
    _renderCards(_places);
  } catch (e) {
    console.error('[LALA] 장소 로드 실패:', e);
  } finally {
    _showLoading(false);
  }
}

// ══════════════════════════════════════════════════════════════
// 3. 마커 렌더링
// ══════════════════════════════════════════════════════════════
function _renderMarkers(places) {
  _markers.forEach(({ marker, overlay }) => { marker.setMap(null); overlay?.setMap(null); });
  _markers = [];

  places.forEach((place, idx) => {
    const cfg = CAT_CONFIG[place.category] || CAT_CONFIG.attraction;
    const pos = new kakao.maps.LatLng(place.lat, place.lng);

    const marker = new kakao.maps.Marker({
      position: pos,
      image: _makeMarkerImage(cfg.color, false),
      map: _map,
    });

    // 이름 툴팁 오버레이 (기본 숨김)
    const overlay = new kakao.maps.CustomOverlay({
      position: pos,
      content : `<div class="marker-tooltip" style="border-color:${cfg.color}">${place.name}</div>`,
      yAnchor : 1,
      map     : null,
    });

    kakao.maps.event.addListener(marker, 'click', () => _selectPlace(idx));
    _markers.push({ marker, overlay, place, idx });
  });
}

// ── 마커 이미지 팩토리 ───────────────────────────────────────
function _makeMarkerImage(color, active) {
  const size   = active ? new kakao.maps.Size(40, 50) : new kakao.maps.Size(28, 36);
  const offset = active ? new kakao.maps.Point(20, 50) : new kakao.maps.Point(14, 36);
  return new kakao.maps.MarkerImage(_makePinSVG(color, active), size, { offset });
}

function _makePinSVG(color, active) {
  // 활성 상태: 글로우 원 + 큰 내부 원
  const glow = active
    ? `<circle cx="16" cy="16" r="15" fill="${color}" opacity="0.20"/>`
    : '';
  const innerR = active ? 8 : 6;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 40">
    ${glow}
    <path d="M16 0C7.163 0 0 7.163 0 16c0 10 16 24 16 24S32 26 32 16C32 7.163 24.837 0 16 0z"
          fill="${color}"/>
    <circle cx="16" cy="16" r="${innerR}" fill="#fff"/>
  </svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}

// ── 마커 활성/비활성 일괄 업데이트 ──────────────────────────
function _setActiveMarker(idx) {
  _markers.forEach(({ marker, overlay, place }, i) => {
    const cfg = CAT_CONFIG[place.category] || CAT_CONFIG.attraction;
    const isActive = i === idx;
    marker.setImage(_makeMarkerImage(cfg.color, isActive));
    overlay.setMap(isActive ? _map : null);
  });
}

// ══════════════════════════════════════════════════════════════
// 4. 하단 카드 렌더링 (Swiper)
// ══════════════════════════════════════════════════════════════
function _renderCards(places) {
  const wrapper = document.getElementById('swiper-wrapper');
  const panel   = document.getElementById('card-panel');

  if (!places.length) {
    panel.style.display = 'none';
    document.body.classList.remove('has-card-panel');
    return;
  }

  wrapper.innerHTML = places.map((p, i) => `
    <div class="swiper-slide" data-idx="${i}" style="padding:0 6px;">
      <div class="place-card" id="card-${i}">
        <div class="place-card__meta">
          <span class="place-card__badge ${CAT_CONFIG[p.category]?.badgeClass || ''}">
            ${CAT_CONFIG[p.category]?.label || p.category}
          </span>
          ${p.distance_m != null ? `<span class="place-card__dist">${p.distance_m}m</span>` : ''}
          <span class="place-card__region">${p.region || ''}</span>
        </div>
        <div class="place-card__name">${p.name}</div>
        <div class="place-card__addr">${p.address || '주소 정보 없음'}</div>
        <div class="place-card__ai">AI가 이 장소를 추천하는 이유를 분석 중…</div>
      </div>
    </div>
  `).join('');

  panel.style.display = 'block';
  document.body.classList.add('has-card-panel');

  // Swiper 초기화 (재생성)
  if (_swiper) { _swiper.destroy(true, true); }
  _swiper = new Swiper('#place-swiper', {
    slidesPerView  : 1.1,
    centeredSlides : true,
    spaceBetween   : 8,
    breakpoints    : { 640: { slidesPerView: 1.5 } },
    on: {
      // ── 카드 스와이프 → 마커 활성화 + 지도 이동 ──
      slideChange() {
        if (_syncing) return;   // 마커 클릭에서 slideTo() 중이면 무시
        const idx = this.activeIndex;
        _activeIdx = idx;
        _setActiveMarker(idx);
        _setActiveCard(idx);
        const place = _places[idx];
        if (place) _map.panTo(new kakao.maps.LatLng(place.lat, place.lng));
      },
    },
  });
}

// ── 카드 활성 스타일 ─────────────────────────────────────────
function _setActiveCard(idx) {
  document.querySelectorAll('#swiper-wrapper .place-card').forEach((card, i) => {
    card.classList.toggle('place-card--active', i === idx);
  });
}

// ══════════════════════════════════════════════════════════════
// 5. 장소 선택 (마커 클릭 진입점) — 완전 양방향 동기화
// ══════════════════════════════════════════════════════════════
function _selectPlace(idx) {
  if (idx === _activeIdx) return;
  _activeIdx = idx;

  _setActiveMarker(idx);
  _setActiveCard(idx);

  const place = _places[idx];
  if (!place) return;
  _map.panTo(new kakao.maps.LatLng(place.lat, place.lng));

  // Swiper 이동 — slideChange 콜백 루프 방지
  if (_swiper && _swiper.activeIndex !== idx) {
    _syncing = true;
    _swiper.slideTo(idx, 300);
    setTimeout(() => { _syncing = false; }, 350);
  }

  // AI 추천 박스 + TTS FAB 표시
  const aiBox = document.getElementById('ai-recommendation');
  if (aiBox) aiBox.style.display = 'block';
  const ttsFab = document.getElementById('tts-fab');
  if (ttsFab) ttsFab.style.display = 'flex';

  // TTS 재생 중이면 중지 (다른 장소 선택)
  if (_ttsSpeaking && window.speechSynthesis) {
    speechSynthesis.cancel();
    _ttsSpeaking = false;
    const icon = document.getElementById('tts-icon');
    const fab  = document.getElementById('tts-fab');
    if (icon) icon.textContent = '🔊';
    if (fab)  fab.classList.remove('tts-active');
  }
}

// 전역 노출
window._selectPlace = _selectPlace;

// ══════════════════════════════════════════════════════════════
// 6. 날씨 위젯
// ══════════════════════════════════════════════════════════════
async function _loadWeather(lat, lng) {
  try {
    const r = await fetch(`/api/weather?lat=${lat}&lng=${lng}`);
    const d = await r.json();
    if (d.error) { console.warn('[LALA weather]', d.error); return; }
    document.getElementById('weather-icon').textContent = d.icon;
    document.getElementById('weather-temp').textContent = d.temp + '°C';
    document.getElementById('weather-widget').style.display = 'flex';
  } catch (e) {
    console.warn('[LALA weather] 호출 실패:', e);
  }
}

// ══════════════════════════════════════════════════════════════
// 7. TTS (Web Speech API)
// ══════════════════════════════════════════════════════════════
let _ttsSpeaking = false;

function _toggleTTS() {
  if (!window.speechSynthesis) return;
  const fab  = document.getElementById('tts-fab');
  const icon = document.getElementById('tts-icon');
  if (_ttsSpeaking) {
    speechSynthesis.cancel();
    _ttsSpeaking = false;
    if (icon) icon.textContent = '🔊';
    if (fab)  fab.classList.remove('tts-active');
    return;
  }
  const activeCard = document.querySelector('.place-card--active');
  if (!activeCard) return;
  const name    = activeCard.querySelector('.place-card__name')?.textContent?.trim() || '';
  const address = activeCard.querySelector('.place-card__addr')?.textContent?.trim() || '';
  const text    = name + (address ? '. ' + address : '');
  const langMap = { ko: 'ko-KR', en: 'en-US', ja: 'ja-JP' };
  const utt     = new SpeechSynthesisUtterance(text);
  utt.lang = langMap[sessionStorage.getItem('lang') || 'ko'] || 'ko-KR';
  utt.onend = () => {
    _ttsSpeaking = false;
    if (icon) icon.textContent = '🔊';
    if (fab)  fab.classList.remove('tts-active');
  };
  speechSynthesis.speak(utt);
  _ttsSpeaking = true;
  if (icon) icon.textContent = '⏹';
  if (fab)  fab.classList.add('tts-active');
}

// ── 유틸 ──────────────────────────────────────────────────────
function _showLoading(show) {
  const el = document.getElementById('loading-overlay');
  if (el) el.style.display = show ? 'flex' : 'none';
}

