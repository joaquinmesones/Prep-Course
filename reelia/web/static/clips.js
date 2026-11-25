// Subida de videos: lista ordenable con miniatura, duración y quitar.
(function () {
  const input = document.getElementById('clips');
  const lista = document.getElementById('lista');
  const zona = document.getElementById('zona');
  const form = document.getElementById('form-nuevo');
  const MAX = 10, MAX_BYTES = 1024 * 1024 * 1024;
  let items = [];

  const mb = b => (b / 1024 / 1024).toFixed(0) + ' MB';
  const mmss = s => isFinite(s) ? Math.floor(s / 60) + ':' + String(Math.round(s % 60)).padStart(2, '0') : '';

  function agregar(files) {
    for (const f of files) {
      if (!f.type.startsWith('video/') && !/\.(mp4|mov|m4v|webm|avi|mkv|3gp)$/i.test(f.name)) continue;
      if (items.length >= MAX) { alert('Máximo ' + MAX + ' videos.'); break; }
      items.push({ file: f, url: URL.createObjectURL(f), dur: null });
    }
    pintar();
  }

  function pintar() {
    lista.innerHTML = '';
    let total = 0;
    items.forEach((it, i) => {
      total += it.file.size;
      const li = document.createElement('li');
      li.innerHTML = '<video muted preload="metadata" playsinline></video>' +
        '<div class="datos"><strong>Video ' + (i + 1) + '</strong><span></span></div>' +
        '<div class="acciones"><button type="button" data-a="arriba" aria-label="Subir">↑</button>' +
        '<button type="button" data-a="abajo" aria-label="Bajar">↓</button>' +
        '<button type="button" data-a="x" aria-label="Quitar">✕</button></div>';
      const v = li.querySelector('video');
      const info = li.querySelector('.datos span');
      v.src = it.url + '#t=0.5';
      const mostrar = () => { info.textContent = [mmss(it.dur), mb(it.file.size), it.file.name].filter(Boolean).join(' · '); };
      v.onloadedmetadata = () => { it.dur = v.duration; mostrar(); };
      mostrar();
      li.querySelectorAll('button').forEach(b => b.onclick = () => mover(i, b.dataset.a));
      lista.appendChild(li);
    });
    if (total > MAX_BYTES) alert('Los videos superan 1 GB en total. Quitá alguno o subilos más cortos.');
  }

  function mover(i, a) {
    if (a === 'x') { URL.revokeObjectURL(items[i].url); items.splice(i, 1); }
    else {
      const j = a === 'arriba' ? i - 1 : i + 1;
      if (j < 0 || j >= items.length) return;
      [items[i], items[j]] = [items[j], items[i]];
    }
    pintar();
  }

  input.onchange = () => { agregar(input.files); input.value = ''; };
  ['dragover', 'dragenter'].forEach(ev => zona.addEventListener(ev, e => { e.preventDefault(); zona.classList.add('activa'); }));
  ['dragleave', 'drop'].forEach(ev => zona.addEventListener(ev, () => zona.classList.remove('activa')));
  zona.addEventListener('drop', e => { e.preventDefault(); agregar(e.dataTransfer.files); });

  form.onsubmit = e => {
    if (!items.length) { e.preventDefault(); alert('Subí al menos un video.'); return; }
    if (items.reduce((s, it) => s + it.file.size, 0) > MAX_BYTES) { e.preventDefault(); alert('Máximo 1 GB en total.'); return; }
    const dt = new DataTransfer();
    items.forEach(it => dt.items.add(it.file));
    input.files = dt.files;
    const b = document.getElementById('enviar');
    b.disabled = true; b.textContent = 'Subiendo videos… no cierres esta página';
  };
})();
