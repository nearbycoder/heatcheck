/* HEAT CHECK landing page: progressive enhancement only. Everything works without this file. */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var saveData = navigator.connection && navigator.connection.saveData;

  /* ---------- scroll reveal ---------- */
  var revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduceMotion.matches) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    revealEls.forEach(function (el, i) {
      // small stagger for siblings in the same grid
      var idx = Array.prototype.indexOf.call(el.parentNode.children, el);
      el.style.transitionDelay = Math.min(idx, 5) * 60 + 'ms';
      io.observe(el);
    });
  } else {
    revealEls.forEach(function (el) { el.classList.add('in'); });
  }

  /* ---------- hero background video ---------- */
  var hero = document.querySelector('.hero-video');
  if (hero && !reduceMotion.matches && !saveData) {
    var start = parseFloat(hero.getAttribute('data-start') || '0');
    hero.src = hero.getAttribute('data-src');
    hero.addEventListener('loadedmetadata', function () {
      try { hero.currentTime = start; } catch (e) { /* ignore */ }
    }, { once: true });
    hero.addEventListener('playing', function () { hero.classList.add('is-playing'); });
    // loop back to the gameplay, skipping the intro card
    hero.addEventListener('ended', function () { hero.currentTime = start; hero.play(); });
    var p = hero.play();
    if (p && p.catch) p.catch(function () { /* autoplay blocked: the poster stays */ });
    // pause when the hero scrolls away
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { var q = hero.play(); if (q && q.catch) q.catch(function () {}); }
          else hero.pause();
        });
      }).observe(hero.parentNode);
    }
  }

  /* ---------- gallery videos: play while visible ---------- */
  var inline = document.querySelectorAll('.inline-video');
  if (reduceMotion.matches || !('IntersectionObserver' in window)) {
    inline.forEach(function (v) { v.controls = true; });
  } else {
    var vio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        var v = e.target;
        if (e.isIntersecting) { var q = v.play(); if (q && q.catch) q.catch(function () { v.controls = true; }); }
        else v.pause();
      });
    }, { threshold: 0.35 });
    inline.forEach(function (v) { vio.observe(v); });
  }

  /* ---------- optional browser-version screenshots ----------
     .gallery[data-web-shots="N"] reveals the first N [data-optional] figures (media/web-1.jpg ...).
     Nothing is requested while N is 0, and a figure whose image fails to load stays hidden. */
  var gal = document.querySelector('.gallery[data-web-shots]');
  var nWeb = gal ? parseInt(gal.getAttribute('data-web-shots'), 10) || 0 : 0;
  Array.prototype.slice.call(document.querySelectorAll('[data-optional]'), 0, nWeb).forEach(function (fig) {
    var img = fig.querySelector('img[data-src]');
    if (!img) return;
    img.onload = function () { fig.hidden = false; fig.classList.add('in'); };
    img.src = img.getAttribute('data-src');
  });

  /* ---------- lightbox ---------- */
  var dlg = document.getElementById('lightbox');
  if (dlg && typeof dlg.showModal === 'function') {
    var stage = dlg.querySelector('.lightbox__stage');
    var cap = dlg.querySelector('.lightbox__caption');
    var lastFocus = null;

    function open(node, caption) {
      lastFocus = document.activeElement;
      stage.innerHTML = '';
      stage.appendChild(node);
      cap.textContent = caption || '';
      dlg.showModal();
    }
    function captionFor(el) {
      var fig = el.closest('figure');
      var fc = fig && fig.querySelector('figcaption');
      return fc ? fc.textContent.trim() : '';
    }

    document.querySelectorAll('a[data-lightbox]').forEach(function (a) {
      a.addEventListener('click', function (ev) {
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;
        ev.preventDefault();
        var src = a.querySelector('img');
        var img = new Image();
        img.src = a.getAttribute('href');
        img.alt = src ? src.alt : '';
        open(img, captionFor(a));
      });
    });

    document.querySelectorAll('[data-lightbox-video]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var v = document.createElement('video');
        v.src = btn.getAttribute('data-lightbox-video');
        v.poster = btn.getAttribute('data-poster') || '';
        v.controls = true; v.muted = true; v.loop = true; v.playsInline = true;
        v.setAttribute('playsinline', '');
        if (!reduceMotion.matches) v.autoplay = true;
        open(v, captionFor(btn));
      });
    });

    dlg.addEventListener('click', function (ev) {
      // click on the backdrop closes
      if (ev.target === dlg) dlg.close();
    });
    dlg.addEventListener('close', function () {
      stage.innerHTML = '';
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    });
  }

  /* ---------- LED stat counters ---------- */
  var stats = document.querySelectorAll('.stat dd[data-count]');
  if (stats.length && 'IntersectionObserver' in window && !reduceMotion.matches) {
    var fmt = new Intl.NumberFormat('en-US');
    var sio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        sio.unobserve(e.target);
        var el = e.target, target = +el.getAttribute('data-count'), t0 = null, dur = 1200;
        if (!target) return;
        function step(t) {
          if (t0 === null) t0 = t;
          var k = Math.min(1, (t - t0) / dur);
          k = 1 - Math.pow(1 - k, 3);
          el.textContent = fmt.format(Math.round(target * k));
          if (k < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      });
    }, { threshold: 0.6 });
    stats.forEach(function (el) { sio.observe(el); });
  }
})();
