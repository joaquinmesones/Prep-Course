"""
VideoLabs — Transcripción de voz (para subtítulos y para cortar silencios).

Usa faster-whisper, que corre en el propio servidor (sin costo por uso).
La primera vez descarga el modelo (~470 MB para "small").

Variables de entorno:
  REELIA_WHISPER_MODELO   tiny | base | small (default) | medium
"""
import os

_modelo = None


def _cargar():
    global _modelo
    if _modelo is None:
        from faster_whisper import WhisperModel
        nombre = os.environ.get("REELIA_WHISPER_MODELO", "small")
        hilos = max(1, os.cpu_count() or 1)
        _modelo = WhisperModel(nombre, device="cpu", compute_type="int8", cpu_threads=hilos)
    return _modelo


def transcribir(wav):
    """Devuelve una lista de palabras: [{"inicio": s, "fin": s, "texto": str}, ...]."""
    segmentos, _info = _cargar().transcribe(
        wav, language="es", word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400}, beam_size=1,
    )
    palabras = []
    for seg in segmentos:
        for w in seg.words or []:
            texto = w.word.strip()
            if texto:
                palabras.append({"inicio": float(w.start), "fin": float(w.end), "texto": texto})
    return palabras


def disponible():
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False
