#!/usr/bin/env python3
"""
VideoLabs — Curador de fotos con IA (Claude).

Mira las fotos de una propiedad y decide:
  - qué ambiente muestra cada una (living, cocina, dormitorio, baño...),
  - cuáles descartar (repetidas, oscuras, movidas, sin valor),
  - el orden del recorrido (portada → ambientes sociales → cocina → dormitorios → baños → exterior),
  (los textos en pantalla los escribe el usuario: la IA no los inventa).

Necesita la variable de entorno ANTHROPIC_API_KEY.

Uso:
  python3 reelia_curador.py --fotos carpeta/ [--tipo departamento] [--salida curacion.json]
  python3 reelia_curador.py --fotos carpeta/ --datos propiedad.json --aplicar
      -> reescribe "tomas" en propiedad.json con el orden y los textos de la IA
"""
import argparse
import base64
import io
import json
import os
import sys

from PIL import Image, ImageOps

MODELO = "claude-opus-5-5"
LADO_MAX = 1024          # px: suficiente para reconocer ambientes, barato en tokens
MIN_FOTOS = 4            # nunca dejar el video con menos fotos que esto
EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp")

ESQUEMA = {
    "type": "object",
    "properties": {
        "fotos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "numero": {"type": "integer"},
                    "ambiente": {"type": "string"},
                    "calidad": {"type": "integer"},
                    "descartar": {"type": "boolean"},
                    "motivo": {"type": "string"},
                },
                "required": ["numero", "ambiente", "calidad", "descartar", "motivo"],
                "additionalProperties": False,
            },
        },
        "orden": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["fotos", "orden"],
    "additionalProperties": False,
}

INSTRUCCIONES = """Sos el editor de fotos de una inmobiliaria argentina. Vas a armar un video \
vertical tipo Reel que recorre la propiedad. Recibís las fotos numeradas.

Para cada foto indicá:
- ambiente: qué muestra (fachada, living, comedor, living comedor, cocina, dormitorio, \
baño, balcón, terraza, patio, jardín, pileta, cochera, amenities, vista, otro).
- calidad: de 1 (inutilizable) a 5 (excelente), según luz, nitidez, encuadre y lo atractiva que es.
- descartar: true si es casi igual a otra foto mejor (mismo ambiente y mismo ángulo), \
si está muy oscura, movida o no aporta nada. Si dos fotos muestran el mismo ambiente desde \
ángulos distintos, conservá ambas.
- motivo: una frase corta explicando la calidad o el descarte.

Después devolvé "orden": los números de las fotos NO descartadas, en el orden del video:
1. La primera es la portada: la foto más impactante y representativa (fachada linda, \
living amplio o una vista). Debe ser de calidad alta.
2. Seguí un recorrido natural como si alguien entrara: espacios sociales (living, comedor), \
cocina, dormitorios, baños, y al final exteriores (balcón, terraza, patio, pileta) y amenities. \
Si el exterior es lo más fuerte, puede ir como portada.
3. No pongas dos fotos casi iguales seguidas.
Si hay menos de 5 fotos, no descartes ninguna."""


def foto_a_base64(ruta):
    im = ImageOps.exif_transpose(Image.open(ruta)).convert("RGB")
    im.thumbnail((LADO_MAX, LADO_MAX))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")


def curar(rutas, tipo=None, cliente=None):
    """Devuelve {"fotos": [...], "orden": [...]} con números de foto empezando en 1."""
    import anthropic  # import diferido: el resto de VideoLabs funciona sin la librería

    cliente = cliente or anthropic.Anthropic()
    contenido = []
    for i, ruta in enumerate(rutas, start=1):
        contenido.append({"type": "text", "text": f"Foto {i}:"})
        contenido.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg", "data": foto_a_base64(ruta)}})
    pedido = f"Son {len(rutas)} fotos" + (f" de un/a {tipo}" if tipo else "") + \
        ". Analizalas y devolvé la curación."
    contenido.append({"type": "text", "text": pedido})

    respuesta = cliente.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # si el modelo declina, la API reintenta en otro modelo
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": ESQUEMA}},
        system=INSTRUCCIONES,
        messages=[{"role": "user", "content": contenido}],
    )
    if respuesta.stop_reason == "refusal":
        raise RuntimeError("La IA no pudo analizar las fotos.")
    if respuesta.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta de la IA quedó incompleta.")
    texto = next(b.text for b in respuesta.content if b.type == "text")
    return validar(json.loads(texto), len(rutas))


