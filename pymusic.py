import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import configparser
import threading
import time
import shutil
from datetime import datetime

import requests

# --- DEPENDENCIAS DE AUDIO (MPV) ---
try:
    import mpv
    HAS_MPV = True
except ImportError:
    HAS_MPV = False
    print("ERROR CRÍTICO: Instala python-mpv (pip install python-mpv).")
    print("NOTA: Necesitas tener la librería libmpv instalada en tu sistema.")
    sys.exit(1)
except OSError:
    print("ERROR CRÍTICO: No se encontró la librería compartida de MPV (libmpv).")
    print("En Linux: sudo apt install libmpv1")
    print("En Windows: Asegúrate de tener mpv-1.dll en el PATH o junto al script.")
    sys.exit(1)

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Vertical, Horizontal
    from textual.screen import ModalScreen
    from textual.widgets import (
        Header, Footer, DataTable, Label, Button, Tree, Static, Input, OptionList
    )
    from textual import on, work, events
    from textual.binding import Binding
    from textual.widgets.tree import TreeNode
except ImportError:
    print("ERROR CRÍTICO: Instala textual (pip install textual)")
    sys.exit(1)

# --- CONFIGURACIÓN ---
class ConfigManager:
    def __init__(self, config_path: str = "pymusic.conf"):
        self.config = configparser.ConfigParser()
        
        self.template_data = {
            'WEBDAV_SERVER': 'http://TU_IP_AQUI/musica/',
            'USER': '',
            'PASS': '',
            'ROOT_PATH': '/musica/',
            'PLAYLISTS_DIR': '/musica/listas/',
            'LOCAL_PATH': '' 
        }

        if not os.path.exists(config_path):
            try:
                self.config['Servidor'] = self.template_data
                with open(config_path, 'w', encoding='utf-8') as f:
                    self.config.write(f)
            except: pass
        else:
            try: self.config.read(config_path, encoding='utf-8')
            except: pass
        
        self.user = self.get('USER')
        raw_playlists_dir = self.get('PLAYLISTS_DIR')
        self.local_path = self.get('LOCAL_PATH')
        
        if not raw_playlists_dir: raw_playlists_dir = '/' 
        if not raw_playlists_dir.endswith('/'): raw_playlists_dir += '/'
        if self.local_path and not self.local_path.endswith('/'):
            self.local_path += '/'

        if self.user:
            self.user_playlists_path = f"{raw_playlists_dir}{self.user}/"
        else:
            self.user_playlists_path = raw_playlists_dir

        self.history_file = f"{self.user_playlists_path}Últimas Reproducciones.m3u"
        self.favorites_file = f"{self.user_playlists_path}Favoritos.m3u"
        self.fav_albums_file = f"{self.user_playlists_path}albums.txt"
        
        # Archivos de cola
        self.queue_file = f"{self.user_playlists_path}en_cola.m3u"
        self.played_queue_file = f"{self.user_playlists_path}reproducida_en_cola.m3u"

    def get(self, key): 
        return self.config.get('Servidor', key, fallback="")

