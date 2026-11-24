# Instalar Reelia en el VPS de Hostinger (KVM 1, AlmaLinux 9 + nginx)

Resultado: `https://videolabs.luciolopezfleming.com` con login. Solo entran usuarios creados por un administrador.

> El KVM 1 tiene 1 CPU y 4 GB de RAM: alcanza para arrancar. Cada video tarda ~1 minuto y se procesan de a uno (los demás quedan "En cola").

## 1. Apuntar el subdominio
hPanel → Dominios → `luciolopezfleming.com` → DNS: registro **A** `videolabs` → `2.25.255.207`.

## 2. Entrar por SSH como root
hPanel → VPS → Administrar → **Acceso SSH**. Desde tu compu: `ssh root@2.25.255.207`

## 3. Instalar ffmpeg y Python (AlmaLinux)
```bash
dnf install -y epel-release
dnf install -y --nogpgcheck https://mirrors.rpmfusion.org/free/el/rpmfusion-free-release-$(rpm -E %rhel).noarch.rpm
dnf install -y ffmpeg python3.11 python3.11-pip git google-noto-sans-fonts
```
(Inter es la tipografía del video: `dnf install -y rsms-inter-fonts` si está; si no, copiá los .otf a `/usr/share/fonts/inter/`.)

## 4. Descargar Reelia
```bash
useradd -r -m -d /opt/reelia reelia
git clone -b claude/video-editor-agents-platform-p3108d https://github.com/joaquinmesones/Prep-Course /opt/reelia/src
ln -s /opt/reelia/src/reelia /opt/reelia/reelia
python3.11 -m venv /opt/reelia/.venv
/opt/reelia/.venv/bin/pip install -r /opt/reelia/reelia/web/requirements.txt
chown -R reelia:reelia /opt/reelia
```
(Si el repositorio es privado, usá un token de GitHub de solo lectura en la URL o subí la carpeta `reelia/` por SFTP.)

## 5. Configuración y servicio
```bash
cat > /etc/reelia.env <<EOT
REELIA_SECRET_KEY=$(openssl rand -hex 32)
REELIA_DATOS=/opt/reelia/datos
REELIA_HTTPS=1
EOT
chmod 600 /etc/reelia.env
cp /opt/reelia/reelia/web/despliegue/reelia.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now reelia
curl -I http://127.0.0.1:8765/login     # debe responder 200
```

## 6. Conectar el subdominio (nginx + HTTPS)
En este VPS la web la atiende **nginx** (un archivo por sitio en `/etc/nginx/conf.d/`), no el Apache de cPanel.
```bash
cp /opt/reelia/reelia/web/despliegue/nginx-videolabs.conf /etc/nginx/conf.d/videolabs.conf
nginx -t && systemctl reload nginx
certbot --nginx -d videolabs.luciolopezfleming.com --redirect
```
`nginx -t` revisa la configuración antes de recargar, así no se cae ningún otro sitio.

## 7. Crear el primer administrador
```bash
cd /opt/reelia/reelia/web
sudo -u reelia REELIA_DATOS=/opt/reelia/datos /opt/reelia/.venv/bin/flask --app app crear-usuario TU@EMAIL --nombre "Tu nombre" --admin
```
Te pide la contraseña. Después entrás a `https://videolabs.luciolopezfleming.com` y creás el resto de los usuarios desde **Usuarios**.

## 8. Activar la IA (ordenar fotos y escribir textos)
1. Creá una clave en https://console.anthropic.com → **API Keys** (necesita saldo; cada video usa unos USD 0,05–0,10).
2. En la Consola web del VPS (te pide pegar la clave; no se muestra):
```bash
read -s -p "Clave de Anthropic: " K && echo && sed -i '/^ANTHROPIC_API_KEY=/d' /etc/reelia.env && echo "ANTHROPIC_API_KEY=$K" >> /etc/reelia.env && unset K && systemctl restart reelia && echo "== IA ACTIVADA =="
```
Sin clave, la plataforma funciona igual y la opción de IA no aparece.

## Actualizar a una versión nueva
```bash
cd /opt/reelia/src && sudo -u reelia git pull && /opt/reelia/.venv/bin/pip install -q -r /opt/reelia/reelia/web/requirements.txt && systemctl restart reelia
```

## Copias de seguridad
Todo (usuarios, fotos y videos) vive en `/opt/reelia/datos`. Respaldá esa carpeta.
