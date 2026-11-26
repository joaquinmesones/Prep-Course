"""
VideoLabs — Voz en off con ElevenLabs.

Variables de entorno:
  ELEVENLABS_API_KEY     clave de la cuenta (obligatoria)
  REELIA_ELEVEN_MODELO   modelo de voz (default: eleven_multilingual_v2)

Uso suelto:
  python3 reelia_voz.py --voces
  python3 reelia_voz.py --voz <voice_id> --texto "Hola..." --salida voz.mp3
"""
import argparse
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")
MODELO = os.environ.get("REELIA_ELEVEN_MODELO", "eleven_multilingual_v2")


class ErrorVoz(RuntimeError):
    pass


def _clave():
    clave = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not clave:
        raise ErrorVoz("Falta la clave de ElevenLabs (ELEVENLABS_API_KEY).")
    return clave


def _pedido(metodo, ruta, cuerpo=None, timeout=120):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(BASE + ruta, data=datos, method=metodo, headers={
        "xi-api-key": _clave(), "Content-Type": "application/json", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")[:400]
        try:  # ElevenLabs suele responder {"detail": {"status": ..., "message": ...}}
            info = json.loads(detalle).get("detail") or {}
            estado = info.get("status", "") if isinstance(info, dict) else ""
            mensaje = info.get("message", "") if isinstance(info, dict) else str(info)
        except (ValueError, AttributeError):
            estado, mensaje = "", detalle
        if "permission" in (estado + mensaje).lower():
            raise ErrorVoz("A la clave de ElevenLabs le falta un permiso. Editala en ElevenLabs → "
                           "Desarrolladores → Claves de API y habilitá “De texto a voz: Acceso” y "
                           f"“Voces: Lectura”. (ElevenLabs dice: {mensaje})") from e
        if e.code == 401:
            raise ErrorVoz("ElevenLabs rechazó la clave: revisá que esté bien copiada, completa y "
                           f"sin espacios. (ElevenLabs dice: {mensaje or estado or 'no autorizado'})") from e
        if e.code in (402, 429) or "quota" in detalle.lower():
            raise ErrorVoz("Se terminaron los créditos de ElevenLabs de este mes.") from e
        raise ErrorVoz(f"ElevenLabs respondió {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise ErrorVoz(f"No se pudo conectar con ElevenLabs: {e.reason}") from e


def listar_voces():
    """Voces de la cuenta ("My Voices"): [{id, nombre, descripcion, muestra}]."""
    datos = json.loads(_pedido("GET", "/v1/voices", timeout=20))
    voces = []
    for v in datos.get("voices", []):
        etiquetas = v.get("labels") or {}
        desc = " · ".join(x for x in (etiquetas.get("gender"), etiquetas.get("accent"),
                                       etiquetas.get("age"), etiquetas.get("description")) if x)
        voces.append({"id": v["voice_id"], "nombre": v.get("name", "Voz"),
                      "descripcion": desc, "muestra": v.get("preview_url"),
                      "categoria": v.get("category", "")})
    # primero las que agregó el usuario, después las prediseñadas
    voces.sort(key=lambda v: (v["categoria"] == "premade", v["nombre"].lower()))
    return voces


def _multipart(campos, archivos):
    """Arma un cuerpo multipart/form-data: campos [(nombre, valor)], archivos [(nombre, ruta)]."""
    import uuid
    limite = uuid.uuid4().hex
    cuerpo = b""
    for k, v in campos:
        cuerpo += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                   f"{v}\r\n").encode()
    for k, ruta in archivos:
        nombre = os.path.basename(ruta)
        with open(ruta, "rb") as fh:
            cuerpo += (f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                       f"filename=\"{nombre}\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode()
            cuerpo += fh.read() + b"\r\n"
    cuerpo += f"--{limite}--\r\n".encode()
    return cuerpo, f"multipart/form-data; boundary={limite}"


def _pedido_multipart(ruta, campos, archivos, timeout=180):
    cuerpo, tipo = _multipart(campos, archivos)
    req = urllib.request.Request(BASE + ruta, data=cuerpo, method="POST",
                                 headers={"xi-api-key": _clave(), "Content-Type": tipo})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")[:400]
        if "permission" in detalle.lower():
            raise ErrorVoz("A la clave de ElevenLabs le falta el permiso “Voces: Escribir”.") from e
        raise ErrorVoz(f"ElevenLabs respondió {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise ErrorVoz(f"No se pudo conectar con ElevenLabs: {e.reason}") from e


def _es_argentina(v):
    texto = " ".join(str(v.get(k) or "") for k in
                     ("accent", "locale", "description", "name", "descriptive")).lower()
    return "argentin" in texto or "es-ar" in texto or "rioplatense" in texto or "porteñ" in texto


def buscar_voces_argentinas(cantidad=12):
    """Busca en la Voice Library voces en español con acento argentino.
    Devuelve [{public_owner_id, voice_id, nombre, genero, descripcion, muestra}]."""
    from urllib.parse import urlencode
    vistos, encontradas = set(), []
    intentos = [{"language": "es", "accent": "argentine"}, {"language": "es", "locale": "es-AR"},
                {"language": "es", "search": "argentina"}, {"search": "argentino"},
                {"search": "argentinian"}]
    for params in intentos:
        try:
            datos = json.loads(_pedido("GET", "/v1/shared-voices?" + urlencode(
                {"page_size": 50, **params}), timeout=30))
        except ErrorVoz:
            if not encontradas and params is intentos[0]:
                raise
            continue
        for v in datos.get("voices", []):
            clave = v.get("voice_id")
            if not clave or clave in vistos or not _es_argentina(v):
                continue
            vistos.add(clave)
            encontradas.append({
                "public_owner_id": v.get("public_owner_id"), "voice_id": clave,
                "nombre": v.get("name", "Voz"), "genero": (v.get("gender") or "").lower(),
                "descripcion": " · ".join(x for x in (v.get("gender"), v.get("age"),
                                                      v.get("descriptive") or v.get("use_case")) if x),
                "muestra": v.get("preview_url"),
                "uso": v.get("cloned_by_count") or v.get("usage_character_count_1y") or 0})
        if len(encontradas) >= cantidad:
            break
    encontradas.sort(key=lambda v: -(v["uso"] or 0))  # las más usadas primero
    return encontradas[:cantidad]


def agregar_de_biblioteca(public_owner_id, voice_id, nombre):
    """Agrega una voz de la Voice Library a la cuenta y devuelve el voice_id para usarla."""
    datos = json.loads(_pedido("POST", f"/v1/voices/add/{public_owner_id}/{voice_id}",
                               {"new_name": nombre}, timeout=30))
    return datos.get("voice_id") or voice_id


def clonar_voz(nombre, audios, descripcion=""):
    """Clonación instantánea: crea una voz con 1 o más audios y devuelve su voice_id."""
    datos = json.loads(_pedido_multipart(
        "/v1/voices/add", [("name", nombre), ("description", descripcion),
                           ("remove_background_noise", "true")],
        [("files", a) for a in audios]))
    if not datos.get("voice_id"):
        raise ErrorVoz("ElevenLabs no devolvió la voz clonada.")
    return datos["voice_id"]


def borrar_voz(voice_id):
    try:
        _pedido("DELETE", f"/v1/voices/{voice_id}", timeout=30)
    except ErrorVoz:
        pass  # si ya no existe en la cuenta, no importa


def sintetizar(texto, voice_id, salida):
    """Genera el audio y lo guarda como mp3. Devuelve la cantidad de caracteres usados."""
    texto = " ".join(texto.split())
    if not texto:
        raise ErrorVoz("El guion está vacío.")
    audio = _pedido("POST", f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128", {
        "text": texto,
        "model_id": MODELO,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.15,
                           "use_speaker_boost": True},
    })
    if len(audio) < 1000:
        raise ErrorVoz("ElevenLabs devolvió un audio vacío.")
    with open(salida, "wb") as fh:
        fh.write(audio)
    return len(texto)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voces", action="store_true")
    ap.add_argument("--voz")
    ap.add_argument("--texto")
    ap.add_argument("--salida", default="voz.mp3")
    a = ap.parse_args()
    if a.voces:
        for v in listar_voces():
            print(f"{v['id']}  {v['nombre']}  ({v['descripcion']})")
    elif a.voz and a.texto:
        n = sintetizar(a.texto, a.voz, a.salida)
        print(f"Listo: {a.salida} ({n} caracteres)")
    else:
        ap.error("usá --voces, o --voz y --texto")


if __name__ == "__main__":
    main()