# --- CLIENTE WEBDAV ---
class WebDAVClient:
    def __init__(self, config: ConfigManager):
        raw_url = config.get('WEBDAV_SERVER')
        if not raw_url or "TU_IP_AQUI" in raw_url:
            print("❌ ERROR: Configura la URL en 'pymusic.conf'")
            sys.exit(1)

        self.base_url = raw_url.rstrip('/')
        self.user = config.get('USER')
        self.password = config.get('PASS')
        self.auth = (self.user, self.password) if self.user else None
        self.session = requests.Session()
        self.session.auth = self.auth
        self.history_file = config.history_file
        self.favorites_file = config.favorites_file
        self.fav_albums_file = config.fav_albums_file
        
        parsed = urllib.parse.urlparse(self.base_url)
        self.server_root = f"{parsed.scheme}://{parsed.netloc}" 

    def get_full_url(self, path):
        decoded_path = urllib.parse.unquote(path)
        clean_path = decoded_path if decoded_path.startswith('/') else '/' + decoded_path
        encoded_path = urllib.parse.quote(clean_path, safe='/')
        url = f"{self.server_root}{encoded_path}"
        return url

    def get_stream_url(self, path):
        url = self.get_full_url(path)
        if self.user and self.password:
            try:
                scheme, rest = url.split('://', 1)
                safe_user = urllib.parse.quote(self.user)
                safe_pass = urllib.parse.quote(self.password)
                return f"{scheme}://{safe_user}:{safe_pass}@{rest}"
            except: return url
        return url

    def list_directory(self, path):
        url = self.get_full_url(path)
        headers = {'Depth': '1'}
        try:
            r = self.session.request('PROPFIND', url, headers=headers, timeout=10)
            if r.status_code == 207: return self._parse_xml(r.content, path)
            return []
        except: return []

    def _parse_xml(self, content, current_path):
        items = []
        try:
            root = ET.fromstring(content)
            ns_url = root.tag.split('}')[0].strip('{') if '}' in root.tag else ''
            ns = {'d': ns_url} if ns_url else {}
            decoded_curr = urllib.parse.unquote(current_path).rstrip('/')

            for response in root.findall('.//d:response' if ns_url else './/response', ns):
                href_tag = response.find('.//d:href', ns) if ns_url else response.find('.//href')
                if href_tag is None: continue
                raw_href = href_tag.text
                href = urllib.parse.unquote(raw_href)
                clean_href = href.rstrip('/')
                name = clean_href.split('/')[-1]
                if not name or name.startswith('.'): continue
                if clean_href == decoded_curr or clean_href == decoded_curr + "/": continue

                is_dir = False
                propstat = response.find('.//d:propstat', ns) if ns_url else response.find('.//propstat')
                if propstat:
                    prop = propstat.find('.//d:prop', ns) if ns_url else propstat.find('.//prop')
                    if prop:
                        rtype = prop.find('.//d:resourcetype', ns) if ns_url else prop.find('.//resourcetype')
                        if rtype is not None:
                            coll = rtype.find('.//d:collection', ns) if ns_url else rtype.find('.//collection')
                            if coll is not None: is_dir = True
                items.append({'name': name, 'path': raw_href, 'is_dir': is_dir})
        except: pass
        return sorted(items, key=lambda x: (not x['is_dir'], x['name'].lower()))

    def read_file(self, path):
        url = self.get_full_url(path)
        try:
            r = self.session.get(url)
            return r.text if r.status_code == 200 else ""
        except: return ""

    def save_file(self, path, content):
        url = self.get_full_url(path)
        try:
            r = self.session.put(url, data=content.encode('utf-8'), headers={'Content-Type': 'audio/x-mpegurl; charset=utf-8'})
            return r.status_code in [200, 201, 204]
        except: return False

    def clear_file(self, path):
        return self.save_file(path, "#EXTM3U\n")

    def append_to_m3u(self, m3u_path, track_path):
        try:
            content = self.read_file(m3u_path)
            track_clean = urllib.parse.unquote(track_path)
            if "://" in track_clean:
                track_clean = "/" + track_clean.split("://", 1)[1].split("/", 1)[1]
            elif not track_clean.startswith("/"):
                track_clean = "/" + track_clean
            
            new_content = content.strip() + "\n" + track_clean
            if not content.strip(): new_content = "#EXTM3U\n" + track_clean
            return self.save_file(m3u_path, new_content)
        except: return False

    def pop_first_from_m3u(self, m3u_path):
        try:
            content = self.read_file(m3u_path)
            if not content: return None
            lines = [l.strip() for l in content.split('\n') if l.strip()]
            valid_lines = [l for l in lines if not l.startswith('#')]
            if not valid_lines: return None
            
            first_track = valid_lines[0]
            
            # Guardamos el resto
            new_lines = ["#EXTM3U"] + valid_lines[1:]
            new_content = "\n".join(new_lines)
            self.save_file(m3u_path, new_content)
            
            return first_track
        except: return None

    def append_to_history(self, track_path):
        if not self.history_file: return
        try:
            content = self.read_file(self.history_file)
            lines = [line.strip() for line in content.split('\n') if line.strip() and not line.startswith('#EXTM3U')]
            track_clean = urllib.parse.unquote(track_path)
            if "://" in track_clean:
                track_clean = "/" + track_clean.split("://", 1)[1].split("/", 1)[1]
            elif not track_clean.startswith("/"):
                track_clean = "/" + track_clean
            if lines and lines[0] == track_clean: return
            lines.insert(0, track_clean)
            lines = lines[:100]
            new_content = "#EXTM3U\n" + "\n".join(lines)
            self.save_file(self.history_file, new_content)
        except: pass
    
    def append_line_to_file(self, file_path, line):
        try:
            content = self.read_file(file_path)
            clean_line = urllib.parse.unquote(line).strip()
            existing_lines = [l.strip() for l in content.split('\n') if l.strip()]
            if clean_line in existing_lines: return True
            new_content = content.strip() + "\n" + clean_line
            return self.save_file(file_path, new_content)
        except: return False

# --- MOTOR DE AUDIO (MPV) ---
class AudioPlayer:
    def __init__(self):
        self.player = mpv.MPV(input_default_bindings=True, input_vo_keyboard=True, ytdl=True)
        self.player['vo'] = 'null'
        self.current_meta = {"title": " - ", "artist": " "}
        self.volume = 80
        self.player.volume = self.volume

    def play(self, url, name):
        try:
            self.player.play(url)
            self.current_meta["title"] = name
            self.player.volume = self.volume
            self.player.pause = False 
        except Exception as e:
            print(f"Error reproduciendo: {e}")

    def toggle(self):
        self.player.pause = not self.player.pause

    def stop(self):
        self.player.stop()

    def seek(self, seconds):
        if self.player.time_pos is not None:
            self.player.time_pos += seconds

    def change_volume(self, delta):
        self.volume = max(0, min(100, self.volume + delta))
        self.player.volume = self.volume
        return self.volume

    def get_status(self):
        try:
            curr = (self.player.time_pos or 0) * 1000
            total = (self.player.duration or 0) * 1000
        except:
            curr, total = 0, 0
        
        if self.player.core_idle:
            status = "Stopped"
            if total > 0 and curr >= total - 1000:
                status = "Ended"
        elif self.player.pause:
            status = "Paused"
        else:
            status = "Playing"

        return curr, total, self.volume, status
    
    def close(self):
        try: self.player.terminate()
        except: pass

