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
    btn.addEventListener('click', function () {
      var next = root.dataset.theme === 'light' ? 'dark' : 'light';
      root.dataset.theme = next;
      try { localStorage.setItem('theme', next); } catch (e) {}
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

  document.addEventListener('DOMContentLoaded', function () {
    startClock();
    loadWeather();
    setupThemeToggle();
    setupTabs();
  });
})();
