// Ingreso con huella / Face ID (WebAuthn - passkeys).
(function () {
  const csrf = document.querySelector('meta[name=csrf]')?.content || '';
  const b64aBuf = s => { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '=';
    return Uint8Array.from(atob(s), c => c.charCodeAt(0)).buffer; };
  const bufAb64 = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const pedir = (url, cuerpo) => fetch(url, { method: 'POST', credentials: 'same-origin',
    headers: { 'X-CSRF': csrf, 'Content-Type': 'application/json' }, body: cuerpo ? JSON.stringify(cuerpo) : '{}' });

  window.Huella = {
    disponible: async () => !!(window.PublicKeyCredential &&
      await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().catch(() => false)),

    async activar() {
      const o = await (await pedir('/huella/registro/opciones')).json();
      o.challenge = b64aBuf(o.challenge);
      o.user.id = b64aBuf(o.user.id);
      (o.excludeCredentials || []).forEach(c => { c.id = b64aBuf(c.id); });
      const cred = await navigator.credentials.create({ publicKey: o });
      const r = await pedir('/huella/registro/verificar', {
        id: cred.id, rawId: bufAb64(cred.rawId), type: cred.type,
        response: { clientDataJSON: bufAb64(cred.response.clientDataJSON),
                    attestationObject: bufAb64(cred.response.attestationObject),
                    transports: cred.response.getTransports ? cred.response.getTransports() : [] },
        clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {} });
      return r.json();
    },

    async ingresar() {
      const o = await (await pedir('/huella/ingreso/opciones')).json();
      o.challenge = b64aBuf(o.challenge);
      (o.allowCredentials || []).forEach(c => { c.id = b64aBuf(c.id); });
      const cred = await navigator.credentials.get({ publicKey: o });
      const r = await pedir('/huella/ingreso/verificar', {
        id: cred.id, rawId: bufAb64(cred.rawId), type: cred.type,
        response: { clientDataJSON: bufAb64(cred.response.clientDataJSON),
                    authenticatorData: bufAb64(cred.response.authenticatorData),
                    signature: bufAb64(cred.response.signature),
                    userHandle: cred.response.userHandle ? bufAb64(cred.response.userHandle) : null },
        clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {} });
      return r.json();
    },
  };

  const mensajeError = e => (e && e.name === 'NotAllowedError') ? 'Se canceló o no se reconoció la huella.' :
    (e && e.name === 'InvalidStateError') ? 'Este dispositivo ya tiene la huella activada.' : 'No se pudo usar la huella en este dispositivo.';

  // Botón del login
  const bLogin = document.getElementById('ingresar-huella');
  if (bLogin) {
    Huella.disponible().then(ok => { if (ok) bLogin.closest('.huella-login').hidden = false; });
    bLogin.onclick = async () => {
      const aviso = document.getElementById('aviso-huella');
      bLogin.disabled = true; aviso.textContent = '';
      try {
        const r = await Huella.ingresar();
        if (r.ok) { location.href = r.destino; return; }
        aviso.textContent = r.error;
      } catch (e) { aviso.textContent = mensajeError(e); }
      bLogin.disabled = false;
    };
  }

  // Botones de activar (Mi cuenta y aviso del panel)
  document.querySelectorAll('.activar-huella').forEach(b => {
    Huella.disponible().then(ok => {
      const caja = b.closest('[data-huella]');
      if (!caja) return;
      if (ok) caja.hidden = false;
      else if (caja.dataset.huella === 'cuenta') { b.disabled = true; b.textContent = 'Este dispositivo no tiene huella o Face ID'; caja.hidden = false; }
    });
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await Huella.activar();
        if (r.ok) { location.href = '/cuenta?huella=1'; return; }
        alert(r.error);
      } catch (e) { alert(mensajeError(e)); }
      b.disabled = false;
    };
  });
})();
