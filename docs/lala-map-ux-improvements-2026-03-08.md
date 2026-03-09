# LALA Map UX 개선 — 2026-03-08

> 브랜치: `feat/local-dev-dashboard`
> 커밋 범위: `src/frontend/web/` 하위 파일 5개

---

## 1. 변경 목록

### 1-1. 시트 열릴 때 카드 패널 + 자막 패널 동시 숨기기

**파일**: `map_logic.js`, `layout.css`

**문제**: 마커/카드 클릭 → 상세 시트(bottom-sheet)가 열려도 상단 카드 패널과 하단 도슨트 자막 패널이 그대로 겹쳐 표시됨.

**해결**:
- `openSheet()` — `#card-panel`, `#status-panel` 모두 `.hidden` 클래스 추가
- `closeSheets()` — `.hidden` 클래스 제거 (복원)
- CSS `.map-subtitle-panel.hidden` 신규 추가 (`opacity:0`, `visibility:hidden`, `transition 0.22s`)
- 기존 `.map-card-panel.hidden` 동일 패턴 활용

```js
// openSheet()
const cardPanel = document.getElementById('card-panel');
if (cardPanel) cardPanel.classList.add('hidden');
const subtitlePanel = document.getElementById('status-panel');
if (subtitlePanel) subtitlePanel.classList.add('hidden');
```

---

### 1-2. 카드 썸네일 이미지 깨짐 처리

**파일**: `map_logic.js`

**문제**: `place.image_url`이 있어도 실제 이미지 로드 실패 시 깨진 아이콘 + alt 텍스트가 회색 박스 안에 그대로 노출됨.

**해결**: `<img>` 태그에 `onerror` 핸들러 추가 — 로드 실패 시 요소 자체를 숨김.

```js
`<img class="place-card__thumb" src="${escapeHtml(place.image_url)}"
     alt="${escapeHtml(placeName(place))}"
     onerror="this.style.display='none'" />`
```

---

### 1-3. 자동 도슨트 ON/OFF 시각적 강화

**파일**: `map_logic.js`, `layout.css`

**문제**: ON/OFF 상태가 텍스트("ON"/"OFF")만으로 구분되어 시각적 피드백이 약함.

**해결**:
- **ON**: 배경색 강조(`--obang-east`) + 파란 글로우 링(`box-shadow`) + `scale(1.06)` + 이모지 `✨`
- **OFF**: 어두운 배경 유지 + 이모지 `⏸`
- `transition: background 0.25s, box-shadow 0.25s, transform 0.18s` — 부드러운 전환

```css
.fab-circle.auto.active {
  background: var(--obang-east);
  box-shadow: 0 0 0 4px rgba(var(--obang-east-rgb, 59,130,246), 0.28),
              0 6px 20px rgba(16, 24, 40, 0.38);
  transform: scale(1.06);
}
```

```js
if (iconSpan) iconSpan.textContent = APP.isAutoDocentEnabled ? '✨' : '⏸';
```

---

### 1-4. 카드 가로 스와이프 CSS 버그 수정

**파일**: `layout.css`

**문제**: `.map-card-panel {}` 블록 중간에 `}`가 잘못 삽입되어 `display:flex`, `overflow-x:auto` 등 속성이 선택자 밖에 떠돌아 카드가 세로 나열됨.

**해결**: 모든 속성을 `.map-card-panel {}` 블록 안으로 통합.

---

### 1-5. 도슨트 자막 텍스트 5줄 스크롤 제한

**파일**: `layout.css`

**문제**: 긴 도슨트 텍스트 수신 시 자막 패널이 위로 무한 확장되어 지도 UI를 덮음.

**해결**: `.map-subtitle-text`에 최대 높이 + 스크롤 적용, 버튼은 패널 하단 항상 고정.

```css
.map-subtitle-text {
  max-height: calc(1.6em * 5);   /* 5줄 제한 */
  overflow-y: auto;
  scrollbar-width: thin;
}
```

---

### 1-6. 카드 단일 클릭 → 상세 시트 즉시 열기

**파일**: `map_logic.js`

**문제**: 상세 시트를 열려면 더블클릭이 필요했음.

**해결**: `buildCard()` 클릭 핸들러를 단일 클릭으로 변경. 이미 선택된 카드 재클릭 시 시트 토글(닫힘).

```js
wrapper.addEventListener('click', () => {
  const alreadySelected = APP.selectedPlace && APP.selectedPlace.id === place.id;
  selectPlace(place, { from: 'card', openDetail: !alreadySelected });
});
```

---

### 1-7. Contentsquare 추적 스크립트 삽입

**파일**: `base.html`, `app.py`

- `base.html` `</head>` 직전에 Contentsquare 스크립트 `async` 삽입
- `app.py`에서 Hotjar 잔재 코드 제거

```html
<script src="https://t.contentsquare.net/uxa/34e2b3fc07281.js" async></script>
```

> **주의**: Contentsquare는 배포 환경(https)에서만 실제 데이터를 수집합니다. 로컬(http)에서는 수집되지 않습니다.

---

## 2. 수정된 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `src/frontend/web/app.py` | Hotjar 잔재 코드 제거 |
| `src/frontend/web/static/css/layout.css` | 카드 스와이프 버그 수정, 도슨트 텍스트 5줄 제한, 시트 hidden 전환, 도슨트 버튼 ON/OFF 글로우 |
| `src/frontend/web/static/js/map_logic.js` | 카드 단일 클릭, 시트 열릴 때 패널 숨기기, 이미지 onerror, 도슨트 토글 아이콘 |
| `src/frontend/web/templates/base.html` | Contentsquare 스크립트 삽입 |
| `src/frontend/web/templates/map/index.html` | 상세 시트 이미지 onerror 처리 |

---

## 3. 삭제된 파일

| 파일 | 이유 |
|------|------|
| `scripts/capture_screenshots.py` | 테스트용 스크린샷 자동화 스크립트 — 더 이상 불필요 |
