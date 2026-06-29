import os
import sys
import json
import logging
import sqlite3
import requests
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AuraDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_profile (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS facts (fact TEXT PRIMARY KEY)")
        cursor.execute("CREATE TABLE IF NOT EXISTS assistant_state (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, text TEXT)")
        conn.commit()
        conn.close()

    def get_config(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'main'")
        row = cursor.fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row[0])
            except:
                pass
        return None

    def save_config(self, config_dict):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('main', ?)", 
                      (json.dumps(config_dict, ensure_ascii=False),))
        conn.commit()
        conn.close()

    def get_user_profile(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM user_profile WHERE key = 'profile'")
        row = cursor.fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row[0])
            except:
                pass
        return None

    def save_user_profile(self, profile_dict):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_profile (key, value) VALUES ('profile', ?)", 
                      (json.dumps(profile_dict, ensure_ascii=False),))
        conn.commit()
        conn.close()

    def get_facts(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT fact FROM facts")
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def add_fact(self, fact):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO facts (fact) VALUES (?)", (fact,))
            conn.commit()
        except Exception as e:
            logging.error(f"Erro ao adicionar fato: {e}")
        conn.close()

    def get_assistant_state(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM assistant_state")
        rows = cursor.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}

    def save_assistant_state(self, state_dict):
        conn = self.get_connection()
        cursor = conn.cursor()
        for k, v in state_dict.items():
            cursor.execute("INSERT OR REPLACE INTO assistant_state (key, value) VALUES (?, ?)", (k, str(v)))
        conn.commit()
        conn.close()

    def get_history(self, limit=20):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT role, text FROM history ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [{"role": r[0], "text": r[1]} for r in reversed(rows)]

    def add_history_entry(self, role, text):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO history (role, text) VALUES (?, ?)", (role, text))
        conn.commit()
        conn.close()

    def clear_history(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history")
        conn.commit()
        conn.close()


class LocalVectorStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector_store (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT,
                text TEXT,
                vector TEXT,
                metadata TEXT
            )
        """)
        conn.commit()
        conn.close()

    def get_embedding(self, text, api_key=None):
        """
        Gera embeddings. Se houver api_key do Gemini, tenta o text-embedding-004 do Gemini.
        Caso contrário ou em caso de erro, usa TF-IDF local (128 posições).
        """
        if api_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "model": "models/text-embedding-004",
                    "content": {"parts": [{"text": text}]}
                }
                res = requests.post(url, headers=headers, json=payload, timeout=5, verify=False)
                if res.status_code == 200:
                    embedding = res.json().get("embedding", {}).get("values", [])
                    if embedding:
                        return embedding
            except Exception:
                pass

        # TF-IDF Hash local simplificado (128 posições)
        import hashlib
        words = [w.lower() for w in text.split() if len(w) > 2]
        vector = [0.0] * 128
        if not words:
            return vector
            
        for w in words:
            h_idx = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16) % 128
            vector[h_idx] += 1.0
            
        # Normalização L2
        norm = sum(x*x for x in vector) ** 0.5
        if norm > 0:
            vector = [x / norm for x in vector]
        return vector

    def add_document(self, collection, text, metadata=None, api_key=None):
        vector = self.get_embedding(text, api_key)
        vector_json = json.dumps(vector)
        metadata_json = json.dumps(metadata or {})
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO vector_store (collection, text, vector, metadata) VALUES (?, ?, ?, ?)",
            (collection, text, vector_json, metadata_json)
        )
        conn.commit()
        conn.close()

    def query(self, collection, query_text, top_k=3, api_key=None):
        query_vector = self.get_embedding(query_text, api_key)
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT text, vector, metadata FROM vector_store WHERE collection = ?", (collection,))
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for text, vector_str, metadata_str in rows:
            try:
                vector = json.loads(vector_str)
                metadata = json.loads(metadata_str)
                # Cosine Similarity (ambos L2-norm, então produto escalar é a similaridade)
                score = sum(a*b for a, b in zip(query_vector, vector))
                results.append((score, text, metadata))
            except Exception:
                continue
                
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:top_k]


class LLMClient:
    def __init__(self, workspace_dir=None):
        self.workspace_dir = workspace_dir or os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Aura")
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "aura_data.db")
        self.db = AuraDatabase(self.db_path)
        self.config = self.load_config()
        self.memory = self.load_memory()
        self.vector_store = LocalVectorStore(self.db_path)

    def load_config(self):
        default_config = {
            "api_key": "",
            "assistant_name": "Aura",
            "personality": {"shy": 50, "funny": 50, "sarcasm": 30, "humor": 70},
            "voice": {"gender": "female", "speed": 1.0, "volume": 1.0},
            "use_wake_word": True,
            "avatar_scale": 180,
            "use_offline_tts": False,
            "use_custom_voice": False,
            "elevenlabs_api_key": "",
            "elevenlabs_voice_id": "",
            "autonomous_learning": True,
            "emotion_autonomy": True,
            "autonomous_movement": True
        }
        db_config = self.db.get_config()
        if db_config:
            return {**default_config, **db_config}
        self.db.save_config(default_config)
        return default_config

    def save_config(self, config=None):
        if config:
            self.config = config
        try:
            self.db.save_config(self.config)
            logging.info("Configurações salvas com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao salvar configurações: {e}")

    def load_memory(self):
        db_profile = self.db.get_user_profile()
        if not db_profile:
            db_profile = {"name": "Mestre", "preferences": {}}
            self.db.save_user_profile(db_profile)
        
        db_facts = self.db.get_facts()
        db_state = self.db.get_assistant_state()
        db_history = self.db.get_history(20)
        
        return {
            "user_profile": {
                "name": db_profile.get("name", "Mestre"),
                "preferences": db_profile.get("preferences", {}),
                "facts_learned": db_facts
            },
            "assistant_state": {
                "affection": int(db_state.get("affection", 50)),
                "mood": db_state.get("mood", "HAPPY")
            },
            "history": db_history
        }

    def save_memory(self):
        try:
            profile = {
                "name": self.memory["user_profile"].get("name", "Mestre"),
                "preferences": self.memory["user_profile"].get("preferences", {})
            }
            self.db.save_user_profile(profile)
            
            for fact in self.memory["user_profile"].get("facts_learned", []):
                self.db.add_fact(fact)
                
            state = {
                "affection": self.memory["assistant_state"].get("affection", 50),
                "mood": self.memory["assistant_state"].get("mood", "HAPPY")
            }
            self.db.save_assistant_state(state)
        except Exception as e:
            logging.error(f"Erro ao salvar memória: {e}")

    def clear_history(self):
        self.memory["history"] = []
        try:
            self.db.clear_history()
            logging.info("Histórico apagado.")
        except Exception as e:
            logging.error(f"Erro ao limpar histórico: {e}")

    def get_system_instruction(self):
        name = self.config.get("assistant_name", "Aura")
        pers = self.config.get("personality", {})
        user_name = self.memory["user_profile"].get("name", "Mestre")
        
        return (
            f"Você é {name}, uma assistente virtual de desktop.\n"
            f"Personalidade: tímida={pers.get('shy', 50)}, engraçada={pers.get('funny', 50)}, "
            f"sarcástica={pers.get('sarcasm', 30)}\n"
            f"Usuário: {user_name}\n\n"
            "Responda de forma curta (2-3 frases) em português.\n"
            "Retorne no formato JSON:\n"
            '{"reply": "sua resposta", "emotion": "HAPPY", "actions": []}'
        )

    def get_rag_context(self, query_text):
        api_key = self.config.get("api_key", "")
        rag_context = ""
        try:
            memories = self.vector_store.query("memories", query_text, top_k=2, api_key=api_key)
            documents = self.vector_store.query("documents", query_text, top_k=3, api_key=api_key)
            
            context_pieces = []
            if memories:
                context_pieces.append("Memórias do Usuário Recuperadas:")
                for score, text, meta in memories:
                    if score > 0.15:
                        context_pieces.append(f"- {text}")
            if documents:
                context_pieces.append("Documentos Locais Recuperados (RAG):")
                for score, text, meta in documents:
                    if score > 0.15:
                        source = meta.get("source", "arquivo")
                        context_pieces.append(f"- [{source}]: {text}")
                        
            if context_pieces:
                rag_context = "\n[CONTEXTO VETORIAL DE LONGO PRAZO (RAG):\n" + "\n".join(context_pieces) + "\n]"
        except Exception as e:
            logging.error(f"Erro ao recuperar contexto RAG: {e}")
        return rag_context

    def local_offline_reply(self, user_text):
        """
        Gera uma resposta inteligente 100% offline usando o banco de dados SQLite local
        para responder, aprender fatos e executar comandos básicos.
        """
        import re
        import random
        text_clean = user_text.strip().lower()
        uname = self.memory["user_profile"].get("name", "Mestre")
        name = self.config.get("assistant_name", "Aura")
        
        # 1. Comando de aprendizado (ex: "Aprenda que..." ou "Lembre que...")
        learn_patterns = [
            r"(?:aprenda|lembre|salve|grave)\s+que\s+(.+)",
            r"(?:meu|minha)\s+(.+)\s+é\s+(.+)"
        ]
        
        for pattern in learn_patterns:
            match = re.search(pattern, text_clean)
            if match:
                if len(match.groups()) == 1:
                    fact = match.group(1).strip()
                else:
                    fact = f"{match.group(1).strip()} é {match.group(2).strip()}"
                
                # Salvar o fato no banco de dados SQLite local
                self.db.add_fact(fact)
                # Salvar no Banco Vetorial local (Mem0-like)
                api_key = self.config.get("api_key", "")
                self.vector_store.add_document("memories", fact, {"type": "user_fact"}, api_key=api_key)
                
                # Salvar também no perfil em memória
                if "facts_learned" not in self.memory["user_profile"]:
                    self.memory["user_profile"]["facts_learned"] = []
                if fact not in self.memory["user_profile"]["facts_learned"]:
                    self.memory["user_profile"]["facts_learned"].append(fact)
                self.save_memory()
                
                reply = f"Entendido, {uname}! Salvei essa informação na minha memória vetorial local: '{fact}'. Já aprendi! 🧠✨"
                return {"reply": reply, "emotion": "HAPPY", "actions": []}
                
        # 2. Comando de consulta de memória com suporte RAG / Busca Vetorial local
        rag_context = self.get_rag_context(user_text)
        if rag_context:
            # Se encontrou fatos na memória vetorial ou documentos locais (RAG), responde baseado neles!
            reply_lines = [f"Mestre {uname}, consultei meu banco de dados vetorial offline:"]
            reply_lines.append(rag_context.strip())
            reply_lines.append("Como posso te ajudar mais com isso? 😊")
            return {"reply": "\n".join(reply_lines), "emotion": "HAPPY", "actions": []}
            
        if any(q in text_clean for q in ["o que", "qual", "quem", "lembra", "sabe"]):
            facts = self.db.get_facts()
            # Procurar por palavras-chave do texto nos fatos salvos
            words = [w for w in text_clean.split() if len(w) > 3]
            for fact in facts:
                for word in words:
                    if word in fact.lower():
                        reply = f"Eu lembro disso, {uname}! Minha memória diz: '{fact}'. 😊"
                        return {"reply": reply, "emotion": "HAPPY", "actions": []}
            
            # Se perguntou quem sou eu
            if "quem sou eu" in text_clean:
                reply = f"Você é o meu querido mestre, {uname}! O administrador do meu sistema. 🥰"
                return {"reply": reply, "emotion": "HAPPY", "actions": []}

        # 3. Comandos básicos de sistema offline
        actions = []
        if "calculadora" in text_clean:
            actions.append({"type": "open_program", "name": "calc.exe"})
            return {"reply": f"Abrindo a calculadora para você, {uname}!", "emotion": "HAPPY", "actions": actions}
        elif "bloco de notas" in text_clean or "notepad" in text_clean:
            actions.append({"type": "open_program", "name": "notepad.exe"})
            return {"reply": f"Abrindo o Bloco de Notas, mestre!", "emotion": "HAPPY", "actions": actions}
        elif "cmd" in text_clean or "prompt" in text_clean:
            actions.append({"type": "open_program", "name": "cmd.exe"})
            return {"reply": "Abrindo o prompt de comando.", "emotion": "HAPPY", "actions": actions}
            
        # 4. Saudações comuns
        greetings = ["olá", "oi", "bom dia", "boa tarde", "boa noite", "hello"]
        if any(g in text_clean for g in greetings):
            replies = [
                f"Oi, {uname}! Estou operando offline agora, mas adorando conversar com você! 😊",
                f"Olá, mestre {uname}! Como posso ajudar você hoje localmente? 🌸",
                f"Oi! Sentiu saudades? Estou online na minha memória local! 😳"
            ]
            return {"reply": random.choice(replies), "emotion": "HAPPY", "actions": []}
            
        # 5. Fallback padrão fofo
        fallbacks = [
            f"Mestre {uname}, estou operando no modo offline porque meu cérebro na nuvem está sem conexão. Mas eu guardei tudo o que você me ensinou na minha memória local! 😳",
            f"Estou sem conexão com a API do Gemini agora, mestre. Mas posso abrir programas, guardar fatos locais na minha memória ou apenas te fazer companhia! 😉",
            f"A internet parece instável, mestre. Mas não se preocupe, eu continuo aqui do seu ladinho usando meu banco de dados local! 🥰"
        ]
        return {"reply": random.choice(fallbacks), "emotion": "SHY", "actions": []}

    def send_message(self, user_text, image_b64=None):
        api_key = self.config.get("api_key", "")
        if not api_key:
            return self.local_offline_reply(user_text)
            
        # Busca contexto vetorial (RAG)
        rag_context = self.get_rag_context(user_text)
        user_text_with_rag = user_text
        if rag_context:
            user_text_with_rag = f"{user_text}\n\n{rag_context}"
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        
        # History
        history_contents = []
        for msg in self.memory.get("history", [])[-10:]:
            try:
                js_val = json.loads(msg["text"])
                text_val = js_val.get("reply", msg["text"])
            except:
                text_val = msg["text"]
            history_contents.append({
                "role": "user" if msg["role"] == "user" else "model",
                "parts": [{"text": text_val}]
            })
        
        current_parts = []
        if image_b64:
            current_parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_b64}})
        current_parts.append({"text": user_text_with_rag})
        history_contents.append({"role": "user", "parts": current_parts})
        
        payload = {
            "contents": history_contents,
            "systemInstruction": {"parts": [{"text": self.get_system_instruction()}]},
            "generationConfig": {"temperature": 0.5, "responseMimeType": "application/json"}
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=12, verify=False)
            response.raise_for_status()
            res_json = response.json()
            
            raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
            
            try:
                parsed = json.loads(raw_text)
                
                # Save history
                self.db.add_history_entry("user", user_text[:300])
                self.db.add_history_entry("model", json.dumps(parsed, ensure_ascii=False))
                self.memory["history"].append({"role": "user", "text": user_text[:300]})
                self.memory["history"].append({"role": "model", "text": json.dumps(parsed, ensure_ascii=False)})
                
                return parsed
                
            except json.JSONDecodeError:
                fallback = raw_text.strip()
                self.db.add_history_entry("user", user_text[:300])
                self.db.add_history_entry("model", fallback)
                return {"reply": fallback, "emotion": "HAPPY", "actions": []}
                
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            logging.warning("API do Gemini indisponível. Ativando cérebro offline local.")
            return self.local_offline_reply(user_text)
        except Exception as e:
            logging.error(f"Erro na chamada Gemini: {e}. Ativando cérebro offline local.")
            return self.local_offline_reply(user_text)


if __name__ == "__main__":
    client = LLMClient()
    print("✅ LLMClient inicializado com sucesso!")