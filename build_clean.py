import os
import sys
import shutil
import subprocess

def run_cmd(args, cwd):
    print(f"Executando: {' '.join(args)} em {cwd}")
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Erro ao executar comando! Código: {result.returncode}")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        raise Exception(f"Comando falhou: {args[0]}")
    return result.stdout

def build():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    temp_build_dir = r"C:\Users\Admin\AppData\Local\Temp\AuraCleanBuild"
    
    print(f"--- Iniciando Compilação Limpa ---")
    print(f"Workspace originário: {workspace_dir}")
    print(f"Diretório temporário de build: {temp_build_dir}")
    
    if os.path.exists(temp_build_dir):
        print("Removendo diretório temporário antigo...")
        shutil.rmtree(temp_build_dir, ignore_errors=True)
        
    os.makedirs(temp_build_dir, exist_ok=True)
    
    # 1. Copy source files to temp build directory
    files_to_copy = ["gui.py", "llm_client.py", "voice_engine.py", "system_tools.py", "requirements.txt", "installer.py"]
    for f in files_to_copy:
        src = os.path.join(workspace_dir, f)
        dest = os.path.join(temp_build_dir, f)
        if os.path.exists(src):
            shutil.copy2(src, dest)
            print(f"Copiado: {f}")
        else:
            print(f"AVISO: Arquivo de origem não encontrado: {src}")
            
    # Copy assets
    src_assets = os.path.join(workspace_dir, "assets")
    dest_assets = os.path.join(temp_build_dir, "assets")
    if os.path.exists(src_assets):
        shutil.copytree(src_assets, dest_assets)
        print("Pasta assets copiada.")
    else:
        print(f"AVISO: Pasta de assets não encontrada: {src_assets}")
        
    # Copy assets_wolf
    src_assets_wolf = os.path.join(workspace_dir, "assets_wolf")
    dest_assets_wolf = os.path.join(temp_build_dir, "assets_wolf")
    if os.path.exists(src_assets_wolf):
        shutil.copytree(src_assets_wolf, dest_assets_wolf)
        print("Pasta assets_wolf copiada.")
    else:
        print(f"AVISO: Pasta de assets_wolf não encontrada: {src_assets_wolf}")
        
    # 2. Create local virtual environment in the temp directory (no commas!)
    print("Criando ambiente virtual limpo...")
    run_cmd([sys.executable, "-m", "venv", ".venv"], temp_build_dir)
    
    venv_pip = os.path.join(temp_build_dir, ".venv", "Scripts", "pip.exe")
    venv_python = os.path.join(temp_build_dir, ".venv", "Scripts", "python.exe")
    
    # 3. Install requirements and pyinstaller inside the temp environment
    print("Instalando dependências a partir do cache local...")
    run_cmd([venv_pip, "install", "-r", "requirements.txt"], temp_build_dir)
    
    print("Instalando PyInstaller...")
    run_cmd([venv_pip, "install", "pyinstaller"], temp_build_dir)
    
    # 4. Run PyInstaller in the temp directory
    print("Compilando aplicativo com PyInstaller...")
    cmd = [
        venv_python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--add-data=assets;assets",
        "--add-data=assets_wolf;assets_wolf",
        "--name=Aura",
        "--clean",
        "gui.py"
    ]
    
    run_cmd(cmd, temp_build_dir)
    
    # 4.2 Compilar o Instalador
    print("Compilando o Instalador com PyInstaller...")
    cmd_installer = [
        venv_python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--add-data=dist/Aura.exe;.",
        "--add-data=assets;assets",
        "--add-data=assets_wolf;assets_wolf",
        "--name=Instalador_Aura",
        "--clean",
        "installer.py"
    ]
    run_cmd(cmd_installer, temp_build_dir)
    
    # 5. Copy the compiled .exes back to the workspace dist directory
    workspace_dist = os.path.join(workspace_dir, "dist")
    os.makedirs(workspace_dist, exist_ok=True)
    
    # Aura.exe
    compiled_exe = os.path.join(temp_build_dir, "dist", "Aura.exe")
    target_exe = os.path.join(workspace_dist, "Aura.exe")
    
    if os.path.exists(compiled_exe):
        if os.path.exists(target_exe):
            try:
                os.remove(target_exe)
            except PermissionError:
                print("Aura.exe está em execução. Renomeando para permitir a substituição...")
                old_exe = target_exe + ".old"
                if os.path.exists(old_exe):
                    try:
                        os.remove(old_exe)
                    except Exception:
                        pass
                try:
                    os.rename(target_exe, old_exe)
                except Exception as e:
                    print(f"Erro ao renomear executável antigo: {e}")
        try:
            shutil.copy2(compiled_exe, target_exe)
            print(f"Sucesso! O executável Aura.exe foi movido para: {target_exe}")
        except Exception as e:
            print(f"Erro ao copiar novo executável para dist: {e}")
    else:
        print("Erro: O executável Aura.exe compilado não foi encontrado.")

    # Instalador_Aura.exe
    compiled_installer = os.path.join(temp_build_dir, "dist", "Instalador_Aura.exe")
    target_installer = os.path.join(workspace_dist, "Instalador_Aura.exe")
    
    if os.path.exists(compiled_installer):
        if os.path.exists(target_installer):
            try:
                os.remove(target_installer)
            except PermissionError:
                print("Instalador_Aura.exe está em execução. Renomeando para permitir a substituição...")
                old_inst = target_installer + ".old"
                if os.path.exists(old_inst):
                    try:
                        os.remove(old_inst)
                    except Exception:
                        pass
                try:
                    os.rename(target_installer, old_inst)
                except Exception as e:
                    print(f"Erro ao renomear instalador antigo: {e}")
        try:
            shutil.copy2(compiled_installer, target_installer)
            print(f"Sucesso! O Instalador foi movido para: {target_installer}")
        except Exception as e:
            print(f"Erro ao copiar novo instalador para dist: {e}")
    else:
        print("Erro: O Instalador compilado não foi encontrado.")
        
    # 6. Clean up temporary directory
    print("Limpando arquivos temporários de compilação...")
    shutil.rmtree(temp_build_dir, ignore_errors=True)
    print("Processo concluído com sucesso!")

if __name__ == "__main__":
    build()
