// Botones "▶ Escuchar": un solo reproductor para toda la página.
(function () {
  if (window.__escuchar) return; window.__escuchar = true;
  const audio = new Audio();
  let actual = null;
  const reset = b => { if (b) { b.textContent = '▶ Escuchar'; b.classList.remove('sonando'); } };
  audio.onended = () => { reset(actual); actual = null; };
  document.addEventListener('click', e => {
    const b = e.target.closest('.escuchar'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    if (actual === b) { audio.pause(); reset(b); actual = null; return; }
    reset(actual); actual = b;
    b.textContent = '… cargando'; b.classList.add('sonando');
    audio.src = b.dataset.src;
    audio.play().then(() => { if (actual === b) b.textContent = '■ Parar'; })
      .catch(() => { reset(b); actual = null; });
  });
})();
