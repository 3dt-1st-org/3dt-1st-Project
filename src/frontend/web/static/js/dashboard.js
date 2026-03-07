/* =============================================================
   dashboard.js — 수도권 실시간 대기질 대시보드
   Chart.js + 카카오맵 버블 오버레이
   ============================================================= */
(function () {
  'use strict';

  /* ── 상수 ────────────────────────────────────────────────── */
  const STATUS_COLORS = {
    '야외활동 쾌적':    '#48BB78',
    '보통':          '#ECC94B',
    '미세먼지 나쁨':   '#FC8181',
    '미세먼지 매우나쁨': '#E53E3E',
    '비/눈':         '#90CDF4',
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
      refreshBtn.textContent = '↻ 갱신 중...';
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
          refreshBtn.textContent = '↻ 새로고침';
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
      opt.textContent = loc;
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

    donutChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: donut.labels,
        datasets: [{
          data:            donut.data,
          backgroundColor: donut.colors,
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
                return ' ' + ctx.label + ': ' + ctx.raw + '개 도시 (' + pct + '%)';
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
      titleEl.textContent = '[' + locationLabel + '] 최근 12시간 기온 / PM2.5 추이';
    }

    if (lineChart) { lineChart.destroy(); lineChart = null; }

    lineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: trend.labels,
        datasets: [
          {
            label:           '기온(°C)',
            data:            trend.temperature,
            borderColor:     '#4299E1',
            backgroundColor: 'rgba(66,153,225,0.07)',
            tension:         0.3,
            yAxisID:         'y',
            pointRadius:     2,
            borderWidth:     2,
          },
          {
            label:           'PM2.5(㎍/㎥)',
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
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#A0AEC0;padding:1rem;">데이터 없음</td></tr>';
      return;
    }

    tbody.innerHTML = rawData.map(function (r) {
      var badgeClass = getStatusBadgeClass(r.outdoor_status);
      var timeStr    = formatRecordTime(r.record_time);
      return [
        '<tr>',
          '<td>', r.location, '</td>',
          '<td>', timeStr, '</td>',
          '<td>', r.temperature !== null ? r.temperature + '°' : '—', '</td>',
          '<td>', r.pm10 !== null ? r.pm10 : '—', '</td>',
          '<td>', r.pm25 !== null ? r.pm25 : '—', '</td>',
          '<td>', r.wind_speed !== null ? r.wind_speed : '—', '</td>',
          '<td><span class="db-badge ', badgeClass, '">', r.outdoor_status || '—', '</span></td>',
        '</tr>',
      ].join('');
    }).join('');
  }

  function getStatusBadgeClass(status) {
    if (!status) return 'db-badge--grey';
    if (status.indexOf('쾌적') !== -1) return 'db-badge--good';
    if (status.indexOf('나쁨') !== -1 || status.indexOf('매우') !== -1) return 'db-badge--bad';
    if (status.indexOf('비') !== -1 || status.indexOf('눈') !== -1) return 'db-badge--rain';
    return 'db-badge--normal';
  }

  function formatRecordTime(isoStr) {
    if (!isoStr || isoStr === '—') return '—';
    try {
      var d = new Date(isoStr);
      return d.toLocaleString('ko-KR', {
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
      var hhmm = d.toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
        hour: '2-digit', minute: '2-digit', hour12: false,
      });
      lastRefreshed.textContent = '데이터 기준: ' + hhmm + ' (KST) · 15분 전 갱신(개념적, ASA 30분 윈도우)';
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
      var color  = STATUS_COLORS[city.outdoor_status] || DEFAULT_BUBBLE_COLOR;
      var pm10   = city.pm10 || 0;
      var size   = Math.max(28, Math.min(78, pm10 * 0.65 + 12));
      var font   = Math.max(8, Math.round(size / 4.2));

      var tooltipLines = [
        '<strong>' + city.location + '</strong>',
        '기온: ' + (city.temperature !== null ? city.temperature + '°C' : '—'),
        'PM10: ' + pm10 + ' ㎍/㎥',
        'PM2.5: ' + city.pm25 + ' ㎍/㎥',
        city.outdoor_status || '',
      ].join('<br>');

      var content = [
        '<div class="db-bubble-wrap" style="width:', size + 2, 'px;height:', size + 2, 'px;">',
          '<div class="db-bubble" style="',
            'width:', size, 'px;',
            'height:', size, 'px;',
            'background:', color, ';',
            'font-size:', font, 'px;',
          '">',
            city.location,
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
    narrativeEl.innerHTML = '<span class="db-narrative-spinner">⟳</span> AI 분석 중...';

    fetch('/api/dashboard/narrative', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kpi:               data.kpi,
        bar_top5:          data.bar_top5,
        donut:             data.donut,
        selected_location: data.selected_location,
      }),
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        narrativeEl.textContent = res.narrative || '데이터를 분석 중입니다.';
      })
      .catch(function () {
        narrativeEl.textContent = 'AI 요약을 일시적으로 불러오지 못했습니다.';
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
