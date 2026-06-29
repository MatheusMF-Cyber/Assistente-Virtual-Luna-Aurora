import os
import shutil

def setup():
    # Source paths
    artifact_dir = r"C:\Users\Admin\.gemini\antigravity\brain\8dc4d41e-87f6-4e5d-9182-5c817e7dccb4"
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(workspace_dir, "assets")
    
    os.makedirs(assets_dir, exist_ok=True)
    
    files_to_copy = {
        "aura_idle_1781835711868.png": "idle.png",
        "aura_talking_1781835723637.png": "talking.png",
        "aura_shy_1781835734602.png": "shy.png",
        "aura_happy_1781835744617.png": "happy.png"
    }
    
    # Also add duplicates for thinking, sad, sarcastic using fallback to make sure all emotions have images
    emotion_fallbacks = {
        "thinking.png": "idle.png",
        "sad.png": "shy.png",
        "sarcastic.png": "happy.png"
    }
    
    print("Iniciando cópia dos arquivos do avatar...")
    for src_name, dest_name in files_to_copy.items():
        src_path = os.path.join(artifact_dir, src_name)
        dest_path = os.path.join(assets_dir, dest_name)
        
        if os.path.exists(src_path):
            try:
                shutil.copy2(src_path, dest_path)
                print(f"Copiado: {src_name} -> {dest_name}")
            except Exception as e:
                print(f"Erro ao copiar {src_name}: {e}")
        else:
            print(f"Aviso: Arquivo de origem não encontrado: {src_path}")
            
    # Copy fallbacks
    for dest_name, src_ref in emotion_fallbacks.items():
        src_path = os.path.join(assets_dir, src_ref)
        dest_path = os.path.join(assets_dir, dest_name)
        if os.path.exists(src_path) and not os.path.exists(dest_path):
            try:
                shutil.copy2(src_path, dest_path)
                print(f"Criado fallback: {src_ref} -> {dest_name}")
            except Exception as e:
                print(f"Erro ao criar fallback {dest_name}: {e}")
                
    print("Configuração de ativos concluída.")

if __name__ == "__main__":
    setup()
