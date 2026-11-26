"""
Reelia — plataforma web.

Solo usuarios registrados (email + contraseña). No hay registro público: los
usuarios los crea un administrador desde /usuarios o por consola:

    flask --app app crear-usuario admin@dominio.com --admin

Cada usuario sube fotos de una propiedad, completa los datos y Reelia arma el
video en segundo plano con el motor de fotos_a_video/.
"""
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

import click
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DATOS = os.environ.get("REELIA_DATOS", os.path.join(BASE, "datos"))
LOGO_DEFECTO = os.environ.get("REELIA_LOGO_DEFECTO",
                              os.path.join(BASE, "static", "marca", "logo_defecto.png"))
MOTOR = os.environ.get("REELIA_MOTOR",
                       os.path.join(BASE, "..", "fotos_a_video", "reelia_fotos.py"))
EXT_FOTOS = {".jpg", ".jpeg", ".png", ".webp"}
EXT_CLIPS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".3gp"}
MAX_CLIPS = 10
ESTILOS_MUSICA = {  # música compuesta por VideoLabs (libre de derechos)
    "calido": ("Cálida", "Piano eléctrico y ritmo suave"),
    "elegante": ("Elegante", "Piano acústico, para propiedades de categoría"),
    "sereno": ("Serena", "Lenta y ambiental, premium"),
    "chill": ("Chill", "Lo-fi relajado"),
    "inspirador": ("Inspiradora", "Piano que va creciendo"),
    "alegre": ("Alegre", "Cuerdas y palmas, con energía"),
    "tropical": ("Tropical", "Marimba veraniega, quintas y piletas"),
    "moderno": ("Moderna", "Pulso tipo house, para anuncios"),
}
EXT_MUSICA = {".mp3", ".m4a", ".aac", ".wav", ".ogg"}
TRANSICIONES = ("variadas", "fundido", "deslizar", "zoom", "circulo", "barrido", "negro", "ninguna")
MOTOR_VIDEOS = os.path.join(os.path.dirname(MOTOR), "reelia_videos.py")
sys.path.insert(0, os.path.dirname(MOTOR))  # para importar el curador de fotos


def ia_disponible():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def voz_disponible():
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


_voces_cache = {"t": 0, "voces": [], "error": None}


def voces_cuenta():
    """Voces de la cuenta de ElevenLabs (se consultan cada 10 minutos como mucho)."""
    if not voz_disponible():
        return [], None
    if time.time() - _voces_cache["t"] > 600 or _voces_cache["error"]:
        try:
            import reelia_voz
            _voces_cache.update(t=time.time(), voces=reelia_voz.listar_voces(), error=None)
        except Exception as e:  # noqa: BLE001
            _voces_cache.update(t=time.time(), error=str(e))
    return _voces_cache["voces"], _voces_cache["error"]
MAX_FOTOS = 15

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("REELIA_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=1024 * 1024 * 1024,  # 1 GB por envío (clips de video)
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("REELIA_HTTPS", "1") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)
trabajos = ThreadPoolExecutor(max_workers=int(os.environ.get("REELIA_WORKERS", "1")))


# --------------------------------------------------------------- base de datos
def db():
    if "db" not in g:
        os.makedirs(DATOS, exist_ok=True)
        g.db = sqlite3.connect(os.path.join(DATOS, "reelia.db"))
        g.db.row_factory = sqlite3.Row
    return g.db


def db_suelta():
    c = sqlite3.connect(os.path.join(DATOS, "reelia.db"))
    c.row_factory = sqlite3.Row
    return c


