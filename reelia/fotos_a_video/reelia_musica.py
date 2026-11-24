#!/usr/bin/env python3
"""
Reelia — Compositor de música original (libre de derechos).

Genera una pista instrumental nueva para cada video, así no hay que licenciar
música de terceros. Toda la música sale de síntesis por código: no usa samples.

Estilos:
  calido   — piano eléctrico + bajo + batería suave, ~96 BPM (propiedades, hogar)
  moderno  — pulso tipo house suave, ~118 BPM (ads, lanzamientos)
  sereno   — pads y piano lento, ~72 BPM (premium, lujo)

Uso:
  python3 reelia_musica.py --estilo calido --segundos 20 --salida musica.mp3 [--semilla 7]
"""
import argparse
import subprocess
import tempfile
import os

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, fftconvolve

SR = 44100

ESTILOS = {
    "calido": dict(bpm=96, progresion=[("C", "maj9"), ("A", "m9"), ("F", "maj9"), ("G", "6sus")],
                   bombo=[0, 2.5], caja=[1, 3], hats=8, brillo=0.35, swing=0.06),
    "moderno": dict(bpm=118, progresion=[("A", "m9"), ("F", "maj9"), ("C", "maj9"), ("G", "6sus")],
                    bombo=[0, 1, 2, 3], caja=[1, 3], hats=8, brillo=0.5, swing=0.0),
    "sereno": dict(bpm=72, progresion=[("D", "maj9"), ("B", "m9"), ("G", "maj9"), ("A", "6sus")],
                   bombo=[0], caja=[], hats=0, brillo=0.25, swing=0.0),
}

NOTAS = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8,
         "A": 9, "A#": 10, "B": 11}
ACORDES = {"maj9": [0, 4, 7, 11, 14], "m9": [0, 3, 7, 10, 14], "6sus": [0, 5, 7, 9, 14]}


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n, a=0.005, d=0.3, s=0.0, r=0.05):
    t = np.arange(n) / SR
    e = np.where(t < a, t / a, s + (1 - s) * np.exp(-(t - a) / max(d, 1e-4)))
    rel = int(r * SR)
    if rel and n > rel:
        e[-rel:] *= np.linspace(1, 0, rel)
    return e


def lowpass(x, fc, orden=2):
    return sosfilt(butter(orden, fc, btype="low", fs=SR, output="sos"), x)


def highpass(x, fc, orden=2):
    return sosfilt(butter(orden, fc, btype="high", fs=SR, output="sos"), x)


