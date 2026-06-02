(function () {
  function initIcons() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      try {
        window.lucide.createIcons()
      } catch (error) {
        console.warn('Icon initialization skipped', error)
      }
    }
  }

  function initVanta() {
    const target = document.getElementById('vanta-net')
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!target || reducedMotion || !window.VANTA || !window.THREE) {
      return
    }

    window.__cgaVanta = window.VANTA.NET({
      el: target,
      THREE: window.THREE,
      mouseControls: true,
      touchControls: true,
      gyroControls: false,
      minHeight: 200.0,
      minWidth: 200.0,
      scale: 1.0,
      scaleMobile: 1.0,
      color: 0x39f2bd,
      backgroundColor: 0x05070d,
      points: 13.0,
      maxDistance: 22.0,
      spacing: 17.0,
      showDots: true
    })
  }

  function boot() {
    if (window.__cgaSiteBooted) {
      return
    }
    window.__cgaSiteBooted = true
    initVanta()
    initIcons()
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    window.setTimeout(boot, 0)
  } else {
    window.addEventListener('DOMContentLoaded', boot, { once: true })
  }
})()