@app.teardown_appcontext
def cerrar_db(_):
    c = g.pop("db", None)
    if c:
        c.close()


ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, nombre TEXT,
  hash TEXT NOT NULL, admin INTEGER DEFAULT 0, activo INTEGER DEFAULT 1,
  creado REAL
);
CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL, titulo TEXT,
  estado TEXT, error TEXT, datos TEXT, creado REAL, terminado REAL
);
CREATE TABLE IF NOT EXISTS intentos_login (ip TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS musica (
  id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, animo TEXT, archivo TEXT NOT NULL,
  duracion REAL, subido_por INTEGER, creado REAL
);
"""


def iniciar_db():
    os.makedirs(DATOS, exist_ok=True)
    c = db_suelta()
    c.executescript(ESQUEMA)
    # si el servidor se reinició con videos a medio hacer, los marcamos con error
    c.execute("UPDATE videos SET estado='error', error='El servidor se reinició' "
              "WHERE estado IN ('en_cola','procesando')")
    c.commit()
    c.close()


# ---------------------------------------------------------------- seguridad
@app.before_request
def csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    if request.method == "POST":
        if not secrets.compare_digest(request.form.get("csrf", ""), session["csrf"]):
            abort(400)


@app.template_filter("fecha")
def filtro_fecha(ts):
    if not ts:
        return ""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    zona = ZoneInfo(os.environ.get("REELIA_ZONA", "America/Argentina/Buenos_Aires"))
    return datetime.fromtimestamp(ts, zona).strftime("%d/%m/%Y %H:%M")


@app.context_processor
def contexto():
    def lista_pistas():
        return db().execute("SELECT * FROM musica ORDER BY creado DESC").fetchall()
    return {"csrf": session.get("csrf", ""), "usuario": usuario_actual(),
            "estilos_musica": ESTILOS_MUSICA, "lista_pistas": lista_pistas,
            "voz_disponible": voz_disponible(), "voces_cuenta": voces_cuenta}


def usuario_actual():
    uid = session.get("uid")
    if not uid:
        return None
    if "usuario" not in g:
        g.usuario = db().execute("SELECT * FROM usuarios WHERE id=? AND activo=1",
                                 (uid,)).fetchone()
    return g.usuario


def login_requerido(f):
    @wraps(f)
    def envuelta(*a, **k):
        if not usuario_actual():
            session.pop("uid", None)
            return redirect(url_for("login", siguiente=request.path))
        return f(*a, **k)
    return envuelta


def admin_requerido(f):
    @wraps(f)
    @login_requerido
    def envuelta(*a, **k):
        if not usuario_actual()["admin"]:
            abort(403)
        return f(*a, **k)
    return envuelta


def demasiados_intentos(ip):
    c = db()
    c.execute("DELETE FROM intentos_login WHERE ts < ?", (time.time() - 900,))
    n = c.execute("SELECT COUNT(*) FROM intentos_login WHERE ip=?", (ip,)).fetchone()[0]
    c.commit()
    return n >= 8


@app.after_request
def cabeceras(r):
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    return r


@app.route("/favicon.ico")
def favicon():
    return send_file(os.path.join(BASE, "static", "marca", "favicon.ico"),
                     mimetype="image/vnd.microsoft.icon", max_age=86400)


# ------------------------------------------------------------------- acceso
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]
        if demasiados_intentos(ip):
            flash("Demasiados intentos. Probá de nuevo en 15 minutos.", "error")
            return render_template("login.html"), 429
        email = request.form.get("email", "").strip().lower()
        u = db().execute("SELECT * FROM usuarios WHERE email=? AND activo=1", (email,)).fetchone()
        if u and check_password_hash(u["hash"], request.form.get("clave", "")):
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            session["csrf"] = secrets.token_urlsafe(32)
            destino = request.args.get("siguiente", "")
            if not destino.startswith("/") or destino.startswith("//"):
                destino = url_for("panel")
            return redirect(destino)
        db().execute("INSERT INTO intentos_login VALUES (?,?)", (ip, time.time()))
        db().commit()
        flash("Email o contraseña incorrectos.", "error")
    return render_template("login.html")


@app.route("/salir", methods=["POST"])
def salir():
    session.clear()
    return redirect(url_for("login"))


@app.route("/cuenta", methods=["GET", "POST"])
@login_requerido
def cuenta():
    if request.method == "POST":
        u = usuario_actual()
        actual, nueva = request.form.get("actual", ""), request.form.get("nueva", "")
        if not check_password_hash(u["hash"], actual):
            flash("La contraseña actual no es correcta.", "error")
        elif len(nueva) < 8:
            flash("La nueva contraseña debe tener al menos 8 caracteres.", "error")
        else:
            db().execute("UPDATE usuarios SET hash=? WHERE id=?",
                         (generate_password_hash(nueva), u["id"]))
            db().commit()
            flash("Contraseña actualizada.", "ok")
            return redirect(url_for("panel"))
    return render_template("cuenta.html")


# ----------------------------------------------------------------- usuarios
@app.route("/usuarios", methods=["GET", "POST"])
@admin_requerido
def usuarios():
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "crear":
            email = request.form.get("email", "").strip().lower()
            clave = request.form.get("clave", "")
            if "@" not in email or len(clave) < 8:
                flash("Email válido y contraseña de al menos 8 caracteres.", "error")
            else:
                try:
                    db().execute("INSERT INTO usuarios (email,nombre,hash,admin,creado) "
                                 "VALUES (?,?,?,?,?)",
                                 (email, request.form.get("nombre", "").strip(),
                                  generate_password_hash(clave),
                                  1 if request.form.get("admin") else 0, time.time()))
                    db().commit()
                    flash(f"Usuario {email} creado.", "ok")
                except sqlite3.IntegrityError:
                    flash("Ya existe un usuario con ese email.", "error")
        elif accion in ("activar", "desactivar"):
            uid = int(request.form.get("id", 0))
            if uid == usuario_actual()["id"]:
                flash("No podés desactivar tu propio usuario.", "error")
            else:
                db().execute("UPDATE usuarios SET activo=? WHERE id=?",
                             (1 if accion == "activar" else 0, uid))
                db().commit()
        return redirect(url_for("usuarios"))
    lista = db().execute("SELECT * FROM usuarios ORDER BY creado DESC").fetchall()
    return render_template("usuarios.html", lista=lista)


# ------------------------------------------------------------------- videos
def carpeta_video(vid):
    return os.path.join(DATOS, "videos", vid)


def video_del_usuario(vid):
    v = db().execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    if not v or (v["usuario_id"] != usuario_actual()["id"] and not usuario_actual()["admin"]):
        abort(404)
    return v


@app.route("/")
@login_requerido
def panel():
    u = usuario_actual()
    consulta = ("SELECT v.*, u.nombre AS autor_nombre, u.email AS autor_email "
                "FROM videos v JOIN usuarios u ON u.id = v.usuario_id ")
    if not u["admin"]:
        vids = db().execute(consulta + "WHERE v.usuario_id=? ORDER BY v.creado DESC",
                            (u["id"],)).fetchall()
        return render_template("panel.html", videos=vids, vista="mios")
    # el administrador ve los videos de todos (o filtra por usuario)
    vista = request.args.get("ver", "todos")
    autores = db().execute("SELECT u.id, u.nombre, u.email, COUNT(v.id) AS cantidad "
                           "FROM usuarios u JOIN videos v ON v.usuario_id = u.id "
                           "GROUP BY u.id ORDER BY cantidad DESC").fetchall()
    if vista == "mios":
        vids = db().execute(consulta + "WHERE v.usuario_id=? ORDER BY v.creado DESC",
                            (u["id"],)).fetchall()
    elif vista.isdigit():
        vids = db().execute(consulta + "WHERE v.usuario_id=? ORDER BY v.creado DESC",
                            (int(vista),)).fetchall()
    else:
        vista = "todos"
        vids = db().execute(consulta + "ORDER BY v.creado DESC").fetchall()
    return render_template("panel.html", videos=vids, vista=vista, autores=autores)


def numero(valor):
    valor = (valor or "").strip().replace(".", "").replace(",", "")
    return int(valor) if valor.isdigit() else None


@app.route("/nuevo", methods=["GET", "POST"])
@login_requerido
def nuevo():
    if request.method == "GET":
        ultimo = db().execute("SELECT datos FROM videos WHERE usuario_id=? "
                              "ORDER BY creado DESC LIMIT 1",
                              (usuario_actual()["id"],)).fetchone()
        marca = {}
        if ultimo:  # recordamos los datos de la inmobiliaria del último video
            d = json.loads(ultimo["datos"])
            marca = {k: d.get(k) for k in ("inmobiliaria", "asesor", "whatsapp", "color_marca")}
            if (marca.get("color_marca") or "").upper() == "#C8742B":  # color viejo por defecto
                marca["color_marca"] = None
        modo = "videos" if request.args.get("modo") == "videos" else "fotos"
        return render_template("nuevo.html", marca=marca, ia=ia_disponible(), modo=modo,
                               logo_defecto=os.path.exists(LOGO_DEFECTO))

    f = request.form
    if f.get("modo") == "videos":
        return nuevo_desde_videos(f)
    fotos = [x for x in request.files.getlist("fotos") if x and x.filename]
    if not fotos:
        flash("Subí al menos una foto.", "error")
        return redirect(url_for("nuevo"))
    if len(fotos) > MAX_FOTOS:
        flash(f"Máximo {MAX_FOTOS} fotos por video.", "error")
        return redirect(url_for("nuevo"))

    vid = uuid.uuid4().hex[:12]
    carpeta = carpeta_video(vid)
    os.makedirs(os.path.join(carpeta, "fotos"))
    etiquetas = f.getlist("etiqueta")
    tomas = []
    for i, foto in enumerate(fotos):
        ext = os.path.splitext(secure_filename(foto.filename))[1].lower()
        if ext not in EXT_FOTOS:
            shutil.rmtree(carpeta, ignore_errors=True)
            flash("Formato no permitido. Usá JPG, PNG o WEBP.", "error")
            return redirect(url_for("nuevo"))
        nombre = f"{i:02d}{ext}"
        foto.save(os.path.join(carpeta, "fotos", nombre))
        etiqueta = etiquetas[i].strip()[:40] if i < len(etiquetas) else ""
        tomas.append({"foto": nombre, "etiqueta": None if i == 0 else (etiqueta or None)})

    datos = datos_del_formulario(f, carpeta)
    datos["tomas"] = tomas
    datos["ia"] = bool(f.get("ia")) and ia_disponible()
    return encolar(vid, carpeta, datos, f)


def datos_del_formulario(f, carpeta, logo_actual=None):
    """Datos de la propiedad y de la marca, comunes a los dos modos."""
    datos = {
        "operacion": f.get("operacion", "Venta"),
        "tipo": f.get("tipo", "").strip() or "propiedad",
        "ubicacion": f.get("ubicacion", "").strip(),
        "moneda": f.get("moneda", "USD"),
        "precio": numero(f.get("precio")),
        "ambientes": numero(f.get("ambientes")),
        "dormitorios": numero(f.get("dormitorios")),
        "banos": numero(f.get("banos")),
        "m2_totales": numero(f.get("m2")),
        "cochera": bool(f.get("cochera")),
        "inmobiliaria": f.get("inmobiliaria", "").strip(),
        "asesor": f.get("asesor", "").strip(),
        "whatsapp": f.get("whatsapp", "").strip(),
        "color_marca": f.get("color_marca", "#F40009"),
        "formato": "horizontal" if f.get("formato") == "horizontal" else "vertical",
        "ficha": bool(f.get("ficha")),
        "transicion": f.get("transicion") if f.get("transicion") in TRANSICIONES else "variadas",
        "voz": {"activa": bool(f.get("voz_activa")) and voz_disponible(),
                "id": f.get("voz_id", "").strip()[:64],
                "guion": " ".join(f.get("guion", "").split())[:1500]},
    }
    logo = request.files.get("logo")
    if logo and logo.filename:
        ext = os.path.splitext(secure_filename(logo.filename))[1].lower()
        if ext in {".png", ".jpg", ".jpeg", ".webp"}:
            logo.save(os.path.join(carpeta, "logo" + ext))
            datos["logo"] = os.path.join(carpeta, "logo" + ext)
    if "logo" not in datos and logo_actual and os.path.exists(logo_actual):
        datos["logo"] = logo_actual
    if "logo" not in datos and os.path.exists(LOGO_DEFECTO):
        datos["logo"] = LOGO_DEFECTO  # logo de la inmobiliaria por defecto
    return datos


def encolar(vid, carpeta, datos, f):
    with open(os.path.join(carpeta, "propiedad.json"), "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
    titulo = " · ".join(x for x in (datos["tipo"].capitalize(), datos["ubicacion"]) if x)
    estilo = estilo_musica(f)
    datos["musica"] = estilo
    with open(os.path.join(carpeta, "propiedad.json"), "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
    db().execute("INSERT INTO videos VALUES (?,?,?,?,?,?,?,?)",
                 (vid, usuario_actual()["id"], titulo or "Propiedad", "en_cola", None,
                  json.dumps(datos, ensure_ascii=False), time.time(), None))
    db().commit()
    trabajos.submit(renderizar, vid, estilo)
    return redirect(url_for("ver_video", vid=vid))


def estilo_musica(f):
    """'calido', 'ninguno', ... o 'pista:<id>' para un tema subido a la biblioteca."""
    estilo = f.get("musica", "calido")
    if estilo.startswith("pista:") and estilo[6:].isdigit():
        if db().execute("SELECT 1 FROM musica WHERE id=?", (int(estilo[6:]),)).fetchone():
            return estilo
        return "calido"
    return estilo if estilo in ESTILOS_MUSICA or estilo == "ninguno" else "calido"


def archivo_pista(estilo):
    if not (estilo or "").startswith("pista:"):
        return None
    c = db_suelta()
    fila = c.execute("SELECT archivo FROM musica WHERE id=?", (estilo[6:],)).fetchone()
    c.close()
    ruta = os.path.join(DATOS, "musica", fila["archivo"]) if fila else None
    return ruta if ruta and os.path.exists(ruta) else None


def nuevo_desde_videos(f):
    clips = [x for x in request.files.getlist("clips") if x and x.filename]
    if not clips:
        flash("Subí al menos un video.", "error")
        return redirect(url_for("nuevo", modo="videos"))
    if len(clips) > MAX_CLIPS:
        flash(f"Máximo {MAX_CLIPS} videos por edición.", "error")
        return redirect(url_for("nuevo", modo="videos"))
    vid = uuid.uuid4().hex[:12]
    carpeta = carpeta_video(vid)
    os.makedirs(os.path.join(carpeta, "clips"))
    nombres = []
    for i, clip in enumerate(clips):
        ext = os.path.splitext(secure_filename(clip.filename))[1].lower()
        if ext not in EXT_CLIPS:
            shutil.rmtree(carpeta, ignore_errors=True)
            flash("Formato no permitido. Usá MP4, MOV, M4V o WEBM.", "error")
            return redirect(url_for("nuevo", modo="videos"))
        nombre = f"{i:02d}{ext}"
        clip.save(os.path.join(carpeta, "clips", nombre))
        nombres.append(nombre)
    datos = datos_del_formulario(f, carpeta)
    objetivo = f.get("objetivo", "30")
    datos.update({
        "modo": "videos",
        "clips": nombres,
        "objetivo": int(objetivo) if objetivo in ("15", "30", "45", "60") else 30,
        "subtitulos": bool(f.get("subtitulos")),
        "ambiente": bool(f.get("ambiente")),
    })
    return encolar(vid, carpeta, datos, f)


def renderizar(vid, estilo):
    carpeta = carpeta_video(vid)
    c = db_suelta()
    c.execute("UPDATE videos SET estado='procesando' WHERE id=?", (vid,))
    c.commit()
    with open(os.path.join(carpeta, "propiedad.json"), encoding="utf-8") as fh:
        datos = json.load(fh)
    if datos.get("ia"):
        curar_con_ia(carpeta, datos)
    if datos.get("modo") == "videos":
        cmd = [sys.executable, MOTOR_VIDEOS,
               "--clips", *[os.path.join(carpeta, "clips", n) for n in datos["clips"]],
               "--objetivo", str(datos.get("objetivo", 30)),
               "--informe", os.path.join(carpeta, "informe.json")]
        if not datos.get("subtitulos", True):
            cmd.append("--sin-subtitulos")
        if datos.get("ambiente"):
            cmd.append("--con-ambiente")
        limite = 3600
    else:
        cmd = [sys.executable, MOTOR, "--fotos", os.path.join(carpeta, "fotos"),
               "--segundos-por-foto", "3.4"]
        limite = 900
        voz = preparar_voz(carpeta, datos)
        if voz:
            cmd += ["--voz", voz]
    nuevo = os.path.join(carpeta, "video_nuevo.mp4")
    cmd += ["--formato", datos.get("formato", "vertical"),
            "--transicion", datos.get("transicion", "variadas")]
    pista = archivo_pista(estilo)
    if pista:
        cmd += ["--musica", pista, "--estilo-musica", "ninguno"]
    else:
        cmd += ["--estilo-musica", estilo if estilo in ESTILOS_MUSICA or estilo == "ninguno"
                else "calido"]
    cmd += ["--datos", os.path.join(carpeta, "propiedad.json"), "--salida", nuevo]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=limite)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-1500:] or r.stdout[-1500:])
        os.replace(nuevo, os.path.join(carpeta, "video.mp4"))  # el anterior queda hasta acá
        c.execute("UPDATE videos SET estado='listo', terminado=? WHERE id=?", (time.time(), vid))
    except Exception as e:  # noqa: BLE001 — guardamos el error para mostrarlo
        c.execute("UPDATE videos SET estado='error', error=? WHERE id=?", (str(e)[-1500:], vid))
    c.commit()
    c.close()


def preparar_voz(carpeta, datos):
    """Genera la voz en off con ElevenLabs (o reutiliza la anterior si no cambió nada).
    Si falla, el video se arma igual sin voz y queda un aviso."""
    aviso = os.path.join(carpeta, "aviso_voz.txt")
    if os.path.exists(aviso):
        os.remove(aviso)
    voz = datos.get("voz") or {}
    if not voz.get("activa"):
        return None
    import hashlib
    sys.path.insert(0, os.path.dirname(MOTOR))
    import reelia_fotos
    import reelia_voz
    texto = voz.get("guion") or reelia_fotos.generar_guion(datos)
    voice_id = voz.get("id")
    if not voice_id:
        voces, _ = voces_cuenta()
        voice_id = voces[0]["id"] if voces else ""
    huella = hashlib.sha256(f"{voice_id}|{reelia_voz.MODELO}|{texto}".encode()).hexdigest()
    ruta, info = os.path.join(carpeta, "voz.mp3"), os.path.join(carpeta, "voz.json")
    try:
        if os.path.exists(info) and os.path.exists(ruta):
            with open(info, encoding="utf-8") as fh:
                if json.load(fh).get("huella") == huella:
                    return ruta  # mismo texto y misma voz: no gastamos créditos de nuevo
        if not voice_id:
            raise reelia_voz.ErrorVoz("No hay voces en la cuenta de ElevenLabs.")
        reelia_voz.sintetizar(texto, voice_id, ruta)
        with open(info, "w", encoding="utf-8") as fh:
            json.dump({"huella": huella, "texto": texto, "voz": voice_id}, fh, ensure_ascii=False)
        return ruta
    except Exception as e:  # noqa: BLE001
        app.logger.warning("Voz en off falló: %s", e)
        with open(aviso, "w", encoding="utf-8") as fh:
            fh.write(f"No se pudo generar la voz en off: {e} El video se armó sin voz.")
        return None


@app.route("/voz/guion", methods=["POST"])
@login_requerido
def voz_guion():
    """Arma el guion sugerido con lo que está cargado en el formulario."""
    sys.path.insert(0, os.path.dirname(MOTOR))
    import reelia_fotos
    f = request.form
    d = {"operacion": f.get("operacion", "Venta"), "tipo": f.get("tipo", "").strip() or "propiedad",
         "ubicacion": f.get("ubicacion", "").strip(), "moneda": f.get("moneda", "USD"),
         "precio": numero(f.get("precio")), "ambientes": numero(f.get("ambientes")),
         "dormitorios": numero(f.get("dormitorios")), "banos": numero(f.get("banos")),
         "m2_totales": numero(f.get("m2")), "cochera": bool(f.get("cochera"))}
    return {"guion": reelia_fotos.generar_guion(d)}


def curar_con_ia(carpeta, datos):
    """Ordena las fotos y escribe los textos con IA. Si falla, sigue con el orden del usuario."""
    try:
        import reelia_curador
        nombres = [t["foto"] for t in datos["tomas"]]
        cur = reelia_curador.curar([os.path.join(carpeta, "fotos", n) for n in nombres],
                                   datos.get("tipo"))
        usuario = {t["foto"]: t["etiqueta"] for t in datos["tomas"] if t.get("etiqueta")}
        datos["tomas"] = reelia_curador.aplicar_a_tomas(cur, nombres, usuario)
        cur["archivos"] = nombres
        with open(os.path.join(carpeta, "curacion.json"), "w", encoding="utf-8") as fh:
            json.dump(cur, fh, ensure_ascii=False, indent=2)
        with open(os.path.join(carpeta, "propiedad.json"), "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        app.logger.warning("Curador IA falló: %s", e)
        with open(os.path.join(carpeta, "aviso_ia.txt"), "w", encoding="utf-8") as fh:
            fh.write("La IA no pudo ordenar las fotos; se usó el orden que subiste.")


def leer_curacion(vid):
    carpeta = carpeta_video(vid)
    ruta = os.path.join(carpeta, "curacion.json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as fh:
            cur = json.load(fh)
        fotos = cur["fotos"]
        orden = [dict(fotos[k - 1], archivo=cur["archivos"][k - 1]) for k in cur["orden"]]
        descartadas = [dict(f, archivo=cur["archivos"][f["numero"] - 1])
                       for f in fotos if f["descartar"]]
        return {"orden": orden, "descartadas": descartadas}
    aviso = os.path.join(carpeta, "aviso_ia.txt")
    if os.path.exists(aviso):
        with open(aviso, encoding="utf-8") as fh:
            return {"aviso": fh.read()}
    return None


@app.route("/video/<vid>/foto/<nombre>")
@login_requerido
def foto_video(vid, nombre):
    v = video_del_usuario(vid)
    ruta = os.path.join(carpeta_video(v["id"]), "fotos", secure_filename(nombre))
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta)


@app.route("/video/<vid>")
@login_requerido
def ver_video(vid):
    v = video_del_usuario(vid)
    informe = None
    ruta = os.path.join(carpeta_video(v["id"]), "informe.json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as fh:
            informe = json.load(fh)
    aviso_voz = None
    ruta_aviso = os.path.join(carpeta_video(v["id"]), "aviso_voz.txt")
    if os.path.exists(ruta_aviso):
        with open(ruta_aviso, encoding="utf-8") as fh:
            aviso_voz = fh.read()
    autor = db().execute("SELECT id, nombre, email FROM usuarios WHERE id=?",
                         (v["usuario_id"],)).fetchone()
    return render_template("video.html", v=v, curacion=leer_curacion(v["id"]), informe=informe,
                           autor=autor, aviso_voz=aviso_voz)


@app.route("/video/<vid>/archivo")
@login_requerido
def archivo_video(vid):
    v = video_del_usuario(vid)
    ruta = os.path.join(carpeta_video(v["id"]), "video.mp4")
    if v["estado"] != "listo" or not os.path.exists(ruta):
        abort(404)
    descargar = request.args.get("descargar") == "1"
    return send_file(ruta, mimetype="video/mp4", as_attachment=descargar,
                     download_name=f"videolabs-{v['id']}.mp4", conditional=True)


@app.route("/video/<vid>/clip/<nombre>")
@login_requerido
def clip_video(vid, nombre):
    v = video_del_usuario(vid)
    ruta = os.path.join(carpeta_video(v["id"]), "clips", secure_filename(nombre))
    if not os.path.exists(ruta):
        abort(404)
    return send_file(ruta, conditional=True)


@app.route("/video/<vid>/editar", methods=["GET", "POST"])
@login_requerido
def editar_video(vid):
    v = video_del_usuario(vid)
    if v["estado"] in ("en_cola", "procesando"):
        flash("Esperá a que termine de procesarse para editarlo.", "error")
        return redirect(url_for("ver_video", vid=vid))
    carpeta = carpeta_video(v["id"])
    with open(os.path.join(carpeta, "propiedad.json"), encoding="utf-8") as fh:
        anterior = json.load(fh)
    modo = anterior.get("modo", "fotos")

    if request.method == "GET":
        sin_usar = []
        if modo != "videos":
            usadas = {t["foto"] for t in anterior.get("tomas", [])}
            sin_usar = sorted(n for n in os.listdir(os.path.join(carpeta, "fotos"))
                              if n not in usadas and os.path.splitext(n)[1].lower() in EXT_FOTOS)
        return render_template("editar.html", v=v, d=anterior, modo=modo, ia=ia_disponible(),
                               sin_usar=sin_usar, logo_defecto=os.path.exists(LOGO_DEFECTO),
                               logo_propio=anterior.get("logo") not in (None, LOGO_DEFECTO))

    f = request.form
    datos = datos_del_formulario(f, carpeta, logo_actual=anterior.get("logo"))
    if modo == "videos":
        existentes = set(anterior.get("clips", []))
        orden = [n for n in f.getlist("orden") if n in existentes]
        if not orden:
            flash("Dejá al menos un video.", "error")
            return redirect(url_for("editar_video", vid=vid))
        objetivo = f.get("objetivo", "30")
        datos.update({"modo": "videos", "clips": orden,
                      "objetivo": int(objetivo) if objetivo in ("15", "30", "45", "60") else 30,
                      "subtitulos": bool(f.get("subtitulos")), "ambiente": bool(f.get("ambiente"))})
    else:
        existentes = {t["foto"] for t in anterior.get("tomas", [])}
        existentes |= set(os.listdir(os.path.join(carpeta, "fotos")))
        nuevas = [x for x in request.files.getlist("fotos_nuevas") if x and x.filename]
        nombres_nuevos = []
        base_n = len(os.listdir(os.path.join(carpeta, "fotos")))
        for k, foto in enumerate(nuevas):
            ext = os.path.splitext(secure_filename(foto.filename))[1].lower()
            if ext not in EXT_FOTOS:
                flash("Formato no permitido. Usá JPG, PNG o WEBP.", "error")
                return redirect(url_for("editar_video", vid=vid))
            nombre = f"{base_n + k:02d}{ext}"
            foto.save(os.path.join(carpeta, "fotos", nombre))
            nombres_nuevos.append(nombre)
        tomas = []
        for item, etiqueta in zip(f.getlist("orden"), f.getlist("etiqueta")):
            if item.startswith("nueva:"):
                k = int(item.split(":", 1)[1]) if item.split(":", 1)[1].isdigit() else -1
                nombre = nombres_nuevos[k] if 0 <= k < len(nombres_nuevos) else None
            else:
                nombre = item if item in existentes else None
            if nombre:
                tomas.append({"foto": nombre,
                              "etiqueta": None if not tomas else (etiqueta.strip()[:40] or None)})
        if not tomas:
            flash("Dejá al menos una foto.", "error")
            return redirect(url_for("editar_video", vid=vid))
        if len(tomas) > MAX_FOTOS:
            flash(f"Máximo {MAX_FOTOS} fotos por video.", "error")
            return redirect(url_for("editar_video", vid=vid))
        datos["tomas"] = tomas
        datos["ia"] = bool(f.get("ia")) and ia_disponible()
    estilo = estilo_musica(f)
    datos["musica"] = estilo
    # lo que mostraba la IA o el informe anterior ya no corresponde
    for viejo in ("curacion.json", "aviso_ia.txt"):
        ruta = os.path.join(carpeta, viejo)
        if os.path.exists(ruta) and not datos.get("ia"):
            os.remove(ruta)
    with open(os.path.join(carpeta, "propiedad.json"), "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)
    titulo = " · ".join(x for x in (datos["tipo"].capitalize(), datos["ubicacion"]) if x)
    db().execute("UPDATE videos SET titulo=?, estado='en_cola', error=NULL, datos=?, "
                 "terminado=NULL WHERE id=?",
                 (titulo or "Propiedad", json.dumps(datos, ensure_ascii=False), v["id"]))
    db().commit()
    trabajos.submit(renderizar, v["id"], estilo)
    flash("Cambios guardados. Estamos volviendo a armar el video.", "ok")
    return redirect(url_for("ver_video", vid=vid))


@app.route("/video/<vid>/borrar", methods=["POST"])
@login_requerido
def borrar_video(vid):
    v = video_del_usuario(vid)
    if v["estado"] in ("en_cola", "procesando"):
        flash("Esperá a que termine de procesarse para borrarlo.", "error")
        return redirect(url_for("ver_video", vid=vid))
    shutil.rmtree(carpeta_video(v["id"]), ignore_errors=True)
    db().execute("DELETE FROM videos WHERE id=?", (v["id"],))
    db().commit()
    flash("Video borrado.", "ok")
    return redirect(url_for("panel"))


@app.errorhandler(413)
def muy_grande(_):
    flash("Los archivos pesan demasiado (máximo 1 GB en total).", "error")
    return redirect(url_for("nuevo"))


# ------------------------------------------------------------------ música
def duracion_audio(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", ruta],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def nombre_desde_archivo(nombre_archivo):
    """'kornevmusic-upbeat-happy-corporate-487426.mp3' -> 'Upbeat Happy Corporate (kornevmusic)'."""
    import re
    base = os.path.splitext(os.path.basename(nombre_archivo))[0]
    base = re.sub(r"^[0-9a-f]{8}-", "", base)          # prefijo que agregan algunos sistemas
    base = re.sub(r"[-_ ]?\d{4,}$", "", base)          # número de Pixabay al final
    partes = [p for p in re.split(r"[-_ ]+", base) if p]
    if len(partes) >= 2:
        autor, titulo = partes[0], partes[1:]
        # "corporate-corporate-music" -> sin palabras repetidas seguidas
        limpio = [w for i, w in enumerate(titulo) if i == 0 or w.lower() != titulo[i - 1].lower()]
        return (" ".join(w.capitalize() for w in limpio) + f" ({autor})")[:80]
    return (base.replace("-", " ").strip().capitalize() or "Tema")[:80]


@app.route("/musica", methods=["GET", "POST"])
@login_requerido
def musica():
    if request.method == "POST":
        if not usuario_actual()["admin"]:
            abort(403)
        accion = request.form.get("accion")
        if accion == "subir":
            archivos = [a for a in request.files.getlist("archivo") if a and a.filename]
            if not archivos:
                flash("Elegí al menos un archivo de audio.", "error")
                return redirect(url_for("musica"))
            carpeta = os.path.join(DATOS, "musica")
            os.makedirs(carpeta, exist_ok=True)
            nombre_form = request.form.get("nombre", "").strip()[:80]
            animo = request.form.get("animo", "").strip()[:40]
            subidos, rechazados = [], []
            for archivo in archivos:
                ext = os.path.splitext(secure_filename(archivo.filename))[1].lower()
                if ext not in EXT_MUSICA:
                    rechazados.append(archivo.filename)
                    continue
                destino = uuid.uuid4().hex[:12] + ext
                ruta = os.path.join(carpeta, destino)
                archivo.save(ruta)
                dur = duracion_audio(ruta)
                if not dur:
                    os.remove(ruta)
                    rechazados.append(archivo.filename)
                    continue
                # con un solo archivo se respeta el nombre escrito; si no, se arma del archivo
                nombre = (nombre_form if len(archivos) == 1 and nombre_form
                          else nombre_desde_archivo(archivo.filename))
                base, n = nombre, 2  # sin nombres repetidos en la biblioteca
                while db().execute("SELECT 1 FROM musica WHERE nombre=?", (nombre,)).fetchone():
                    nombre, n = f"{base} {n}", n + 1
                db().execute("INSERT INTO musica (nombre, animo, archivo, duracion, subido_por, "
                             "creado) VALUES (?,?,?,?,?,?)",
                             (nombre, animo, destino, dur, usuario_actual()["id"], time.time()))
                subidos.append(nombre)
            db().commit()
            if subidos:
                flash(f"{len(subidos)} tema{'s' if len(subidos) != 1 else ''} agregado"
                      f"{'s' if len(subidos) != 1 else ''}: " + ", ".join(subidos), "ok")
            if rechazados:
                flash("No se pudieron leer: " + ", ".join(rechazados), "error")
        elif accion == "renombrar":
            nombre = request.form.get("nombre", "").strip()[:80]
            animo = request.form.get("animo", "").strip()[:40]
            if nombre:
                db().execute("UPDATE musica SET nombre=?, animo=? WHERE id=?",
                             (nombre, animo, request.form.get("id", "0")))
                db().commit()
                flash("Tema actualizado.", "ok")
        elif accion == "borrar":
            fila = db().execute("SELECT * FROM musica WHERE id=?",
                                (request.form.get("id", "0"),)).fetchone()
            if fila:
                try:
                    os.remove(os.path.join(DATOS, "musica", fila["archivo"]))
                except OSError:
                    pass
                db().execute("DELETE FROM musica WHERE id=?", (fila["id"],))
                db().commit()
                flash(f"Tema “{fila['nombre']}” eliminado.", "ok")
        return redirect(url_for("musica"))
    return render_template("musica.html")


@app.route("/musica/pista/<int:pid>")
@login_requerido
def musica_pista(pid):
    fila = db().execute("SELECT archivo FROM musica WHERE id=?", (pid,)).fetchone()
    if not fila:
        abort(404)
    return send_file(os.path.join(DATOS, "musica", fila["archivo"]), conditional=True)


@app.route("/musica/muestra/<estilo>.mp3")
@login_requerido
def musica_muestra(estilo):
    """Muestra de 20 s de cada estilo compuesto; se genera una vez y queda guardada."""
    if estilo not in ESTILOS_MUSICA:
        abort(404)
    carpeta = os.path.join(DATOS, "muestras")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, f"{estilo}.mp3")
    if not os.path.exists(ruta):
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(MOTOR), "reelia_musica.py"),
                            "--estilo", estilo, "--segundos", "20", "--salida", ruta],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            abort(500)
    return send_file(ruta, mimetype="audio/mpeg", conditional=True, max_age=86400)


# ------------------------------------------------------------------ consola
@app.cli.command("crear-usuario")
@click.argument("email")
@click.option("--nombre", default="")
@click.option("--admin", is_flag=True)
@click.password_option("--clave")
def crear_usuario(email, nombre, admin, clave):
    """Crea un usuario (pide la contraseña)."""
    iniciar_db()
    c = db_suelta()
    c.execute("INSERT INTO usuarios (email,nombre,hash,admin,creado) VALUES (?,?,?,?,?)",
              (email.strip().lower(), nombre, generate_password_hash(clave),
               1 if admin else 0, time.time()))
    c.commit()
    click.echo(f"Usuario {email} creado{' (admin)' if admin else ''}.")


iniciar_db()