# --- UI COMPONENTS ---

class InputNameScreen(ModalScreen):
    CSS = """
    InputNameScreen { align: center middle; background: rgba(0,0,0,0.8); }
    #dialog_input { width: 40%; height: auto; background: #262626; border: thick #005f87; padding: 1; }
    Label { margin-bottom: 1; text-style: bold; }
    Input { margin-bottom: 1; background: #1c1c1c; border: none; }
    #btn_row { align: center middle; height: 3; }
    Button { margin: 0 1; }
    """
    def __init__(self, title="Nuevo nombre"):
        super().__init__()
        self.lbl_title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog_input"):
            yield Label(self.lbl_title)
            yield Input(id="name_input")
            with Horizontal(id="btn_row"):
                yield Button("Aceptar", variant="primary", id="ok_btn")
                yield Button("Cancelar", variant="error", id="cancel_btn")

    def on_mount(self):
        self.query_one(Input).focus()

    @on(Button.Pressed, "#ok_btn")
    def on_ok(self):
        val = self.query_one(Input).value.strip()
        if val: self.dismiss(val)
        else: self.dismiss(None)

    @on(Input.Submitted)
    def on_enter(self): self.on_ok()

    @on(Button.Pressed, "#cancel_btn")
    def on_cancel(self): self.dismiss(None)


class PlaylistSelectionScreen(ModalScreen):
    CSS = """
    PlaylistSelectionScreen { align: center middle; background: rgba(0,0,0,0.7); }
    #dialog_plist { width: 45%; max-height: 70%; background: #262626; border: thick #005f87; padding: 1; }
    #plist_header { background: #005f87; color: white; text-align: center; text-style: bold; padding: 0 1; margin-bottom: 1; }
    OptionList { background: #1c1c1c; color: #b2b2b2; border: solid #3a3a3a; height: 1fr; }
    OptionList:focus { border: solid #005f87; }
    #btn_container { height: 3; align: center middle; margin-top: 1; }
    Button { min-width: 12; height: 3; margin: 0 1; }
    """
    def __init__(self, client: WebDAVClient, path_dir, mode="load"):
        super().__init__()
        self.client = client
        self.path_dir = path_dir
        self.mode = mode
        self.playlists = []
        self.title = "Cargar Lista" if mode == "load" else "Añadir a Lista"

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog_plist"):
            yield Label(self.title, id="plist_header")
            yield OptionList(id="plist_options")
            with Horizontal(id="btn_container"):
                yield Button("Nueva", variant="primary", id="new_btn")
                yield Button("Cancelar", variant="error", id="cancel_btn")

    def on_mount(self):
        self.refresh_list()

    def refresh_list(self):
        self.run_worker(self._fetch_playlists, thread=True)

    def _fetch_playlists(self):
        items = self.client.list_directory(self.path_dir)
        self.playlists = [i for i in items if i['name'].endswith('.m3u')]
        names = [p['name'] for p in self.playlists]
        
        def update_ui():
            try:
                ol = self.query_one(OptionList)
                ol.clear_options()
                ol.add_options(names)
                ol.focus()
            except: pass
        
        self.app.call_from_thread(update_ui)

    @on(OptionList.OptionSelected)
    def on_select(self, event: OptionList.OptionSelected): 
        if 0 <= event.option_index < len(self.playlists):
            self.dismiss(self.playlists[event.option_index])

    @on(Button.Pressed, "#cancel_btn")
    def cancel(self): self.dismiss(None)

    @on(Button.Pressed, "#new_btn")
    def new_playlist(self):
        def on_name(name):
            if name:
                if not name.endswith('.m3u'): name += '.m3u'
                full_path = self.path_dir + name
                self.client.save_file(full_path, "#EXTM3U\n")
                self.refresh_list()
        
        self.app.push_screen(InputNameScreen("Nombre de nueva lista"), on_name)


