(function () {
  const TEXT = window.LALA_MAP_TEXT || {};
  const S = window.LalaState;
  S.ensureDefaults();
  const storedLat = Number(sessionStorage.getItem('user_lat') || '37.2636');
  const storedLng = Number(sessionStorage.getItem('user_lng') || '127.0286');
  const storedAccuracy = Number(sessionStorage.getItem('user_accuracy') || '');

  const APP = {
    map: null,
    markers: [],
    places: [],
    weather: null,
    selectedPlace: null,
    selectedCategory: 'all',
    selectedLanguage: S.getString(S.keys.selectedLanguage, 'ko'),
    fontScale: S.getNumber(S.keys.fontScale, 1.0),
    isVoiceGuidanceEnabled: S.getBool(S.keys.isVoiceGuidanceEnabled, true),
    isAutoDocentEnabled: S.getBool(S.keys.isAutoDocentEnabled, false),
    autoDocentCooldownMs: 12000,
    autoDocentTriggerMeters: 100,
    lastAutoDocentAt: 0,
    lastAutoPlaceId: null,
    userPosition: {
      lat: Number.isFinite(storedLat) ? storedLat : 37.2636,
      lng: Number.isFinite(storedLng) ? storedLng : 127.0286,
      accuracy: Number.isFinite(storedAccuracy) && storedAccuracy > 0 ? storedAccuracy : null
    },
    userMarker: null,
    userAccuracyCircle: null,
    weatherRequest: null,
    weatherCacheTtlMs: 180000,
    weatherMaxAgeMs: 600000,
    weatherReloadThresholdMeters: 10000,
    lastWeatherFetchAt: 0,
    lastWeatherKey: '',
    lastWeatherPosition: null,
    currentAudio: null,
    watchId: null,
    hasPlayedDetailForPlace: new Set(),
    dailyPlan: null
  };

  function guardRoute() {
    if (!S.getBool(S.keys.hasAcceptedPrivacyNotice, false)) {
      window.location.replace('/privacy');
      return false;
    }
    if (!S.getBool(S.keys.isLocationConsentEnabled, false)) {
      window.location.replace('/location-consent');
      return false;
    }
    if (!S.getBool(S.keys.hasCompletedOnboarding, false)) {
      window.location.replace('/onboarding');
      return false;
    }
    return true;
  }

  if (!guardRoute()) {
    return;
  }

  function showLoading(show) {
    const el = document.getElementById('loading-overlay');
    if (!el) return;
    el.style.display = show ? 'flex' : 'none';
  }

  function setStatus(text, options = {}) {
    const statusEl = document.getElementById('status-text');
    const retryBtn = document.getElementById('retry-btn');
    if (statusEl) statusEl.textContent = text;
    if (retryBtn) {
      retryBtn.style.display = options.showRetry ? 'inline-flex' : 'none';
    }
  }

  function categoryColor(category) {
    if (category === 'attraction') return '#C53030';
    if (category === 'restaurant') return '#F5C842';
    if (category === 'event') return '#2B6CB0';
    return '#1A202C';
  }

  function placeName(place) {
    if (APP.selectedLanguage === 'en') {
      return (place.name_en || place.name || '').trim();
    }
    return (place.name || '').trim();
  }

  function placeRegion(place) {
    if (APP.selectedLanguage === 'en') {
      return (place.region_en || place.region || '').trim();
    }
    return (place.region || '').trim();
  }

  function placeAddress(place) {
    if (APP.selectedLanguage === 'en') {
      return (place.address_en || place.address || '').trim();
    }
    return (place.address || '').trim();
  }

  function placeDistance(place) {
    if (place.distance_m == null) return '';
    const value = Number(place.distance_m);
    if (!Number.isFinite(value)) return '';
    if (value >= 1000) return (value / 1000).toFixed(1) + 'km';
    return value + 'm';
  }

  function placeCategoryLabel(place) {
    const category = (place.category || '').trim().toLowerCase();
    if (APP.selectedLanguage === 'en') {
      if (category === 'attraction') return 'Local Attraction';
      if (category === 'restaurant') return 'Local Restaurant';
      if (category === 'event') return 'Local Event';
      return 'Local Place';
    }

    if (category === 'attraction') return '로컬 명소';
    if (category === 'restaurant') return '로컬 맛집';
    if (category === 'event') return '로컬 행사';
    return '로컬 장소';
  }

  function makePinSvg(color, active) {
    const size = active ? 42 : 34;
    const inner = active ? 7.5 : 6;
    const glow = active
      ? `<circle cx="16" cy="16" r="15" fill="${color}" opacity="0.18"/>`
      : '';
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 40">${glow}
      <path d="M16 0C7.163 0 0 7.163 0 16c0 10 16 24 16 24s16-14 16-24C32 7.163 24.837 0 16 0z" fill="${color}"/>
      <circle cx="16" cy="16" r="${inner}" fill="#fff"/>
    </svg>`;
    const src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    return new kakao.maps.MarkerImage(
      src,
      new kakao.maps.Size(size, size + 10),
      { offset: new kakao.maps.Point(size / 2, size + 10) }
    );
  }

  function makeUserMarkerSvg() {
    const size = 28;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 28 28">
      <circle cx="14" cy="14" r="12" fill="#2B6CB0" opacity="0.18"/>
      <circle cx="14" cy="14" r="8" fill="#2B6CB0" stroke="#fff" stroke-width="4"/>
      <circle cx="14" cy="14" r="2.4" fill="#fff"/>
    </svg>`;
    const src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    return new kakao.maps.MarkerImage(
      src,
      new kakao.maps.Size(size, size),
      { offset: new kakao.maps.Point(size / 2, size / 2) }
    );
  }

  function clearMarkers() {
    APP.markers.forEach((item) => item.marker.setMap(null));
    APP.markers = [];
  }

  function renderUserLocation() {
    if (!APP.map || !APP.userPosition) return;
    const latLng = new kakao.maps.LatLng(APP.userPosition.lat, APP.userPosition.lng);

    if (!APP.userMarker) {
      APP.userMarker = new kakao.maps.Marker({
        position: latLng,
        image: makeUserMarkerSvg(),
        zIndex: 5
      });
    } else {
      APP.userMarker.setPosition(latLng);
    }
    APP.userMarker.setMap(APP.map);

    if (APP.userAccuracyCircle) {
      APP.userAccuracyCircle.setMap(null);
      APP.userAccuracyCircle = null;
    }

    const accuracy = Number(APP.userPosition.accuracy);
    if (Number.isFinite(accuracy) && accuracy > 0) {
      APP.userAccuracyCircle = new kakao.maps.Circle({
        center: latLng,
        radius: Math.min(Math.max(accuracy, 20), 160),
        strokeWeight: 1,
        strokeColor: '#2B6CB0',
        strokeOpacity: 0.32,
        strokeStyle: 'solid',
        fillColor: '#2B6CB0',
        fillOpacity: 0.12
      });
      APP.userAccuracyCircle.setMap(APP.map);
    }
  }

  function setUserPosition(nextPosition, options = {}) {
    const lat = Number(nextPosition.lat);
    const lng = Number(nextPosition.lng);
    const accuracy = Number(nextPosition.accuracy);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

    APP.userPosition = {
      lat,
      lng,
      accuracy: Number.isFinite(accuracy) && accuracy > 0 ? accuracy : null
    };

    sessionStorage.setItem('user_lat', String(lat));
    sessionStorage.setItem('user_lng', String(lng));
    if (APP.userPosition.accuracy != null) {
      sessionStorage.setItem('user_accuracy', String(APP.userPosition.accuracy));
    } else {
      sessionStorage.removeItem('user_accuracy');
    }

    renderUserLocation();
    if (options.panTo && APP.map) {
      APP.map.setCenter(new kakao.maps.LatLng(lat, lng));
    }
  }

  function drawMarkers(places) {
    clearMarkers();
    places.forEach((place) => {
      const marker = new kakao.maps.Marker({
        position: new kakao.maps.LatLng(place.lat, place.lng),
        image: makePinSvg((place.category === 'event' && place.is_ongoing === false) ? '#9ca3af' : categoryColor(place.category), false),
        map: APP.map
      });
      kakao.maps.event.addListener(marker, 'click', () => {
        selectPlace(place, { from: 'marker', openDetail: true });
      });
      APP.markers.push({ placeId: place.id, marker, place });
    });
  }

  function syncMarkerState() {
    APP.markers.forEach((item) => {
      const active = APP.selectedPlace && APP.selectedPlace.id === item.placeId;
      item.marker.setImage(makePinSvg((item.place.category === 'event' && item.place.is_ongoing === false) ? '#9ca3af' : categoryColor(item.place.category), active));
    });
  }

  function buildCard(place) {
    const active = APP.selectedPlace && APP.selectedPlace.id === place.id;
    const isExpiredEvent = place.category === 'event' && place.is_ongoing === false;
    const wrapper = document.createElement('button');
    wrapper.type = 'button';
    wrapper.className = 'place-card' + (active ? ' active' : '') + (isExpiredEvent ? ' place-card--expired' : '');
    wrapper.dataset.placeId = place.id;

    const image = place.image_url
      ? `<img class="place-card__thumb" src="${escapeHtml(place.image_url)}" alt="${escapeHtml(placeName(place))}" onerror="this.style.display='none'" />`
      : `<div class="place-card__thumb" aria-hidden="true"></div>`;
    const distance = placeDistance(place);
    const region = placeRegion(place);
    const category = (place.category || 'all').toLowerCase();
    const metaParts = [];
    if (region) metaParts.push(`<span>${escapeHtml(region)}</span>`);
    if (distance) metaParts.push(`<span>${escapeHtml(distance)}</span>`);
    let categoryLabel = placeCategoryLabel(place);
    if (place.category === 'event') {
      categoryLabel += isExpiredEvent ? ' · 종료됨' : ' · 진행중';
    }

    wrapper.innerHTML = `
      <div class="place-card__copy">
        <div class="place-card__name">${escapeHtml(placeName(place))}</div>
        <div class="place-card__category place-card__category--${escapeHtml(category)}">
          ${escapeHtml(categoryLabel)}
        </div>
        <div class="place-card__meta">${metaParts.join('')}</div>
      </div>
      ${image}
    `;

    wrapper.addEventListener('click', () => {
      const alreadySelected = APP.selectedPlace && APP.selectedPlace.id === place.id;
      selectPlace(place, { from: 'card', openDetail: !alreadySelected });
    });
    return wrapper;
  }

  function renderCards() {
    const panel = document.getElementById('card-panel');
    panel.innerHTML = '';
    APP.places.forEach((place) => {
      panel.appendChild(buildCard(place));
    });
  }

  function recommendationText(place) {
    const category = place.category || '';
    const district = placeRegion(place);
    const address = placeAddress(place);
    const distance = placeDistance(place);

    if (APP.selectedLanguage === 'en') {
      if (!distance) return `A highly rated ${category} spot around ${district}. ${address}`;
      return `A recommended ${category} spot about ${distance} from your current location. ${address}`;
    }

    if (!distance) return `${district}의 ${category} 카테고리에서 인기가 높은 장소예요. ${address}`;
    return `현재 위치에서 약 ${distance} 거리의 ${category} 추천 장소예요. ${address}`;
  }

  function formatForecastTime(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';

    const hasTimezone = /[zZ]|[+-]\d{2}:\d{2}$/.test(raw);
    const normalized =
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(raw) && !hasTimezone
        ? raw + '+09:00'
        : raw;
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return raw;

    const locale = APP.selectedLanguage === 'en' ? 'en-US' : 'ko-KR';
    return new Intl.DateTimeFormat(locale, {
      timeZone: 'Asia/Seoul',
      month: APP.selectedLanguage === 'en' ? 'short' : 'long',
      day: 'numeric',
      weekday: 'short',
      hour: 'numeric',
      minute: '2-digit'
    }).format(date);
  }

  function dustGradeLabel(dust) {
    if (!dust) return APP.selectedLanguage === 'en' ? 'Unknown' : '정보없음';
    if (APP.selectedLanguage !== 'en') {
      return dust.grade_ko || '정보없음';
    }

    if (dust.grade === 'good') return 'Good';
    if (dust.grade === 'normal') return 'Moderate';
    if (dust.grade === 'bad') return 'Bad';
    if (dust.grade === 'very_bad') return 'Very Bad';
    return 'Unknown';
  }

  function dustSummaryText(dust) {
    const label = APP.selectedLanguage === 'en' ? 'Fine Dust' : '미세먼지';
    const grade = dustGradeLabel(dust);
    const isNormal = !dust || dust.grade === 'normal' || dust.grade === 'good';
    if (isNormal) return `${label} ${grade}`;
    const metrics = [];
    if (dust.pm10 != null) metrics.push(`PM10 ${dust.pm10}`);
    if (dust.pm25 != null) metrics.push(`PM2.5 ${dust.pm25}`);
    if (!metrics.length) {
      return `${label} ${grade}`;
    }
    return `${label} ${grade} (${metrics.join(' / ')})`;
  }

  function weatherRequestKey() {
    return `${APP.userPosition.lat.toFixed(3)}|${APP.userPosition.lng.toFixed(3)}`;
  }

  function currentWeatherPosition() {
    return {
      lat: APP.userPosition.lat,
      lng: APP.userPosition.lng
    };
  }

  function shouldReloadWeather(options = {}) {
    if (options.force) return true;
    if (!APP.weather || !APP.lastWeatherPosition) return true;

    const ageMs = Date.now() - APP.lastWeatherFetchAt;
    if (ageMs >= APP.weatherMaxAgeMs) {
      return true;
    }

    return distanceMeters(
      APP.lastWeatherPosition.lat,
      APP.lastWeatherPosition.lng,
      APP.userPosition.lat,
      APP.userPosition.lng
    ) >= APP.weatherReloadThresholdMeters;
  }

  function renderWeatherSummary(payload) {
    APP.weather = payload;
    const tempText = payload && payload.temp != null && payload.temp !== '' ? payload.temp : '--';
    document.getElementById('weather-icon').textContent = payload.icon || '🌡️';
    document.getElementById('weather-temp').textContent = `${tempText}°C`;
    document.getElementById('weather-dust').textContent = dustSummaryText(payload.dust);
  }

  function openSheet(id) {
    document.getElementById('sheet-backdrop').classList.add('active');
    document.getElementById(id).classList.add('active');
    // [UX개선] 시트가 열리면 카드 패널 + 자막 패널 숨기기 (Google Maps 방식)
    const cardPanel = document.getElementById('card-panel');
    if (cardPanel) cardPanel.classList.add('hidden');
    const subtitlePanel = document.getElementById('status-panel');
    if (subtitlePanel) subtitlePanel.classList.add('hidden');
  }

  function closeSheets() {
    document.getElementById('sheet-backdrop').classList.remove('active');
    document.querySelectorAll('.bottom-sheet').forEach((sheet) => {
      sheet.classList.remove('active');
    });
    // [UX개선] 시트가 닫히면 카드 패널 + 자막 패널 복원
    const cardPanel = document.getElementById('card-panel');
    if (cardPanel) cardPanel.classList.remove('hidden');
    const subtitlePanel = document.getElementById('status-panel');
    if (subtitlePanel) subtitlePanel.classList.remove('hidden');
  }

  function _fmtEventDate(dateStr) {
    if (!dateStr) return '';
    const m = dateStr.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return dateStr;
    return `${m[1]}년 ${m[2]}월 ${m[3]}일`;
  }

  function renderDetailSheet(place) {
    document.getElementById('detail-title').textContent = placeName(place);
    const sub = [place.category || '', placeRegion(place), placeDistance(place)].filter(Boolean).join(' · ');
    document.getElementById('detail-sub').textContent = sub;
    const detailImage = document.getElementById('detail-image');
    if (place.image_url) {
      detailImage.style.display = 'block';
      detailImage.src = place.image_url;
    } else {
      detailImage.style.display = 'none';
    }
    document.getElementById('detail-recommend').textContent = recommendationText(place);

    const eventInfoEl = document.getElementById('detail-event-info');
    const hasEvent = place.category === 'event';
    eventInfoEl.style.display = hasEvent ? 'block' : 'none';
    if (hasEvent) {
      const isOngoing = place.is_ongoing !== false;
      const statusEl = document.getElementById('detail-event-status');
      statusEl.textContent = isOngoing ? '🟢 진행 중' : '⛔ 종료된 행사';
      statusEl.style.color = isOngoing ? '#2B6CB0' : '#9ca3af';

      const hasDates = !!(place.event_start_date || place.event_end_date);
      const datesEl = document.getElementById('detail-event-dates');
      if (hasDates) {
        const start = _fmtEventDate(place.event_start_date);
        const end   = _fmtEventDate(place.event_end_date);
        let dateText = '🗓️';
        if (start && end)  dateText += ` ${start} ~ ${end}`;
        else if (start)    dateText += ` ${start}부터`;
        else if (end)      dateText += ` ~${end}까지`;
        datesEl.textContent = dateText;
        datesEl.style.display = 'block';
      } else {
        datesEl.style.display = 'none';
      }
      const linkEl = document.getElementById('detail-event-link');
      if (place.event_url) {
        linkEl.href = place.event_url;
        linkEl.style.display = 'block';
      } else {
        linkEl.style.display = 'none';
      }
      const approxEl = document.getElementById('detail-event-approx');
      approxEl.style.display = place.is_approximate_location ? 'block' : 'none';
    }

    const moreBtn = document.getElementById('detail-more-btn');
    const canMore = !APP.hasPlayedDetailForPlace.has(place.id);
    moreBtn.style.display = canMore ? 'inline-block' : 'none';
    moreBtn.onclick = () => {
      APP.hasPlayedDetailForPlace.add(place.id);
      closeSheets();
      requestDocent(place, 'detail');
    };
    openSheet('detail-sheet');
  }

  function renderWeatherSheet() {
    const wrap = document.getElementById('forecast-chart');
    const nowText = document.getElementById('weather-now');
    const dustText = document.getElementById('weather-dust-detail');

    if (!APP.weather) {
      nowText.textContent = TEXT.weatherEmpty || '';
      dustText.textContent = '';
      wrap.innerHTML = '';
      return;
    }

    nowText.textContent = `${TEXT.weatherNow || ''} ${APP.weather.temp}°C`;
    dustText.textContent = dustSummaryText(APP.weather.dust);

    const list = Array.isArray(APP.weather.forecast) ? APP.weather.forecast : [];
    if (!list.length) {
      wrap.innerHTML = `<p class="forecast-empty">${escapeHtml(TEXT.weatherEmpty || '')}</p>`;
      return;
    }

    const COL_W = 56;
    const SVG_H = 88;
    const PAD_TOP = 26;
    const PAD_BOT = 18;
    const DRAW_H = SVG_H - PAD_TOP - PAD_BOT;
    const totalW = list.length * COL_W;

    const parsedTemps = list.map(d => { const v = parseFloat(d.temp); return isNaN(v) ? null : v; });
    const validTemps = parsedTemps.filter(v => v !== null);
    const tMax = validTemps.length ? Math.max(...validTemps) : 1;
    const tMin = validTemps.length ? Math.min(...validTemps) : 0;
    const tRange = tMax - tMin || 1;

    const pts = list.map((item, i) => {
      const temp = parsedTemps[i];
      const x = i * COL_W + COL_W / 2;
      const y = temp !== null
        ? PAD_TOP + ((tMax - temp) / tRange) * DRAW_H
        : PAD_TOP + DRAW_H / 2;
      return { x, y, temp };
    });

    // Smooth cubic bezier curve
    let pathD = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
    for (let i = 1; i < pts.length; i++) {
      const mx = ((pts[i - 1].x + pts[i].x) / 2).toFixed(1);
      pathD += ` C ${mx} ${pts[i - 1].y.toFixed(1)}, ${mx} ${pts[i].y.toFixed(1)}, ${pts[i].x.toFixed(1)} ${pts[i].y.toFixed(1)}`;
    }

    const svgContent = [
      `<path d="${pathD}" fill="none" stroke="#c8c8cc" stroke-width="2.5" stroke-linecap="round"/>`,
      ...pts.map(p => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3.5" fill="#9ca3af"/>`),
      ...pts.map((p, i) => {
        const label = p.temp !== null ? `${Math.round(p.temp)}°` : '--';
        return `<text x="${p.x.toFixed(1)}" y="${(p.y - 10).toFixed(1)}" text-anchor="middle" class="forecast-temp-lbl">${escapeHtml(label)}</text>`;
      }),
    ].join('');

    const iconCells = list.map(item =>
      `<div class="forecast-icon-cell">${escapeHtml(item.icon || '')}</div>`
    ).join('');
    const timeCells = list.map(item =>
      `<div class="forecast-time-cell">${escapeHtml(_chartHourLabel(item.time))}</div>`
    ).join('');

    wrap.innerHTML = `
      <div class="forecast-chart-inner" style="width:${totalW}px">
        <svg class="forecast-svg" width="${totalW}" height="${SVG_H}" viewBox="0 0 ${totalW} ${SVG_H}">
          ${svgContent}
        </svg>
        <div class="forecast-icon-row">${iconCells}</div>
        <div class="forecast-time-row">${timeCells}</div>
      </div>`;
  }

  function _chartHourLabel(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const m = raw.match(/T(\d{2}):/);
    if (m) return `${m[1]}시`;
    const date = new Date(/[zZ+]/.test(raw) ? raw : raw + '+09:00');
    if (isNaN(date.getTime())) return raw;
    return `${String(date.getHours()).padStart(2, '0')}시`;
  }

  function setVoiceButtonState() {
    const voiceBtn = document.getElementById('voice-btn');
    voiceBtn.classList.toggle('secondary', !APP.isVoiceGuidanceEnabled);
    voiceBtn.textContent = APP.isVoiceGuidanceEnabled ? '🔊' : '🔇';
    S.setBool(S.keys.isVoiceGuidanceEnabled, APP.isVoiceGuidanceEnabled);
  }

  function setAutoButtonState() {
    const autoBtn = document.getElementById('auto-btn');
    const label = document.getElementById('auto-label');
    const iconSpan = autoBtn.querySelector('span:first-child');
    autoBtn.classList.toggle('active', APP.isAutoDocentEnabled);
    autoBtn.classList.toggle('secondary', !APP.isAutoDocentEnabled);
    label.textContent = APP.isAutoDocentEnabled ? 'ON' : 'OFF';
    if (iconSpan) iconSpan.textContent = APP.isAutoDocentEnabled ? '✨' : '⏸';
    S.setBool(S.keys.isAutoDocentEnabled, APP.isAutoDocentEnabled);
  }

  async function requestDocent(place, mode) {
    if (!place) return;
    setStatus(TEXT.docentLoading || '...');

    try {
      const response = await fetch('/api/docent/script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          place_id: place.id,
          category: place.category,
          language: APP.selectedLanguage,
          mode: mode || 'brief'
        })
      });
      const payload = await response.json();
      if (!response.ok || !payload.script) {
        throw new Error(payload.error || 'docent-script-failed');
      }

      setStatus(payload.script);
      const moreBtn = document.getElementById('more-info-btn');
      if (mode === 'brief' && !APP.hasPlayedDetailForPlace.has(place.id)) {
        moreBtn.style.display = 'inline-flex';
        moreBtn.onclick = () => {
          APP.hasPlayedDetailForPlace.add(place.id);
          requestDocent(place, 'detail');
          moreBtn.style.display = 'none';
        };
      } else {
        moreBtn.style.display = 'none';
      }

      if (APP.isVoiceGuidanceEnabled) {
        await requestDocentAudio(payload.script);
      }
    } catch (error) {
      setStatus(TEXT.docentUnavailable || String(error));
    }
  }

  async function requestDocentAudio(script) {
    try {
      const response = await fetch('/api/docent/audio', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script, language: APP.selectedLanguage })
      });
      if (!response.ok) {
        return;
      }
      const audioBlob = await response.blob();
      if (APP.currentAudio) {
        APP.currentAudio.pause();
      }
      const audioUrl = URL.createObjectURL(audioBlob);
      APP.currentAudio = new Audio(audioUrl);
      APP.currentAudio.onended = () => URL.revokeObjectURL(audioUrl);
      APP.currentAudio.play().catch(() => {
        URL.revokeObjectURL(audioUrl);
      });
    } catch (_err) {
      // Keep subtitle text even when audio playback fails.
    }
  }

  function selectPlace(place, options = {}) {
    APP.selectedPlace = place;
    syncMarkerState();
    renderCards();

    if (APP.map && options.shouldPan !== false) {
      APP.map.panTo(new kakao.maps.LatLng(place.lat, place.lng));
    }

    requestDocent(place, 'brief');
    if (options.openDetail) {
      renderDetailSheet(place);
    }
  }

  function distanceMeters(lat1, lng1, lat2, lng2) {
    const R = 6371000;
    const toRad = (v) => (v * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
      Math.sin(dLng / 2) * Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  function runAutoDocentIfNeeded() {
    if (!APP.isAutoDocentEnabled) return;
    if (!APP.userPosition || !APP.places.length) return;
    const now = Date.now();
    if (now - APP.lastAutoDocentAt < APP.autoDocentCooldownMs) return;

    let nearest = null;
    APP.places.forEach((place) => {
      const d = distanceMeters(APP.userPosition.lat, APP.userPosition.lng, place.lat, place.lng);
      if (!nearest || d < nearest.distance) {
        nearest = { place, distance: d };
      }
    });

    if (!nearest || nearest.distance > APP.autoDocentTriggerMeters) {
      APP.lastAutoPlaceId = null;
      return;
    }
    if (nearest.place.id === APP.lastAutoPlaceId) {
      return;
    }

    APP.lastAutoPlaceId = nearest.place.id;
    APP.lastAutoDocentAt = now;
    selectPlace(nearest.place, { from: 'auto', openDetail: false });
  }

  function renderLocationOverlay(show) {
    const overlay = document.getElementById('location-overlay');
    overlay.classList.toggle('active', !!show);
  }

  async function loadPlaces() {
    if (!APP.map) return;
    showLoading(true);
    try {
      const center = APP.map.getCenter();
      const lat = center.getLat();
      const lng = center.getLng();
      const query = new URLSearchParams({
        lat: String(lat),
        lng: String(lng),
        radius: '20000',
        category: APP.selectedCategory,
        scope: 'radius',
        limit: '100'
      });

      const response = await fetch('/api/places?' + query.toString());
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'places-failed');
      }

      APP.places = Array.isArray(payload.places) ? payload.places : [];
      drawMarkers(APP.places);
      renderCards();

      if (!APP.places.length) {
        setStatus(TEXT.noResults || 'No results', { showRetry: true });
      } else if (!APP.selectedPlace || !APP.places.find((p) => p.id === APP.selectedPlace.id)) {
        selectPlace(APP.places[0], { from: 'load', openDetail: false, shouldPan: false });
      }
      runAutoDocentIfNeeded();
    } catch (_error) {
      setStatus(TEXT.noResults || 'No results', { showRetry: true });
    } finally {
      showLoading(false);
    }
  }

  async function loadWeather(options = {}) {
    if (!shouldReloadWeather(options)) {
      renderWeatherSummary(APP.weather);
      return APP.weather;
    }

    const key = weatherRequestKey();
    const isFresh = !options.force && APP.weather && APP.lastWeatherKey === key &&
      (Date.now() - APP.lastWeatherFetchAt) < APP.weatherCacheTtlMs;

    if (isFresh) {
      renderWeatherSummary(APP.weather);
      return APP.weather;
    }

    if (APP.weatherRequest && APP.weatherRequest.key === key) {
      return APP.weatherRequest.promise;
    }

    const requestPromise = (async () => {
      try {
        const response = await fetch(`/api/weather?lat=${APP.userPosition.lat}&lng=${APP.userPosition.lng}`);
        const payload = await response.json();
        if (!response.ok) {
          return APP.weather;
        }
        APP.lastWeatherFetchAt = Date.now();
        APP.lastWeatherKey = key;
        APP.lastWeatherPosition = currentWeatherPosition();
        renderWeatherSummary(payload);
        // 날씨 갱신 직후 개입 알림 체크
        checkIntervention(APP.userPosition.lat, APP.userPosition.lng);
        return payload;
      } catch (_error) {
        return APP.weather;
      } finally {
        if (APP.weatherRequest && APP.weatherRequest.key === key) {
          APP.weatherRequest = null;
        }
      }
    })();

    APP.weatherRequest = { key, promise: requestPromise };
    return requestPromise;
  }

  async function requestCurrentLocation(options = {}) {
    const config = {
      panTo: false,
      reloadPlaces: false,
      reloadWeather: false,
      forceWeather: false,
      showOverlayOnError: true,
      enableHighAccuracy: true,
      timeout: 8000,
      maximumAge: 60000,
      ...options
    };

    if (!navigator.geolocation) {
      if (config.showOverlayOnError) {
        renderLocationOverlay(true);
      }
      return false;
    }

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          setUserPosition(
            {
              lat: pos.coords.latitude,
              lng: pos.coords.longitude,
              accuracy: pos.coords.accuracy
            },
            { panTo: config.panTo }
          );
          renderLocationOverlay(false);

          if (config.reloadPlaces) {
            await loadPlaces();
          }
          if (config.reloadWeather) {
            await loadWeather({ force: config.forceWeather });
          }
          resolve(true);
        },
        () => {
          if (config.showOverlayOnError) {
            renderLocationOverlay(true);
          }
          resolve(false);
        },
        {
          enableHighAccuracy: config.enableHighAccuracy,
          timeout: config.timeout,
          maximumAge: config.maximumAge
        }
      );
    });
  }

  async function bootstrapLocationState() {
    const initialPlacesPromise = loadPlaces();

    const resolved = await requestCurrentLocation({
      panTo: true,
      reloadPlaces: true,
      reloadWeather: true,
      forceWeather: true,
      showOverlayOnError: false,
      enableHighAccuracy: true,
      timeout: 7000,
      maximumAge: 120000
    });

    await initialPlacesPromise;

    if (!resolved) {
      await loadWeather({ force: true });
      renderLocationOverlay(true);
    }
  }

  function bindEvents() {
    document.getElementById('weather-btn').addEventListener('click', async () => {
      await loadWeather();
      renderWeatherSheet();
      openSheet('weather-sheet');
    });

    document.getElementById('sheet-backdrop').addEventListener('click', closeSheets);

    document.getElementById('voice-btn').addEventListener('click', () => {
      APP.isVoiceGuidanceEnabled = !APP.isVoiceGuidanceEnabled;
      setVoiceButtonState();
      if (!APP.isVoiceGuidanceEnabled && APP.currentAudio) {
        APP.currentAudio.pause();
      }
    });

    document.getElementById('auto-btn').addEventListener('click', () => {
      APP.isAutoDocentEnabled = !APP.isAutoDocentEnabled;
      setAutoButtonState();
      runAutoDocentIfNeeded();
    });

    document.getElementById('loc-btn').addEventListener('click', () => {
      requestCurrentLocation({
        panTo: true,
        reloadPlaces: true,
        reloadWeather: true,
        forceWeather: true,
        showOverlayOnError: true,
        enableHighAccuracy: true,
        timeout: 8000,
        maximumAge: 0
      });
    });

    document.getElementById('overlay-retry').addEventListener('click', () => {
      document.getElementById('loc-btn').click();
    });

    document.getElementById('retry-btn').addEventListener('click', () => {
      loadPlaces();
    });

    document.querySelectorAll('.map-chip').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.map-chip').forEach((el) => el.classList.remove('active'));
        btn.classList.add('active');
        APP.selectedCategory = btn.dataset.category;
        loadPlaces();
      });
    });

    document.getElementById('planner-btn').addEventListener('click', () => {
      if (APP.dailyPlan) {
        // 기존 계획 있으면 바로 시트를 열고, 재생성 여부를 확인
        openSheet('planner-sheet');
        renderPlannerSheet(APP.dailyPlan);
        // 헤더에 재생성 버튼 표시
        _showPlannerRefreshBtn();
        return;
      }
      const center = APP.map ? APP.map.getCenter() : null;
      const lat = center ? center.getLat() : APP.userPosition?.lat;
      const lng = center ? center.getLng() : APP.userPosition?.lng;
      if (!lat || !lng) return;
      fetchDailyPlan(lat, lng);
    });

    document.getElementById('intervention-toast-close').addEventListener('click', () => {
      document.getElementById('intervention-toast').style.display = 'none';
    });
  }

  function startGeolocationWatch() {
    if (!navigator.geolocation) {
      renderLocationOverlay(true);
      return;
    }

    APP.watchId = navigator.geolocation.watchPosition(
      (pos) => {
        setUserPosition({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy
        });
        renderLocationOverlay(false);
        loadWeather();
        runAutoDocentIfNeeded();
      },
      () => {
        renderLocationOverlay(true);
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 120000 }
    );
  }

  // ── 하루 일정 플래너 ────────────────────────────────────────────────────

  const PERIOD_ICON = { '오전': '🌅', '오후': '☀️', '저녁': '🌙' };
  const ALERT_LABEL = {
    rain_alert: '☔ 비가 옵니다 — 실내 장소를 추천해요',
    pm_alert: '😷 미세먼지가 나빠요 — 실내 장소를 추천해요',
    clear_sky_alert: '☀️ 날씨가 맑아요! 야외 활동하기 좋아요',
  };

  async function fetchDailyPlan(lat, lng) {
    openSheet('planner-sheet');
    const slotsEl = document.getElementById('planner-slots');
    slotsEl.innerHTML = '<div class="planner-skeleton">일정을 생성하는 중…<br><small style="opacity:.6;font-size:.75rem">처음 방문하는 장소는 최대 30~60초 소요돼요</small></div>';
    document.getElementById('planner-location').textContent = '';
    document.getElementById('planner-weather').textContent = '';

    try {
      const res = await fetch('/api/planner/daily-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat, lng, language: APP.selectedLanguage || 'Korean' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'planner error');
      APP.dailyPlan = data;
      renderPlannerSheet(data);
      _showPlannerRefreshBtn();
    } catch (err) {
      slotsEl.innerHTML = `<p class="planner-error">일정을 가져오지 못했어요. 다시 시도해주세요.</p>`;
    }
  }

  function _showPlannerRefreshBtn() {
    const header = document.querySelector('#planner-sheet .planner-sheet__header');
    if (!header) return;
    let btn = header.querySelector('.planner-refresh-btn');
    if (!btn) {
      btn = document.createElement('button');
      btn.className = 'map-pill-btn planner-refresh-btn';
      btn.textContent = '🔄 일정 재생성';
      btn.addEventListener('click', () => {
        if (!confirm('하루 일정을 다시 생성할까요?\n현재 지도의 위치를 기준으로 새 일정이 만들어집니다.')) return;
        APP.dailyPlan = null;
        const center = APP.map ? APP.map.getCenter() : null;
        const lat = center ? center.getLat() : APP.userPosition?.lat;
        const lng = center ? center.getLng() : APP.userPosition?.lng;
        if (!lat || !lng) return;
        fetchDailyPlan(lat, lng);
      });
      header.appendChild(btn);
    }
  }

  function renderPlannerSheet(data) {
    document.getElementById('planner-location').textContent = data.location || '';
    const w = data.weather || {};
    const badge = [w.outdoor_status, w.temperature ? `${w.temperature}°C` : null]
      .filter(Boolean).join('  ');
    document.getElementById('planner-weather').textContent = badge;

    const slotsEl = document.getElementById('planner-slots');
    slotsEl.innerHTML = '';

    const plan = data.plan || [];
    if (!plan.length) {
      slotsEl.innerHTML = '<p class="planner-error">추천 장소가 없어요.</p>';
      return;
    }

    plan.forEach((item) => {
      const icon = PERIOD_ICON[item.period] || '📍';
      const place = item.place || {};
      const card = document.createElement('div');
      card.className = 'plan-slot-card';
      card.innerHTML = `
        <div class="plan-slot-card__period">${icon} <strong>${escapeHtml(item.period)}</strong><span class="plan-slot-card__time">${escapeHtml(item.time || '')}</span></div>
        <div class="plan-slot-card__name">${escapeHtml(place.name || '')}</div>
        ${place.road_addr ? `<div class="plan-slot-card__addr">${escapeHtml(place.road_addr)}</div>` : ''}
        ${item.script ? `<p class="plan-slot-card__script">${escapeHtml(item.script)}</p>` : ''}
      `;
      // 지도 이동
      if (place.lat && place.lng) {
        card.addEventListener('click', () => {
          closeSheets();
          if (APP.map) {
            APP.map.setCenter(new kakao.maps.LatLng(place.lat, place.lng));
            APP.map.setLevel(4);
          }
        });
        card.style.cursor = 'pointer';
      }
      slotsEl.appendChild(card);
    });
  }

  // ── 날씨 개입 알림 ────────────────────────────────────────────────────────

  async function checkIntervention(lat, lng) {
    try {
      const res = await fetch(`/api/planner/intervention?lat=${lat}&lng=${lng}`);
      const data = await res.json();
      if (!res.ok || !data.intervention) return;
      showInterventionToast(data.intervention);
    } catch (_) {
      // 개입 알림 실패는 무시
    }
  }

  function showInterventionToast(intervention) {
    const label = ALERT_LABEL[intervention.type] || '날씨가 바뀌었어요';
    const toast = document.getElementById('intervention-toast');
    document.getElementById('intervention-toast-text').textContent = label;
    toast.style.display = 'flex';
    // 8초 후 자동 닫기
    setTimeout(() => { toast.style.display = 'none'; }, 8000);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function initMap() {
    if (typeof kakao === 'undefined' || !kakao.maps) {
      setStatus('Kakao map sdk unavailable', { showRetry: true });
      return;
    }

    APP.map = new kakao.maps.Map(document.getElementById('map-container'), {
      center: new kakao.maps.LatLng(APP.userPosition.lat, APP.userPosition.lng),
      level: 5
    });
    renderUserLocation();

    kakao.maps.event.addListener(APP.map, 'dragend', function () {
      loadPlaces();
    });

    bindEvents();
    setVoiceButtonState();
    setAutoButtonState();
    setStatus(TEXT.defaultSubtitle || '');

    bootstrapLocationState().finally(() => {
      startGeolocationWatch();
    });
  }

  if (typeof kakao === 'undefined' || !kakao.maps || typeof kakao.maps.load !== 'function') {
    setStatus('Kakao map sdk unavailable', { showRetry: true });
    return;
  }

  kakao.maps.load(initMap);
})();
