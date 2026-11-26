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
        detalle = e.read().decode(errors="replace")[:300]
        if e.code == 401:
            raise ErrorVoz("ElevenLabs rechazó la clave (revisá que esté bien copiada).") from e
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
