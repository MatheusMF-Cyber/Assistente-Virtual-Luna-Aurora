import os
import sys
import subprocess

def build():
    print("Iniciando processo de compilação da Aura...")
    
    # 1. Check if pyinstaller is installed
    try:
        import PyInstaller
        print("PyInstaller detectado.")
    except ImportError:
        print("Instalando PyInstaller...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("PyInstaller instalado com sucesso.")
        except Exception as e:
            print(f"Erro ao instalar PyInstaller: {e}")
            return
            
    # 2. Define pathing
    current_dir = os.path.dirname(os.path.abspath(__file__))
    entry_point = os.path.join(current_dir, "gui.py")
    
    # Check if assets exist
    assets_dir = os.path.join(current_dir, "assets")
    if not os.path.exists(assets_dir) or not os.listdir(assets_dir):
        print("Erro: A pasta 'assets' está vazia ou não existe. Execute 'setup_assets.py' primeiro!")
        return

    print("Configurando comandos do PyInstaller...")
    
    # PyInstaller command arguments
    # --noconfirm: Overwrite existing output directories
    # --onefile: Pack everything into a single .exe
    # --windowed: Do not display a console window
    # --add-data: Include assets folder (on Windows, format is "source;destination")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        f"--add-data=assets;assets",
        "--name=Aura",
        "--clean",
        entry_point
    ]
    
    print(f"Executando comando: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True)
        print("\n==================================================")
        print("COMPILAÇÃO CONCLUÍDA COM SUCESSO!")
        print("O arquivo executável da Aura foi criado na pasta 'dist'.")
        print(f"Caminho do arquivo: {os.path.join(current_dir, 'dist', 'Aura.exe')}")
        print("Você pode enviar este executável para qualquer PC Windows 10/11!")
        print("==================================================")
    except subprocess.CalledProcessError as e:
        print(f"Erro durante a execução do PyInstaller: {e}")
    except Exception as e:
        print(f"Erro inesperado: {e}")

if __name__ == "__main__":
    build()
