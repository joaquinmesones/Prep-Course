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
Datos: ver `propiedad.ejemplo.json`. El campo `orden` permite fijar el orden de las fotos (lo completa el Curador de fotos); si está vacío se usan en orden alfabético.

Requiere `ffmpeg` y `Pillow`.

## Pendiente
- Voz en off con acento argentino: conectar un proveedor de voz (ElevenLabs o Azure, voces `es-AR`).
- Curador automático: clasificar fotos por ambiente y ordenar el recorrido con IA.
- Biblioteca de música libre de derechos.
- Exportar también 4:5 (feed) y versiones de 15 / 30 / 60 s.
