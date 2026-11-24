// Subida de fotos con vista previa, orden por arrastre y texto por foto.
(function () {
  const input = document.getElementById('fotos');
  const lista = document.getElementById('lista');
  const zona = document.getElementById('zona');
  const form = document.getElementById('form-nuevo');
  const MAX = 15;
  let items = []; // {file, url, etiqueta}

  function agregar(files) {
    for (const f of files) {
      if (!/^image\/(jpeg|png|webp)$/.test(f.type)) continue;
      if (items.length >= MAX) { alert('Máximo ' + MAX + ' fotos.'); break; }
      items.push({ file: f, url: URL.createObjectURL(f), etiqueta: '' });
    }
    pintar();
  }

  function pintar() {
    lista.innerHTML = '';
    items.forEach((it, i) => {
      const li = document.createElement('li');
      li.draggable = true;
      li.dataset.i = i;
      li.innerHTML =
        '<img alt="">' +
        '<span class="num">' + (i === 0 ? 'Portada' : i + 1) + '</span>' +
        '<div class="acciones">' +
        '<button type="button" data-a="izq" aria-label="Mover antes">‹</button>' +
        '<button type="button" data-a="der" aria-label="Mover después">›</button>' +
        '<button type="button" data-a="x" aria-label="Quitar">✕</button></div>' +
        (i === 0 ? '<small>Muestra precio y ubicación</small>'
                 : '<input maxlength="40" placeholder="Texto (opcional)">');
      li.querySelector('img').src = it.url;
      const txt = li.querySelector('input');
      if (txt) { txt.value = it.etiqueta; txt.oninput = e => { it.etiqueta = e.target.value; }; }
      li.querySelectorAll('button').forEach(b => b.onclick = () => mover(i, b.dataset.a));
      li.ondragstart = e => { e.dataTransfer.setData('text/plain', i); li.classList.add('arrastrando'); };
      li.ondragend = () => li.classList.remove('arrastrando');
      li.ondragover = e => e.preventDefault();
      li.ondrop = e => {
        e.preventDefault();
        const de = +e.dataTransfer.getData('text/plain');
        if (isNaN(de) || de === i) return;
        const [x] = items.splice(de, 1);
        items.splice(i, 0, x);
        pintar();
      };
      lista.appendChild(li);
    });
  }

  function mover(i, a) {
    if (a === 'x') { URL.revokeObjectURL(items[i].url); items.splice(i, 1); }
    else {
      const j = a === 'izq' ? i - 1 : i + 1;
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
    if (!items.length) { e.preventDefault(); alert('Subí al menos una foto.'); return; }
    const dt = new DataTransfer();
    items.forEach(it => dt.items.add(it.file));
    input.files = dt.files;
    form.querySelectorAll('input[name=etiqueta]').forEach(n => n.remove());
    items.forEach(it => {
      const h = document.createElement('input');
      h.type = 'hidden'; h.name = 'etiqueta'; h.value = it.etiqueta;
      form.appendChild(h);
    });
    const b = document.getElementById('enviar');
    b.disabled = true; b.textContent = 'Subiendo fotos…';
  };
})();
