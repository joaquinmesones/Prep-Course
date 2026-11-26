#!/usr/bin/env python3
"""
Reelia — Modo 2: Fotos a video (propiedades).

Toma una carpeta de fotos de una propiedad + un archivo propiedad.json con los
datos y arma un video vertical (1080x1920) listo para Reels / Historias:

  - Cada foto con movimiento (zoom suave o paneo tipo recorrido).
  - Transiciones suaves entre fotos.
  - Datos de la propiedad en pantalla (precio, ubicación, ambientes, m², etc.).
  - Cierre con inmobiliaria, asesor, WhatsApp y llamado a la acción.
  - Voz en off (opcional en este prototipo: se pasa un .mp3 con --voz) y música
    de fondo (--musica). Si hay voz, la música baja automáticamente debajo.

Uso:
  python3 reelia_fotos.py --fotos carpeta/ --datos propiedad.json --salida video.mp4 \
      [--voz voz.mp3] [--musica musica.mp3 | --estilo-musica calido|moderno|sereno|ninguno]
      [--segundos-por-foto 3.2]

  python3 reelia_fotos.py --datos propiedad.json --guion
      -> imprime el guion de la voz en off generado a partir de los datos.

Requiere: ffmpeg, Pillow.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920  # vertical por defecto; usar_formato() cambia a horizontal
FORMATOS = {"vertical": (1080, 1920), "horizontal": (1920, 1080)}


def usar_formato(nombre):
    """Cambia el tamaño de salida (todas las placas y tomas leen W y H al dibujar)."""
    global W, H
    W, H = FORMATOS.get(nombre, FORMATOS["vertical"])


def es_horizontal():
    return W > H
FPS = 30
TRANSICION = 0.6  # segundos de transición entre tomas

# Transiciones que se pueden elegir (nombre en la plataforma -> efecto de ffmpeg xfade).
# "variadas" va rotando para que el video tenga ritmo; "ninguna" es corte directo.
TRANSICIONES = {
    "variadas": None,
    "fundido": "fade",
    "deslizar": "smoothleft",
    "zoom": "zoomin",
    "circulo": "circleopen",
    "barrido": "wipeleft",
    "negro": "fadeblack",
    "ninguna": None,
}
ROTACION = ["smoothleft", "zoomin", "fade", "circleopen", "slideup", "wipeleft", "dissolve"]


def efecto_transicion(estilo, i):
    """Efecto para la unión número i (empieza en 1), o None para un corte directo."""
    if estilo == "ninguna":
        return None
    if estilo == "variadas" or estilo not in TRANSICIONES:
        return ROTACION[(i - 1) % len(ROTACION)]
    if estilo == "deslizar":  # en vertical sube, como al pasar historias; en horizontal, de costado
        return "smoothleft" if es_horizontal() else "smoothup"
    return TRANSICIONES[estilo]

FUENTE_BOLD = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
FUENTE_SEMI = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"
FUENTE_REG = "/usr/share/fonts/opentype/inter/Inter-Regular.otf"
EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp")


# ----------------------------------------------------------------- utilidades
def fuente(ruta, tam):
    try:
        return ImageFont.truetype(ruta, tam)
    except OSError:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", tam)


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"Falló: {' '.join(cmd[:6])} ...")
    return r.stdout


def duracion(ruta):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", ruta])
    return float(out.strip())


def hex_a_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def formatear_precio(d):
    precio = d.get("precio")
    if precio is None:
        return None
    if isinstance(precio, (int, float)):
        precio = f"{int(precio):,}".replace(",", ".")
    moneda = d.get("moneda", "USD")
    return f"{moneda} {precio}"


# ------------------------------------------------------------ guion de la voz
def generar_guion(d):
    """Guion corto en español rioplatense a partir de los datos."""
    partes = []
    op = d.get("operacion", "venta").lower()
    tipo = d.get("tipo", "propiedad")
    zona = d.get("ubicacion", "")
    femeninos = ("casa", "propiedad", "oficina", "quinta", "cabaña", "chacra")
    art = "esta" if tipo.lower().split()[0] in femeninos else "este"
    partes.append(f"¡Mirá {art} {tipo} en {op} en {zona}!" if zona else f"¡Mirá {art} {tipo} en {op}!")

    detalles = []
    if d.get("ambientes"):
        detalles.append(f"{d['ambientes']} ambientes")
    if d.get("dormitorios"):
        detalles.append(f"{d['dormitorios']} dormitorios")
    if d.get("banos"):
        n = d["banos"]
        detalles.append(f"{n} baño" if n == 1 else f"{n} baños")
    if d.get("m2_totales"):
        detalles.append(f"{d['m2_totales']} metros cuadrados")
    if detalles:
        partes.append("Tiene " + ", ".join(detalles[:-1]) +
                      (f" y {detalles[-1]}." if len(detalles) > 1 else f"{detalles[0]}."))

    if d.get("destacados"):
        partes.append(" ".join(d["destacados"][:2]))
    if d.get("cochera"):
        partes.append("Además, cuenta con cochera.")
    precio = formatear_precio(d)
    if precio:
        moneda, monto = precio.split(" ", 1)
        nombre = {"USD": "dólares", "U$S": "dólares", "ARS": "pesos", "$": "pesos"}.get(moneda, moneda)
        partes.append(f"Su valor es de {monto} {nombre}.")
    partes.append(d.get("cta", "Escribinos por WhatsApp y coordiná tu visita."))
    return " ".join(partes).replace("  ", " ")


# ----------------------------------------------------------- placas de texto
def placa_portada(d, marca):
    """Overlay transparente para la primera foto: operación, precio, ubicación."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    # degradé inferior para legibilidad
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(max(0, (y - H * 0.45) / (H * 0.55)) * 210))
    img.paste(Image.new("RGBA", (W, H), (0, 0, 0, 255)), (0, 0), grad.resize((W, H)))
    dr = ImageDraw.Draw(img)

    # en vertical el bloque deja lugar al logo centrado abajo; en horizontal el logo va a la derecha
    b = (H - 70 if es_horizontal() else H - 375) - 385  # y del chip
    x0 = 90 if es_horizontal() else 80
    op = d.get("operacion", "Venta").upper()
    f_chip = fuente(FUENTE_BOLD, 44)
    tw = dr.textlength(op, font=f_chip)
    dr.rounded_rectangle((x0, b, x0 + tw + 60, b + 84), radius=42, fill=marca + (255,))
    dr.text((x0 + 30, b + 16), op, font=f_chip, fill="white")

    precio = formatear_precio(d)
    if precio:
        dr.text((x0, b + 110), precio, font=fuente(FUENTE_BOLD, 112), fill="white")
    else:
        dr.text((x0, b + 130), "Consultá el precio", font=fuente(FUENTE_BOLD, 92), fill="white")
    if d.get("ubicacion"):
        dr.text((x0 + 4, b + 260), d["ubicacion"], font=fuente(FUENTE_SEMI, 54), fill=(235, 235, 235))
    if d.get("tipo"):
        dr.text((x0 + 4, b + 335), d["tipo"].capitalize(), font=fuente(FUENTE_REG, 46),
                fill=(210, 210, 210))
    return img


