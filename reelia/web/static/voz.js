// Voz en off: mostrar opciones, armar guion sugerido y contar caracteres.
(function () {
  const activa = document.getElementById('voz-activa');
  const opciones = document.getElementById('voz-opciones');
  const guion = document.getElementById('guion');
  const contador = document.getElementById('contador-guion');
  const boton = document.getElementById('sugerir-guion');
  const url = document.currentScript.dataset.url;
  if (!activa) return;
  const contar = () => {
    const n = guion.value.trim().length;
    const seg = Math.round(n / 15);
    contador.textContent = n ? `${n} caracteres · ~${seg} s de voz` : 'Vacío: se arma solo con la ficha';
  };
  activa.onchange = () => { opciones.hidden = !activa.checked; };
  guion.oninput = contar;
  boton.onclick = async () => {
    const form = guion.closest('form');
    const datos = new FormData(form);
    ['fotos', 'clips', 'logo', 'fotos_nuevas'].forEach(k => datos.delete(k));
    boton.disabled = true;
    try {
      const r = await fetch(url, { method: 'POST', body: datos });
      if (r.ok) { guion.value = (await r.json()).guion; contar(); }
    } finally { boton.disabled = false; }
  };
  contar();
})();