class FavAlbumsScreen(ModalScreen):
    CSS = """
    FavAlbumsScreen { align: center middle; background: rgba(0,0,0,0.7); }
    #dialog_fav { width: 50%; max-height: 75%; background: #262626; border: thick #d7005f; padding: 1; }
    #fav_header { background: #d7005f; color: white; text-align: center; text-style: bold; padding: 0 1; margin-bottom: 1; }
    OptionList { background: #1c1c1c; color: #b2b2b2; border: solid #3a3a3a; height: 1fr; }
    OptionList:focus { border: solid #d7005f; }
    #btn_container { height: 3; align: center middle; margin-top: 1; }
    Button { min-width: 16; height: 3; }
    """
    def __init__(self, albums):
        super().__init__()
        self.albums = albums
        self.display_names = [urllib.parse.unquote(a).rstrip('/').split('/')[-1] for a in albums]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog_fav"):
            yield Label("⭐ Álbumes Favoritos", id="fav_header")
            yield OptionList(*self.display_names, id="fav_options")
            with Horizontal(id="btn_container"):
                yield Button("Cerrar", variant="error", id="cancel_btn")

    def on_mount(self): self.query_one(OptionList).focus()
    
    @on(OptionList.OptionSelected)
    def on_select(self, event: OptionList.OptionSelected): 
        self.dismiss(self.albums[event.option_index])
        
    @on(Button.Pressed, "#cancel_btn")
    def cancel(self): self.dismiss(None)