def placa_dato(texto, marca):
    """Etiqueta flotante inferior (ej: '3 ambientes · 85 m²')."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    f = fuente(FUENTE_BOLD, 58)
    tw = dr.textlength(texto, font=f)
    x0 = (W - tw) / 2 - 48
    y0 = H - 200 if es_horizontal() else H - 420
    dr.rounded_rectangle((x0 + 6, y0 + 8, x0 + tw + 102, y0 + 128), radius=30, fill=(0, 0, 0, 90))
    dr.rounded_rectangle((x0, y0, x0 + tw + 96, y0 + 120), radius=30, fill=(255, 255, 255, 240))
    dr.rectangle((x0, y0 + 20, x0 + 10, y0 + 100), fill=marca + (255,))
    dr.text((x0 + 48, y0 + 26), texto, font=f, fill=(20, 20, 20))
    return img


def placa_cierre(d, marca, fondo):
    """Placa final opaca con CTA, inmobiliaria, asesor y WhatsApp."""
    base = ImageOps.fit(fondo.convert("RGB"), (W, H)).filter(ImageFilter.GaussianBlur(28))
    base = Image.blend(base, Image.new("RGB", (W, H), (10, 10, 14)), 0.62).convert("RGBA")
    dr = ImageDraw.Draw(base)

    def centrado(txt, y, f, color):
        tw = dr.textlength(txt, font=f)
        dr.text(((W - tw) / 2, y), txt, font=f, fill=color)

    y = 560
    logo = d.get("logo")
    horizontal = es_horizontal()
    if horizontal:  # logo a la izquierda, textos a la derecha, todo centrado en alto
        col = W * 0.70

        def centrado(txt, y, f, color):  # noqa: F811
            tw = dr.textlength(txt, font=f)
            dr.text((col - tw / 2, y), txt, font=f, fill=color)
        y = (H - 600) // 2 + 20
    if logo and os.path.exists(logo):
        lg = Image.open(logo).convert("RGBA")
        lg.thumbnail((560, 230) if horizontal else (760, 300))
        pad_x, pad_y = 56, 44
        cw, ch = lg.width + 2 * pad_x, lg.height + 2 * pad_y
        if horizontal:
            x0, y0 = int(W * 0.25 - cw / 2), (H - ch) // 2
        else:  # con la ficha arriba, el contenido del cierre baja un poco
            x0, y0 = (W - cw) // 2, 470 if d.get("ficha", True) else 380
        dr.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=36, fill=(255, 255, 255, 250))
        base.alpha_composite(lg, (x0 + pad_x, y0 + pad_y))
        if not horizontal:
            y = y0 + ch + 90
    elif d.get("inmobiliaria"):
        centrado(d["inmobiliaria"], y, fuente(FUENTE_BOLD, 76), "white")
        y += 150

    cta = d.get("cta_corto", "¿Querés conocerla?")
    centrado(cta, y, fuente(FUENTE_BOLD, 80), "white")
    y += 120
    centrado("Coordiná tu visita", y, fuente(FUENTE_REG, 52), (220, 220, 220))
    y += 150

    if d.get("whatsapp"):
        f = fuente(FUENTE_BOLD, 52 if horizontal else 60)
        txt = f"WhatsApp  {d['whatsapp']}"
        tw = dr.textlength(txt, font=f)
        x0 = (W * 0.70 if horizontal else W / 2) - tw / 2 - 50
        dr.rounded_rectangle((x0, y, x0 + tw + 100, y + 130), radius=65, fill=(37, 211, 102, 255))
        dr.text((x0 + 50, y + (34 if horizontal else 30)), txt, font=f, fill="white")
        y += 220
    if d.get("asesor"):
        centrado(d["asesor"], y, fuente(FUENTE_SEMI, 54), "white")
        y += 80
    if d.get("inmobiliaria") and logo and os.path.exists(logo):
        centrado(d["inmobiliaria"], y, fuente(FUENTE_REG, 46), (200, 200, 200))
    dr.rectangle((0, H - 18, W, H), fill=marca + (255,))
    return base


def caracteristicas(d):
    """Lista corta de características para la ficha: '3 amb.', '2 dorm.', '78 m²'..."""
    c = []
    if d.get("ambientes"):
        c.append(f"{d['ambientes']} amb.")
    if d.get("dormitorios"):
        c.append(f"{d['dormitorios']} dorm.")
    if d.get("banos"):
        c.append(f"{d['banos']} baño{'s' if d['banos'] != 1 else ''}")
    if d.get("m2_totales"):
        c.append(f"{d['m2_totales']} m²")
    if d.get("cochera"):
        c.append("Cochera")
    return c


def placa_ficha(d, marca):
    """Ficha fija arriba, visible todo el video: operación + precio, tipo · ubicación
    y características (ambientes, dormitorios, baños, m², cochera)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    horizontal = es_horizontal()
    m = 44 if horizontal else 48                 # margen exterior
    ancho = 820 if horizontal else W - 2 * m     # ancho del panel
    pad = 30 if horizontal else 34
    f_chip = fuente(FUENTE_BOLD, 34 if horizontal else 38)
    f_precio = fuente(FUENTE_BOLD, 60 if horizontal else 70)
    f_sub = fuente(FUENTE_SEMI, 36 if horizontal else 42)
    f_car = fuente(FUENTE_SEMI, 32 if horizontal else 38)
    interior = ancho - 2 * pad

    op = d.get("operacion", "Venta").upper()
    precio = formatear_precio(d) or "Consultá el precio"
    sub = " · ".join(x for x in (str(d.get("tipo", "")).capitalize(), d.get("ubicacion", "")) if x)
    # características en una o dos líneas según entren
    lineas_car, actual = [], ""
    for c in caracteristicas(d):
        prueba = f"{actual}  ·  {c}" if actual else c
        if dr.textlength(prueba, font=f_car) > interior and actual:
            lineas_car.append(actual)
            actual = c
        else:
            actual = prueba
    if actual:
        lineas_car.append(actual)

    alto_chip = 58 if horizontal else 64
    alto = pad + max(alto_chip, 74 if horizontal else 86)
    if sub:
        alto += 54 if horizontal else 62
    alto += len(lineas_car) * (46 if horizontal else 54) + (8 if lineas_car else 0) + pad - 10
    x0, y0 = m, m
    dr.rounded_rectangle((x0, y0, x0 + ancho, y0 + alto), radius=30, fill=(12, 12, 14, 168))
    dr.rectangle((x0, y0 + 26, x0 + 8, y0 + alto - 26), fill=marca + (255,))

    x, y = x0 + pad, y0 + pad
    tw = dr.textlength(op, font=f_chip)
    dr.rounded_rectangle((x, y + 6, x + tw + 44, y + 6 + alto_chip), radius=alto_chip // 2,
                         fill=marca + (255,))
    dr.text((x + 22, y + 6 + (alto_chip - 38) // 2 - 2), op, font=f_chip, fill="white")
    while dr.textlength(precio, font=f_precio) > interior - tw - 70 and f_precio.size > 36:
        f_precio = fuente(FUENTE_BOLD, f_precio.size - 4)
    dr.text((x + tw + 70, y - 2), precio, font=f_precio, fill="white")
    y += (74 if horizontal else 86)
    if sub:
        while dr.textlength(sub, font=f_sub) > interior and f_sub.size > 26:
            f_sub = fuente(FUENTE_SEMI, f_sub.size - 2)
        dr.text((x, y), sub, font=f_sub, fill=(235, 235, 235))
        y += 54 if horizontal else 62
    if lineas_car:
        y += 8
        dr.line((x, y - 6, x + interior, y - 6), fill=(255, 255, 255, 60), width=2)
        for linea in lineas_car:
            dr.text((x, y + 2), linea, font=f_car, fill=(255, 255, 255))
            y += 46 if horizontal else 54
    return img


def poner_capas_fijas(video, ficha_png, pie_png, hasta, salida):
    """Ficha visible todo el video (aparece con un fundido) y logo al pie hasta el cierre."""
    entradas, filtros, cadena, n = ["-i", video], [], "[0:v]", 1
    if ficha_png:
        entradas += ["-loop", "1", "-i", ficha_png]
        filtros.append(f"[{n}:v]format=rgba,fade=in:st=0.15:d=0.5:alpha=1[fi]")
        filtros.append(f"{cadena}[fi]overlay=0:0:shortest=1[c{n}]")
        cadena, n = f"[c{n}]", n + 1
    if pie_png:
        entradas += ["-loop", "1", "-i", pie_png]
        filtros.append(f"[{n}:v]format=rgba[pi]")
        filtros.append(f"{cadena}[pi]overlay=0:0:shortest=1:enable='lt(t,{hasta:.3f})'[c{n}]")
        cadena, n = f"[c{n}]", n + 1
    filtros.append(f"{cadena}format=yuv420p[v]")
    run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
         "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", salida])


