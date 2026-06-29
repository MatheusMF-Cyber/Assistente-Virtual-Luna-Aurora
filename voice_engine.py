import os
import sys
import logging
import asyncio
import threading
import tempfile
import requests
import edge_tts
import pyttsx3
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# PySide6 components for audio playback
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl, QObject, Signal

# Handle optional dependencies for STT
STT_AVAILABLE = False
try:
    import speech_recognition as sr
    STT_AVAILABLE = True
except ImportError:
    logging.warning("SpeechRecognition ou PyAudio não instalados. Reconhecimento de voz desativado.")

class VoiceEngineSignals(QObject):
    finished_speaking = Signal()
    heard_text = Signal(str)
    listening_status = Signal(bool)  # True if listening, False if idle

class VoiceEngine:
    def __init__(self, main_gui=None):
        self.main_gui = main_gui
        self.workspace_dir = main_gui.workspace_dir if main_gui else os.path.dirname(os.path.abspath(__file__))
        self.signals = VoiceEngineSignals()
        
        # Audio Player (PySide6 native)
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        
        # Offline TTS Engine (pyttsx3)
        self.offline_engine = None
        try:
            self.offline_engine = pyttsx3.init()
            self.offline_engine.setProperty('rate', 170)
        except Exception as e:
            logging.error(f"Erro ao inicializar pyttsx3: {e}")
            
        # STT variables
        self.recognizer = None
        self.microphone = None
        self.stop_listening_fn = None
        self.is_listening = False
        self.wake_word = "aura"
        
        if STT_AVAILABLE:
            try:
                self.recognizer = sr.Recognizer()
                self.microphone = sr.Microphone()
                self.recognizer.pause_threshold = 0.8  # Espera 0.8s para evitar cortes prematuros no meio da fala
                self.recognizer.non_speaking_duration = 0.5 # Dá tempo razoável para fechar frase
            except Exception as e:
                logging.error(f"Erro ao inicializar Microfone/STT: {e}")
                self.microphone = None

    def _playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self.signals.finished_speaking.emit()

    def speak_neural(self, text, gender="female", speed=1.0):
        """
        Sintetiza voz usando o Microsoft Edge Neural TTS (100% gratuito, estilo Google Assistant).
        """
        import asyncio
        import edge_tts
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, "aura_neural_speech.mp3")
        
        # Seleciona voz neural em português do Brasil
        if gender == "male":
            voice = "pt-BR-AntonioNeural"
        else:
            voice = "pt-BR-FranciscaNeural"
            
        # Converter velocidade para formato do edge-tts (ex: "+0%", "+10%", "-5%")
        rate_percent = int((speed - 1.0) * 100)
        rate_str = f"{rate_percent:+d}%" if rate_percent != 0 else "+0%"
        
        async def generate_speech():
            try:
                communicate = edge_tts.Communicate(text, voice, rate=rate_str)
                await communicate.save(temp_path)
                return True
            except Exception as e:
                logging.error(f"Erro ao gerar Edge TTS: {e}")
                return False
                
        def run_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success = loop.run_until_complete(generate_speech())
                loop.close()
                
                if success and os.path.exists(temp_path):
                    print("   ⚡ Edge TTS gerado e reproduzido com sucesso!")
                    self.player.setSource(QUrl.fromLocalFile(temp_path))
                    self.player.play()
                else:
                    raise Exception("Falha na geração do arquivo Edge TTS")
            except Exception as e:
                logging.warning(f"Edge TTS indisponível. Usando pyttsx3 offline: {e}")
                self.speak_offline_sapi(text, gender, speed)
                
        threading.Thread(target=run_thread, daemon=True).start()

    def speak(self, text, gender="female", speed=1.0, volume=1.0):
        """
        Falar um texto. Se a voz clonada estiver ativada nas configurações, usa ElevenLabs.
        Caso contrário, usa o Microsoft Edge Neural TTS (voz natural, estilo Google Assistant).
        """
        print(f"🔊 speak() chamado: '{text[:50]}...'")
        self.audio_output.setVolume(volume)
        
        use_custom_voice = False
        api_key = ""
        voice_id = ""
        
        if self.main_gui and hasattr(self.main_gui, "llm"):
            config = self.main_gui.llm.config
            use_custom_voice = config.get("use_custom_voice", False)
            api_key = config.get("elevenlabs_api_key", "").strip()
            voice_id = config.get("elevenlabs_voice_id", "").strip()
            
        if use_custom_voice and api_key and voice_id:
            print("   → Usando ElevenLabs (Voz Clonada)")
            self.speak_elevenlabs(text, api_key, voice_id, volume)
        else:
            print("   → Usando Microsoft Edge Neural TTS (Estilo Google Assistant)")
            self.speak_neural(text, gender, speed)

    def speak_elevenlabs(self, text, api_key, voice_id, volume=1.0):
        """
        Sintetiza voz usando a própria voz clonada do usuário via ElevenLabs com cache persistente.
        """
        import hashlib
        self.audio_output.setVolume(volume)
        
        cache_dir = os.path.join(self.workspace_dir, "voice_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # Gerar hash único para o texto + ID da voz
        text_hash = hashlib.md5(f"{text}_{voice_id}".encode("utf-8")).hexdigest()
        cached_file_path = os.path.join(cache_dir, f"{text_hash}.mp3")
        
        # Se já está no cache, reproduzir instantaneamente!
        if os.path.exists(cached_file_path):
            print(f"   ⚡ Áudio carregado do cache instantaneamente: '{text[:30]}...'")
            self.player.setSource(QUrl.fromLocalFile(cached_file_path))
            self.player.play()
            return
            
        def run_elevenlabs():
            try:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {
                    "Accept": "audio/mpeg",
                    "Content-Type": "application/json",
                    "xi-api-key": api_key
                }
                data = {
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                }
                response = requests.post(url, json=data, headers=headers, timeout=12)
                response.raise_for_status()
                
                # Salvar no cache persistente
                with open(cached_file_path, "wb") as f:
                    f.write(response.content)
                    
                self.player.setSource(QUrl.fromLocalFile(cached_file_path))
                self.player.play()
                
                # Limpeza automática do cache (evita crescimento exagerado)
                try:
                    files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith(".mp3")]
                    if len(files) > 100:
                        files.sort(key=os.path.getmtime)
                        for old_f in files[:20]:
                            try:
                                os.remove(old_f)
                            except Exception:
                                pass
                except Exception:
                    pass
            except Exception as e:
                logging.error(f"Erro ao usar ElevenLabs para voz personalizada: {e}")
                # Fallback automático para Edge Neural TTS
                gender = "female"
                speed = 1.0
                if self.main_gui and hasattr(self.main_gui, "llm"):
                    gender = self.main_gui.llm.config.get("voice", {}).get("gender", "female")
                    speed = self.main_gui.llm.config.get("voice", {}).get("speed", 1.0)
                self.speak_neural(text, gender, speed)
                
        threading.Thread(target=run_elevenlabs, daemon=True).start()

    def speak_offline_sapi(self, text, gender="female", speed=1.0):
        """
        Geração de áudio usando SAPI5 local (pyttsx3) - Totalmente offline e instantâneo.
        VERSÃO CORRIGIDA COM MAIS DIAGNÓSTICOS.
        """
        print(f"🔊 speak_offline_sapi: '{text[:50]}...'")
        
        if not self.offline_engine:
            logging.error("Nenhum motor de TTS disponível. Tentando reinicializar...")
            try:
                self.offline_engine = pyttsx3.init()
                print("   ✅ pyttsx3 reinicializado com sucesso!")
            except Exception as e:
                print(f"   ❌ Falha ao reinicializar pyttsx3: {e}")
                self.signals.finished_speaking.emit()
                return
            
        def run_offline():
            try:
                print("   🔊 Gerando áudio offline...")
                
                # Configurar velocidade
                base_rate = 170
                self.offline_engine.setProperty('rate', int(base_rate * speed))
                print(f"   📊 Velocidade: {int(base_rate * speed)}")
                
                # Selecionar voz
                voices = self.offline_engine.getProperty('voices')
                selected_voice = None
                
                print(f"   🔍 Vozes disponíveis: {len(voices)}")
                
                # Priorizar vozes em português
                for v in voices:
                    v_name = v.name.lower() if hasattr(v, 'name') else str(v).lower()
                    v_id = v.id.lower() if hasattr(v, 'id') else ''
                    
                    if "portuguese" in v_name or "brazil" in v_name or "pt-br" in v_id:
                        if gender == "female" and ("maria" in v_name or "female" in v_name or "zira" in v_name):
                            selected_voice = v.id
                            print(f"   ✅ Voz feminina selecionada: {v.name}")
                            break
                        elif gender == "male" and ("daniel" in v_name or "male" in v_name or "david" in v_name):
                            selected_voice = v.id
                            print(f"   ✅ Voz masculina selecionada: {v.name}")
                            break
                
                # Fallback: qualquer voz em português
                if not selected_voice:
                    for v in voices:
                        v_name = v.name.lower() if hasattr(v, 'name') else ''
                        if "portuguese" in v_name or "brazil" in v_name:
                            selected_voice = v.id
                            print(f"   ✅ Voz fallback selecionada: {v.name}")
                            break
                
                # Último fallback: primeira voz disponível
                if not selected_voice and voices:
                    selected_voice = voices[0].id
                    print(f"   ⚠️ Voz padrão selecionada (sem português)")
                
                if selected_voice:
                    self.offline_engine.setProperty('voice', selected_voice)
                    print("   ✅ Voz configurada")
                
                # Falar
                print(f"   🗣️ Falando: '{text}'")
                self.offline_engine.say(text)
                self.offline_engine.runAndWait()
                print("   ✅ Fala concluída")
                
            except Exception as e:
                print(f"   ❌ Erro ao falar offline: {e}")
                logging.error(f"Erro ao falar offline: {e}")
            finally:
                self.signals.finished_speaking.emit()
                print("   ✅ sinal finished_speaking emitido")
                
        threading.Thread(target=run_offline, daemon=True).start()

    def clone_voice_from_file(self, api_key, file_path, voice_name="Aura Custom Voice"):
        """
        Clona uma voz na ElevenLabs a partir de um arquivo de áudio ou vídeo local.
        Retorna o voice_id se bem-sucedido.
        """
        import requests
        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {
            "xi-api-key": api_key
        }
        data = {
            "name": voice_name,
            "description": "Voz personalizada clonada via Aura Assistant."
        }
        
        mime = "audio/mpeg"
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".wav":
            mime = "audio/wav"
        elif ext == ".mp4":
            mime = "video/mp4"
        elif ext == ".m4a":
            mime = "audio/mp4"
            
        try:
            with open(file_path, "rb") as f:
                files = [
                    ("files", (os.path.basename(file_path), f, mime))
                ]
                logging.info(f"Enviando arquivo {file_path} para ElevenLabs para clonagem...")
                response = requests.post(url, headers=headers, data=data, files=files, timeout=45)
                response.raise_for_status()
                res_data = response.json()
                voice_id = res_data.get("voice_id")
                logging.info(f"Voz clonada criada com ID: {voice_id}")
                return voice_id
        except Exception as e:
            logging.error(f"Erro ao clonar voz na ElevenLabs: {e}")
            raise e

    def start_listening(self, wake_word="aura"):
        """
        Inicia a escuta em segundo plano pelo microfone.
        """
        if not STT_AVAILABLE:
            logging.warning("STT indisponível.")
            return False
            
        if self.is_listening:
            return True
            
        # Re-instancia o microfone para limpar qualquer estado de context manager travado
        try:
            self.microphone = sr.Microphone()
        except Exception as e:
            logging.error(f"Erro ao instanciar microfone: {e}")
            return False
            
        self.wake_word = wake_word.strip().lower()
        self.is_listening = True
        self.signals.listening_status.emit(True)
        
        try:
            def calibrate_and_start():
                try:
                    # Configuração de alta sensibilidade e adaptação dinâmica de ruído
                    self.recognizer.energy_threshold = 300
                    self.recognizer.dynamic_energy_threshold = True
                    self.recognizer.dynamic_energy_adjustment_damping = 0.15
                    self.recognizer.dynamic_energy_ratio = 1.5
                    
                    with self.microphone as source:
                        # Calibração rápida de ruído de fundo
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        
                    # Limita o limiar de energia para garantir que ela sempre ouça vozes normais
                    if self.recognizer.energy_threshold > 450:
                        self.recognizer.energy_threshold = 450
                    logging.info(f"Microfone ativado. Limiar de energia calibrado para: {self.recognizer.energy_threshold}")
                    
                    self.stop_listening_fn = self.recognizer.listen_in_background(
                        self.microphone, 
                        self._audio_callback,
                        phrase_time_limit=10.0
                    )
                    logging.info("Escuta em segundo plano iniciada com sucesso.")
                except Exception as e:
                    logging.error(f"Erro ao calibrar microfone: {e}")
                    self.is_listening = False
                    self.signals.listening_status.emit(False)
            
            threading.Thread(target=calibrate_and_start, daemon=True).start()
            return True
        except Exception as e:
            logging.error(f"Erro ao iniciar escuta: {e}")
            self.is_listening = False
            self.signals.listening_status.emit(False)
            return False

    def stop_listening(self):
        if self.stop_listening_fn:
            self.stop_listening_fn(wait_for_stop=False)
            self.stop_listening_fn = None
        self.is_listening = False
        self.signals.listening_status.emit(False)
        logging.info("Escuta em segundo plano parada.")

    def _audio_callback(self, recognizer, audio):
        if not self.is_listening:
            return
            
        try:
            text = recognizer.recognize_google(audio, language="pt-BR")
            text_lower = text.strip().lower()
            logging.info(f"STT Ouvido: {text}")
            
            is_called = False
            matched_word = ""
            
            # 1. Determinar se estamos no modo de Conversa Contínua (última fala da Aura há menos de 15 segundos)
            import time
            last_speak = 0
            if self.main_gui and hasattr(self.main_gui, "last_speak_time"):
                last_speak = self.main_gui.last_speak_time
                
            if time.time() - last_speak < 15.0:
                is_called = True
                command = text_lower
                print("   🗣️ [Conversa Contínua] Aceitando comando sem palavra de ativação.")
            else:
                # 2. Determinar o gênero da voz configurado para escolher fallbacks
                gender = "female"
                if self.main_gui and hasattr(self.main_gui, "llm"):
                    gender = self.main_gui.llm.config.get("voice", {}).get("gender", "female")
                
                # 3. Definir variantes de ativação
                if self.wake_word == "aura":
                    if gender == "female":
                        fallbacks = ["aura", "laura", "luna", "belinha", "agora", "ora", "ahora", "auras", "abra", "olha", "aula", "aurora", "alra", "ouvir", "ouviu"]
                    else:
                        fallbacks = ["mfb", "auro", "lauro", "lobão", "lobinho", "beto", "agora", "ora", "ahora", "auras", "ouvir", "ouviu"]
                else:
                    fallbacks = [self.wake_word]
                    if gender == "male" and self.wake_word.endswith("a"):
                        fallbacks.append(self.wake_word[:-1] + "o")
                    elif gender == "female" and self.wake_word.endswith("o"):
                        fallbacks.append(self.wake_word[:-1] + "a")
                
                for word in fallbacks:
                    if word in text_lower:
                        is_called = True
                        matched_word = word
                        break
                        
                if is_called:
                    parts = text_lower.split(matched_word, 1)
                    command = parts[1].strip()
                    # Se disse apenas o nome, envia o nome
                    if not command:
                        command = self.wake_word
            
            if is_called:
                self.signals.heard_text.emit(command)
                
        except sr.UnknownValueError:
            pass
        except sr.RequestError as e:
            logging.warning(f"Erro de conexão com o serviço de STT da Google: {e}")
        except Exception as e:
            logging.error(f"Erro geral no callback de áudio: {e}")

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    engine = VoiceEngine()
    engine.signals.finished_speaking.connect(lambda: print("Terminou!") or app.quit())
    print("Testando...")
    engine.speak("Olá! Testando voz padrão da Aura.", gender="female")
    sys.exit(app.exec())
