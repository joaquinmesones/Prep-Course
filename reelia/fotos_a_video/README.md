# Reelia — Modo 2: Fotos a video (prototipo)

Convierte las fotos de una propiedad + sus datos en un video vertical (1080x1920) para Reels, Historias y Ads.

## Qué hace hoy
- Movimiento en cada foto: paneo lateral tipo recorrido o zoom suave (alternados).
- Fundidos entre tomas.
- Portada con operación, precio, ubicación y tipo.
- Etiquetas con los datos (ambientes, m², dormitorios, baños, cochera, destacados).
- Cierre con inmobiliaria/logo, "¿Querés conocerla?", botón de WhatsApp y asesor.
- Guion de voz en off en español rioplatense generado desde los datos (`--guion`).
- Mezcla de voz + música (la música baja sola cuando habla la voz) y el video se ajusta a la duración de la voz.

## Uso
```bash
# 1. Ver el guion de la voz en off
python3 reelia_fotos.py --datos propiedad.json --guion

# 2. Armar el video
python3 reelia_fotos.py --fotos fotos/ --datos propiedad.json --salida propiedad.mp4 \
    --voz voz.mp3 --musica musica.mp3
```
Datos: ver `propiedad.ejemplo.json`. El campo `tomas` fija el orden de las fotos y la etiqueta que aparece en cada una (lo completa el Curador de fotos); si no está, se usan en orden alfabético con etiquetas armadas desde los datos. Si no hay `precio`, la portada muestra "Consultá el precio". La voz en off es opcional.

Requiere `ffmpeg` y `Pillow`.

## Pendiente
- Voz en off opcional con acento argentino: conectar ElevenLabs (más adelante).
- Curador automático: clasificar fotos por ambiente y ordenar el recorrido con IA.
- Biblioteca de música libre de derechos.
- Exportar también 4:5 (feed) y versiones de 15 / 30 / 60 s.