def piano_electrico(f, dur, vel=0.5):
    """FM simple tipo Rhodes."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    mod = np.sin(2 * np.pi * f * 1.0 * t) * (1.6 * np.exp(-t * 3.0))
    tono = np.sin(2 * np.pi * f * t + mod)
    tono += 0.18 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t * 4)
    trem = 1 + 0.08 * np.sin(2 * np.pi * 4.5 * t)
    return vel * tono * trem * env(n, 0.004, 1.1, 0.25, 0.15)


def pad(f, dur, vel=0.25):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * f * (1 + det) * t + ph)
            for det, ph in ((-0.004, 0), (0.0, 1.3), (0.005, 2.1)))
    a = np.minimum(1, t / 0.8) * np.minimum(1, (dur - t) / 0.6).clip(0, 1)
    return vel * x / 3 * a


def bajo(f, dur, vel=0.6):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    return vel * x * env(n, 0.008, 0.45, 0.55, 0.06)


def bombo(vel=0.9):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 50 + 90 * np.exp(-t * 35)
    return vel * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def caja(rng, vel=0.22):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    ruido = highpass(rng.standard_normal(n), 1800) * np.exp(-t * 22)
    cuerpo = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    return vel * (0.6 * ruido + 0.5 * cuerpo)


def hat(rng, vel=0.06):
    n = int(0.06 * SR)
    t = np.arange(n) / SR
    return vel * highpass(rng.standard_normal(n), 7000) * np.exp(-t * 70)


def reverb(x, rng, seg=1.8, mezcla=0.22):
    n = int(seg * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t * 3.2)
    ir = lowpass(ir, 5000)
    ir /= np.sqrt(np.sum(ir ** 2))
    mojada = fftconvolve(x, ir)[: len(x)]
    return (1 - mezcla) * x + mezcla * mojada


def poner(pista, x, inicio):
    i = int(inicio * SR)
    if i >= len(pista):
        return
    fin = min(len(pista), i + len(x))
    pista[i:fin] += x[: fin - i]


def componer(estilo="calido", segundos=20.0, semilla=7):
    cfg = ESTILOS[estilo]
    rng = np.random.default_rng(semilla)
    beat = 60.0 / cfg["bpm"]
    compas = 4 * beat
    total = segundos + 2.0
    n = int(total * SR)
    armonia = np.zeros(n)
    ritmo = np.zeros(n)
    graves = np.zeros(n)
    melodia = np.zeros(n)

    escala = [0, 2, 4, 7, 9, 12, 14, 16]  # pentatónica mayor relativa al acorde
    num_compases = int(np.ceil(total / compas))
    for c in range(num_compases):
        raiz, tipo = cfg["progresion"][c % len(cfg["progresion"])]
        base = 48 + NOTAS[raiz]
        if base > 53:
            base -= 12
        t0 = c * compas
        notas = [base + 12 + iv for iv in ACORDES[tipo]]
        # acordes: piano en los tiempos 1 y 2.5 (y pad en el estilo sereno)
        for k, m in enumerate(notas):
            if estilo == "sereno":
                poner(armonia, pad(hz(m), compas + 0.4), t0)
                poner(armonia, piano_electrico(hz(m), 2.5, 0.22), t0 + k * 0.06)
            else:
                poner(armonia, piano_electrico(hz(m), beat * 2.2, 0.28), t0 + k * 0.012)
                poner(armonia, piano_electrico(hz(m), beat * 1.5, 0.18), t0 + 2.5 * beat + k * 0.012)
                poner(armonia, pad(hz(m), compas, 0.06), t0)
        # bajo
        patron_bajo = [0, 2.5, 3] if estilo != "sereno" else [0, 2]
        for b in patron_bajo:
            poner(graves, bajo(hz(base - 12 + (7 if b == 3 else 0)), beat * 1.2), t0 + b * beat)
        # batería (entra en el compás 2 para dar respiro al inicio)
        if c >= 1:
            for b in cfg["bombo"]:
                poner(ritmo, bombo(), t0 + b * beat)
            for b in cfg["caja"]:
                poner(ritmo, caja(rng), t0 + b * beat)
            for h in range(cfg["hats"]):
                desfase = cfg["swing"] * beat if h % 2 else 0
                poner(ritmo, hat(rng, 0.045 if h % 2 else 0.07), t0 + h * beat / 2 + desfase)
        # melodía simple en compases pares a partir del 2
        if c >= 2 and c % 2 == 0:
            pasos = rng.choice([0.5, 1.0], size=6, p=[0.6, 0.4])
            pos = 0.5
            for p in pasos:
                if pos >= 4:
                    break
                nota = base + 24 + rng.choice(escala[:6])
                poner(melodia, piano_electrico(hz(nota), beat * p * 1.6, 0.16), t0 + pos * beat)
                pos += p

    # "sidechain" suave: la armonía respira con el bombo
    if cfg["bombo"] and estilo != "sereno":
        duck = np.ones(n)
        for c in range(1, num_compases):
            for b in cfg["bombo"]:
                i = int((c * compas + b * beat) * SR)
                largo = int(0.22 * SR)
                if i < n:
                    seg = duck[i:i + largo]
                    seg *= 1 - 0.35 * np.exp(-np.arange(len(seg)) / (0.06 * SR))
        armonia *= duck

    armonia = lowpass(armonia, 2500 + 6000 * cfg["brillo"])
    mezcla = 0.9 * reverb(armonia + melodia, rng, mezcla=0.28) + 0.85 * lowpass(graves, 400) \
        + 0.5 * lowpass(reverb(ritmo, rng, 0.8, 0.08), 9000)
    mezcla = highpass(mezcla, 30)
    # fade in / fade out y recorte a la duración pedida
    mezcla = mezcla[: int(segundos * SR)]
    fi, fo = int(0.4 * SR), int(1.8 * SR)
    mezcla[:fi] *= np.linspace(0, 1, fi)
    mezcla[-fo:] *= np.linspace(1, 0, fo)
    # compresión suave + normalización
    mezcla /= np.max(np.abs(mezcla)) + 1e-9
    mezcla = np.tanh(mezcla * 0.9) / np.tanh(0.9)
    mezcla /= np.max(np.abs(mezcla)) + 1e-9
    mezcla *= 0.89
    estereo = np.stack([mezcla, np.roll(mezcla, int(0.0004 * SR))], axis=1)
    return estereo


def main():
    ap = argparse.ArgumentParser(description="Reelia — música original libre de derechos")
    ap.add_argument("--estilo", choices=list(ESTILOS), default="calido")
    ap.add_argument("--segundos", type=float, default=20)
    ap.add_argument("--semilla", type=int, default=7, help="cambiala para otra variación")
    ap.add_argument("--salida", default="musica.mp3")
    a = ap.parse_args()

    audio = componer(a.estilo, a.segundos, a.semilla)
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "m.wav")
        wavfile.write(wav, SR, (audio * 32767).astype(np.int16))
        if a.salida.lower().endswith(".wav"):
            os.replace(wav, a.salida)
        else:
            # -16 LUFS: volumen estándar para redes; queda de fondo sin saturar
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav,
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(SR),
                            "-b:a", "192k", a.salida],
                           check=True)
    print(f"Listo: {a.salida} ({a.estilo}, {a.segundos:.0f} s)")


if __name__ == "__main__":
    main()
