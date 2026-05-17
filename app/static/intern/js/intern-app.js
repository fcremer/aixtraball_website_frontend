/* Aixtraball Intern – PWA App Script */

// Theme toggle (sidebar) — uses 'intern-theme' key, default dark
(function () {
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('intern-theme', theme);
    var icon = document.getElementById('sidebar-theme-icon');
    var label = document.getElementById('sidebar-theme-label');
    if (icon) icon.className = theme === 'dark' ? 'bi bi-moon-fill' : 'bi bi-sun-fill';
    if (label) label.textContent = theme === 'dark' ? 'Dark Mode' : 'Light Mode';
  }

  var btn = document.getElementById('sidebar-theme-toggle');
  if (btn) {
    btn.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });
  }

  // Sync icon with current theme set by inline script
  var current = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(current);
})();

// Service Worker Registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('/intern/sw.js', { scope: '/intern/' })
      .then(function (reg) {
        // Registration successful
      })
      .catch(function (err) {
        console.warn('SW registration failed:', err);
      });
  });
}

// Offline/Online detection
(function () {
  var banner = document.getElementById('offline-banner');
  if (!banner) return;

  function updateOnline() {
    banner.hidden = navigator.onLine;
  }

  updateOnline();
  window.addEventListener('online', updateOnline);
  window.addEventListener('offline', updateOnline);
})();

// iOS Add-to-Home hint
(function () {
  var hint = document.getElementById('ios-hint');
  if (!hint) return;
  if (localStorage.getItem('ios-hint-dismissed')) return;

  var isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  var isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone === true;

  if (isIOS && !isStandalone) {
    hint.hidden = false;
  }
})();


// Auto-dismiss flash messages after 4 seconds
(function () {
  var flashes = document.querySelectorAll('.intern-flash');
  flashes.forEach(function (el) {
    setTimeout(function () {
      el.style.transition = 'opacity 0.4s';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 400);
    }, 4000);
  });
})();
