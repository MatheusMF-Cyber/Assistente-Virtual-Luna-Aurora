import os
import sys
import shutil
import zipfile
import subprocess
import webbrowser
import logging
from PIL import ImageGrab

# Optional dependency for active window detection
PYWIN32_AVAILABLE = False
try:
    import win32gui
    import win32process
    import psutil
    PYWIN32_AVAILABLE = True
except ImportError:
    logging.warning("pywin32 ou psutil não instalados. Detecção de janela ativa limitada.")

class SystemTools:
    def __init__(self, workspace_dir=None):
        self.workspace_dir = workspace_dir or os.path.dirname(os.path.abspath(__file__))
        self.downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        
    def open_website(self, url):
        """Abre um website ou executa uma busca se não for uma URL válida."""
        if not url.startswith("http://") and not url.startswith("https://"):
            # If not a link, do a Google search
            url = f"https://www.google.com/search?q={url}"
        try:
            webbrowser.open(url)
            return True, f"Abri o site/pesquisa no seu navegador."
        except Exception as e:
            logging.error(f"Erro ao abrir site: {e}")
            return False, str(e)

    def open_program(self, program_name):
        """Abre um programa instalado ou executa um comando."""
        try:
            # On Windows, os.startfile can open standard programs (notepad, calc, etc.)
            # as well as registered applications or files
            os.startfile(program_name)
            return True, f"Iniciei o programa '{program_name}'."
        except Exception:
            # If direct launch fails, try starting via CMD/powershell shell command
            try:
                subprocess.Popen(program_name, shell=True)
                return True, f"Iniciei '{program_name}' via prompt."
            except Exception as e:
                logging.error(f"Erro ao abrir programa '{program_name}': {e}")
                return False, f"Não consegui abrir o programa '{program_name}'. Ele está instalado?"

    def extract_archive(self, file_path, dest_dir=None):
        """
        Descompacta arquivos .zip ou .rar.
        Para .zip, usa a biblioteca nativa.
        Para .rar, tenta usar o WinRAR instalado no sistema.
        """
        if not os.path.exists(file_path):
            return False, "O arquivo especificado não existe."

        if not dest_dir:
            # Create a folder with the same name as the archive in the same directory
            base_dir = os.path.dirname(file_path)
            file_name = os.path.basename(file_path)
            folder_name = os.path.splitext(file_name)[0]
            dest_dir = os.path.join(base_dir, folder_name)
            
        os.makedirs(dest_dir, exist_ok=True)
        
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == ".zip":
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(dest_dir)
                return True, f"Arquivo descompactado com sucesso na pasta: {dest_dir}"
            except Exception as e:
                return False, f"Falha ao extrair arquivo zip: {e}"
                
        elif ext == ".rar":
            # Search for WinRAR in common default paths
            winrar_paths = [
                r"C:\Program Files\WinRAR\WinRAR.exe",
                r"C:\Program Files (x86)\WinRAR\WinRAR.exe",
                r"C:\Program Files\WinRAR\UnRAR.exe",
                "winrar"
            ]
            
            winrar_exe = None
            for path in winrar_paths:
                if path == "winrar" or os.path.exists(path):
                    winrar_exe = path
                    break
                    
            if winrar_exe:
                try:
                    # Execute: winrar x -ibck "archive.rar" "dest_dir\"
                    # -ibck runs WinRAR in the background
                    cmd = f'"{winrar_exe}" x -ibck "{file_path}" "{dest_dir}\\"'
                    subprocess.run(cmd, shell=True, check=True)
                    return True, f"Arquivo RAR extraído com sucesso usando o WinRAR na pasta: {dest_dir}"
                except Exception as e:
                    return False, f"Falha ao extrair RAR usando WinRAR: {e}"
            else:
                return False, "WinRAR não encontrado no computador. Por favor, instale-o ou use arquivos ZIP."
        else:
            return False, f"Formato de arquivo '{ext}' não suportado. Apenas ZIP ou RAR."

    def get_active_window_title(self):
        """Retorna o título da janela ativa atual e o nome do processo."""
        if not PYWIN32_AVAILABLE:
            return "Área de Trabalho", "desconhecido"
            
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            
            # Get process name
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            proc_name = proc.name()
            
            return title, proc_name
        except Exception:
            return "Área de Trabalho", "desconhecido"

    def capture_screen(self, output_path=None):
        """Captura a tela principal do computador e salva em um arquivo temporário."""
        try:
            screenshot = ImageGrab.grab()
            # Convert to RGB to ensure compatibility (PNG/JPEG conversion)
            screenshot = screenshot.convert("RGB")
            
            if not output_path:
                temp_dir = os.path.join(self.workspace_dir, "scratch")
                os.makedirs(temp_dir, exist_ok=True)
                output_path = os.path.join(temp_dir, "screen_capture.jpg")
                
            # Resize image if too large, to optimize Gemini API speed
            max_size = (1280, 720)
            screenshot.thumbnail(max_size)
            screenshot.save(output_path, "JPEG", quality=80)
            
            return output_path
        except Exception as e:
            logging.error(f"Erro ao capturar tela: {e}")
            return None

    def scan_downloads_folder(self, last_seen_files=None):
        """
        Escaneia a pasta Downloads procurando por novos arquivos.
        Retorna uma lista de novos arquivos detectados.
        """
        if last_seen_files is None:
            last_seen_files = set()
            
        if not os.path.exists(self.downloads_dir):
            return [], last_seen_files
            
        try:
            current_files = set(os.listdir(self.downloads_dir))
            # Find files that are new
            new_files = current_files - last_seen_files
            
            # Filter to keep only completed files (avoid partial downloads like .crdownload or .tmp)
            valid_new_files = []
            for f in new_files:
                path = os.path.join(self.downloads_dir, f)
                if os.path.isfile(path):
                    ext = os.path.splitext(f)[1].lower()
                    if ext not in ['.tmp', '.crdownload', '.part']:
                        valid_new_files.append(path)
                        
            # Update last seen files
            updated_seen_files = current_files
            return valid_new_files, updated_seen_files
        except Exception as e:
            logging.error(f"Erro ao escanear Downloads: {e}")
            return [], last_seen_files

    def inspect_file(self, file_path):
        """
        Obtém informações básicas sobre um arquivo (tamanho, conteúdo de ZIP/RAR, etc.).
        """
        if not os.path.exists(file_path):
            return "Arquivo não encontrado."
            
        file_name = os.path.basename(file_path)
        size_bytes = os.path.getsize(file_path)
        size_mb = size_bytes / (1024 * 1024)
        ext = os.path.splitext(file_name)[1].lower()
        
        info = f"Nome: {file_name}\nTamanho: {size_mb:.2f} MB\n"
        
        if ext == ".zip":
            try:
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    files_inside = zip_ref.namelist()[:10]  # List first 10 files
                    total_files = len(zip_ref.namelist())
                    info += f"Tipo: Arquivo ZIP\nConteúdo (primeiros 10 itens):\n"
                    for f in files_inside:
                        info += f"  - {f}\n"
                    if total_files > 10:
                        info += f"  ... e mais {total_files - 10} arquivos."
            except Exception as e:
                info += f"Erro ao ler conteúdo ZIP: {e}"
        elif ext == ".rar":
            info += f"Tipo: Arquivo RAR (Necessário descompactar para listar conteúdo)."
        elif ext in [".exe", ".msi"]:
            info += f"Tipo: Instalador ou Executável de Programa Windows."
        else:
            info += f"Tipo: Arquivo {ext.upper()}"
            
    def is_startup_enabled(self):
        """Verifica se a inicialização automática está habilitada no registro do Windows."""
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
            try:
                val, _ = winreg.QueryValueEx(key, "Aura")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
        except Exception as e:
            logging.error(f"Erro ao verificar startup no registro: {e}")
            return False

    def set_startup_enabled(self, enabled):
        """Habilita ou desabilita a inicialização automática no registro do Windows."""
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        if getattr(sys, 'frozen', False):
            exe_path = os.path.abspath(sys.executable)
        else:
            exe_path = os.path.abspath(sys.argv[0])
            
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE | winreg.KEY_READ)
            if enabled:
                winreg.SetValueEx(key, "Aura", 0, winreg.REG_SZ, f'"{exe_path}" --startup')
            else:
                try:
                    winreg.DeleteValue(key, "Aura")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True, f"Inicialização automática {'ativada' if enabled else 'desativada'}."
        except Exception as e:
            logging.error(f"Erro ao salvar startup no registro: {e}")
            return False, str(e)

    def search_browser_history(self, search_term):
        """
        Procura por termos de busca no histórico do Google Chrome e do Microsoft Edge.
        """
        import sqlite3
        import shutil
        import tempfile
        
        paths = [
            # Google Chrome
            os.path.join(os.environ["USERPROFILE"], "AppData", "Local", "Google", "Chrome", "User Data", "Default", "History"),
            # Microsoft Edge
            os.path.join(os.environ["USERPROFILE"], "AppData", "Local", "Microsoft", "Edge", "User Data", "Default", "History")
        ]
        
        results = []
        for path in paths:
            if os.path.exists(path):
                try:
                    # Copia para arquivo temporário para evitar travamento de banco ocupado
                    temp_db = os.path.join(tempfile.gettempdir(), f"aura_hist_temp_{os.path.basename(path)}")
                    shutil.copy2(path, temp_db)
                    
                    conn = sqlite3.connect(temp_db)
                    cursor = conn.cursor()
                    query = """
                        SELECT url, title, last_visit_time 
                        FROM urls 
                        WHERE url LIKE ? OR title LIKE ? 
                        ORDER BY last_visit_time DESC 
                        LIMIT 5
                    """
                    cursor.execute(query, (f"%{search_term}%", f"%{search_term}%"))
                    for row in cursor.fetchall():
                        results.append({
                            "url": row[0],
                            "title": row[1] or row[0],
                            "visit_time": row[2]
                        })
                    conn.close()
                    try:
                        os.remove(temp_db)
                    except Exception:
                        pass
                except Exception as e:
                    logging.warning(f"Erro ao ler histórico de {path}: {e}")
                    
        # Ordenar por tempo de visita decrescente
        results.sort(key=lambda x: x["visit_time"], reverse=True)
        return results

    def type_and_open_website(self, site_name):
        """
        Abre o site simulando a digitação no Executar do Windows (Win+R) e pressionando Enter.
        """
        import pyautogui
        import time
        
        if "." not in site_name:
            site_url = f"{site_name}.com"
        else:
            site_url = site_name
            
        try:
            # Pressiona Win+R
            pyautogui.hotkey('win', 'r')
            time.sleep(0.8)
            # Digita a URL
            pyautogui.write(site_url, interval=0.08)
            time.sleep(0.3)
            # Pressiona Enter
            pyautogui.press('enter')
            return True
        except Exception as e:
            logging.error(f"Erro ao digitar e abrir site via pyautogui: {e}")
            return False

if __name__ == "__main__":
    tools = SystemTools()
    print("Downloads dir:", tools.downloads_dir)
    print("Testing active window:", tools.get_active_window_title())
    print("Capturing screen...")
    path = tools.capture_screen()
    print("Captured to:", path)
