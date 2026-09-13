// 실시간 시계 + 방문자 위치 기반 날씨(Open-Meteo, 무료/키 불필요) + 라이트/다크 토글
(function () {
  'use strict';

  function pad(n) { return String(n).padStart(2, '0'); }

  function startClock() {
    var el = document.getElementById('live-clock');
    if (!el) return;
    function tick() {
      var d = new Date();
      el.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    }
    tick();
    setInterval(tick, 1000);
  }

  var WEATHER_CODE_LABEL = {
    0: '맑음', 1: '대체로 맑음', 2: '부분 흐림', 3: '흐림',
    45: '안개', 48: '안개', 51: '이슬비', 53: '이슬비', 55: '이슬비',
    61: '비', 63: '비', 65: '강한 비', 71: '눈', 73: '눈', 75: '강한 눈',
    80: '소나기', 81: '소나기', 82: '강한 소나기', 95: '뇌우',
  };

  function loadWeather() {
    var el = document.getElementById('weather-widget');
    if (!el || !navigator.geolocation) return;

    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      var url = 'https://api.open-meteo.com/v1/forecast?latitude=' + lat +
        '&longitude=' + lon + '&current=temperature_2m,weather_code';
      fetch(url).then(function (r) { return r.json(); }).then(function (data) {
        var cur = data && data.current;
        if (!cur) return;
        var label = WEATHER_CODE_LABEL[cur.weather_code] || '';
        el.textContent = '🌤️ ' + Math.round(cur.temperature_2m) + '°C ' + label;
        el.removeAttribute('data-loading');
      }).catch(function () { el.textContent = ''; });
    }, function () {
      // 권한 거부/실패 — 초기 안내 문구를 그대로 둠
      el.textContent = '';
    }, { timeout: 8000 });
  }

  function setupThemeToggle() {
    var root = document.documentElement;
    var btn = document.getElementById('theme-toggle');

    if (!localStorage.getItem('theme')) {
      var prefersLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
      if (prefersLight) root.dataset.theme = 'light';
    }

    if (!btn) return;

    // 스위치라서 현재 상태를 스크린리더에도 알려야 한다
    function syncState() {
      var isDark = root.dataset.theme
        ? root.dataset.theme === 'dark'
        : !(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);
      btn.setAttribute('aria-checked', isDark ? 'true' : 'false');
      btn.setAttribute('aria-label', isDark ? '라이트 모드로 전환' : '다크 모드로 전환');
    }
    syncState();

    btn.addEventListener('click', function () {
      var next = root.dataset.theme === 'light' ? 'dark' : 'light';
      root.dataset.theme = next;
      try { localStorage.setItem('theme', next); } catch (e) {}
      syncState();
    });
  }

  // 지표/주식추천 박스의 탭 전환 — 페이지에 [data-tabs] 박스가 여러 개 있어도
  // 각자 독립적으로 동작 (querySelectorAll을 컨테이너 범위로 한정)
  function setupTabs() {
    document.querySelectorAll('[data-tabs]').forEach(function (box) {
      var buttons = box.querySelectorAll('[data-tab-target]');
      var panels = box.querySelectorAll('[data-tab-panel]');
      buttons.forEach(function (btn) {
        btn.addEventListener('click', function () {
          var target = btn.getAttribute('data-tab-target');
          buttons.forEach(function (b) { b.classList.toggle('active', b === btn); });
          panels.forEach(function (p) {
            p.classList.toggle('active', p.getAttribute('data-tab-panel') === target);
          });
        });
      });
    });
  }

  // 시사용어 탭의 분야 필터 + 정렬. 용어는 날마다 쌓여서 '올해' 탭이 수백 건까지
  // 길어지므로, 서버에서 미리 나눠 내려주는 대신 브라우저에서 걸러 쓴다
  // (정적 호스팅이라 서버 쪽 질의가 없다).
  function setupTermControls() {
    document.querySelectorAll('[data-term-controls]').forEach(function (controls) {
      var panel = controls.closest('[data-tab-panel]') || document;
      var grid = panel.querySelector('[data-term-grid]');
      var empty = panel.querySelector('[data-term-empty]');
      if (!grid) { return; }

      var cards = Array.prototype.slice.call(grid.querySelectorAll('[data-term-card]'));
      var filters = controls.querySelectorAll('[data-filter]');
      var sortSelect = controls.querySelector('[data-term-sort]');
      var current = 'all';

      function apply() {
        var shown = 0;
        cards.forEach(function (card) {
          var hit = current === 'all' || card.getAttribute('data-category') === current;
          card.hidden = !hit;
          if (hit) { shown++; }
        });
        if (empty) { empty.hidden = shown !== 0; }
      }

      function sortBy(mode) {
        var sorted = cards.slice().sort(function (a, b) {
          var ad = a.getAttribute('data-date') || '';
          var bd = b.getAttribute('data-date') || '';
          if (mode === 'oldest') { return ad.localeCompare(bd); }
          if (mode === 'term') {
            return (a.getAttribute('data-term') || '').localeCompare(b.getAttribute('data-term') || '', 'ko');
          }
          if (mode === 'category') {
            var ac = a.getAttribute('data-category-name') || '';
            var bc = b.getAttribute('data-category-name') || '';
            // 같은 분야 안에서는 최신순을 유지해야 목록이 뒤죽박죽으로 보이지 않는다
            return ac.localeCompare(bc, 'ko') || bd.localeCompare(ad);
          }
          return bd.localeCompare(ad);   // newest
        });
        sorted.forEach(function (card) { grid.appendChild(card); });
      }

      filters.forEach(function (btn) {
        btn.addEventListener('click', function () {
          current = btn.getAttribute('data-filter');
          filters.forEach(function (b) { b.classList.toggle('active', b === btn); });
          apply();
        });
      });

      if (sortSelect) {
        sortSelect.addEventListener('change', function () { sortBy(sortSelect.value); });
      }
      apply();
    });
  }

  // 장중 지표 갱신 — 별도 워크플로가 15분마다 덮어쓰는 indicators.json을 읽어
  // 값/등락률만 바꿔치기한다. 네이버 지표 API는 CORS를 허용하지 않아 브라우저에서
  // 직접 부를 수 없기 때문에 같은 도메인의 JSON을 경유한다.
  // 스파크라인(7일 추이)은 일간 빌드 때 그린 걸 그대로 두고 숫자만 갱신한다 —
  // 하루 안에 7일 추이선이 눈에 띄게 바뀌지 않고, textContent만 쓰면 HTML 주입 여지도 없다.
  // indicators.py의 _UP_COLOR/_DOWN_COLOR/_FLAT_COLOR과 같은 값이어야 한다
  var DIR_COLORS = { up: '#ef4444', down: '#3b82f6', flat: '#8890a3' };

  function refreshIndicators() {
    var box = document.querySelector('[data-indicator-box]');
    if (!box) return;
    var url = box.getAttribute('data-indicators-url');
    if (!url) return;
    fetch(url, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        [].concat(data.main || [], data.fx || []).forEach(function (ind) {
          document.querySelectorAll('[data-ind-key="' + ind.key + '"]').forEach(function (node) {
            var value = node.querySelector('.ind-value');
            var pct = node.querySelector('.ind-pct');
            if (value) value.textContent = ind.value;
            if (pct) {
              pct.textContent = ind.pct;
              pct.className = 'ind-pct ' + ind.dir;
            }
            // 장중에 등락 방향이 뒤집히면 스파크라인 색도 같이 바꿔야
            // 숫자(빨강)와 선(파랑)이 어긋나 보이지 않는다
            var line = node.querySelector('.indicator-spark polyline');
            if (line && DIR_COLORS[ind.dir]) line.setAttribute('stroke', DIR_COLORS[ind.dir]);
          });
        });
        if (data.as_of) {
          document.querySelectorAll('[data-ind-asof]').forEach(function (n) {
            n.textContent = data.as_of;
          });
        }
      })
      .catch(function () { /* 갱신 실패 시 빌드 시점 값을 그대로 둔다 */ });
  }

  // 전 페이지 공통 메뉴 — 바깥 클릭/Esc로 닫힌다
  function setupMenu() {
    var root = document.querySelector('[data-menu]');
    if (!root) return;
    var button = root.querySelector('[data-menu-toggle]');
    var panel = root.querySelector('[data-menu-panel]');
    if (!button || !panel) return;

    function setOpen(open) {
      panel.hidden = !open;
      root.classList.toggle('open', open);
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
      button.setAttribute('aria-label', open ? '메뉴 닫기' : '메뉴 열기');
    }

    button.addEventListener('click', function (e) {
      e.stopPropagation();
      setOpen(panel.hidden);
    });
    document.addEventListener('click', function (e) {
      if (!panel.hidden && !root.contains(e.target)) setOpen(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.hidden) { setOpen(false); button.focus(); }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    startClock();
    loadWeather();
    setupThemeToggle();
    setupTabs();
    setupTermControls();
    setupMenu();
    refreshIndicators();
  });
})();
