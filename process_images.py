import os
import sys
import shutil
import fnmatch
from PIL import Image

def find_latest_file(directory, pattern):
    """
    Encontra o arquivo mais recente no diretório que corresponda ao padrão.
    """
    if not os.path.exists(directory):
        return None
    files = [f for f in os.listdir(directory) if fnmatch.fnmatch(f.lower(), pattern.lower())]
    if not files:
        return None
    # Ordenar por tempo de modificação decrescente (mais recente primeiro)
    files.sort(key=lambda f: os.path.getmtime(os.path.join(directory, f)), reverse=True)
    return os.path.join(directory, files[0])

def remove_checkerboard(image_path, output_path):
    """
    Remove o fundo xadrez e as bordas externas escuras da imagem da menina
    e recorta a personagem bem rente ao corpo de forma 100% automatizada.
    """
    print(f"Processando imagem: {os.path.basename(image_path)}")
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    
    # 1. Verificar se a imagem possui borda externa escura analisando os cantos
    corner_pixels = [img.getpixel((0, 0)), img.getpixel((w-1, 0)), img.getpixel((0, h-1)), img.getpixel((w-1, h-1))]
    has_dark_border = any(all(c < 35 for c in rgb) for rgb in corner_pixels)
    
    if has_dark_border:
        data = img.load()
        non_dark_coords = []
        for y in range(h):
            for x in range(w):
                r, g, b = data[x, y]
                if r >= 35 or g >= 35 or b >= 35:
                    non_dark_coords.append((x, y))
        if non_dark_coords:
            min_x = max(0, min(c[0] for c in non_dark_coords) - 1)
            max_x = min(w - 1, max(c[0] for c in non_dark_coords) + 1)
            min_y = max(0, min(c[1] for c in non_dark_coords) - 1)
            max_y = min(h - 1, max(c[1] for c in non_dark_coords) + 1)
            crop_box = (min_x, min_y, max_x + 1, max_y + 1)
        else:
            crop_box = (0, 0, w, h)
    else:
        crop_box = (0, 0, w, h)
        
    cropped = img.crop(crop_box)
    cw, ch = cropped.size
    cropped_data = cropped.load()
    
    # 2. Executar Flood-Fill para achar o fundo xadrez (cinzas e brancos)
    visited = set()
    queue = []
    
    # Iniciar com a borda externa da imagem cortada
    for x in range(cw):
        queue.append((x, 0))
        queue.append((x, ch-1))
    for y in range(ch):
        queue.append((0, y))
        queue.append((cw-1, y))
        
    def is_bg(r, g, b):
        # O xadrez pode conter branco puro (255, 255, 255)
        return abs(r - g) < 12 and abs(g - b) < 12 and 120 < r <= 255
        
    bg_pixels = set()
    while queue:
        p = queue.pop(0)
        if p in visited:
            continue
        visited.add(p)
        
        r, g, b = cropped_data[p[0], p[1]]
        if is_bg(r, g, b):
            bg_pixels.add(p)
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = p[0] + dx, p[1] + dy
                if 0 <= nx < cw and 0 <= ny < ch and (nx, ny) not in visited:
                    queue.append((nx, ny))
                    
    # 3. Criar imagem transparente
    out_img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    out_data = out_img.load()
    
    for y in range(ch):
        for x in range(cw):
            if (x, y) not in bg_pixels:
                out_data[x, y] = cropped_data[x, y] + (255,)
                
    # 4. Cortar rente aos pixels não transparentes da personagem (removendo margens vazias)
    final_bbox = out_img.getbbox()
    if final_bbox:
        final_img = out_img.crop(final_bbox)
        final_img.save(output_path, "PNG")
        print(f"Sucesso ao salvar com transparência e recorte perfeito ({final_img.size}): {os.path.basename(output_path)}")
    else:
        out_img.save(output_path, "PNG")
        print(f"Aviso: Bounding box de recorte vazio. Salvo original em: {os.path.basename(output_path)}")

