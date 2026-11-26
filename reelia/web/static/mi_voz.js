// Grabación de la voz en el navegador (o archivo subido) para clonarla.
(function () {
  const btn = document.getElementById('grabar');
  const tiempo = document.getElementById('tiempo');
  const escucha = document.getElementById('escucha');
  const archivo = document.getElementById('archivo');
  const enviar = document.getElementById('enviar-voz');
  const form = document.getElementById('form-voz');
  let grabador = null, partes = [], inicio = 0, reloj = null, grabado = null;

  const listo = () => { enviar.disabled = !(grabado || archivo.files.length); };
  archivo.onchange = listo;

  btn.onclick = async () => {
    if (grabador && grabador.state === 'recording') { grabador.stop(); return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { noiseSuppression: true, echoCancellation: true } }); }
    catch (e) { alert('No se pudo usar el micrófono. Revisá los permisos del navegador o subí un audio.'); return; }
    partes = []; grabado = null; listo();
    grabador = new MediaRecorder(stream);
    grabador.ondataavailable = e => { if (e.data.size) partes.push(e.data); };
    grabador.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      clearInterval(reloj);
      grabado = new Blob(partes, { type: grabador.mimeType || 'audio/webm' });
      escucha.src = URL.createObjectURL(grabado); escucha.hidden = false;
      const seg = Math.round((Date.now() - inicio) / 1000);
      tiempo.textContent = seg < 30 ? `Grabaste ${seg} s: necesitás al menos 30 s.` : `Grabaste ${seg} s. Escuchala y, si está bien, tocá “Clonar mi voz”.`;
      btn.textContent = '● Grabar de nuevo';
      if (seg < 30) grabado = null;
      listo();
    };
    grabador.start(1000); inicio = Date.now();
    btn.textContent = '■ Terminar';
    reloj = setInterval(() => {
      const s = Math.round((Date.now() - inicio) / 1000);
      tiempo.textContent = `Grabando… ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    }, 500);
  };

  form.onsubmit = e => {
    if (grabado) {
      const dt = new DataTransfer();
      const ext = (grabado.type.includes('ogg') ? 'ogg' : grabado.type.includes('mp4') ? 'm4a' : 'webm');
      dt.items.add(new File([grabado], 'grabacion.' + ext, { type: grabado.type }));
      [...archivo.files].forEach(f => dt.items.add(f));
      archivo.files = dt.files;
    }
    enviar.disabled = true; enviar.textContent = 'Clonando tu voz…';
  };
})();
