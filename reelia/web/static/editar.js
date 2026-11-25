// Edición de un video ya hecho: orden, textos, quitar/agregar fotos o clips.
(function () {
  const form = document.getElementById('form-editar');
  const lista = document.getElementById('lista');
  const esClips = lista.classList.contains('clips');

  function oculto(nombre, valor) {
    const h = document.createElement('input');
    h.type = 'hidden'; h.name = nombre; h.value = valor; h.className = 'oculto-envio';
    form.appendChild(h);
  }

  // ---------------------------------------------------------------- videos
  if (esClips) {
    const numerar = () => lista.querySelectorAll('li').forEach((li, i) => {
      li.querySelector('.titulo-item').textContent = 'Video ' + (i + 1);
    });
    lista.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      const li = b.closest('li');
      if (b.dataset.a === 'x') {
        if (lista.children.length === 1) { alert('Tiene que quedar al menos un video.'); return; }
        li.remove();
      } else if (b.dataset.a === 'arriba' && li.previousElementSibling) lista.insertBefore(li, li.previousElementSibling);
      else if (b.dataset.a === 'abajo' && li.nextElementSibling) lista.insertBefore(li.nextElementSibling, li);
      numerar();
    });
    form.onsubmit = () => {
      form.querySelectorAll('.oculto-envio').forEach(n => n.remove());
      lista.querySelectorAll('li').forEach(li => oculto('orden', li.dataset.nombre));
      const b = document.getElementById('enviar'); b.disabled = true; b.textContent = 'Guardando…';
    };
    return;
  }

  // ----------------------------------------------------------------- fotos
  const MAX = 15;
  const input = document.getElementById('fotos-nuevas');
  const zona = document.getElementById('zona');
  const sinUsar = document.getElementById('sin-usar');
  let items = [...lista.querySelectorAll('li')].map(li => ({
    nombre: li.dataset.nombre, url: li.dataset.url, etiqueta: li.dataset.etiqueta || ''
  }));
  let libres = sinUsar ? [...sinUsar.querySelectorAll('li')].map(li => ({ nombre: li.dataset.nombre, url: li.dataset.url, etiqueta: '' })) : [];

  function pintar() {
    lista.innerHTML = '';
    items.forEach((it, i) => {
      const li = document.createElement('li');
      li.draggable = true;
      li.innerHTML = '<img alt=""><span class="num">' + (i === 0 ? 'Portada' : i + 1) + '</span>' +
        '<div class="acciones"><button type="button" data-a="izq" aria-label="Mover antes">‹</button>' +
        '<button type="button" data-a="der" aria-label="Mover después">›</button>' +
        '<button type="button" data-a="x" aria-label="Quitar">✕</button></div>' +
        (i === 0 ? '<small>Muestra precio y ubicación</small>'
                 : '<input maxlength="40" placeholder="Sin texto">');
      li.querySelector('img').src = it.url;
      const txt = li.querySelector('input');
      if (txt) {
        txt.value = it.etiqueta;
        txt.oninput = e => { it.etiqueta = e.target.value; };
        if (it.etiqueta) {
          const borrar = document.createElement('button');
          borrar.type = 'button'; borrar.className = 'borrar-texto'; borrar.textContent = 'Borrar texto';
          borrar.onclick = () => { it.etiqueta = ''; pintar(); };
          li.appendChild(borrar);
        }
      }
      li.querySelectorAll('.acciones button').forEach(b => b.onclick = () => mover(i, b.dataset.a));
      li.ondragstart = e => { e.dataTransfer.setData('text/plain', i); li.classList.add('arrastrando'); };
      li.ondragend = () => li.classList.remove('arrastrando');
      li.ondragover = e => e.preventDefault();
      li.ondrop = e => {
        e.preventDefault();
        const de = +e.dataTransfer.getData('text/plain');
        if (isNaN(de) || de === i) return;
        const [x] = items.splice(de, 1); items.splice(i, 0, x); pintar();
      };
      lista.appendChild(li);
    });
    if (sinUsar) {
      sinUsar.innerHTML = '';
      libres.forEach((it, k) => {
        const li = document.createElement('li');
        li.innerHTML = '<img alt=""><button type="button" class="btn chico agregar">+ Agregar</button>';
        li.querySelector('img').src = it.url;
        li.querySelector('button').onclick = () => {
          if (items.length >= MAX) { alert('Máximo ' + MAX + ' fotos.'); return; }
          items.push(libres.splice(k, 1)[0]); pintar();
        };
        sinUsar.appendChild(li);
      });
      sinUsar.previousElementSibling.hidden = sinUsar.hidden = libres.length === 0;
    }
  }

  function mover(i, a) {
    if (a === 'x') {
      if (items.length === 1) { alert('Tiene que quedar al menos una foto.'); return; }
      const [x] = items.splice(i, 1);
      if (x.file) URL.revokeObjectURL(x.url); else if (sinUsar) { x.etiqueta = ''; libres.push(x); }
    } else {
      const j = a === 'izq' ? i - 1 : i + 1;
      if (j < 0 || j >= items.length) return;
      [items[i], items[j]] = [items[j], items[i]];
    }
    pintar();
  }

  function agregar(files) {
    for (const f of files) {
      if (!/^image\/(jpeg|png|webp)$/.test(f.type)) continue;
      if (items.length >= MAX) { alert('Máximo ' + MAX + ' fotos.'); break; }
      items.push({ file: f, url: URL.createObjectURL(f), etiqueta: '' });
    }
    pintar();
  }
  input.onchange = () => { agregar(input.files); input.value = ''; };
  ['dragover', 'dragenter'].forEach(ev => zona.addEventListener(ev, e => { e.preventDefault(); zona.classList.add('activa'); }));
  ['dragleave', 'drop'].forEach(ev => zona.addEventListener(ev, () => zona.classList.remove('activa')));
  zona.addEventListener('drop', e => { e.preventDefault(); agregar(e.dataTransfer.files); });

  form.onsubmit = () => {
    form.querySelectorAll('.oculto-envio').forEach(n => n.remove());
    const dt = new DataTransfer();
    items.forEach(it => {
      if (it.file) { oculto('orden', 'nueva:' + dt.items.length); dt.items.add(it.file); }
      else oculto('orden', it.nombre);
      oculto('etiqueta', it.etiqueta || '');
    });
    input.files = dt.files;
    const b = document.getElementById('enviar'); b.disabled = true; b.textContent = 'Guardando…';
  };
  pintar();
})();