def validar(cur, n):
    """Corrige lo que la IA pueda devolver fuera de rango y asegura un orden usable."""
    por_numero = {}
    for f in cur.get("fotos", []):
        if isinstance(f.get("numero"), int) and 1 <= f["numero"] <= n:
            por_numero[f["numero"]] = f
    orden = []
    for x in cur.get("orden", []):
        if isinstance(x, int) and 1 <= x <= n and x not in orden:
            orden.append(x)
    # si la IA descartó demasiado, recuperamos las mejores descartadas
    if len(orden) < min(MIN_FOTOS, n):
        resto = sorted((k for k in range(1, n + 1) if k not in orden),
                       key=lambda k: -por_numero.get(k, {}).get("calidad", 0))
        orden += resto[:min(MIN_FOTOS, n) - len(orden)]
    for k in range(1, n + 1):
        por_numero.setdefault(k, {"numero": k, "ambiente": "otro",
                                  "calidad": 3, "descartar": k not in orden, "motivo": ""})
        por_numero[k]["descartar"] = k not in orden
    return {"fotos": [por_numero[k] for k in range(1, n + 1)], "orden": orden}


def aplicar_a_tomas(cur, nombres, etiquetas_usuario=None):
    """Convierte la curación en la lista "tomas" del motor de video.
    La IA solo decide el orden; los textos son únicamente los que escribió el usuario."""
    etiquetas_usuario = etiquetas_usuario or {}
    tomas = []
    for pos, k in enumerate(cur["orden"]):
        nombre = nombres[k - 1]
        texto = etiquetas_usuario.get(nombre) or None
        tomas.append({"foto": nombre, "etiqueta": None if pos == 0 else texto})
    return tomas


def main():
    ap = argparse.ArgumentParser(description="VideoLabs — curador de fotos con IA")
    ap.add_argument("--fotos", required=True)
    ap.add_argument("--tipo")
    ap.add_argument("--datos", help="propiedad.json (para --aplicar)")
    ap.add_argument("--aplicar", action="store_true")
    ap.add_argument("--salida", help="guardar la curación en este .json")
    a = ap.parse_args()

    nombres = sorted(x for x in os.listdir(a.fotos) if x.lower().endswith(EXTENSIONES))
    if not nombres:
        sys.exit("No encontré fotos.")
    d = {}
    if a.datos:
        with open(a.datos, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("tomas"):  # respetamos el conjunto de fotos que eligió el usuario
            nombres = [t["foto"] for t in d["tomas"]]
    cur = curar([os.path.join(a.fotos, x) for x in nombres], a.tipo or d.get("tipo"))
    cur["archivos"] = nombres

    for pos, k in enumerate(cur["orden"], start=1):
        f = cur["fotos"][k - 1]
        print(f"{pos:2d}. {nombres[k - 1]:<24} {f['ambiente']}")
    for f in cur["fotos"]:
        if f["descartar"]:
            print(f"    descartada: {nombres[f['numero'] - 1]} — {f['motivo']}")

    if a.salida:
        with open(a.salida, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, ensure_ascii=False, indent=2)
    if a.aplicar and a.datos:
        usuario = {t["foto"]: t["etiqueta"] for t in d.get("tomas", []) if t.get("etiqueta")}
        d["tomas"] = aplicar_a_tomas(cur, nombres, usuario)
        with open(a.datos, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