def placa_pie_logo(logo):
    """Franja blanca redondeada con el logo, abajo al centro, para todas las tomas."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    lg = Image.open(logo).convert("RGBA")
    lg.thumbnail((340, 74) if es_horizontal() else (420, 92))
    pad_x, pad_y = 34, 20
    cw, ch = lg.width + 2 * pad_x, lg.height + 2 * pad_y
    if es_horizontal():
        x0, y0 = W - cw - 56, H - ch - 48
    else:
        x0, y0 = (W - cw) // 2, H - ch - 64
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((x0 + 4, y0 + 6, x0 + cw + 4, y0 + ch + 6), radius=26, fill=(0, 0, 0, 70))
    dr.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=26, fill=(255, 255, 255, 245))
    img.alpha_composite(lg, (x0 + pad_x, y0 + pad_y))
    return img


def poner_pie_logo(video, png, hasta, salida):
    """Superpone el logo fijo desde el inicio hasta el comienzo del cierre."""
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-loop", "1", "-i", png,
         "-filter_complex",
         f"[1:v]format=rgba[l];[0:v][l]overlay=0:0:shortest=1:enable='lt(t,{hasta:.3f})',"
         "format=yuv420p[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", salida])


def datos_por_toma(d):
    """Lista de etiquetas que se van mostrando sobre las fotos siguientes."""
    et = []
    amb = []
    if d.get("ambientes"):
        amb.append(f"{d['ambientes']} ambientes")
    if d.get("m2_totales"):
        amb.append(f"{d['m2_totales']} m²")
    if amb:
        et.append(" · ".join(amb))
    dorm = []
    if d.get("dormitorios"):
        dorm.append(f"{d['dormitorios']} dorm.")
    if d.get("banos"):
        dorm.append(f"{d['banos']} baño{'s' if d['banos'] != 1 else ''}")
    if dorm:
        et.append(" · ".join(dorm))
    if d.get("cochera"):
        et.append("Cochera")
    et.extend(d.get("destacados_cortos", []))
    return et


# ------------------------------------------------------------- tomas animadas
def preparar_foto(ruta, destino):
    """Normaliza la foto: orientación EXIF, RGB, leve mejora de contraste."""
    im = ImageOps.exif_transpose(Image.open(ruta)).convert("RGB")
    im = ImageOps.autocontrast(im, cutoff=0.5)
    im.save(destino, quality=95)
    return im.size


def movimiento_horizontal(ancho, alto, seg, idx, n):
    """Salida 16:9: fotos horizontales llenan la pantalla (paneo si son panorámicas,
    zoom suave si no); fotos verticales van centradas sobre la misma foto desenfocada."""
    z_ini, z_fin = (1.0, 1.1) if idx % 2 == 0 else (1.1, 1.0)
    zoom = (f"zoompan=z='{z_ini}+({z_fin}-{z_ini})*on/{n}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}")
    if ancho / alto >= 1.2:
        factor = max(W / ancho, H * 1.06 / alto)
        ew, eh = int(ancho * factor) // 2 * 2, int(alto * factor) // 2 * 2
        if ew > W * 1.25:  # panorámica: recorrido lateral
            direc = f"(iw-ow)*t/{seg}" if idx % 4 == 0 else f"(iw-ow)*(1-t/{seg})"
            return f"scale={ew}:{eh},crop={W}:{H}:x='{direc}':y='(ih-oh)/2'"
        return (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
                f"crop={W * 2}:{H * 2},{zoom}")
    return (f"split=2[fondo][frente];"
            f"[fondo]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
            f"crop={W * 2}:{H * 2},boxblur=40:2,eq=brightness=-0.08[f];"
            f"[frente]scale=-2:{H * 2}[c];[f][c]overlay=(W-w)/2:0,{zoom}")


def render_toma(foto, overlay_png, seg, idx, salida):
    """Una toma: foto con movimiento + overlay de texto con fundido."""
    with Image.open(foto) as im:
        ancho, alto = im.size
    n = int(seg * FPS)
    horizontal = ancho / alto > 0.75  # casi todas las fotos de propiedades

    if es_horizontal():
        mov = movimiento_horizontal(ancho, alto, seg, idx, n)
    elif horizontal:
        # Fondo desenfocado + foto llenando el alto con paneo lateral (recorrido)
        # o zoom lento, alternando para dar variedad.
        escala_h = int(H * 1.08)
        escala_w = int(ancho * escala_h / alto)
        if idx % 2 == 0 and escala_w > W * 1.3:
            direc = "(iw-ow)*on/{n}" if idx % 4 == 0 else "(iw-ow)*(1-on/{n})"
            mov = (f"scale={escala_w}:{escala_h},"
                   f"crop={W}:{H}:x='{direc.format(n=n)}':y='(ih-oh)/2'")
            # crop no conoce 'on'; usamos 't' en segundos
            mov = mov.replace("on/" + str(n), f"t/{seg}")
        else:
            z_ini, z_fin = (1.0, 1.12) if idx % 4 in (1, 2) else (1.12, 1.0)
            mov = (f"scale=-2:{H * 2},"
                   f"zoompan=z='{z_ini}+({z_fin}-{z_ini})*on/{n}':"
                   f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}")
    else:
        z_ini, z_fin = (1.0, 1.1) if idx % 2 == 0 else (1.1, 1.0)
        mov = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
               f"zoompan=z='{z_ini}+({z_fin}-{z_ini})*on/{n}':"
               f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}")

    filtros = f"[0:v]{mov},setsar=1,fps={FPS},format=yuv420p[v0]"
    entradas = ["-loop", "1", "-t", f"{seg}", "-i", foto]
    if overlay_png:
        entradas += ["-loop", "1", "-t", f"{seg}", "-i", overlay_png]
        filtros += (f";[1:v]format=rgba,fade=in:st=0.35:d=0.45:alpha=1[o];"
                    f"[v0][o]overlay=0:0:format=auto,format=yuv420p[v]")
        mapa = "[v]"
    else:
        mapa = "[v0]"
    run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", filtros,
         "-map", mapa, "-t", f"{seg}", "-r", str(FPS), "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", salida])


def unir_con_transiciones(tomas, segs, salida, estilo="variadas"):
    """Une las tomas. Entre fotos usa la transición elegida; hacia el cierre, siempre fundido."""
    entradas = []
    for t in tomas:
        entradas += ["-i", t]
    # misma base de tiempo en todas las entradas (xfade y concat se mezclan)
    partes = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={FPS}[n{i}]" for i in range(len(tomas))]
    ultimo = "[n0]"
    fin = segs[0]  # dónde termina hasta ahora el video unido
    for i in range(1, len(tomas)):
        efecto = "fade" if i == len(tomas) - 1 else efecto_transicion(estilo, i)
        etiqueta = f"[x{i}]"
        if efecto:
            offset = fin - TRANSICION
            partes.append(f"{ultimo}[n{i}]xfade=transition={efecto}:duration={TRANSICION}:"
                          f"offset={offset:.3f}{etiqueta}")
            fin = offset + segs[i]
        else:  # corte directo
            partes.append(f"{ultimo}[n{i}]concat=n=2:v=1:a=0,settb=AVTB,fps={FPS}{etiqueta}")
            fin += segs[i]
        ultimo = etiqueta
    if len(tomas) == 1:
        shutil.copy(tomas[0], salida)
        return
    run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(partes),
         "-map", ultimo, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", salida])


def mezclar_audio(video, voz, musica, salida):
    dur = duracion(video)
    if not voz and not musica:
        shutil.copy(video, salida)
        return
    entradas = ["-i", video]
    filtros = []
    if voz:
        entradas += ["-i", voz]
    if musica:
        entradas += ["-stream_loop", "-1", "-i", musica]
    iv = 1 if voz else None
    im = (2 if voz else 1) if musica else None
    if voz:
        filtros.append(f"[{iv}:a]adelay=400|400,loudnorm=I=-16:TP=-1.5,apad[voz]")
    if musica:
        filtros.append(f"[{im}:a]loudnorm=I=-16:TP=-1.5,volume={'0.18' if voz else '1.0'},"
                       f"afade=t=out:st={max(0, dur - 1.5):.2f}:d=1.5[mus]")
    if voz and musica:
        filtros.append("[voz][mus]amix=inputs=2:duration=longest:normalize=0[a]")
    else:
        filtros.append(f"[{'voz' if voz else 'mus'}]anull[a]")
    run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{dur:.3f}", "-movflags", "+faststart", salida])


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Reelia — fotos de propiedad a video")
    ap.add_argument("--fotos", help="carpeta con las fotos (se usan en orden alfabético)")
    ap.add_argument("--datos", required=True, help="propiedad.json")
    ap.add_argument("--salida", default="reelia_propiedad.mp4")
    ap.add_argument("--voz", help="mp3/wav con la voz en off")
    ap.add_argument("--musica", help="mp3/wav con la música de fondo")
    ap.add_argument("--estilo-musica", choices=["calido", "moderno", "sereno", "alegre", "elegante", "inspirador",
                             "chill", "tropical", "ninguno"],
                    default="calido",
                    help="si no pasás --musica, Reelia compone una pista original en este estilo")
    ap.add_argument("--segundos-por-foto", type=float, default=3.2)
    ap.add_argument("--max-fotos", type=int, default=12)
    ap.add_argument("--guion", action="store_true", help="solo imprimir el guion de la voz")
    ap.add_argument("--formato", choices=list(FORMATOS), default="vertical")
    ap.add_argument("--transicion", choices=list(TRANSICIONES), default="variadas")
    a = ap.parse_args()

    with open(a.datos, encoding="utf-8") as f:
        d = json.load(f)
    usar_formato(a.formato)
    if a.guion:
        print(generar_guion(d))
        return
    if not a.fotos:
        ap.error("--fotos es obligatorio para generar el video")

    fotos = sorted(os.path.join(a.fotos, x) for x in os.listdir(a.fotos)
                   if x.lower().endswith(EXTENSIONES))
    etiquetas_fijas = None
    if d.get("tomas"):  # orden + etiqueta por foto definidos por el Curador de fotos
        fotos = [os.path.join(a.fotos, t["foto"]) for t in d["tomas"]]
        etiquetas_fijas = [t.get("etiqueta") for t in d["tomas"]]
    elif d.get("orden"):  # solo orden explícito
        fotos = [os.path.join(a.fotos, x) for x in d["orden"]]
    fotos = fotos[:a.max_fotos]
    if not fotos:
        raise SystemExit("No encontré fotos en la carpeta.")

    marca = hex_a_rgb(d.get("color_marca", "#F40009"))
    tmp = tempfile.mkdtemp(prefix="reelia_")
    try:
        ficha = d.get("ficha", True)  # por defecto la ficha va fija todo el video
        # con ficha, los datos ya se ven siempre: solo se muestran los textos del usuario
        etiquetas = [] if ficha else datos_por_toma(d)
        tomas, segs = [], []
        seg = a.segundos_por_foto
        # si hay voz, estiramos las tomas para que el video dure lo mismo que la voz
        if a.voz:
            dur_voz = duracion(a.voz) + 1.2
            total_fotos = dur_voz - 3.5 + TRANSICION * len(fotos)
            seg = max(2.4, min(5.0, total_fotos / len(fotos)))

        for i, foto in enumerate(fotos):
            limpia = os.path.join(tmp, f"foto_{i:02d}.jpg")
            preparar_foto(foto, limpia)
            ov = None
            if i == 0:
                if not ficha:
                    ov = os.path.join(tmp, f"ov_{i}.png")
                    placa_portada(d, marca).save(ov)
            elif etiquetas_fijas is not None:
                if etiquetas_fijas[i]:
                    ov = os.path.join(tmp, f"ov_{i}.png")
                    placa_dato(etiquetas_fijas[i], marca).save(ov)
            elif i - 1 < len(etiquetas):
                ov = os.path.join(tmp, f"ov_{i}.png")
                placa_dato(etiquetas[i - 1], marca).save(ov)
            dur_toma = seg + (0.6 if i == 0 else 0)
            out = os.path.join(tmp, f"toma_{i:02d}.mp4")
            render_toma(limpia, ov, dur_toma, i, out)
            tomas.append(out)
            segs.append(dur_toma)
            print(f"  toma {i + 1}/{len(fotos)} lista")

        cierre_png = os.path.join(tmp, "cierre.png")
        placa_cierre(d, marca, Image.open(fotos[0])).convert("RGB").save(cierre_png, quality=95)
        cierre = os.path.join(tmp, "toma_cierre.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", "3.5", "-i", cierre_png,
             "-vf", f"zoompan=z='1+0.03*on/{int(3.5 * FPS)}':x='iw/2-(iw/zoom/2)':"
                    f"y='ih/2-(ih/zoom/2)':d={int(3.5 * FPS)}:s={W}x{H}:fps={FPS},format=yuv420p",
             "-t", "3.5", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", cierre])
        tomas.append(cierre)
        segs.append(3.5)

        mudo = os.path.join(tmp, "mudo.mp4")
        unir_con_transiciones(tomas, segs, mudo, a.transicion)
        logo = d.get("logo")
        pie_png = ficha_png = None
        if d.get("logo_pie", True) and logo and os.path.exists(logo):
            pie_png = os.path.join(tmp, "pie.png")
            placa_pie_logo(logo).save(pie_png)
        if ficha:
            ficha_png = os.path.join(tmp, "ficha.png")
            placa_ficha(d, marca).save(ficha_png)
        if pie_png or ficha_png:
            con_capas = os.path.join(tmp, "con_capas.mp4")
            # el cierre ya muestra el logo grande: el pie se va cuando empieza el fundido
            poner_capas_fijas(mudo, ficha_png, pie_png, duracion(mudo) - 3.5, con_capas)
            mudo = con_capas
        musica = a.musica
        if not musica and a.estilo_musica != "ninguno":
            musica = os.path.join(tmp, "musica.mp3")
            run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "reelia_musica.py"),
                 "--estilo", a.estilo_musica, "--segundos", f"{duracion(mudo) + 0.5:.2f}",
                 "--salida", musica])
        mezclar_audio(mudo, a.voz, musica, a.salida)
        print(f"Listo: {a.salida} ({duracion(a.salida):.1f} s)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
