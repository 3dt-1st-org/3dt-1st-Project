/* =============================================================
   dashboard.js — 수도권 실시간 대기질 대시보드
   Chart.js + 카카오맵 버블 오버레이
   ============================================================= */
(function () {
  'use strict';

  const TEXT = window.LALA_DASH_TEXT || {};
  const LANG = (document.documentElement.lang || 'ko').toLowerCase() === 'en' ? 'en' : 'ko';

  const CITY_EN_MAP = {
    '서울': 'Seoul',
    '인천': 'Incheon',
    '수원': 'Suwon',
    '성남': 'Seongnam',
    '의정부': 'Uijeongbu',
    '안양': 'Anyang',
    '부천': 'Bucheon',
    '광명': 'Gwangmyeong',
    '평택': 'Pyeongtaek',
    '동두천': 'Dongducheon',
    '안산': 'Ansan',
    '고양': 'Goyang',
    '과천': 'Gwacheon',
    '구리': 'Guri',
    '남양주': 'Namyangju',
    '오산': 'Osan',
    '시흥': 'Siheung',
    '군포': 'Gunpo',
    '의왕': 'Uiwang',
    '하남': 'Hanam',
    '용인': 'Yongin',
    '파주': 'Paju',
    '이천': 'Icheon',
    '안성': 'Anseong',
    '김포': 'Gimpo',
    '화성': 'Hwaseong',
    '광주': 'Gwangju',
    '양주': 'Yangju',
    '포천': 'Pocheon',
    '여주': 'Yeoju',
    '연천': 'Yeoncheon',
    '가평': 'Gapyeong',
    '양평': 'Yangpyeong',
    '전체': TEXT.locationAll || 'All Metro Areas',
  };

  function displayLocation(name) {
    const raw = String(name || '').trim();
    if (!raw || LANG !== 'en') return raw;
    return CITY_EN_MAP[raw] || raw;
  }

  function statusCategory(status) {
    const s = String(status || '').toLowerCase();
    if (!s) return 'fair';
    if (s.includes('쾌적') || s.includes('comfortable')) return 'good';
    if (s.includes('비') || s.includes('눈') || s.includes('rain') || s.includes('snow')) return 'rain';
    if (s.includes('나쁨') || s.includes('매우') || s.includes('poor') || s.includes('bad')) return 'poor';
    return 'fair';
  }

  function statusLabel(status) {
    const cat = statusCategory(status);
    if (LANG !== 'en') {
      if (cat === 'good') return TEXT.statusGood || '야외활동 쾌적';
      if (cat === 'rain') return TEXT.statusRain || '비/눈';
      if (cat === 'poor') return TEXT.statusPoor || '미세먼지 나쁨';
      return TEXT.statusFair || '보통';
    }
    if (cat === 'good') return TEXT.statusGood || 'Comfortable Outdoors';
    if (cat === 'rain') return TEXT.statusRain || 'Rain/Snow';
    if (cat === 'poor') return TEXT.statusPoor || 'Poor Air Quality';
    return TEXT.statusFair || 'Moderate';
  }

  /* ── 상수 ────────────────────────────────────────────────── */
  const STATUS_COLORS = {
    good: '#48BB78',
    fair: '#ECC94B',
    poor: '#FC8181',
    rain: '#90CDF4',
  };
  const DEFAULT_BUBBLE_COLOR = '#CBD5E0';

  /* ── 상태 ────────────────────────────────────────────────── */
  let donutChart   = null;
  let barChart     = null;
  let lineChart    = null;
  let kakaoMap     = null;
  let bubbleOverlays = [];
  let currentData  = null;
  let isFetching   = false;

  /* ── DOM 참조 ─────────────────────────────────────────────── */
  const locationSel    = document.getElementById('db-location-sel');
  const refreshBtn     = document.getElementById('db-refresh-btn');
  const lastRefreshed  = document.getElementById('db-last-refreshed');
  const narrativeEl    = document.getElementById('db-narrative-text');

  /* ── 초기화 ───────────────────────────────────────────────── */
  function init() {
    if (locationSel) {
      locationSel.addEventListener('change', fetchData);
    }
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function () {
        if (!isFetching) {
          fetchData();
        }
      });
    }
    fetchData();
  }

  /* ── 데이터 fetch ─────────────────────────────────────────── */
  function fetchData() {
    if (isFetching) return;
    isFetching = true;
    if (refreshBtn) {
      refreshBtn.classList.add('loading');
      refreshBtn.textContent = TEXT.refreshing || '↻ Refreshing...';
    }

    const loc = locationSel ? locationSel.value : '';
    const qs  = loc ? '?location=' + encodeURIComponent(loc) : '';

    fetch('/api/dashboard/data' + qs)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        currentData = data;
        populateLocationSelector(data.locations, loc || data.selected_location);
        renderAll(data);
        fetchNarrative(data);
      })
      .catch(function (err) {
        console.error('[Dashboard] fetch error:', err);
      })
      .finally(function () {
        isFetching = false;
        if (refreshBtn) {
          refreshBtn.classList.remove('loading');
          refreshBtn.textContent = TEXT.refresh || '↻ Refresh';
        }
      });
  }

  /* ── 지역 슬라이서 채우기 ─────────────────────────────────── */
  function populateLocationSelector(locations, selectedLoc) {
    if (!locationSel || locationSel.dataset.populated === 'true') return;
    locationSel.dataset.populated = 'true';

    // 기존 옵션 유지 (전체 수도권 option value="")
    locations.forEach(function (loc) {
      const opt = document.createElement('option');
      opt.value = loc;
      opt.textContent = displayLocation(loc);
      if (loc === selectedLoc) opt.selected = true;
      locationSel.appendChild(opt);
    });
  }

  /* ── 전체 렌더링 ──────────────────────────────────────────── */
  function renderAll(data) {
    renderKpi(data.kpi);
    renderDonut(data.donut);
    renderBar(data.bar_top5);
    renderLine(data.trend, data.selected_location);
    renderTable(data.raw_data);
    updateLastRefreshed(data.last_refreshed);
    if (kakaoMap !== null) {
      updateBubbles(data.map_data);
    }
  }

  /* ── KPI 카드 ─────────────────────────────────────────────── */
  function renderKpi(kpi) {
    renderKpiCard('kpi-temperature', kpi.temperature, '°C',    /* reverseDelta */ false);
    renderKpiCard('kpi-pm10',        kpi.pm10,        '㎍/㎥', /* reverseDelta */ true);
    renderKpiCard('kpi-pm25',        kpi.pm25,        '㎍/㎥', /* reverseDelta */ true);
    renderKpiCard('kpi-wind',        kpi.wind_speed,  'm/s',   /* reverseDelta */ false);
  }

  function renderKpiCard(cardId, item, unit, reverseDelta) {
    var card = document.getElementById(cardId);
    if (!card) return;

    var valEl   = card.querySelector('.db-kpi-card__value');
    var unitEl  = card.querySelector('.db-kpi-card__unit');
    var deltaEl = card.querySelector('.db-kpi-card__delta');

    var val   = item.value;
    var grade = item.grade || 'neutral';
    var delta = item.delta || {};

    if (valEl) {
      valEl.textContent = (val !== null && val !== undefined) ? val : '--';
      valEl.className   = 'db-kpi-card__value db-kpi--' + grade;
    }
    if (unitEl) unitEl.textContent = unit;

    if (deltaEl && delta.str && delta.str !== '—') {
      deltaEl.textContent = delta.str;
      if (reverseDelta) {
        // PM10/PM2.5: 오르면 나쁨(빨강), 내리면 좋음(초록)
        deltaEl.className = 'db-kpi-card__delta ' + (delta.up ? 'delta-up' : 'delta-down');
      } else {
        // 기온/풍속: 변화 방향만 표시
        deltaEl.className = 'db-kpi-card__delta delta-flat';
      }
    } else if (deltaEl) {
      deltaEl.textContent = '';
      deltaEl.className   = 'db-kpi-card__delta delta-flat';
    }
  }

  /* ── 도넛 차트 ────────────────────────────────────────────── */
  function renderDonut(donut) {
    var ctx = document.getElementById('db-donut-chart');
    if (!ctx) return;
    if (donutChart) { donutChart.destroy(); donutChart = null; }

    var labels = (donut.labels || []).map(statusLabel);
    var colors = (donut.labels || []).map(function (s) {
      return STATUS_COLORS[statusCategory(s)] || DEFAULT_BUBBLE_COLOR;
    });

    donutChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data:            donut.data,
          backgroundColor: colors,
          borderWidth:     2,
          borderColor:     '#fff',
          hoverOffset:     6,
        }],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'right',
            labels: {
              font:     { size: 10 },
              padding:  8,
              boxWidth: 10,
              color:    '#4A5568',
            },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                var pct   = total ? Math.round(ctx.raw / total * 100) : 0;
                return ' ' + ctx.label + ': ' + ctx.raw + (TEXT.cityUnit || ' cities') + ' (' + pct + '%)';
              },
            },
          },
        },
        cutout: '62%',
      },
    });
  }

  /* ── 가로 막대 차트 (TOP 5) ───────────────────────────────── */
  function renderBar(top5) {
    var ctx = document.getElementById('db-bar-chart');
    if (!ctx) return;
    if (barChart) { barChart.destroy(); barChart = null; }

    var labels   = top5.map(function (d) { return d.location; });
    labels = labels.map(displayLocation);
    var pm10data = top5.map(function (d) { return d.pm10; });
    var pm25data = top5.map(function (d) { return d.pm25; });

    barChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            label:           'PM10',
            data:            pm10data,
            backgroundColor: '#F6AD55',
            borderRadius:    3,
            barPercentage:   0.6,
          },
          {
            label:           'PM2.5',
            data:            pm25data,
            backgroundColor: '#FC8181',
            borderRadius:    3,
            barPercentage:   0.6,
          },
        ],
      },
      options: {
        indexAxis:           'y',
        responsive:          true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'top',
            labels:   { font: { size: 9 }, boxWidth: 9, padding: 6, color: '#4A5568' },
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                return ' ' + ctx.dataset.label + ': ' + ctx.raw + ' ㎍/㎥';
              },
            },
          },
        },
        scales: {
          x: {
            stacked: false,
            ticks:   { font: { size: 9 }, color: '#718096' },
            grid:    { color: '#EDF2F7' },
          },
          y: {
            ticks: { font: { size: 10 }, color: '#2D3748' },
            grid:  { display: false },
          },
        },
      },
    });
  }

  /* ── 꺾은선 차트 (12시간 트렌드) ─────────────────────────── */
  function renderLine(trend, locationLabel) {
    var ctx = document.getElementById('db-line-chart');
    if (!ctx) return;

    var titleEl = document.getElementById('db-trend-title');
    if (titleEl) {
      const tmpl = TEXT.trendTitleWithLoc || '[{location}] Last 12 Hours: Temperature / PM2.5 Trend';
      titleEl.textContent = tmpl.replace('{location}', displayLocation(locationLabel));
    }

    if (lineChart) { lineChart.destroy(); lineChart = null; }

    lineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: trend.labels,
        datasets: [
          {
            label:           TEXT.lineTemp || 'Temperature (°C)',
            data:            trend.temperature,
            borderColor:     '#4299E1',
            backgroundColor: 'rgba(66,153,225,0.07)',
            tension:         0.3,
            yAxisID:         'y',
            pointRadius:     2,
            borderWidth:     2,
          },
          {
            label:           TEXT.linePm25 || 'PM2.5 (ug/m3)',
            data:            trend.pm25,
            borderColor:     '#FC8181',
            backgroundColor: 'rgba(252,129,129,0.07)',
            tension:         0.3,
            yAxisID:         'y1',
            pointRadius:     2,
            borderWidth:     2,
          },
        ],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        interaction:         { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { font: { size: 9 }, boxWidth: 9, padding: 8, color: '#4A5568' } },
        },
        scales: {
          y: {
            position: 'left',
            ticks:    { font: { size: 9 }, color: '#718096' },
            title:    { display: true, text: '°C', font: { size: 9 }, color: '#4299E1' },
            grid:     { color: '#EDF2F7' },
          },
          y1: {
            position: 'right',
            grid:     { drawOnChartArea: false },
            ticks:    { font: { size: 9 }, color: '#718096' },
            title:    { display: true, text: '㎍/㎥', font: { size: 9 }, color: '#FC8181' },
          },
          x: {
            ticks: { font: { size: 8 }, maxRotation: 0, color: '#718096' },
            grid:  { color: '#EDF2F7' },
          },
        },
      },
    });
  }

  /* ── Raw Data 테이블 ──────────────────────────────────────── */
  function renderTable(rawData) {
    var tbody = document.getElementById('db-table-body');
    if (!tbody) return;

    if (!rawData || rawData.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#A0AEC0;padding:1rem;">' + (TEXT.tableEmpty || 'No data') + '</td></tr>';
      return;
    }

    tbody.innerHTML = rawData.map(function (r) {
      var badgeClass = getStatusBadgeClass(r.outdoor_status);
      var timeStr    = formatRecordTime(r.record_time);
      return [
        '<tr>',
          '<td>', displayLocation(r.location), '</td>',
          '<td>', timeStr, '</td>',
          '<td>', r.temperature !== null ? r.temperature + '°' : '—', '</td>',
          '<td>', r.pm10 !== null ? r.pm10 : '—', '</td>',
          '<td>', r.pm25 !== null ? r.pm25 : '—', '</td>',
          '<td>', r.wind_speed !== null ? r.wind_speed : '—', '</td>',
          '<td><span class="db-badge ', badgeClass, '">', statusLabel(r.outdoor_status), '</span></td>',
        '</tr>',
      ].join('');
    }).join('');
  }

  function getStatusBadgeClass(status) {
    if (!status) return 'db-badge--grey';
    var cat = statusCategory(status);
    if (cat === 'good') return 'db-badge--good';
    if (cat === 'poor') return 'db-badge--bad';
    if (cat === 'rain') return 'db-badge--rain';
    return 'db-badge--normal';
  }

  function formatRecordTime(isoStr) {
    if (!isoStr || isoStr === '—') return '—';
    try {
      var d = new Date(isoStr);
      return d.toLocaleString(LANG === 'en' ? 'en-US' : 'ko-KR', {
        timeZone:  'Asia/Seoul',
        month:     '2-digit',
        day:       '2-digit',
        hour:      '2-digit',
        minute:    '2-digit',
        hour12:    false,
      });
    } catch (e) {
      return isoStr.slice(0, 16);
    }
  }

  /* ── 마지막 갱신 시각 ─────────────────────────────────────── */
  function updateLastRefreshed(isoStr) {
    if (!lastRefreshed) return;
    if (!isoStr || isoStr === '—') { lastRefreshed.textContent = ''; return; }
    try {
      var d = new Date(isoStr);
      var hhmm = d.toLocaleString(LANG === 'en' ? 'en-US' : 'ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit', minute: '2-digit', hour12: false,
      });
      var tmpl = TEXT.lastRefreshed || 'Data timestamp: {time} (KST) - refreshed every 15 minutes';
      lastRefreshed.textContent = tmpl.replace('{time}', hhmm);
    } catch (e) {
      lastRefreshed.textContent = isoStr.slice(0, 16);
    }
  }

  /* ── 카카오맵 버블 초기화 & 업데이트 ─────────────────────── */
  function initMap(mapData) {
    var container = document.getElementById('db-map');
    if (!container) return;
    if (typeof kakao === 'undefined' || !kakao.maps) return;

    kakaoMap = new kakao.maps.Map(container, {
      center: new kakao.maps.LatLng(37.57, 127.10),
      level:  10,
    });
    updateBubbles(mapData);
  }

  function updateBubbles(mapData) {
    if (!kakaoMap) return;

    // 기존 오버레이 제거
    bubbleOverlays.forEach(function (ov) { ov.setMap(null); });
    bubbleOverlays = [];

    mapData.forEach(function (city) {
      var color  = STATUS_COLORS[statusCategory(city.outdoor_status)] || DEFAULT_BUBBLE_COLOR;
      var pm10   = city.pm10 || 0;
      var size   = Math.max(28, Math.min(78, pm10 * 0.65 + 12));
      var font   = Math.max(8, Math.round(size / 4.2));

      var tooltipLines = [
        '<strong>' + displayLocation(city.location) + '</strong>',
        (TEXT.tempLabel || 'Temp') + ': ' + (city.temperature !== null ? city.temperature + '°C' : '—'),
        'PM10: ' + pm10 + ' ㎍/㎥',
        'PM2.5: ' + city.pm25 + ' ㎍/㎥',
        statusLabel(city.outdoor_status),
      ].join('<br>');

      var content = [
        '<div class="db-bubble-wrap" style="width:', size + 2, 'px;height:', size + 2, 'px;">',
          '<div class="db-bubble" style="',
            'width:', size, 'px;',
            'height:', size, 'px;',
            'background:', color, ';',
            'font-size:', font, 'px;',
          '">',
            displayLocation(city.location),
          '</div>',
          '<div class="db-bubble-tooltip">', tooltipLines, '</div>',
        '</div>',
      ].join('');

      var overlay = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(city.lat, city.lng),
        content:  content,
        yAnchor:  0.5,
        xAnchor:  0.5,
      });
      overlay.setMap(kakaoMap);
      bubbleOverlays.push(overlay);
    });
  }

  /* ── Smart Narrative ──────────────────────────────────────── */
  function fetchNarrative(data) {
    if (!narrativeEl) return;
    narrativeEl.innerHTML = '<span class="db-narrative-spinner">⟳</span> ' + (TEXT.narrativeLoading || 'Analyzing with AI...');

    fetch('/api/dashboard/narrative', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kpi:               data.kpi,
        bar_top5:          data.bar_top5,
        donut:             data.donut,
        selected_location: data.selected_location,
        language:          LANG,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        narrativeEl.textContent = res.narrative || (TEXT.narrativeDefault || 'Analyzing incoming data.');
      })
      .catch(function () {
        narrativeEl.textContent = TEXT.narrativeError || 'Failed to load AI summary temporarily.';
      });
  }

  /* ── 엔트리포인트 ─────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', function () {
    // 이벤트 바인딩
    if (locationSel) locationSel.addEventListener('change', fetchData);
    if (refreshBtn)  refreshBtn.addEventListener('click', function () { if (!isFetching) fetchData(); });

    // 카카오맵 병렬 초기화 (지도만 담당 — 데이터 fetch와 독립)
    if (typeof kakao !== 'undefined' && kakao.maps) {
      kakao.maps.load(function () {
        var container = document.getElementById('db-map');
        if (container) {
          kakaoMap = new kakao.maps.Map(container, {
            center: new kakao.maps.LatLng(37.57, 127.10),
            level:  10,
          });
          // 데이터가 이미 로드됐다면 즉시 버블 표시
          if (currentData) updateBubbles(currentData.map_data);
        }
      });
    }

    // 데이터 fetch (지도와 무관하게 즉시 실행)
    fetchData();
  });

})();
