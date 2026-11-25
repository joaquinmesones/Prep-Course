# VideoLabs — motores de video

- **Modo 1 — Video a video** (`reelia_videos.py`): clips del celular → Reel 9:16. Detecta voz con Whisper (`reelia_transcribir.py`), corta pausas, subtítulos palabra por palabra, recorridos recortados a la duración objetivo, horizontal → vertical con fondo desenfocado, color, portada, logo, cierre y música que baja cuando alguien habla.
  ```bash
  python3 reelia_videos.py --clips a.mp4 b.mov --datos propiedad.json --salida reel.mp4 --objetivo 30
  ```
- **Modo 2 — Fotos a video** (`reelia_fotos.py`), detallado abajo.

# Modo 2: Fotos a video

Convierte las fotos de una propiedad + sus datos en un video vertical (1080x1920) para Reels, Historias y Ads.

## Qué hace hoy
- Movimiento en cada foto: paneo lateral tipo recorrido o zoom suave (alternados).
- Fundidos entre tomas.
- Portada con operación, precio, ubicación y tipo.
- Etiquetas con los datos (ambientes, m², dormitorios, baños, cochera, destacados).
- Cierre con inmobiliaria/logo, "¿Querés conocerla?", botón de WhatsApp y asesor.
- Guion de voz en off en español rioplatense generado desde los datos (`--guion`).
- Música original compuesta por Reelia (libre de derechos), en 3 estilos: `calido`, `moderno` y `sereno` (`reelia_musica.py`).
- Mezcla de voz + música (la música baja sola cuando habla la voz) y el video se ajusta a la duración de la voz.

## Curador de fotos con IA (`reelia_curador.py`)
Con `ANTHROPIC_API_KEY` configurada, Claude mira las fotos, detecta cada ambiente, descarta repetidas/malas, elige la portada, ordena el recorrido y escribe un texto corto por foto:
```bash
python3 reelia_curador.py --fotos fotos/ --datos propiedad.json --aplicar
```

## Uso
```bash
# 1. Ver el guion de la voz en off
python3 reelia_fotos.py --datos propiedad.json --guion

# 2. Armar el video
python3 reelia_fotos.py --fotos fotos/ --datos propiedad.json --salida propiedad.mp4 \
    --estilo-musica calido          # o --musica tema.mp3, o --voz voz.mp3

# Solo la música
python3 reelia_musica.py --estilo moderno --segundos 30 --salida musica.mp3 --semilla 3
```
Datos: ver `propiedad.ejemplo.json`. El campo `tomas` fija el orden de las fotos y la etiqueta que aparece en cada una (lo completa el Curador de fotos); si no está, se usan en orden alfabético con etiquetas armadas desde los datos. Si no hay `precio`, la portada muestra "Consultá el precio". La voz en off es opcional.

Requiere `ffmpeg`, `Pillow`, `numpy` y `scipy`.

## Pendiente
- Voz en off opcional con acento argentino: conectar ElevenLabs (más adelante).
- Sumar una biblioteca de temas con licencia comercial (ej. Pixabay Music) como alternativa a la música propia.
- Exportar también 4:5 (feed) y versiones de 15 / 30 / 60 s.