def remove_dark_background(img_cropped):
    """
    Torna transparente o fundo escuro/violeta dos sprites do lobinho.
    """
    img = img_cropped.convert("RGBA")
    width, height = img.size
    data = img.load()
    
    visited = set()
    queue = []
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height-1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width-1, y))
        
    def is_dark_bg(r, g, b):
        return (r < 40 and g < 40 and b < 65) or (r + g + b < 90)
        
    while queue:
        x, y = queue.pop(0)
        if (x, y) in visited:
            continue
        visited.add((x, y))
        
        r, g, b, a = data[x, y]
        if is_dark_bg(r, g, b) or a == 0:
            data[x, y] = (r, g, b, 0)
            for dx, dy in [(-1,0), (1,0), (0,-1), (0,1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in visited:
                    queue.append((nx, ny))
                    
    return img

def crop_wolf_sprites(src_path, dest_dir):
    """
    Recorta e processa os sprites do lobinho, garantindo tamanho correto.
    """
    os.makedirs(dest_dir, exist_ok=True)
    img_sheet = Image.open(src_path)
    
    if img_sheet.size != (1024, 1024):
        print(f"Redimensionando folha de sprites do lobinho de {img_sheet.size} para (1024, 1024)")
        img_sheet = img_sheet.resize((1024, 1024), Image.Resampling.LANCZOS)
        
    # Poses da fileira do meio (largura ~204 cada)
    mid_row_y = (510, 750)
    mid_sprites = []
    for idx in range(5):
        box = (idx * 204, mid_row_y[0], (idx + 1) * 204, mid_row_y[1])
        cropped = img_sheet.crop(box)
        processed = remove_dark_background(cropped)
        mid_sprites.append(processed)
        
    # Poses da fileira de baixo (largura ~170 cada)
    bot_row_y = (780, 980)
    bot_sprites = []
    for idx in range(6):
        box = (idx * 170, bot_row_y[0], (idx + 1) * 170, bot_row_y[1])
        cropped = img_sheet.crop(box)
        processed = remove_dark_background(cropped)
        bot_sprites.append(processed)
        
    # Salvar nos arquivos individuais
    bot_sprites[0].save(os.path.join(dest_dir, "idle.png"), "PNG")
    mid_sprites[0].save(os.path.join(dest_dir, "talking.png"), "PNG")
    bot_sprites[5].save(os.path.join(dest_dir, "happy.png"), "PNG")
    mid_sprites[2].save(os.path.join(dest_dir, "shy.png"), "PNG")
    mid_sprites[3].save(os.path.join(dest_dir, "sad.png"), "PNG")
    bot_sprites[3].save(os.path.join(dest_dir, "thinking.png"), "PNG")
    mid_sprites[2].save(os.path.join(dest_dir, "sarcastic.png"), "PNG")
    
    bot_sprites[3].save(os.path.join(dest_dir, "thought.png"), "PNG")
    mid_sprites[1].save(os.path.join(dest_dir, "curious.png"), "PNG")
    mid_sprites[1].save(os.path.join(dest_dir, "confused.png"), "PNG")
    bot_sprites[3].save(os.path.join(dest_dir, "sleeping.png"), "PNG")
    mid_sprites[1].save(os.path.join(dest_dir, "walking.png"), "PNG")
    print("Sprites do lobinho gerados com sucesso!")

def main():
    brain_dir = r"C:\Users\Admin\.gemini\antigravity\brain\8dc4d41e-87f6-4e5d-9182-5c817e7dccb4"
    workspace_dir = r"C:\Users\Admin\Documents\ia"
    
    # 1. Processar menina chibi (pasta assets)
    assets_girl = os.path.join(workspace_dir, "assets")
    os.makedirs(assets_girl, exist_ok=True)
    
    # Mapeamento dos arquivos específicos do cérebro
    girl_sources = {
        "idle.png": "aura_idle_*.png",
        "talking.png": "aura_talking_*.png",
        "shy.png": "aura_shy_*.png",
        "happy.png": "aura_happy_*.png"
    }
    
    any_girl_processed = False
    for dest_name, pattern in girl_sources.items():
        src_path = find_latest_file(brain_dir, pattern)
        if src_path and os.path.exists(src_path):
            dest_path = os.path.join(assets_girl, dest_name)
            try:
                remove_checkerboard(src_path, dest_path)
                any_girl_processed = True
            except Exception as e:
                print(f"Erro ao processar {src_path}: {e}")
        else:
            print(f"Aviso: Não encontrou arquivo para o padrão: {pattern}")
            
    # Caso o cérebro não tenha as imagens individuais separadas, tenta processar o sprite sheet único
    if not any_girl_processed:
        print("Tentando processar do sprite sheet único (media__*.png)...")
        girl_src = find_latest_file(brain_dir, "media__*.png")
        if girl_src and os.path.exists(girl_src):
            temp_path = os.path.join(assets_girl, "idle.png")
            remove_checkerboard(girl_src, temp_path)
            for pose in ["talking.png", "shy.png", "happy.png"]:
                shutil.copy2(temp_path, os.path.join(assets_girl, pose))
            any_girl_processed = True
            print("Sprite sheet único processado e copiado para poses básicas.")
            
    # Criar fallbacks coerentes para as poses restantes da menina
    if any_girl_processed:
        girl_fallbacks = {
            "thinking.png": "shy.png",
            "sad.png": "shy.png",
            "sarcastic.png": "happy.png",
            "thought.png": "shy.png",
            "curious.png": "happy.png",
            "confused.png": "shy.png",
            "sleeping.png": "shy.png",
            "walking.png": "curious.png"
        }
        for dest, src in girl_fallbacks.items():
            src_path = os.path.join(assets_girl, src)
            dest_path = os.path.join(assets_girl, dest)
            if os.path.exists(src_path):
                shutil.copy2(src_path, dest_path)
                print(f"Criado pose: {dest} (de {src})")
                
    # 2. Processar lobinho (pasta assets_wolf)
    assets_wolf = os.path.join(workspace_dir, "assets_wolf")
    wolf_src = find_latest_file(brain_dir, "media__*.jpg")
    if not wolf_src:
        pngs = [f for f in os.listdir(brain_dir) if fnmatch.fnmatch(f.lower(), "media__*.png")]
        for p in pngs:
            p_path = os.path.join(brain_dir, p)
            try:
                with Image.open(p_path) as test_img:
                    if test_img.size[0] > 500:
                        wolf_src = p_path
                        break
            except Exception:
                pass
                
    if wolf_src and os.path.exists(wolf_src):
        print(f"Folha de sprites do Lobinho encontrada em: {wolf_src}")
        crop_wolf_sprites(wolf_src, assets_wolf)
    else:
        print("Aviso: Folha de sprites do lobinho não encontrada no cérebro.")

if __name__ == "__main__":
    main()
