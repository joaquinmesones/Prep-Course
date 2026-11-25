#!/usr/bin/env python3
"""
VideoLabs — Modo 1: Video a video.

Toma uno o varios clips filmados con el celular y arma un Reel vertical 1080x1920:

  - Detecta si en cada clip alguien habla (Whisper):
      * con voz  -> corta silencios y pausas (cortes tipo "jump cut") y pone subtítulos
                    animados palabra por palabra;
      * sin voz  -> lo trata como recorrido: recorta inicio/fin movidos y, si el total
                    se pasa de la duración objetivo, se queda con la parte central de cada clip.
  - Adapta videos horizontales a vertical con fondo desenfocado.
  - Corrige color (contraste, saturación, nitidez) y une los clips de recorrido con fundidos.
  - Portada con operación/precio/ubicación, logo al pie y cierre con WhatsApp
    (mismo diseño que el Modo 2).
  - Música original: de fondo y bajando sola cuando alguien habla.

Uso:
  python3 reelia_videos.py --clips c1.mp4 c2.mov ... --datos propiedad.json --salida video.mp4
      [--objetivo 30] [--sin-subtitulos] [--estilo-musica calido|moderno|sereno|ninguno]
      [--con-ambiente]   (mantiene el sonido original en los clips sin voz)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reelia_fotos as rf  # noqa: E402  (reutilizamos placas, logo, utilidades)

W, H, FPS = rf.W, rf.H, rf.FPS
FUNDIDO = 0.5
CIERRE = 3.5
DIR_FUENTES = os.path.dirname(rf.FUENTE_BOLD)

COLOR = "eq=contrast=1.05:saturation=1.15:brightness=0.01,unsharp=5:5:0.45"


# ------------------------------------------------------------------ análisis
def info_clip(ruta, tmp, i):
    """Duración, tamaño (ya rotado) y si tiene audio."""
    dur = rf.duracion(ruta)
    cuadro = os.path.join(tmp, f"cuadro_{i}.png")
    rf.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(0.5, dur / 2):.2f}", "-i", ruta,
            "-frames:v", "1", cuadro])
    with Image.open(cuadro) as im:
        ancho, alto = im.size
    audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", ruta],
                           capture_output=True, text=True).stdout.strip() != ""
    return {"ruta": ruta, "dur": dur, "ancho": ancho, "alto": alto, "audio": audio,
            "cuadro": cuadro}


def extraer_audio(ruta, destino):
    rf.run(["ffmpeg", "-y", "-v", "error", "-i", ruta, "-vn", "-ac", "1", "-ar", "16000",
            destino])


def intervalos_de_voz(palabras, dur, pausa=0.55, antes=0.12, despues=0.22):
    """Agrupa palabras en tramos hablados; las pausas largas se cortan."""
    tramos = []
    for w in palabras:
        if tramos and w["inicio"] - tramos[-1][1] <= pausa:
            tramos[-1][1] = w["fin"]
        else:
            tramos.append([w["inicio"], w["fin"]])
    out = []
    for a, b in tramos:
        a, b = max(0.0, a - antes), min(dur, b + despues)
        if out and a <= out[-1][1]:
            out[-1][1] = b
        elif b - a >= 0.3:
            out.append([a, b])
    return out


def hay_voz(palabras, dur):
    hablado = sum(w["fin"] - w["inicio"] for w in palabras)
    return len(palabras) >= 3 and hablado >= 0.2 * dur


# ------------------------------------------------------------------- render
def filtro_vertical(ancho, alto):
    """Cadena de video que lleva cualquier clip a 1080x1920 vertical."""
    if ancho / alto <= 0.8:  # ya es vertical (o casi): llenar y recortar
        return (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"setsar=1,fps={FPS},{COLOR},format=yuv420p")
    # horizontal o cuadrado: video centrado sobre el mismo video desenfocado
    return (f"split=2[fondo][frente];"
            f"[fondo]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=40:2,eq=brightness=-0.08[f];"
            f"[frente]scale={W}:-2[c];[f][c]overlay=0:(H-h)/2,"
            f"setsar=1,fps={FPS},{COLOR},format=yuv420p")


def render_tramo(clip, inicio, fin, con_audio, salida):
    """Recorta un tramo del clip y lo deja normalizado (video + audio estéreo 48k)."""
    dur = fin - inicio
    vf = filtro_vertical(clip["ancho"], clip["alto"])
    entradas = ["-ss", f"{inicio:.3f}", "-t", f"{dur:.3f}", "-i", clip["ruta"]]
    if clip["audio"] and con_audio:
        audio = "[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS[a]"
    else:
        entradas += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i",
                     "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio = "[1:a]anull[a]"
    rf.run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex",
            f"[0:v]{vf},setpts=PTS-STARTPTS[v];{audio}", "-map", "[v]", "-map", "[a]",
            "-t", f"{dur:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "19", "-c:a", "aac", "-b:a", "192k", salida])
    return rf.duracion(salida)


def render_cierre(d, marca, fondo, salida):
    png = salida.replace(".mp4", ".png")
    rf.placa_cierre(d, marca, fondo).convert("RGB").save(png, quality=95)
    n = int(CIERRE * FPS)
    rf.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", f"{CIERRE}", "-i", png,
            "-f", "lavfi", "-t", f"{CIERRE}", "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex",
            f"[0:v]zoompan=z='1+0.03*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={n}:s={W}x{H}:fps={FPS},format=yuv420p[v]",
            "-map", "[v]", "-map", "1:a", "-t", f"{CIERRE}", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "19", "-c:a", "aac", "-b:a", "192k", salida])
    return CIERRE


def unir(piezas, salida):
    """Une las piezas: fundido entre piezas con fundido=True, corte seco en el resto.
    Devuelve el inicio de cada pieza en el video final."""
    entradas, filtros, inicios = [], [], []
    for i, p in enumerate(piezas):
        entradas += ["-i", p["archivo"]]
        # misma base de tiempo en todas las entradas (xfade la exige)
        filtros.append(f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS,fps={FPS}[iv{i}]")
        filtros.append(f"[{i}:a]asetpts=PTS-STARTPTS[ia{i}]")
    v, a = "[iv0]", "[ia0]"
    t = piezas[0]["dur"]
    inicios.append(0.0)
    for i in range(1, len(piezas)):
        p = piezas[i]
        if p["fundido"]:
            off = t - FUNDIDO
            filtros.append(f"{v}[iv{i}]xfade=transition=fade:duration={FUNDIDO}:"
                           f"offset={off:.3f}[v{i}]")
            filtros.append(f"{a}[ia{i}]acrossfade=d={FUNDIDO}[a{i}]")
            inicios.append(off)
            t = off + p["dur"]
        else:
            filtros.append(f"{v}{a}[iv{i}][ia{i}]concat=n=2:v=1:a=1[cv{i}][a{i}]")
            filtros.append(f"[cv{i}]settb=AVTB,fps={FPS}[v{i}]")
            inicios.append(t)
            t += p["dur"]
        v, a = f"[v{i}]", f"[a{i}]"
    if not filtros:
        shutil.copy(piezas[0]["archivo"], salida)
        return inicios, t
    rf.run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
            "-map", v, "-map", a, "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k", salida])
    return inicios, t


# --------------------------------------------------------------- subtítulos
def ass_color(rgb):
    r, g, b = rgb
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def ass_tiempo(s):
    s = max(0.0, s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def frases(palabras, max_palabras=4, max_chars=24, pausa=0.35):
    grupos, actual = [], []
    for w in palabras:
        texto = " ".join(x["texto"] for x in actual + [w])
        corta = actual and (len(actual) >= max_palabras or len(texto) > max_chars
                            or w["inicio"] - actual[-1]["fin"] > pausa)
        if corta:
            grupos.append(actual)
            actual = []
        actual.append(w)
        if w["texto"][-1:] in ".?!," and len(actual) >= 2:
            grupos.append(actual)
            actual = []
    if actual:
        grupos.append(actual)
    return grupos


def escribir_ass(palabras, marca, ruta):
    """Subtítulos grandes, centrados en la parte baja; la palabra que se dice va en
    el color de la marca y un poco más grande."""
    resaltado = ass_color(marca)
    lineas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Sub,Inter,82,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,"
        "0,0,1,7,3,2,70,70,800,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for grupo in frases(palabras):
        fin_grupo = grupo[-1]["fin"] + 0.15
        for j, w in enumerate(grupo):
            ini = w["inicio"]
            fin = grupo[j + 1]["inicio"] if j + 1 < len(grupo) else fin_grupo
            partes = []
            for k, x in enumerate(grupo):
                t = x["texto"].replace("{", "(").replace("}", ")")
                partes.append(f"{{\\c{resaltado}\\fscx112\\fscy112}}{t}{{\\r}}" if k == j else t)
            pop = "{\\fad(60,0)}" if j == 0 else ""
            lineas.append(f"Dialogue: 0,{ass_tiempo(ini)},{ass_tiempo(fin)},Sub,,0,0,0,,"
                          f"{pop}{' '.join(partes)}")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lineas) + "\n")


# --------------------------------------------------------------- terminación
def capas_finales(video, d, marca, subs_ass, tmp, salida):
    """Portada (primeros segundos), logo al pie y subtítulos, en una sola pasada."""
    total = rf.duracion(video)
    entradas = ["-i", video]
    cadena = "[0:v]"
    filtros = []
    n = 1
    portada = os.path.join(tmp, "portada.png")
    rf.placa_portada(d, marca).save(portada)
    entradas += ["-loop", "1", "-t", f"{total:.3f}", "-i", portada]
    filtros.append(f"[{n}:v]format=rgba,fade=in:st=0.3:d=0.4:alpha=1,"
                   f"fade=out:st=3.4:d=0.4:alpha=1[p]")
    filtros.append(f"{cadena}[p]overlay=0:0:enable='lt(t,3.8)'[c1]")
    cadena, n = "[c1]", n + 1
    logo = d.get("logo")
    if d.get("logo_pie", True) and logo and os.path.exists(logo):
        pie = os.path.join(tmp, "pie.png")
        rf.placa_pie_logo(logo).save(pie)
        entradas += ["-loop", "1", "-t", f"{total:.3f}", "-i", pie]
        filtros.append(f"[{n}:v]format=rgba[l]")
        filtros.append(f"{cadena}[l]overlay=0:0:enable='lt(t,{total - CIERRE:.3f})'[c2]")
        cadena, n = "[c2]", n + 1
    if subs_ass:
        ruta = subs_ass.replace("\\", "/").replace(":", "\\:")
        filtros.append(f"{cadena}ass='{ruta}':fontsdir='{DIR_FUENTES}'[c3]")
        cadena = "[c3]"
    filtros.append(f"{cadena}format=yuv420p[v]")
    rf.run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", ";".join(filtros),
            "-map", "[v]", "-map", "0:a", "-t", f"{total:.3f}", "-c:v", "libx264",
            "-preset", "medium", "-crf", "20", "-c:a", "copy", salida])


def mezclar(video, musica, con_voz, salida):
    total = rf.duracion(video)
    if not musica:
        rf.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-af", "loudnorm=I=-16:TP=-1.5",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                salida])
        return
    fade = f"afade=t=out:st={max(0, total - 1.5):.2f}:d=1.5"
    if con_voz:
        # la música baja sola cuando hay voz (sidechain)
        filtro = (f"[0:a]loudnorm=I=-16:TP=-1.5,asplit=2[voz][sc];"
                  f"[1:a]loudnorm=I=-16:TP=-1.5,volume=0.35,{fade}[m];"
                  f"[m][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[md];"
                  f"[voz][md]amix=inputs=2:duration=first:normalize=0,"
                  f"loudnorm=I=-15:TP=-1.5[a]")
    else:
        filtro = (f"[1:a]loudnorm=I=-16:TP=-1.5,{fade}[m];"
                  f"[0:a][m]amix=inputs=2:duration=first:normalize=0,"
                  f"loudnorm=I=-15:TP=-1.5[a]")
    rf.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-stream_loop", "-1", "-i", musica,
            "-filter_complex", filtro, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart",
            salida])


# ---------------------------------------------------------------------- main
def armar(clips, d, salida, objetivo=30.0, subtitulos=True, estilo_musica="calido",
          ambiente=False, transcriptor=None, informe=None):
    marca = rf.hex_a_rgb(d.get("color_marca", "#F40009"))
    tmp = tempfile.mkdtemp(prefix="videolabs_")
    try:
        if transcriptor is None and subtitulos is not None:
            try:
                import reelia_transcribir
                transcriptor = reelia_transcribir.transcribir
            except ImportError:
                transcriptor = None

        # 1) analizar cada clip
        analisis = []
        for i, ruta in enumerate(clips):
            c = info_clip(ruta, tmp, i)
            c["palabras"] = []
            if c["audio"] and transcriptor:
                wav = os.path.join(tmp, f"audio_{i}.wav")
                extraer_audio(ruta, wav)
                try:
                    c["palabras"] = transcriptor(wav)
                except Exception as e:  # noqa: BLE001 — sin transcripción seguimos igual
                    print(f"  aviso: no se pudo transcribir el clip {i + 1}: {e}")
            c["voz"] = hay_voz(c["palabras"], c["dur"])
            analisis.append(c)
            print(f"  clip {i + 1}: {c['dur']:.1f}s, {'con voz' if c['voz'] else 'recorrido'}")

        # 2) decidir tramos
        hablado_total = 0.0
        for c in analisis:
            if c["voz"]:
                c["tramos"] = intervalos_de_voz(c["palabras"], c["dur"])
                hablado_total += sum(b - a for a, b in c["tramos"])
            else:
                ini, fin = min(0.4, c["dur"] * 0.1), max(c["dur"] - 0.3, c["dur"] * 0.9)
                c["tramos"] = [[ini, fin]]
        recorridos = [c for c in analisis if not c["voz"]]
        presupuesto = max(objetivo - hablado_total - CIERRE, 2.5 * len(recorridos))
        largo_rec = sum(c["tramos"][0][1] - c["tramos"][0][0] for c in recorridos)
        if recorridos and largo_rec > presupuesto:
            factor = presupuesto / largo_rec
            for c in recorridos:
                a, b = c["tramos"][0]
                nuevo = max(2.5, (b - a) * factor)
                medio = (a + b) / 2
                c["tramos"] = [[max(a, medio - nuevo / 2), min(b, medio + nuevo / 2)]]

        # 3) renderizar tramos
        piezas, subs_fuente = [], []
        for i, c in enumerate(analisis):
            for j, (a, b) in enumerate(c["tramos"]):
                archivo = os.path.join(tmp, f"tramo_{i:02d}_{j:03d}.mp4")
                dur = render_tramo(c, a, b, c["voz"] or ambiente, archivo)
                piezas.append({"archivo": archivo, "dur": dur,
                               # fundido entre clips de recorrido; corte seco dentro del habla
                               "fundido": bool(piezas) and not (c["voz"] and j > 0)})
                if c["voz"]:
                    subs_fuente.append((len(piezas) - 1, a, b, c["palabras"]))
        fondo = Image.open(analisis[0]["cuadro"])
        cierre = os.path.join(tmp, "cierre.mp4")
        piezas.append({"archivo": cierre, "dur": render_cierre(d, marca, fondo, cierre),
                       "fundido": True})
        print(f"  {len(piezas) - 1} tramos listos, uniendo…")

        # 4) unir
        unido = os.path.join(tmp, "unido.mp4")
        inicios, _ = unir(piezas, unido)

        # 5) subtítulos en la línea de tiempo final
        subs_ass = None
        if subtitulos and subs_fuente:
            palabras_finales = []
            for idx, a, b, palabras in subs_fuente:
                for w in palabras:
                    if w["inicio"] >= a - 0.05 and w["fin"] <= b + 0.05:
                        palabras_finales.append({
                            "inicio": inicios[idx] + max(0.0, w["inicio"] - a),
                            "fin": inicios[idx] + min(b - a, w["fin"] - a),
                            "texto": w["texto"]})
            if palabras_finales:
                subs_ass = os.path.join(tmp, "subs.ass")
                escribir_ass(palabras_finales, marca, subs_ass)

        # 6) capas: portada, logo, subtítulos
        con_capas = os.path.join(tmp, "capas.mp4")
        capas_finales(unido, d, marca, subs_ass, tmp, con_capas)

        # 7) música
        musica = None
        if estilo_musica != "ninguno":
            musica = os.path.join(tmp, "musica.mp3")
            rf.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "reelia_musica.py"),
                    "--estilo", estilo_musica, "--segundos",
                    f"{rf.duracion(con_capas) + 0.5:.2f}", "--salida", musica])
        con_voz = any(c["voz"] for c in analisis)
        mezclar(con_capas, musica, con_voz, salida)

        resumen = {
            "clips": [{"archivo": os.path.basename(c["ruta"]), "duracion": round(c["dur"], 1),
                       "tipo": "voz" if c["voz"] else "recorrido",
                       "usado": round(sum(b - a for a, b in c["tramos"]), 1),
                       "cortes": max(0, len(c["tramos"]) - 1) if c["voz"] else 0,
                       "texto": " ".join(w["texto"] for w in c["palabras"])[:400]}
                      for c in analisis],
            "duracion_final": round(rf.duracion(salida), 1),
            "subtitulos": bool(subs_ass),
        }
        if informe:
            with open(informe, "w", encoding="utf-8") as fh:
                json.dump(resumen, fh, ensure_ascii=False, indent=2)
        print(f"Listo: {salida} ({resumen['duracion_final']} s)")
        return resumen
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="VideoLabs — video a video")
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--datos", required=True)
    ap.add_argument("--salida", default="videolabs.mp4")
    ap.add_argument("--objetivo", type=float, default=30.0, help="duración buscada (s)")
    ap.add_argument("--sin-subtitulos", action="store_true")
    ap.add_argument("--con-ambiente", action="store_true")
    ap.add_argument("--estilo-musica", default="calido",
                    choices=["calido", "moderno", "sereno", "ninguno"])
    ap.add_argument("--informe", help="guardar un resumen .json de la edición")
    a = ap.parse_args()
    with open(a.datos, encoding="utf-8") as fh:
        d = json.load(fh)
    armar(a.clips, d, a.salida, a.objetivo, not a.sin_subtitulos, a.estilo_musica,
          a.con_ambiente, informe=a.informe)


if __name__ == "__main__":
    main()
