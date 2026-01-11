# 🎵 PyMusic

> Un reproductor de música TUI (Terminal User Interface) moderno, inspirado en `cmus`, diseñado para transmitir tu biblioteca musical vía **WebDAV** o reproducirla localmente.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![Textual](https://img.shields.io/badge/Textual-TUI-green?style=for-the-badge)
![MPV](https://img.shields.io/badge/MPV-Engine-purple?style=for-the-badge)

## 📖 Introducción

**PyMusic** es un cliente de música ligero y potente escrito en Python. Utiliza la librería `Textual` para ofrecer una interfaz rica en la terminal y `mpv` como motor de audio para soportar casi cualquier formato (MP3, FLAC, OGG, Opus, etc.).

Su característica principal es la **hibridez**: puede listar archivos remotamente desde un servidor WebDAV (como Nextcloud, Apache, Rclone) y reproducirlos vía streaming, o mapearlos a una ruta local para reproducción instantánea sin latencia.

## ✨ Características Clave

*   **🌐 Soporte WebDAV Nativo**: Navega y reproduce directamente desde tu nube privada.
*   **📂 Mapeo Local Inteligente**: Define `LOCAL_PATH` para usar archivos locales si coinciden con la estructura del servidor.
*   **📋 Gestión de Listas**: Soporte para archivos `.m3u` (lectura y escritura).
*   **⭐ Favoritos y Cola**: Sistema de favoritos integrado y cola de reproducción persistente (`en_cola.m3u`).
*   **📱 Diseño Responsivo**: La interfaz se adapta automáticamente; vista dividida en PC, vista vertical en móviles (Termux).
*   **🚀 Motor MPV**: Soporte robusto de codecs, control de volumen y búsqueda (seek).

---

## 🛠️ Instalación

PyMusic requiere **Python 3** y la librería compartida de **MPV** (`libmpv`) en el sistema.

### 1. Instalar Dependencias del Sistema

<details>
<summary>🐧 <strong>Arch Linux / Manjaro</strong></summary>

```bash
sudo pacman -S mpv python-pip git
```
</details>

<details>
<summary>🟠 <strong>Ubuntu / Debian</strong></summary>

```bash
sudo apt update
sudo apt install libmpv1 python3-pip git
```
</details>

<details>
<summary>📱 <strong>Android (Termux)</strong></summary>

```bash
pkg update
pkg install mpv python git
```
</details>

### 2. Clonar el Repositorio e Instalar Librerías Python

```bash
git clone https://github.com/uGeek/pymusic.git
cd pymusic

# Instalar dependencias del proyecto
pip install textual python-mpv requests
```

---

## ⚙️ Configuración

Al ejecutar `pymusic.py` por primera vez, se generará automáticamente un archivo `pymusic.conf`. Debes editarlo con tus credenciales.

```ini
[Servidor]
# URL de tu servidor WebDAV (asegúrate de incluir la barra final)
WEBDAV_SERVER = http://192.168.1.100/musica/

# Credenciales (dejar vacío si es acceso público)
USER = tu_usuario
PASS = tu_contraseña

# Directorio raíz en el servidor donde empieza la música
ROOT_PATH = /musica/

# Directorio donde se guardarán las listas de reproducción (.m3u)
PLAYLISTS_DIR = /musica/listas/

# (Opcional) Ruta local. Si el archivo existe aquí, se reproduce localmente en lugar de streaming.
LOCAL_PATH = /home/usuario/Music/
```

> **Nota:** `LOCAL_PATH` es ideal si tienes la biblioteca sincronizada (por ejemplo con Syncthing). PyMusic navegará usando la rapidez de WebDAV pero reproducirá el archivo local ahorrando ancho de banda.

---

## 🎹 Uso y Atajos de Teclado (Keybindings)

La navegación está diseñada para ser rápida y eficiente, similar a `vim` o `cmus`.

### Navegación y Listas

| Tecla | Acción | Descripción |
| :--- | :--- | :--- |
| `Enter` | **Reproducir / Expandir** | Reproduce canción o abre carpeta/lista. |
| `Tab` | **Cambiar Panel** | Alterna entre el árbol de carpetas y la lista de reproducción. |
| `L` | **Listas Usuario** | Carga listas `.m3u` del directorio de usuario (`Shift+l`). |
| `Ctrl+l` | **Listas Raíz** | Carga listas `.m3u` de la raíz del servidor. |
| `m` | **Guardar en Lista** | Añade la canción seleccionada a una lista `.m3u` existente o nueva. |

### Reproducción

| Tecla | Acción | Descripción |
| :--- | :--- | :--- |
| `x` / `Espacio` | **Play / Pause** | Pausa o reanuda la reproducción. |
| `z` | **Anterior** | Reproduce la canción anterior. |
| `b` | **Siguiente** | Reproduce la canción siguiente. |
| `v` | **Stop** | Detiene la reproducción completamente. |
| `+` / `-` | **Volumen** | Sube o baja el volumen. |
| `←` / `→` | **Seek** | Retrocede o avanza 5 segundos. |

### Cola y Favoritos

| Tecla | Acción | Descripción |
| :--- | :--- | :--- |
| `c` | **Añadir a Cola** | Añade canción a la cola persistente (`en_cola.m3u`). |
| `Shift+c` | **Limpiar Cola** | Vacía el archivo de cola. |
| `Alt+c` | **Limpiar Vista** | Limpia la lista de reproducción visual actual. |
| `f` | **Favorito** | Añade canción o álbum a Favoritos. |
| `F` | **Ver Álbumes Fav.** | Muestra lista de álbumes favoritos (`Shift+f`). |

### Comandos de Consola (`:`)

Pulsa `:` para entrar en modo comando:
*   `:save <nombre>`: Guarda la lista actual como `.m3u`.
*   `:load <nombre>`: Carga una lista `.m3u`.
*   `:clear`: Limpia la lista actual.
*   `:q`: Salir.

---

## 📂 Estructura del Proyecto

El Agente de IA ha analizado el código y esta es la estructura lógica:

```graphql
pymusic/
├── pymusic.py         # Punto de entrada principal (Lógica de UI, WebDAV y Audio)
├── pymusic.conf       # Archivo de configuración (Generado automáticamente)
└── README.md          # Documentación
```

### Análisis de Componentes

1.  **`CmusApp` (UI)**: Clase principal que hereda de `textual.App`. Maneja los eventos, el layout responsivo y los atajos de teclado.
2.  **`WebDAVClient`**: Capa de abstracción para `requests`. Maneja la autenticación, el parseo de XML (PROPFIND) y la manipulación de archivos `.m3u` remotos.
3.  **`AudioPlayer`**: Wrapper sobre `python-mpv`. Controla el ciclo de vida de la reproducción y el estado (tiempo, volumen, metadatos).
4.  **`ConfigManager`**: Gestor de configuración robusto que asegura que siempre existan valores por defecto.

---

## 🤝 Contribución

¡Las contribuciones son bienvenidas!

1.  Haz un Fork del proyecto.
2.  Crea una rama para tu funcionalidad (`git checkout -b feature/AmazingFeature`).
3.  Haz Commit de tus cambios (`git commit -m 'Add some AmazingFeature'`).
4.  Haz Push a la rama (`git push origin feature/AmazingFeature`).
5.  Abre un Pull Request.

---

## 📄 Licencia

Distribuido bajo la licencia MIT. Ver `LICENSE` para más información.

---

<div align="center">
  <sub>Desarrollado con ❤️ por uGeek y potenciado por IA</sub>
</div>