class HelpScreen(ModalScreen):
    CSS = """
    HelpScreen { align: center middle; background: rgba(0,0,0,0.8); }
    #help_container { width: 70%; height: 80%; background: #262626; border: thick #d78700; padding: 2; color: #b2b2b2; }
    """
    BINDINGS = [Binding("q", "close_help", "Cerrar"), Binding("escape", "close_help", "Cerrar")]
    HELP_TEXT = """
    # Ayuda de PyMusic

    ## Listas y Favoritos
    - **Shift+l**: Listas de Usuario.
    - **Ctrl+l**: Listas de la Raíz.
    - **m**: Añadir canción a una lista.
    - **f**: Añadir a Favoritos.
    - **c**: Añadir a la COLA (archivo persistente).
    - **Shift+C**: Limpiar la COLA.

    ## Navegación
    - **Enter (Carpeta)**: Expandir.
    - **Enter (Lista .m3u)**: Cargar lista.

    ## Reproducción
    - **x / ESPACIO**: Play/Pause.
    - **z / b**: Anterior / Siguiente.
    - **+ / -**: Subir / Bajar Volumen.
    - **Left / Right**: Atrás / Adelante (Seek).
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="help_container"):
            yield Label(self.HELP_TEXT)
            yield Button("Cerrar (q)", id="close_help", variant="warning")
    def action_close_help(self): self.dismiss()
    @on(Button.Pressed, "#close_help")
    def on_button_close(self): self.dismiss()

class CmusStatusBar(Static):
    DEFAULT_CSS = "CmusStatusBar { dock: bottom; height: 1; background: #000000; color: #d7af00; text-style: bold; }"
    def update_status(self, title, curr_ms, total_ms, volume, status, msg=""):
        def fmt(ms): return f"{int(max(0,ms)/1000)//60:02d}:{int(max(0,ms)/1000)%60:02d}"
        icon = ">" if status == "Playing" else ("||" if status == "Paused" else ".")
        left = f"{icon} {fmt(curr_ms)}/{fmt(total_ms)} - {title} [Vol:{volume}%] [{status}]"
        self.update(f"{left.ljust(60)} {msg}")

class CmusApp(App):
    CSS = """
    Screen { background: #1c1c1c; color: #b2b2b2; }

    #main_container {
        layout: horizontal;
        height: 1fr;
    }
    
    #left_pane { 
        width: 35%; 
        height: 100%; 
        border-right: solid #585858;
        border-bottom: none;
    }
    
    DataTable { 
        width: 65%; 
        height: 100%; 
        background: #1c1c1c; 
        border: none; 
    }

    /* CAMBIO VISUAL: Cursor gris cuando no tiene foco, naranja cuando sí */
    DataTable > .datatable--cursor { background: #585858; color: #000000; text-style: bold; }
    DataTable:focus > .datatable--cursor { background: #d78700; color: #000000; text-style: bold; }
    DataTable > .datatable--header { background: #005f87; color: #ffffff; text-style: bold; }

    .narrow {
        layout: vertical !important;
    }
    
    .narrow #left_pane {
        width: 100%;
        height: 45%;
        border-right: none;
        border-bottom: solid #585858;
    }
    
    .narrow DataTable {
        width: 100%;
        height: 55%;
    }

    #library_header { background: #005f87; color: white; text-style: bold; padding: 0 1; }
    #filter_input { background: #262626; border: none; height: 1; color: #d7af00; }
    #command_input { dock: bottom; height: 1; background: #303030; color: white; border: none; display: none; }
    #command_input.-visible { display: block; }
    Tree { width: 100%; height: 1fr; background: #1c1c1c; color: #b2b2b2; }
    Tree:focus { background: #262626; }
    Tree > .tree--cursor { background: #005f87; color: #ffffff; text-style: bold; } 
    """

    BINDINGS = [
        Binding("tab", "switch_pane", "Switch Pane"),
        Binding("enter", "activate_item", "Play/Expand"),
        Binding("a", "add_to_active_playlist", "Add to Queue (Internal)"),
        Binding("m", "add_to_saved_playlist", "Add to M3U"),
        Binding("L", "list_user_playlists", "User Playlists"), 
        Binding("ctrl+l", "list_root_playlists", "Root Playlists"), 
        Binding("c", "queue_next", "Añadir a Cola"),
        Binding("C", "clear_queue", "Limpiar Cola"),
        Binding("alt+c", "clear_playlist", "Limpiar Vista"),
        Binding("S", "sync_library", "Sync Library"),
        Binding("f", "add_favorite", "Add Favorite"), 
        Binding("F", "show_fav_albums", "Fav Albums"),
        Binding("delete", "remove_from_playlist", "Remove"),
        Binding("D", "remove_from_playlist", "Remove"),
        Binding("space", "toggle_pause", "Pause"),
        Binding("x", "toggle_pause", "Pause"),
        Binding("z", "prev_track", "Previous"),
        Binding("b", "next_track", "Next"),
        Binding("v", "stop_track", "Stop"),
        Binding("left", "seek_back", "Seek -"),
        Binding("right", "seek_fwd", "Seek +"),
        Binding("+", "vol_up", "Vol +"),
        Binding("-", "vol_down", "Vol -"),
        Binding(":", "command_mode", "Cmd"),
        Binding("q", "quit", "Quit"),
        Binding("?", "help", "Help"),
    ]

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.client = WebDAVClient(self.config)
        self.player = AudioPlayer()
        self.root_path = self.config.get('ROOT_PATH')
        self.playlists_dir = self.config.user_playlists_path
        self.active_playlist = []
        self.current_track_index = -1
        self.root_items_cache = []
        self.status_message = ""
        self.audio_exts = ('.mp3', '.ogg', '.flac', '.wav', '.m4a', '.opus')
        self.current_loaded_path = None
        self.queue_offset = 0 

    def compose(self) -> ComposeResult:
        with Container(id="main_container"):
            with Vertical(id="left_pane"):
                yield Label(f" Biblioteca ({self.config.user or 'Invitado'})", id="library_header")
                yield Input(placeholder="Filtrar...", id="filter_input")
                yield Tree("Raiz", id="left_tree")
            yield DataTable(id="right_list", cursor_type="row")
        
        yield Input(id="command_input", placeholder=":comando")
        yield CmusStatusBar(id="status_bar")

    def on_mount(self):
        table = self.query_one(DataTable)
        table.add_columns("Álbum", "Pista")
        tree = self.query_one(Tree)
        tree.root.data = {'path': self.root_path, 'type': 'root'}
        tree.root.expand()
        self.load_tree_root()
        self.set_interval(0.5, self.update_status_bar)
        tree.focus()

    def on_resize(self, event: events.Resize):
        try:
            container = self.query_one("#main_container")
            if event.size.width < 100:
                container.add_class("narrow")
            else:
                container.remove_class("narrow")
        except:
            pass
    
    def on_unmount(self):
        self.player.close()

    def action_help(self): self.push_screen(HelpScreen())
    
    def action_switch_pane(self):
        if self.query_one(Tree).has_focus: self.query_one(DataTable).focus()
        else: self.query_one(Tree).focus()
    
    def set_msg(self, text):
        self.status_message = text
        def clear(): 
            if self.status_message == text: self.status_message = ""
        self.set_timer(3.0, clear)

    @work(thread=True)
    def action_sync_library(self):
        self.call_from_thread(self.set_msg, "Sincronizando biblioteca...")
        self.root_items_cache = []
        self.load_tree_root()
        self.call_from_thread(self.set_msg, "Biblioteca sincronizada.")

    @work(thread=True)
    def action_add_favorite(self):
        if self.query_one(DataTable).has_focus:
            idx = self.query_one(DataTable).cursor_row
            if idx is not None and 0 <= idx < len(self.active_playlist):
                track = self.active_playlist[idx]
                success = self.client.append_to_m3u(self.config.favorites_file, track['path'])
                self.call_from_thread(self.set_msg, f"Canción añadida a Favoritos" if success else "Error añadiendo favorito")
        elif self.query_one(Tree).has_focus:
            node = self.query_one(Tree).cursor_node
            if node and node.data.get('type') == 'dir':
                path = node.data.get('path')
                success = self.client.append_line_to_file(self.config.fav_albums_file, path)
                self.call_from_thread(self.set_msg, f"Álbum añadido a Favoritos" if success else "Error añadiendo álbum")

    @work(thread=True)
    def action_show_fav_albums(self):
        content = self.client.read_file(self.config.fav_albums_file)
        if not content:
            self.call_from_thread(self.set_msg, "No hay álbumes favoritos aún.")
            return
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        if not lines:
             self.call_from_thread(self.set_msg, "Lista de álbumes vacía.")
             return
        def show_modal():
            self.push_screen(FavAlbumsScreen(lines), self.on_album_selected)
        self.call_from_thread(show_modal)

    def on_album_selected(self, album_path):
        if album_path:
            self.set_msg(f"Cargando álbum favorito...")
            self.active_playlist = []
            self.add_tracks_recursive(album_path, is_dir=True)
            self.current_loaded_path = album_path

    # --- LISTAS ---
    def action_list_user_playlists(self):
        self.show_playlist_modal(self.playlists_dir, mode="load")

    def action_list_root_playlists(self):
        self.show_playlist_modal(self.root_path, mode="load")

    def show_playlist_modal(self, path, mode):
        def on_selected(playlist):
            if playlist:
                if mode == "load":
                    self.set_msg(f"Cargando {playlist['name']}...")
                    self.active_playlist = []
                    self.load_playlist_content(playlist['path'], append=False)
                    self.current_loaded_path = playlist['path']
                elif mode == "add" and hasattr(self, 'temp_track_to_add'):
                    self.set_msg(f"Añadiendo a {playlist['name']}...")
                    self.do_append_to_m3u(playlist['path'], self.temp_track_to_add['path'])

        self.push_screen(PlaylistSelectionScreen(self.client, path, mode), on_selected)

    def action_add_to_saved_playlist(self):
        if not self.query_one(DataTable).has_focus: return
        idx = self.query_one(DataTable).cursor_row
        if idx is None or idx < 0 or idx >= len(self.active_playlist): return
        
        self.temp_track_to_add = self.active_playlist[idx]
        self.show_playlist_modal(self.playlists_dir, mode="add")

    @work(thread=True)
    def do_append_to_m3u(self, m3u_path, track_path):
        success = self.client.append_to_m3u(m3u_path, track_path)
        self.call_from_thread(self.set_msg, "Añadida con éxito" if success else "Error")

    # --- EVENTOS ---
    @on(Tree.NodeSelected)
    def on_tree_select(self, event: Tree.NodeSelected):
        node = event.node
        path = node.data.get('path')
        dtype = node.data.get('type')
        
        self.current_loaded_path = path

        if dtype == 'dir':
            self.set_msg(f"Cargando {node.label}...")
            self.active_playlist = []
            self.add_tracks_recursive(path, is_dir=True)
        elif dtype == 'playlist':
            self.set_msg(f"Cargando lista {node.label}...")
            self.active_playlist = []
            self.load_playlist_content(path, append=False)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected):
        idx = event.cursor_row
        if idx is not None and 0 <= idx < len(self.active_playlist):
            self.current_track_index = idx
            self.play_index(idx)

    def action_activate_item(self):
        if self.query_one(DataTable).has_focus:
            idx = self.query_one(DataTable).cursor_row
            if idx is not None and 0 <= idx < len(self.active_playlist):
                self.current_track_index = idx
                self.play_index(idx)
        else:
            node = self.query_one(Tree).cursor_node
            if not node: return
            
            node_path = node.data.get('path')
            dtype = node.data.get('type')

            if dtype == 'dir':
                if node.is_expanded:
                    node.collapse()
                else:
                    node.expand()
                    self.on_tree_select(Tree.NodeSelected(node))

            elif dtype == 'playlist':
                if self.current_loaded_path == node_path:
                    table = self.query_one(DataTable)
                    table.focus()
                    if table.cursor_row is None and len(self.active_playlist) > 0:
                        table.move_cursor(row=0)
                else:
                    self.on_tree_select(Tree.NodeSelected(node))

    def action_add_to_active_playlist(self):
        if not self.query_one(Tree).has_focus: return
        node = self.query_one(Tree).cursor_node
        if not node: return
        path = node.data.get('path')
        dtype = node.data.get('type')
        if dtype == 'playlist': self.load_playlist_content(path, append=True)
        elif dtype == 'dir': self.add_tracks_recursive(path, True, append=True)

    @work(thread=True)
    def action_queue_next(self):
        track_to_add = None
        if self.query_one(DataTable).has_focus:
            idx = self.query_one(DataTable).cursor_row
            if idx is not None and 0 <= idx < len(self.active_playlist):
                track_to_add = self.active_playlist[idx].copy()
        elif self.query_one(Tree).has_focus:
            node = self.query_one(Tree).cursor_node
            if node and node.data.get('type') != 'dir':
                 pass
        
        if track_to_add:
            success = self.client.append_to_m3u(self.config.queue_file, track_to_add['path'])
            self.call_from_thread(self.set_msg, f"Añadido a 'en_cola': {track_to_add['name']}" if success else "Error añadiendo a cola")

    @work(thread=True)
    def action_clear_queue(self):
        success = self.client.clear_file(self.config.queue_file)
        self.call_from_thread(self.set_msg, "Cola 'en_cola.m3u' vaciada" if success else "Error vaciando cola")

    def action_remove_from_playlist(self):
        if not self.query_one(DataTable).has_focus: return
        table = self.query_one(DataTable)
        idx = table.cursor_row
        if idx is not None and 0 <= idx < len(self.active_playlist):
            del self.active_playlist[idx]
            if idx < self.current_track_index: self.current_track_index -= 1
            self.refresh_playlist_view()
            self.set_msg("Pista eliminada de la vista")

    def action_clear_playlist(self):
        self.active_playlist = []
        self.current_track_index = -1
        self.query_one(DataTable).clear()
        self.current_loaded_path = None
        self.set_msg("Lista visual vaciada")

    def action_command_mode(self):
        inp = self.query_one("#command_input")
        inp.add_class("-visible")
        inp.value = ":"
        inp.focus()

    @on(Input.Submitted, "#command_input")
    def on_command_submit(self, event: Input.Submitted):
        cmd = event.value.strip()
        self.query_one("#command_input").remove_class("-visible")
        self.query_one("#command_input").value = ""
        self.query_one(DataTable).focus()
        if cmd.startswith(":save "):
            name = cmd[6:].strip()
            if name: self.save_playlist(name)
        elif cmd.startswith(":load "):
            name = cmd[6:].strip()
            if name: 
                path = self.playlists_dir + (name if name.endswith('.m3u') else name + '.m3u')
                self.active_playlist = []
                self.load_playlist_content(path, append=False)
                self.current_loaded_path = path
        elif cmd == ":clear": self.action_clear_playlist()
        elif cmd == ":q": self.exit()
        else: self.set_msg(f"Comando desconocido: {cmd}")

    @work(thread=True)
    def save_playlist(self, name):
        if not name.endswith('.m3u'): name += '.m3u'
        path = self.playlists_dir + name
        content = "#EXTM3U\n"
        for track in self.active_playlist:
            full_path = track['path']
            if full_path.startswith(self.root_path):
                rel = full_path[len(self.root_path):]
                if rel.startswith('/'): rel = rel[1:]
            else: rel = full_path
            content += f"{rel}\n"
        success = self.client.save_file(path, content)
        self.call_from_thread(self.set_msg, f"Guardado en {self.config.user or 'general'}: {name}" if success else "Error al guardar")

    @work(thread=True)
    def load_playlist_content(self, path, append=False):
        content = self.client.read_file(path)
        if not content: return
        lines = content.split('\n')
        new_tracks = []
        root_prefix = self.root_path if self.root_path.endswith('/') else self.root_path + '/'
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'): continue
            full_path_for_play = line
            if not line.startswith("http") and not line.startswith("/"):
                full_path_for_play = root_prefix + line
            decoded = urllib.parse.unquote(full_path_for_play)
            parts = decoded.rstrip('/').split('/')
            new_tracks.append({'name': parts[-1], 'path': full_path_for_play, 'album': parts[-2] if len(parts)>1 else "-"})
        def finish():
            if not append: 
                self.active_playlist = new_tracks
                self.current_track_index = 0
            else: 
                self.active_playlist.extend(new_tracks)
            self.refresh_playlist_view()
            self.set_msg(f"Lista cargada: {len(new_tracks)} pistas")
        self.call_from_thread(finish)

    @work(thread=True)
    def add_tracks_recursive(self, path, is_dir, append=False):
        new_tracks = []
        if is_dir:
            items = self.client.list_directory(path)
            decoded_path = urllib.parse.unquote(path).rstrip('/')
            album_name = decoded_path.split('/')[-1]
            for i in items:
                if not i['is_dir'] and i['name'].lower().endswith(self.audio_exts):
                    new_tracks.append({'name': urllib.parse.unquote(i['name']), 'path': i['path'], 'album': album_name})
        def update_ui():
            if not append: 
                self.active_playlist = new_tracks
                self.current_track_index = 0
            else: self.active_playlist.extend(new_tracks)
            self.refresh_playlist_view()
            if not append and new_tracks: self.set_msg(f"Cargadas {len(new_tracks)} canciones")
        self.call_from_thread(update_ui)

    def refresh_playlist_view(self):
        table = self.query_one(DataTable)
        table.clear()
        for t in self.active_playlist: table.add_row(t['album'], t['name'])
        if 0 <= self.current_track_index < len(self.active_playlist):
            try: table.move_cursor(row=self.current_track_index)
            except: pass

    @work(thread=True)
    def load_tree_root(self):
        items = self.client.list_directory(self.root_path)
        self.root_items_cache = items
        self.call_from_thread(self.filter_tree, "")

    def filter_tree(self, filter_text):
        tree = self.query_one(Tree)
        root = tree.root
        root.remove_children()
        term = filter_text.lower()
        for item in self.root_items_cache:
            name = item['name']
            if term and term not in name.lower(): continue
            clean = urllib.parse.unquote(name)
            if item['is_dir']: root.add(f"📁 {clean}", data={'path': item['path'], 'type': 'dir'}, allow_expand=True)
            elif name.lower().endswith('.m3u'): root.add(f"📜 {clean}", data={'path': item['path'], 'type': 'playlist'}, allow_expand=False)

    @on(Input.Changed, "#filter_input")
    def on_filter_change(self, event: Input.Changed): self.filter_tree(event.value)

    @on(Input.Submitted, "#filter_input")
    def on_filter_enter(self, event: Input.Submitted):
        tree = self.query_one(Tree)
        if tree.root.children:
            first_node = tree.root.children[0]
            tree.select_node(first_node)
            tree.focus()
            self.on_tree_select(Tree.NodeSelected(first_node))

    @on(Tree.NodeExpanded)
    def on_tree_expand(self, event: Tree.NodeExpanded):
        if event.node != self.query_one(Tree).root: self.load_sub_node(event.node)

    @work(thread=True)
    def load_sub_node(self, node: TreeNode):
        if node.children: return
        items = self.client.list_directory(node.data['path'])
        def update():
            node.remove_children()
            for item in items:
                clean = urllib.parse.unquote(item['name'])
                if item['is_dir']: node.add(f"📁 {clean}", data={'path': item['path'], 'type': 'dir'}, allow_expand=True)
                elif clean.lower().endswith('.m3u'): node.add(f"📜 {clean}", data={'path': item['path'], 'type': 'playlist'})
        self.call_from_thread(update)

    def play_index(self, index):
        if 0 <= index < len(self.active_playlist):
            self.current_track_index = index
            item = self.active_playlist[index]
            
            # --- Lógica LOCAL_PATH vs WEBDAV ---
            path_or_url = ""
            raw_path = item['path']
            
            if self.config.local_path:
                clean_root = self.root_path.rstrip('/')
                decoded_path = urllib.parse.unquote(raw_path)
                
                if decoded_path.startswith(clean_root):
                    rel_path = decoded_path[len(clean_root):]
                    if rel_path.startswith('/'): rel_path = rel_path[1:]
                    path_or_url = os.path.join(self.config.local_path, rel_path)
                else:
                    path_or_url = decoded_path
            else:
                path_or_url = self.client.get_stream_url(raw_path)

            threading.Thread(target=self.client.append_to_history, args=(raw_path,), daemon=True).start()
            self.player.play(path_or_url, item['name'])
            try: self.query_one(DataTable).move_cursor(row=index)
            except: pass

    def action_next_track(self):
        self.check_queue_and_play()

    @work(thread=True)
    def check_queue_and_play(self):
        # 1. Intentar sacar de la cola persistente
        queued_track_path = self.client.pop_first_from_m3u(self.config.queue_file)
        
        if queued_track_path:
            # 2. MOVER A HISTORIAL DE COLA (reproducida_en_cola.m3u)
            self.client.append_to_m3u(self.config.played_queue_file, queued_track_path)
            
            # 3. Preparar reproducción
            path_or_url = ""
            if self.config.local_path:
                clean_root = self.root_path.rstrip('/')
                decoded_path = urllib.parse.unquote(queued_track_path)
                if decoded_path.startswith(clean_root):
                    rel_path = decoded_path[len(clean_root):]
                    if rel_path.startswith('/'): rel_path = rel_path[1:]
                    path_or_url = os.path.join(self.config.local_path, rel_path)
                else:
                    path_or_url = decoded_path 
            else:
                root_prefix = self.root_path if self.root_path.endswith('/') else self.root_path + '/'
                full_path_for_play = queued_track_path
                if not queued_track_path.startswith("http") and not queued_track_path.startswith("/"):
                    full_path_for_play = root_prefix + queued_track_path
                path_or_url = self.client.get_stream_url(full_path_for_play)
            
            name = urllib.parse.unquote(queued_track_path).split('/')[-1]
            self.app.call_from_thread(self.set_msg, f"Reproduciendo de COLA: {name}")
            self.player.play(path_or_url, f"[Cola] {name}")
            
        else:
            # 4. Si no hay cola, seguir con el álbum actual
            self.app.call_from_thread(self._advance_album_index)

    def _advance_album_index(self):
        if self.current_track_index < len(self.active_playlist) - 1:
            self.current_track_index += 1
            self.play_index(self.current_track_index)
        else:
            self.set_msg("Fin del álbum.")

    def action_prev_track(self):
        if self.current_track_index > 0:
            self.current_track_index -= 1
            self.play_index(self.current_track_index)
            
    def action_toggle_pause(self): self.player.toggle()
    def action_stop_track(self): self.player.stop()
    def action_seek_fwd(self): self.player.seek(5)
    def action_seek_back(self): self.player.seek(-5)
    def action_vol_up(self): self.set_msg(f"Vol: {self.player.change_volume(5)}%")
    def action_vol_down(self): self.set_msg(f"Vol: {self.player.change_volume(-5)}%")
    
    def update_status_bar(self):
        curr, total, vol, status = self.player.get_status()
        if status == "Ended": self.action_next_track()
        self.query_one(CmusStatusBar).update_status(self.player.current_meta["title"], curr, total, vol, status, self.status_message)

if __name__ == "__main__":
    app = CmusApp()
    app.run()
