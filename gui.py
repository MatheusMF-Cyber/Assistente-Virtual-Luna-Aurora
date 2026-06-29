import os
import sys
import logging
import base64
import math
import random
import json
import shutil
import time
import threading
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# Configure logging to write to both AppData/Local/Aura/aura.log and console
data_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Aura")
os.makedirs(data_dir, exist_ok=True)
log_file = os.path.join(data_dir, "aura.log")

# Setup Qt platform path configurations before Pyside imports
if getattr(sys, 'frozen', False):
    mei_dir = getattr(sys, '_MEIPASS', '')
    if mei_dir:
        plugins_dir = os.path.join(mei_dir, "PySide6", "plugins")
        platforms_dir = os.path.join(plugins_dir, "platforms")
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms_dir
        os.environ["QT_PLUGIN_PATH"] = plugins_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QDialog, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QSlider, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QGraphicsDropShadowEffect, QPlainTextEdit,
    QScrollArea
)
from PySide6.QtGui import QPixmap, QCursor, QColor, QFont, QIcon, QPainter, QBrush, QPen
from PySide6.QtCore import Qt, QPoint, QTimer, QSize, Signal, Slot

# Import our custom modules
from llm_client import LLMClient
from voice_engine import VoiceEngine
from system_tools import SystemTools

class SpeechBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowFlags.FramelessWindowHint | Qt.WindowFlags.SubWindow | Qt.WindowFlags.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.layout = QVBoxLayout(self)
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setFont(QFont("Outfit", 11, QFont.Weight.Medium))
        self.label.setStyleSheet("color: #FFFFFF; padding: 12px; line-height: 1.4;")
        
        self.layout.addWidget(self.label)
        self.layout.setContentsMargins(15, 10, 15, 18)  # Space for bubble tail
        
        # Drop shadow for bubble
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(2, 2)
        self.setGraphicsEffect(shadow)
        
        self.bubble_color = QColor(30, 20, 45, 235)  # Cute dark violet translucent bubble
        
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def setText(self, text, duration_ms=6000):
        self.label.setText(text)
        self.adjustSize()
        if self.width() > 300:
            self.setFixedWidth(300)
            self.label.adjustSize()
            self.adjustSize()
        self.show()
        self.hide_timer.start(duration_ms)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        rect.setHeight(rect.height() - 12)  # Adjust for tail
        
        path_brush = QBrush(self.bubble_color)
        painter.setBrush(path_brush)
        painter.setPen(QPen(QColor(160, 80, 255, 180), 1.5)) # Neon violet border
        
        painter.drawRoundedRect(rect, 15, 15)
        
        # Draw speech tail (pointing down-left to the avatar)
        tail_points = [
            QPoint(30, rect.height()),
            QPoint(42, rect.height() + 12),
            QPoint(50, rect.height())
        ]
        painter.drawPolygon(tail_points)

class AvatarWindow(QWidget):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        
        # Transparent borderless window stays on top
        self.setWindowFlags(Qt.WindowFlags.FramelessWindowHint | Qt.WindowFlags.WindowStaysOnTopHint | Qt.WindowFlags.Tool | Qt.WindowFlags.BypassWindowManagerHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Habilitar rastreamento do mouse para carícias/interações
        self.setMouseTracking(True)
        
        # UI Elements
        self.avatar_label = QLabel(self)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        layout = QVBoxLayout(self)
        layout.addWidget(self.avatar_label)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.drag_position = QPoint()
        
        # Load avatar images
        self.assets_dir = os.path.join(self.main_app.workspace_dir, "assets")
        self.current_emotion = "idle"
        self.update_avatar_display()
        
        # Position at bottom right initially
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 50, screen.height() - self.height() - 100)
        
        # Speech Bubble
        self.bubble = SpeechBubble()
        
        # Timer to update bubble position relative to avatar
        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.update_bubble_position)
        self.position_timer.start(100)
        
        # OTIMIZAÇÃO: Mecanismo de Deslocamento Procedural (Glide) 100% robusto
        self.glide_timer = QTimer(self)
        self.glide_timer.timeout.connect(self.update_glide)
        self.glide_target = None
        self.glide_step_x = 0.0
        self.glide_step_y = 0.0
        self.glide_steps_remaining = 0
        
        # OTIMIZAÇÃO: Animação de Flutuação Senoidal (Hover)
        self.float_timer = QTimer(self)
        self.float_timer.timeout.connect(self.idle_float)
        self.float_timer.start(100)  # Atualização a cada 100ms
        self.float_counter = 0.0
        self.last_float_offset = 0
        
        # Timer para decidir movimento autônomo (a cada 12 segundos)
        self.wander_timer = QTimer(self)
        self.wander_timer.timeout.connect(self.decide_next_wander)
        self.wander_timer.start(12000)

    def update_avatar_display(self):
        if hasattr(self, "movie") and self.movie:
            self.movie.stop()
            self.movie = None
            
        img_path = None
        # Procura GIFs primeiro (para animação rica), depois PNGs
        for ext in [".gif", ".png"]:
            path = os.path.join(self.assets_dir, f"{self.current_emotion}{ext}")
            if os.path.exists(path):
                img_path = path
                break
                
        if not img_path:
            for ext in [".gif", ".png"]:
                path = os.path.join(self.assets_dir, f"idle{ext}")
                if os.path.exists(path):
                    img_path = path
                    break
        # OTIMIZAÇÃO: Escala dinâmica com suporte a presets (16x16 até 800x800)
        preset = self.main_app.llm.config.get("avatar_size_preset", "Customizado")
        scale = self.main_app.llm.config.get("avatar_scale", 300)
        
        preset_dims = {
            "16 x 16": (16, 16),
            "32 x 32": (32, 32),
            "64 x 64": (64, 64),
            "150 x 150": (150, 150),
            "180 x 180": (180, 180),
            "200 x 250": (200, 250),
            "250 x 400": (250, 400),
            "800 x 800": (800, 800)
        }
        
        if preset in preset_dims:
            w, h = preset_dims[preset]
        else:
            w = scale
            h = -1
            
        if img_path:
            ext = os.path.splitext(img_path)[1].lower()
            if ext == ".gif":
                from PySide6.QtGui import QMovie
                self.movie = QMovie(img_path)
                self.movie.isValid()
                movie_size = self.movie.frameRect().size()
                if h == -1:
                    if movie_size.isValid() and movie_size.width() > 0:
                        aspect = movie_size.height() / movie_size.width()
                        h = int(w * aspect)
                        if h > 1024:
                            h = 1024
                            w = int(1024 / aspect)
                    else:
                        h = w
                self.movie.setScaledSize(QSize(w, h))
                self.avatar_label.setMovie(self.movie)
                self.movie.start()
                self.setFixedSize(w, h)
            else:
                pixmap = QPixmap(img_path)
                if h == -1:
                    scaled_pixmap = pixmap.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > 1024:
                        scaled_pixmap = pixmap.scaledToHeight(1024, Qt.TransformationMode.SmoothTransformation)
                else:
                    scaled_pixmap = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.avatar_label.setPixmap(scaled_pixmap)
                self.setFixedSize(scaled_pixmap.size())
        else:
            self.avatar_label.setText("🌸\nAura")
            self.avatar_label.setStyleSheet("color: magenta; font-size: 24px; font-weight: bold; background-color: rgba(0,0,0,100); border-radius: 15px; padding: 20px;")
            self.setFixedSize(w, h if h != -1 else w)

    def set_emotion(self, emotion):
        emotion = emotion.lower().strip()
        if emotion in ["idle", "talking", "happy", "shy", "sarcastic", "sad", "thinking", "thought", "curious", "confused", "sleeping", "walking", "waking"]:
            self.current_emotion = emotion
        else:
            self.current_emotion = "idle"
        self.update_avatar_display()

    def speak_text(self, text, duration_ms=6000):
        self.bubble.setText(text, duration_ms)
        self.update_bubble_position()

    def update_bubble_position(self):
        if self.bubble.isVisible():
            bubble_x = self.x() + 40
            bubble_y = self.y() - self.bubble.height() + 5
            self.bubble.move(bubble_x, bubble_y)

    def idle_float(self):
        # Não flutua se estiver sendo arrastada ou deslizando (glide)
        if self.drag_position != QPoint() or self.glide_timer.isActive():
            return
            
        self.float_counter += 0.15
        offset = int(math.sin(self.float_counter) * 5)  # Amplitude de 5 pixels
        
        delta = offset - self.last_float_offset
        self.last_float_offset = offset
        
        self.move(self.x(), self.y() + delta)

    def start_glide_to(self, target_x, target_y, duration_ms=2000):
        self.glide_target = QPoint(target_x, target_y)
        start_pos = self.pos()
        
        self.last_float_offset = 0  # Zera flutuação para evitar desvios cumulativos
        
        steps = duration_ms // 30
        if steps <= 0:
            steps = 1
            
        self.glide_step_x = (target_x - start_pos.x()) / steps
        self.glide_step_y = (target_y - start_pos.y()) / steps
        self.glide_steps_remaining = steps
        
        self.original_emotion_before_glide = self.current_emotion
        self.set_emotion("walking")
        
        self.glide_timer.start(30)

    def update_glide(self):
        if self.glide_steps_remaining > 0:
            curr = self.pos()
            self.move(int(curr.x() + self.glide_step_x), int(curr.y() + self.glide_step_y))
            self.glide_steps_remaining -= 1
        else:
            self.glide_timer.stop()
            if self.glide_target:
                self.move(self.glide_target)
            self.set_emotion(getattr(self, "original_emotion_before_glide", "idle"))

    def decide_next_wander(self):
        auton_move = self.main_app.llm.config.get("autonomous_movement", True)
        if not auton_move:
            return
            
        # 30% de chance de se mover a cada ciclo
        if random.random() > 0.3:
            return
            
        screen = QApplication.primaryScreen().geometry()
        max_x = screen.width() - self.width() - 50
        max_y = screen.height() - self.height() - 100
        
        dx = random.randint(-250, 250)
        dy = random.randint(-150, 150)
        
        target_x = max(50, min(max_x, self.x() + dx))
        target_y = max(50, min(max_y, self.y() + dy))
        
        self.start_glide_to(target_x, target_y, duration_ms=2200)

    # Interações com o mouse
    def enterEvent(self, event):
        self.main_app.reset_inactivity()
        self.set_emotion("shy")
        # 25% de chance de fazer um comentário fofo ao receber carinho
        if random.random() < 0.25 and not self.main_app.voice.is_listening and not self.bubble.isVisible():
            uname = self.main_app.llm.memory["user_profile"].get("name", "Mestre")
            greetings = [
                f"Oi, {uname}! Você veio me fazer um carinho? 😳",
                f"Isso faz cócegas, {uname}! Hahaha! 😄",
                f"Adoro quando você passa o mouse por aqui, {uname}! 🥰",
                f"Estou te fazendo companhia, {uname}! 😉"
            ]
            self.main_app.speak(random.choice(greetings), emotion="SHY")
        event.accept()

    def leaveEvent(self, event):
        self.main_app.reset_inactivity()
        self.set_emotion("idle")
        event.accept()

    # Mouse Events para arrastar
    def mousePressEvent(self, event):
        self.main_app.reset_inactivity()
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.set_emotion("confused") # Surpresa ao ser levantada
            event.accept()

    def mouseMoveEvent(self, event):
        self.main_app.reset_inactivity()
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.main_app.reset_inactivity()
        self.drag_position = QPoint()
        self.last_float_offset = 0
        self.set_emotion("idle")

    def mouseDoubleClickEvent(self, event):
        self.main_app.reset_inactivity()
        self.main_app.open_settings()
        event.accept()

    def contextMenuEvent(self, event):
        self.main_app.reset_inactivity()
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e142d;
                color: #ffffff;
                border: 1px solid #9f50ff;
                border-radius: 8px;
                padding: 5px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #9f50ff;
            }
        """)
        
        talk_action = menu.addAction("Conversar (Texto)")
        screen_action = menu.addAction("O que estou fazendo? (Ver Tela)")
        unpack_action = menu.addAction("Descompactar ZIP/RAR")
        settings_action = menu.addAction("Configurações")
        
        menu.addSeparator()
        minimize_action = menu.addAction("Minimizar")
        maximize_action = menu.addAction("Maximizar / Restaurar")
        sleep_action = menu.addAction("Ir Dormir (Soneca)")
        menu.addSeparator()
        
        clear_action = menu.addAction("Limpar Histórico")
        exit_action = menu.addAction("Sair")
        
        action = menu.exec(QCursor.pos())
        
        if action == talk_action:
            self.main_app.prompt_text_dialog()
        elif action == screen_action:
            self.main_app.analyze_screen()
        elif action == unpack_action:
            self.main_app.unpack_file_dialog()
        elif action == settings_action:
            self.main_app.open_settings()
        elif action == minimize_action:
            self.showMinimized()
        elif action == maximize_action:
            if self.isMaximized():
                self.showNormal()
            else:
                self.showMaximized()
        elif action == sleep_action:
            self.main_app.go_to_sleep_command()
        elif action == clear_action:
            self.main_app.llm.clear_history()
            self.speak_text("Memória esvaziada! Começamos do zero.")
        elif action == exit_action:
            QApplication.quit()

class OpenWebsiteChoiceDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Abrir Site - Aura")
        self.setFixedSize(400, 160)
        self.choice = None
        
        self.setStyleSheet("""
            QDialog {
                background-color: #120b1e;
                color: white;
                font-family: 'Outfit', sans-serif;
            }
            QLabel {
                color: #e2d7f5;
                font-size: 13px;
            }
            QPushButton {
                background-color: #9f50ff;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #b376f0;
            }
        """)
        
        lay = QVBoxLayout(self)
        lbl = QLabel(f"Encontrei o site no seu histórico:\n{title}\n\nOnde você deseja abrir?", self)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        
        h_lay = QHBoxLayout()
        btn_main = QPushButton("Página Inicial", self)
        btn_main.clicked.connect(self.select_main)
        h_lay.addWidget(btn_main)
        
        btn_last = QPushButton("Última Aba", self)
        btn_last.clicked.connect(self.select_last)
        h_lay.addWidget(btn_last)
        
        btn_cancel = QPushButton("Cancelar", self)
        btn_cancel.setStyleSheet("background-color: #3e2e50;")
        btn_cancel.clicked.connect(self.reject)
        h_lay.addWidget(btn_cancel)
        
        lay.addLayout(h_lay)
        
    def select_main(self):
        self.choice = "main"
        self.accept()
        
    def select_last(self):
        self.choice = "last"
        self.accept()

class SettingsWindow(QDialog):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setWindowTitle("Configurações da Assistente")
        self.setFixedSize(540, 520) # Fixed size, scrollable
        self.setStyleSheet("""
            QDialog {
                background-color: #120b1e;
                color: #ffffff;
                font-family: 'Outfit', 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #e2d7f5;
                font-size: 13px;
                font-weight: 500;
            }
            QLineEdit, QComboBox, QPlainTextEdit {
                background-color: #1e1330;
                border: 1px solid #783cb0;
                border-radius: 6px;
                color: #ffffff;
                padding: 6px 10px;
                font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                border: 1px solid #b376f0;
            }
            QSlider::groove:horizontal {
                border: 1px solid #4a2770;
                height: 6px;
                background: #1e1330;
                margin: 0px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #9f50ff;
                border: 1px solid #783cb0;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QPushButton {
                background-color: #9f50ff;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #b376f0;
            }
            QPushButton:pressed {
                background-color: #783cb0;
            }
            QCheckBox {
                color: #e2d7f5;
            }
        """)
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(10)
        self.main_layout.setContentsMargins(15, 15, 15, 10)
        
        # 1. Scroll Area
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #120b1e;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #120b1e;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #783cb0;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #9f50ff;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none;
                border: none;
            }
        """)
        self.scroll_area.viewport().setStyleSheet("background-color: #120b1e;")
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: #120b1e;")
        self.scroll_layout = QVBoxLayout(scroll_widget)
        self.scroll_layout.setSpacing(12)
        self.scroll_layout.setContentsMargins(5, 5, 5, 5)
        
        # CONTROLE DE ACESSO (Modo Administrador - Sem senha)
        h_role = QHBoxLayout()
        self.admin_mode_chk = QCheckBox("Habilitar Modo Administrador (Acesso Completo)")
        self.admin_mode_chk.clicked.connect(self.toggle_admin_mode)
        h_role.addWidget(self.admin_mode_chk)
        self.scroll_layout.addLayout(h_role)
        
        # CONFIGURAÇÕES BÁSICAS
        self.basic_container = QWidget()
        basic_layout = QVBoxLayout(self.basic_container)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(10)
        
        # Nome da Assistente
        h_name = QHBoxLayout()
        h_name.addWidget(QLabel("Nome da Assistente:"))
        self.name_edit = QLineEdit()
        h_name.addWidget(self.name_edit)
        basic_layout.addLayout(h_name)
        
        # Nome do Usuário
        h_uname = QHBoxLayout()
        h_uname.addWidget(QLabel("Nome do Usuário:"))
        self.uname_edit = QLineEdit()
        h_uname.addWidget(self.uname_edit)
        basic_layout.addLayout(h_uname)
        
        # Personagem / Visual
        h_avatar = QHBoxLayout()
        h_avatar.addWidget(QLabel("Personagem / Visual:"))
        self.avatar_combo = QComboBox()
        self.avatar_combo.addItems(["Menina Chibi (Aura)", "Lobinho Chibi (Mfb)"])
        h_avatar.addWidget(self.avatar_combo)
        basic_layout.addLayout(h_avatar)
        
        # Botões Importar Roupinha Customizada (.zip/.rar)
        h_outfit = QHBoxLayout()
        self.import_outfit_btn = QPushButton("Importar Roupinha (.zip/.rar)")
        self.import_outfit_btn.setStyleSheet("background-color: #783cb0; border-radius: 6px; padding: 6px; font-size: 11px;")
        self.import_outfit_btn.clicked.connect(self.import_custom_outfit_dialog)
        h_outfit.addWidget(self.import_outfit_btn)
        
        self.clear_outfit_btn = QPushButton("Limpar Roupa")
        self.clear_outfit_btn.setStyleSheet("background-color: #553333; border-radius: 6px; padding: 6px; font-size: 11px;")
        self.clear_outfit_btn.clicked.connect(self.clear_custom_outfit)
        h_outfit.addWidget(self.clear_outfit_btn)
        basic_layout.addLayout(h_outfit)
        
        self.outfit_status_lbl = QLabel("")
        self.outfit_status_lbl.setStyleSheet("font-size: 11px; color: #a5d6a7;")
        basic_layout.addWidget(self.outfit_status_lbl)
        
        # Presets de Tamanho
        h_preset = QHBoxLayout()
        h_preset.addWidget(QLabel("Preset de Tamanho:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Customizado", "16 x 16", "32 x 32", "64 x 64", "150 x 150", "180 x 180", "200 x 250", "250 x 400", "800 x 800"])
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        h_preset.addWidget(self.preset_combo)
        basic_layout.addLayout(h_preset)
        
        # Slider de tamanho
        h_scale = QHBoxLayout()
        h_scale.addWidget(QLabel("Tamanho Personalizado:"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(250, 1600)
        self.scale_slider.valueChanged.connect(self.on_scale_changed)
        h_scale.addWidget(self.scale_slider)
        basic_layout.addLayout(h_scale)
        
        # Sliders de Personalidade/Humor
        lbl_pers = QLabel("Personalidade e Humor:")
        lbl_pers.setFont(QFont("Outfit", 11, QFont.Weight.Bold))
        lbl_pers.setStyleSheet("color: #9f50ff; margin-top: 5px;")
        basic_layout.addWidget(lbl_pers)
        
        h_shy = QHBoxLayout()
        h_shy.addWidget(QLabel("Tímida:"))
        self.shy_slider = QSlider(Qt.Orientation.Horizontal)
        self.shy_slider.setRange(0, 100)
        h_shy.addWidget(self.shy_slider)
        basic_layout.addLayout(h_shy)
        
        h_sarc = QHBoxLayout()
        h_sarc.addWidget(QLabel("Sarcástica:"))
        self.sarc_slider = QSlider(Qt.Orientation.Horizontal)
        self.sarc_slider.setRange(0, 100)
        h_sarc.addWidget(self.sarc_slider)
        basic_layout.addLayout(h_sarc)
        
        h_fun = QHBoxLayout()
        h_fun.addWidget(QLabel("Engraçada:"))
        self.fun_slider = QSlider(Qt.Orientation.Horizontal)
        self.fun_slider.setRange(0, 100)
        h_fun.addWidget(self.fun_slider)
        basic_layout.addLayout(h_fun)
        
        # Voz Básica
        lbl_voice = QLabel("Configuração da Voz:")
        lbl_voice.setFont(QFont("Outfit", 11, QFont.Weight.Bold))
        lbl_voice.setStyleSheet("color: #9f50ff; margin-top: 5px;")
        basic_layout.addWidget(lbl_voice)
        
        h_vgender = QHBoxLayout()
        h_vgender.addWidget(QLabel("Gênero da Voz:"))
        self.gender_combo = QComboBox()
        self.gender_combo.addItems(["Feminina", "Masculina"])
        h_vgender.addWidget(self.gender_combo)
        basic_layout.addLayout(h_vgender)
        
        h_vspeed = QHBoxLayout()
        h_vspeed.addWidget(QLabel("Velocidade:"))
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(80, 150)
        h_vspeed.addWidget(self.speed_slider)
        basic_layout.addLayout(h_vspeed)
        
        self.scroll_layout.addWidget(self.basic_container)
        
        # CONTAINER DE ADMINISTRADOR (Oculto por padrão)
        self.admin_container = QWidget()
        admin_layout = QVBoxLayout(self.admin_container)
        admin_layout.setContentsMargins(0, 0, 0, 0)
        admin_layout.setSpacing(10)
        
        # API Gemini
        h_key = QHBoxLayout()
        h_key.addWidget(QLabel("Chave de API Gemini:"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        h_key.addWidget(self.key_edit)
        admin_layout.addLayout(h_key)
        
        # Configuração de Voz Offline Rápida
        self.offline_tts_chk = QCheckBox("Ativar Voz Offline Rápida (Sem Delay)")
        admin_layout.addWidget(self.offline_tts_chk)
        
        # Clonagem de Voz (ElevenLabs e Botão Upload)
        lbl_custom_voice = QLabel("Voz Personalizada (Mídia / ElevenLabs):")
        lbl_custom_voice.setFont(QFont("Outfit", 11, QFont.Weight.Bold))
        lbl_custom_voice.setStyleSheet("color: #9f50ff; margin-top: 5px;")
        admin_layout.addWidget(lbl_custom_voice)
        
        self.custom_voice_chk = QCheckBox("Usar Voz Clonada do Usuário (ElevenLabs)")
        admin_layout.addWidget(self.custom_voice_chk)
        
        h_el_key = QHBoxLayout()
        h_el_key.addWidget(QLabel("Chave ElevenLabs:"))
        self.el_key_edit = QLineEdit()
        self.el_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        h_el_key.addWidget(self.el_key_edit)
        admin_layout.addLayout(h_el_key)
        
        h_el_id = QHBoxLayout()
        h_el_id.addWidget(QLabel("Voice ID ElevenLabs:"))
        self.el_id_edit = QLineEdit()
        h_el_id.addWidget(self.el_id_edit)
        admin_layout.addLayout(h_el_id)
        
        # Botão para upload de arquivo (clonagem de MP3/MP4/WAV)
        self.clone_voice_btn = QPushButton("Carregar Arquivo de Voz (MP3/MP4/WAV)")
        self.clone_voice_btn.clicked.connect(self.upload_voice_file)
        self.clone_voice_btn.setStyleSheet("background-color: #783cb0; border-radius: 6px;")
        admin_layout.addWidget(self.clone_voice_btn)
        
        # Opções de Autonomia e Sistema
        lbl_auton = QLabel("Autonomia e Inicialização:")
        lbl_auton.setFont(QFont("Outfit", 11, QFont.Weight.Bold))
        lbl_auton.setStyleSheet("color: #9f50ff; margin-top: 5px;")
        admin_layout.addWidget(lbl_auton)
        
        h_auton_checks = QHBoxLayout()
        self.emotion_autonomy_chk = QCheckBox("Autonomia Emoções")
        self.autonomous_learning_chk = QCheckBox("Aprendizado")
        self.auton_move_chk = QCheckBox("Mover/Flutuar")
        h_auton_checks.addWidget(self.emotion_autonomy_chk)
        h_auton_checks.addWidget(self.autonomous_learning_chk)
        h_auton_checks.addWidget(self.auton_move_chk)
        admin_layout.addLayout(h_auton_checks)
        
        self.wake_chk = QCheckBox("Ativar Reconhecimento de Voz (Wake-word)")
        admin_layout.addWidget(self.wake_chk)
        self.startup_chk = QCheckBox("Iniciar junto com o Windows")
        admin_layout.addWidget(self.startup_chk)
        
        # Boas-vindas
        admin_layout.addWidget(QLabel("Bordões de Boas-vindas (Um por linha):"))
        self.welcome_edit = QPlainTextEdit()
        self.welcome_edit.setFixedHeight(60)
        admin_layout.addWidget(self.welcome_edit)
        
        self.scroll_layout.addWidget(self.admin_container)
        self.admin_container.hide() # Oculto por padrão
        
        self.scroll_area.setWidget(scroll_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        # Botões Rodapé (Sempre visíveis)
        h_btns = QHBoxLayout()
        h_btns.addStretch()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setStyleSheet("background-color: #3e2e50;")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("Salvar")
        save_btn.clicked.connect(self.save_settings)
        
        h_btns.addWidget(cancel_btn)
        h_btns.addWidget(save_btn)
        self.main_layout.addLayout(h_btns)
        
        self.load_values()

    def toggle_admin_mode(self):
        if self.admin_mode_chk.isChecked():
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self, 
                "Acesso Desenvolvedor", 
                "Digite a senha de Desenvolvedor / Administrador:", 
                QLineEdit.EchoMode.Password
            )
            if ok and text == "admin123":
                self.admin_container.show()
            else:
                self.admin_mode_chk.setChecked(False)
                self.admin_container.hide()
                if ok:
                    QMessageBox.warning(self, "Acesso Negado", "Senha incorreta!")
        else:
            self.admin_container.hide()

    def on_preset_changed(self, text):
        if text == "Customizado":
            self.scale_slider.setEnabled(True)
        else:
            self.scale_slider.setEnabled(False)
            config = self.main_app.llm.config
            config["avatar_size_preset"] = text
            self.main_app.avatar_win.update_avatar_display()

    def on_scale_changed(self, value):
        self.main_app.llm.config["avatar_scale"] = value
        self.main_app.avatar_win.update_avatar_display()

    def upload_voice_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arquivo de mídia para clonar voz",
            "",
            "Arquivos de Áudio/Vídeo (*.mp3 *.wav *.mp4 *.m4a)"
        )
        if not file_path:
            return
            
        api_key = self.el_key_edit.text().strip()
        
        self.clone_voice_btn.setEnabled(False)
        self.clone_voice_btn.setText("Clonando voz... 0%")
        QApplication.processEvents()
        
        # Animador de progresso simulado
        self.clone_progress = 0
        self.progress_timer = QTimer(self)
        def update_progress():
            if self.clone_progress < 95:
                self.clone_progress += random.randint(5, 15) if self.clone_progress < 60 else random.randint(1, 4)
                if self.clone_progress > 95:
                    self.clone_progress = 95
                self.clone_voice_btn.setText(f"Clonando voz... {self.clone_progress}%")
        self.progress_timer.timeout.connect(update_progress)
        self.progress_timer.start(300)
        
        def run_clone():
            local_saved = False
            # Sempre copia e grava a voz localmente
            try:
                import shutil
                custom_voice_dir = os.path.join(self.main_app.workspace_dir, "custom_voice")
                os.makedirs(custom_voice_dir, exist_ok=True)
                local_voice_path = os.path.join(custom_voice_dir, "user_voice" + os.path.splitext(file_path)[1].lower())
                shutil.copy2(file_path, local_voice_path)
                self.main_app.llm.config["local_voice_file"] = os.path.abspath(local_voice_path)
                self.main_app.llm.save_config(self.main_app.llm.config)
                local_saved = True
                logging.info(f"Voz gravada localmente com sucesso: {local_voice_path}")
            except Exception as e:
                logging.error(f"Erro ao gravar arquivo de voz localmente: {e}")
                
            # Se a chave API não estiver presente, completa como local imediatamente
            if not api_key:
                if local_saved:
                    QTimer.singleShot(0, lambda: self.on_clone_success_local("Chave API do ElevenLabs não configurada."))
                else:
                    QTimer.singleShot(0, lambda: self.on_clone_failure("Sem chave ElevenLabs e erro ao gravar arquivo local."))
                return

            try:
                voice_id = self.main_app.voice.clone_voice_from_file(api_key, file_path)
                if voice_id:
                    QTimer.singleShot(0, lambda: self.on_clone_success(voice_id))
                else:
                    raise Exception("A API retornou uma resposta vazia.")
            except Exception as e:
                # Se falhar a API online mas o arquivo local foi gravado 100%, completa com sucesso local!
                if local_saved:
                    QTimer.singleShot(0, lambda: self.on_clone_success_local(str(e)))
                else:
                    QTimer.singleShot(0, lambda: self.on_clone_failure(str(e)))
                
        threading.Thread(target=run_clone, daemon=True).start()
        
    def on_clone_success(self, voice_id):
        if hasattr(self, "progress_timer") and self.progress_timer.isActive():
            self.progress_timer.stop()
        self.clone_voice_btn.setText("Clonando voz... 100% (Concluído!)")
        QApplication.processEvents()
        QTimer.singleShot(800, lambda: self.finish_clone_success(voice_id))

    def finish_clone_success(self, voice_id):
        self.clone_voice_btn.setEnabled(True)
        self.clone_voice_btn.setText("Carregar Arquivo de Voz (MP3/MP4/WAV)")
        self.el_id_edit.setText(voice_id)
        self.custom_voice_chk.setChecked(True)
        QMessageBox.information(self, "Sucesso", f"Voz clonada com sucesso! ID da voz: {voice_id}")

    def on_clone_success_local(self, reason):
        if hasattr(self, "progress_timer") and self.progress_timer.isActive():
            self.progress_timer.stop()
        self.clone_voice_btn.setText("Clonando voz... 100% (Local)")
        QApplication.processEvents()
        QTimer.singleShot(800, lambda: self.finish_clone_success_local(reason))

    def finish_clone_success_local(self, reason):
        self.clone_voice_btn.setEnabled(True)
        self.clone_voice_btn.setText("Carregar Arquivo de Voz (MP3/MP4/WAV)")
        self.custom_voice_chk.setChecked(True)
        QMessageBox.information(
            self, 
            "Clonagem Local Concluída", 
            "A clonagem online não pôde ser concluída (ElevenLabs offline ou sem chave de API), "
            "mas seu arquivo de voz foi importado e gravado localmente no banco local com sucesso! 🌟\n\n"
            "Usarei este arquivo local como efeito de som e referência física da sua voz."
        )
        
    def on_clone_failure(self, err_msg):
        if hasattr(self, "progress_timer") and self.progress_timer.isActive():
            self.progress_timer.stop()
        self.clone_voice_btn.setEnabled(True)
        self.clone_voice_btn.setText("Carregar Arquivo de Voz (MP3/MP4/WAV)")
        QMessageBox.critical(self, "Erro na Clonagem", f"Erro ao clonar voz: {err_msg}")

    def import_custom_outfit_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar pacote de roupa (.zip ou .rar)",
            "",
            "Arquivos de Roupa (*.zip *.rar)"
        )
        if not file_path:
            return
            
        success, msg = self.main_app.import_custom_outfit(file_path)
        if success:
            QMessageBox.information(self, "Sucesso", msg)
            self.load_values()
        else:
            QMessageBox.critical(self, "Erro", msg)
            
    def clear_custom_outfit(self):
        self.main_app.llm.config["custom_outfit_path"] = ""
        self.main_app.llm.save_config(self.main_app.llm.config)
        self.main_app.apply_updated_config()
        self.load_values()
        QMessageBox.information(self, "Limpo", "Voltou a usar o visual padrão.")

    def load_values(self):
        config = self.main_app.llm.config
        self.name_edit.setText(config.get("assistant_name", "Aura"))
        self.uname_edit.setText(self.main_app.llm.memory["user_profile"].get("name", "Mestre"))
        self.key_edit.setText(config.get("api_key", ""))
        self.scale_slider.setValue(config.get("avatar_scale", 300))
        
        preset = config.get("avatar_size_preset", "Customizado")
        idx = self.preset_combo.findText(preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self.on_preset_changed(preset)
        
        pers = config.get("personality", {})
        self.shy_slider.setValue(pers.get("shy", 50))
        self.sarc_slider.setValue(pers.get("sarcasm", 30))
        self.fun_slider.setValue(pers.get("funny", 50))
        
        voice = config.get("voice", {})
        gender = voice.get("gender", "female")
        self.gender_combo.setCurrentIndex(0 if gender == "female" else 1)
        self.speed_slider.setValue(int(voice.get("speed", 1.0) * 100))
        self.offline_tts_chk.setChecked(config.get("use_offline_tts", False))
        
        self.custom_voice_chk.setChecked(config.get("use_custom_voice", False))
        self.el_key_edit.setText(config.get("elevenlabs_api_key", ""))
        self.el_id_edit.setText(config.get("elevenlabs_voice_id", ""))
        
        self.wake_chk.setChecked(config.get("use_wake_word", True))
        self.startup_chk.setChecked(self.main_app.tools.is_startup_enabled())
        self.emotion_autonomy_chk.setChecked(config.get("emotion_autonomy", True))
        self.autonomous_learning_chk.setChecked(config.get("autonomous_learning", True))
        self.auton_move_chk.setChecked(config.get("autonomous_movement", True))
        
        theme = config.get("avatar_theme", "assets")
        self.avatar_combo.setCurrentIndex(0 if theme == "assets" else 1)
        
        phrases = config.get("welcome_phrases", [
            "Olá mestre! Senti sua falta. Pronto para começarmos?",
            "Oi! Que bom ver você novamente. No que vamos trabalhar hoje?",
            "Estou de volta! Sentiu saudades? 😳",
            "Aura online! Pronta para curiar seus arquivos e te fazer companhia! 😉"
        ])
        self.welcome_edit.setPlainText("\n".join(phrases))
        
        custom_outfit = config.get("custom_outfit_path", "")
        if custom_outfit:
            folder_name = os.path.basename(custom_outfit)
            self.outfit_status_lbl.setText(f"Roupa Customizada Ativa: {folder_name}")
            self.clear_outfit_btn.setEnabled(True)
        else:
            self.outfit_status_lbl.setText("Usando personagem padrão selecionado acima.")
            self.clear_outfit_btn.setEnabled(False)

    def save_settings(self):
        config = self.main_app.llm.config
        config["assistant_name"] = self.name_edit.text().strip()
        self.main_app.llm.memory["user_profile"]["name"] = self.uname_edit.text().strip()
        self.main_app.llm.save_memory()
        
        config["api_key"] = self.key_edit.text().strip()
        config["avatar_scale"] = self.scale_slider.value()
        config["avatar_size_preset"] = self.preset_combo.currentText()
        
        config["personality"]["shy"] = self.shy_slider.value()
        config["personality"]["sarcasm"] = self.sarc_slider.value()
        config["personality"]["funny"] = self.fun_slider.value()
        
        config["voice"]["gender"] = "female" if self.gender_combo.currentIndex() == 0 else "male"
        config["voice"]["speed"] = self.speed_slider.value() / 100.0
        config["use_offline_tts"] = self.offline_tts_chk.isChecked()
        
        config["use_custom_voice"] = self.custom_voice_chk.isChecked()
        config["elevenlabs_api_key"] = self.el_key_edit.text().strip()
        config["elevenlabs_voice_id"] = self.el_id_edit.text().strip()
        
        config["use_wake_word"] = self.wake_chk.isChecked()
        self.main_app.tools.set_startup_enabled(self.startup_chk.isChecked())
        config["avatar_theme"] = "assets" if self.avatar_combo.currentIndex() == 0 else "assets_wolf"
        config["emotion_autonomy"] = self.emotion_autonomy_chk.isChecked()
        config["autonomous_learning"] = self.autonomous_learning_chk.isChecked()
        config["autonomous_movement"] = self.auton_move_chk.isChecked()
        
        phrases_text = self.welcome_edit.toPlainText().strip()
        phrases = [line.strip() for line in phrases_text.split("\n") if line.strip()]
        if not phrases:
            phrases = ["Oi! Estou de volta!"]
        config["welcome_phrases"] = phrases
        
        self.main_app.llm.save_config(config)
        self.main_app.apply_updated_config()
        self.accept()

GAME_PROCESSES = {
    "league of legends.exe": "League of Legends",
    "csgo.exe": "CS:GO",
    "cs2.exe": "CS2",
    "valorant-win64-shipping.exe": "Valorant",
    "valorant.exe": "Valorant",
    "gta5.exe": "GTA V",
    "witcher3.exe": "The Witcher 3",
    "eldenring.exe": "Elden Ring",
    "cyberpunk2077.exe": "Cyberpunk 2077",
    "minecraft.exe": "Minecraft",
    "robloxplayerbeta.exe": "Roblox",
    "dota2.exe": "Dota 2",
    "fortniteclient-win64-shipping.exe": "Fortnite"
}

class MainApp:
    def __init__(self, workspace_dir=None):
        self.workspace_dir = workspace_dir or os.path.dirname(os.path.abspath(__file__))
        
        # Inicialização dos módulos
        self.llm = LLMClient(self.workspace_dir)
        self.voice = VoiceEngine(self)
        self.tools = SystemTools(self.workspace_dir)
        
        # Configurar processos conhecidos para curiosidade de programas
        self.seen_processes = set()
        seen_json = self.llm.db.get_assistant_state().get("seen_processes", "[]")
        try:
            self.seen_processes = set(json.loads(seen_json))
        except Exception:
            self.seen_processes = set()
            
        if not self.seen_processes:
            # Lista padrão inicial para evitar spams no primeiro boot
            common_procs = ["explorer.exe", "cmd.exe", "powershell.exe", "taskmgr.exe", "svchost.exe", "systemsettings.exe", "python.exe", "aura.exe", "pycharm64.exe", "code.exe", "chrome.exe", "edge.exe", "firefox.exe"]
            self.seen_processes = set(common_procs)
            self.llm.db.save_assistant_state({"seen_processes": json.dumps(list(self.seen_processes))})
        
        # Criar janela de avatar GUI
        self.avatar_win = AvatarWindow(self)
        self.avatar_win.show()
        
        # Conexões (Usa QueuedConnection para thread-safety na escuta de voz)
        self.voice.signals.finished_speaking.connect(self.on_speech_finished, Qt.ConnectionType.QueuedConnection)
        self.voice.signals.heard_text.connect(self.on_voice_command, Qt.ConnectionType.QueuedConnection)
        
        self.last_seen_downloads = set()
        self.init_downloads_monitor()
        
        self.last_window_title = ""
        self.init_activity_monitor()
        
        # Inatividade e Sono
        self.last_interaction_time = time.time()
        self.is_sleeping = False
        self.inactivity_timer = QTimer()
        self.inactivity_timer.timeout.connect(self.check_inactivity)
        self.inactivity_timer.start(5000) # Check every 5 seconds
        
        # Monitoramento de Jogos
        self.active_game_process = None
        self.game_start_time = None
        self.game_comments_made = set()
        self.game_timer = QTimer()
        self.game_timer.timeout.connect(self.check_game_status)
        self.game_timer.start(20000) # Check every 20 seconds
        
        # OTIMIZAÇÃO: Timer de conversação autônoma periódica (a cada 30 segundos)
        self.chatter_timer = QTimer()
        self.chatter_timer.timeout.connect(self.decide_spontaneous_chatter)
        self.chatter_timer.start(30000)
        
        self.apply_updated_config()
        
        # FLUXO DE BOAS-VINDAS: Perguntar nome na primeira execução
        state = self.llm.db.get_assistant_state()
        asked_name = state.get("asked_user_name", "False") == "True"
        name = self.llm.config.get("assistant_name", "Aura")
        
        if not asked_name:
            self.waiting_for_user_name = True
            logging.info("Primeiro arranque detectado. Perguntando nome do usuário.")
            self.speak(f"Olá! Eu sou a {name}. Eu gostaria muito de te conhecer melhor... Como eu deveria te chamar? 😳", emotion="SHY")
            self.llm.db.save_assistant_state({"asked_user_name": "True"})
        else:
            if "--startup" in sys.argv:
                startup_phrases = [
                    "Bocejo... 🥱 Bom dia, mestre! Acabei de acordar junto com o seu computador! O que vamos fazer hoje?",
                    "Olá! Que bom que você ligou o computador! Eu estava dormindo e acordei bem na hora! 😊",
                    "Aura acordando! 🥱 Computador ligado e eu pronta para te ajudar, mestre! O que manda?",
                    "Humm... mestre? Ah! Você ligou o PC! Que bom, eu já estava com saudades de você! 🥰"
                ]
                welcome_phrase = random.choice(startup_phrases)
                self.avatar_win.set_emotion("sleeping")
                QTimer.singleShot(2500, lambda: self.speak(welcome_phrase, emotion="HAPPY"))
            else:
                phrases = self.llm.config.get("welcome_phrases", [
                    "Olá mestre! Senti sua falta. Pronto para começarmos?",
                    "Oi! Que bom ver você novamente. No que vamos trabalhar hoje?",
                    "Estou de volta! Sentiu saudades? 😳",
                    "Aura online! Pronta para curiar seus arquivos e te fazer companhia! 😉"
                ])
                
                try:
                    last_idx = int(state.get("last_welcome_index", -1))
                except Exception:
                    last_idx = -1
                    
                if len(phrases) > 1:
                    allowed = [i for i in range(len(phrases)) if i != last_idx]
                    welcome_idx = random.choice(allowed)
                else:
                    welcome_idx = 0
                    
                self.llm.db.save_assistant_state({"last_welcome_index": welcome_idx})
                welcome_phrase = phrases[welcome_idx]
                self.speak(welcome_phrase)

    def apply_updated_config(self):
        use_wake = self.llm.config.get("use_wake_word", True)
        name = self.llm.config.get("assistant_name", "Aura")
        
        custom_outfit_path = self.llm.config.get("custom_outfit_path", "")
        if custom_outfit_path and os.path.exists(custom_outfit_path):
            self.avatar_win.assets_dir = custom_outfit_path
        else:
            theme = self.llm.config.get("avatar_theme", "assets")
            self.avatar_win.assets_dir = os.path.join(self.workspace_dir, theme)
            
        self.avatar_win.update_avatar_display()
        
        self.voice.stop_listening()
        if use_wake:
            self.voice.start_listening(wake_word=name)

    def import_custom_outfit(self, archive_path):
        outfit_name = os.path.splitext(os.path.basename(archive_path))[0]
        dest_dir = os.path.join(self.workspace_dir, "custom_outfits", outfit_name)
        
        success, msg = self.tools.extract_archive(archive_path, dest_dir)
        if not success:
            return False, f"Erro ao extrair pacote de roupa: {msg}"
            
        # Procurar idle.png recursivamente
        found_pngs = False
        target_dir = dest_dir
        for root, dirs, files in os.walk(dest_dir):
            if "idle.png" in files:
                target_dir = root
                found_pngs = True
                break
                
        if not found_pngs:
            return False, "O arquivo compactado não contém uma imagem 'idle.png' válida para a roupa."
            
        self.llm.config["custom_outfit_path"] = os.path.abspath(target_dir)
        self.llm.save_config(self.llm.config)
        self.apply_updated_config()
        
        # Expressa felicidade com a roupa nova!
        self.speak("Mestre! Adorei a roupinha nova! Ficou muito fofa! 🥰", emotion="HAPPY")
        return True, "Roupa customizada importada e aplicada com sucesso!"

    def init_downloads_monitor(self):
        _, self.last_seen_downloads = self.tools.scan_downloads_folder()
        self.downloads_timer = QTimer()
        self.downloads_timer.timeout.connect(self.check_new_downloads)
        self.downloads_timer.start(10000)

    def check_new_downloads(self):
        new_files, self.last_seen_downloads = self.tools.scan_downloads_folder(self.last_seen_downloads)
        for file_path in new_files:
            file_name = os.path.basename(file_path)
            logging.info(f"Novo download: {file_name}")
            
            # Inicializar conhecidos na memória se não houver
            if "known_downloads" not in self.llm.memory:
                self.llm.memory["known_downloads"] = {}
                self.llm.save_memory()
                
            known_downloads = self.llm.memory["known_downloads"]
            
            self.avatar_win.set_emotion("thinking")
            uname = self.llm.memory["user_profile"].get("name", "Mestre")
            
            # Verificar se já conhecemos / aprendemos sobre esse download
            if file_name in known_downloads:
                logging.info(f"Arquivo já conhecido: {file_name}")
                continue
                
            ext = os.path.splitext(file_name)[1].lower()
            suspicious_exts = ['.exe', '.msi', '.bat', '.cmd', '.vbs', '.ps1', '.scr', '.zip', '.rar']
            
            # Alarme de suspeita de vírus para arquivos não conhecidos
            if ext in suspicious_exts:
                msg = (
                    f"Mestre {uname}! Identifiquei que você baixou o arquivo '{file_name}'. "
                    f"Como eu ainda não o conheço e ele é do tipo '{ext}', ele pode ser suspeito de vírus! "
                    f"Mas eu posso analisá-lo e aprender sobre ele. Quer que eu faça uma análise estrutural?"
                )
                self.speak(msg, emotion="CONFUSED")
                self.waiting_for_download_explanation = file_name
                
                reply = QMessageBox.question(
                    None, 
                    "Alerta de Arquivo Suspeito!",
                    f"A {self.llm.config.get('assistant_name', 'Aura')} detectou um arquivo suspeito não conhecido:\n{file_name}\n\nDeseja que ela o analise estruturalmente para aprender?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    info = self.tools.inspect_file(file_path)
                    prompt = (
                        f"[SISTEMA: O usuário baixou o arquivo '{file_name}' e pediu para você analisá-lo. "
                        f"O relatório do arquivo é: '{info}'. "
                        f"Faça uma análise rápida do relatório em voz alta para o usuário. Diga se há arquivos perigosos "
                        f"(como scripts ou executáveis dentro de ZIPs) ou se parece seguro. Adicione este arquivo à sua memória "
                        f"como aprendido e confiado se parecer tudo certo. Chame o usuário de '{uname}' em português.]"
                    )
                    self.avatar_win.set_emotion("thinking")
                    response = self.llm.send_message(prompt)
                    reply_text = response.get("reply", "Não consegui concluir a análise.")
                    emotion = response.get("emotion", "HAPPY")
                    
                    # Salva na memória que já conhecemos e analisamos o arquivo
                    known_downloads[file_name] = {
                        "analyzed": True,
                        "status": "trusted" if emotion != "SAD" else "suspicious",
                        "time": time.time()
                    }
                    self.llm.memory["known_downloads"] = known_downloads
                    self.llm.save_memory()
                    
                    self.speak(reply_text, emotion=emotion)
                else:
                    # Salva que foi ignorado/conhecido pelo usuário
                    known_downloads[file_name] = {
                        "analyzed": False,
                        "status": "ignored",
                        "time": time.time()
                    }
                    self.llm.memory["known_downloads"] = known_downloads
                    self.llm.save_memory()
                    self.speak("Entendido. Vou deixar esse arquivo para lá, mestre! Mas tome cuidado, hein? 😉", emotion="SHY")
            else:
                # Curiosidade ativa padrão para outros formatos comuns
                if self.llm.config.get("autonomous_learning", True) and not getattr(self, "waiting_for_user_name", False):
                    self.speak(f"Mestre {uname}! Vi que você baixou o arquivo '{file_name}'. O que é isso? Me conta pra eu aprender! 😳", emotion="CURIOUS")
                    self.waiting_for_download_explanation = file_name
                    
                    # Salva como conhecido básico
                    known_downloads[file_name] = {
                        "analyzed": False,
                        "status": "curios_questioned",
                        "time": time.time()
                    }
                    self.llm.memory["known_downloads"] = known_downloads
                    self.llm.save_memory()

    def init_activity_monitor(self):
        self.activity_timer = QTimer()
        self.activity_timer.timeout.connect(self.check_active_activity)
        self.activity_timer.start(15000)

    def check_active_activity(self):
        title, proc = self.tools.get_active_window_title()
        title_clean = title.strip()
        
        ignore_keywords = ["área de trabalho", "desktop", "taskbar", "assistente de desktop", "aura", "conversar com aura"]
        if not title_clean or any(k in title_clean.lower() for k in ignore_keywords):
            return
            
        # SOBRE A TELA (Stay on Top) & COMENTÁRIOS EM TEMPO REAL:
        # Se estiver jogando (game_process ativo ou conhecido), assistindo (youtube, netflix, etc.) ou escutando música (spotify, etc.)
        title_lower = title_clean.lower()
        proc_lower = proc.strip().lower()
        
        media_keywords = [
            "youtube", "netflix", "spotify", "vlc", "prime video", "twitch", "disney", 
            "crunchyroll", "deezer", "soundcloud", "filme", "movie", "série", "music", "música"
        ]
        is_media = any(k in title_lower for k in media_keywords)
        is_game = proc_lower in GAME_PROCESSES or self.active_game_process is not None
        
        if is_media or is_game:
            # Garante que a assistente fica no topo (sobre a tela)
            self.avatar_win.raise_()
            self.avatar_win.activateWindow()
            
            # Comentário em tempo real (15% de chance se não estiver ocupada)
            if not self.avatar_win.bubble.isVisible() and self.avatar_win.current_emotion != "talking":
                if random.random() < 0.15:
                    self.avatar_win.set_emotion("thinking")
                    uname = self.llm.memory["user_profile"].get("name", "Mestre")
                    activity_type = "jogando" if is_game else ("escutando música" if "spotify" in title_lower or "deezer" in title_lower or "music" in title_lower else "assistindo")
                    
                    prompt = (
                        f"[SISTEMA: Comentário em Tempo Real espontâneo. O usuário está atualmente {activity_type} "
                        f"a atividade '{title_clean}' usando o programa '{proc}'. "
                        f"Faça um comentário muito curto (máximo 1 frase), fofo, tímido ou engraçado sobre isso. "
                        f"Chame o usuário pelo nome '{uname}' em português. Se você puder opinar ou dar palpite, faça-o de forma divertida!]"
                    )
                    self.process_command(prompt)
                    return
            
        # OTIMIZAÇÃO: Curiosidade ativa sobre novos programas executados pela primeira vez
        if proc_lower and proc_lower not in self.seen_processes:
            self.seen_processes.add(proc_lower)
            self.llm.db.save_assistant_state({"seen_processes": json.dumps(list(self.seen_processes))})
            
            # Se aprendizado ativo, pergunta ao usuário o que é o programa
            if self.llm.config.get("autonomous_learning", True) and not getattr(self, "waiting_for_user_name", False) and not getattr(self, "waiting_for_program_explanation", None):
                self.ask_about_new_program(proc, title_clean)
                return
            
        if title_clean != self.last_window_title:
            self.last_window_title = title_clean
            logging.info(f"Nova atividade: '{title_clean}' ({proc})")
            
            keywords_to_trigger = [
                "youtube", "netflix", "spotify", "vlc", "anime", "manga", 
                "code", "vs code", "pycharm", "sublime", "github", "stack overflow", 
                "chrome", "edge", "firefox", "crunchyroll", "film", "movie", "série", "song"
            ]
            
            should_comment = False
            if any(k in title_clean.lower() for k in keywords_to_trigger):
                should_comment = random.random() < 0.3
            else:
                should_comment = random.random() < 0.05
                
            if should_comment:
                self.spontaneous_comment(title_clean, proc)

    def ask_about_new_program(self, proc, title):
        uname = self.llm.memory["user_profile"].get("name", "Mestre")
        self.avatar_win.set_emotion("curious")
        self.speak(f"Mestre {uname}, vi que você abriu um programa novo chamado '{proc}' ({title}). Eu nunca vi esse programa antes! O que ele faz? Me ensina! 😳", emotion="CURIOUS")
        self.waiting_for_program_explanation = proc

    def spontaneous_comment(self, title, proc):
        logging.info("Aura comentando atividade espontaneamente...")
        self.avatar_win.set_emotion("thinking")
        uname = self.llm.memory["user_profile"].get("name", "Mestre")
        
        prompt = (
            f"[SISTEMA: O usuário mudou de atividade. Janela ativa: '{title}' (Processo: '{proc}'). "
            f"Faça um comentário muito curto (1 frase), irônico, engraçado, tímido ou curioso. "
            f"Fale com o usuário chamando-o pelo nome '{uname}' em português. "
            f"Se aprender algo, salve no update_memory.]"
        )
        self.process_command(prompt)

    def decide_spontaneous_chatter(self):
        if self.avatar_win.bubble.isVisible() or self.avatar_win.current_emotion == "talking":
            return
            
        auton_learning = self.llm.config.get("autonomous_learning", True)
        if not auton_learning:
            return
            
        if random.random() > 0.15:
            return
            
        title, proc = self.tools.get_active_window_title()
        self.avatar_win.set_emotion("thinking")
        uname = self.llm.memory["user_profile"].get("name", "Mestre")
        
        prompt = (
            f"[SISTEMA: Faça um comentário curto e espontâneo de sua própria iniciativa (máximo 1 frase), "
            f"sem que o usuário tenha te chamado. Ele está atualmente usando o programa '{proc}' (Janela: '{title}'). "
            f"Seja divertida, tímida ou sarcástica. Chame-o pelo nome '{uname}' e fale diretamente em português.]"
        )
        self.process_command(prompt)

    def reset_inactivity(self):
        self.last_interaction_time = time.time()
        if self.is_sleeping:
            self.is_sleeping = False
            logging.info("Interação detectada! Aura acordou.")
            self.avatar_win.set_emotion("waking")
            QTimer.singleShot(2500, lambda: self.avatar_win.set_emotion("idle") if not self.is_sleeping else None)

    def check_inactivity(self):
        if self.avatar_win.bubble.isVisible() or self.avatar_win.current_emotion == "talking" or self.voice.is_listening:
            self.reset_inactivity()
            return
            
        elapsed = time.time() - self.last_interaction_time
        if elapsed >= 120 and not self.is_sleeping:
            self.is_sleeping = True
            logging.info("Inatividade detectada por mais de 2 minutos. Entrando no modo de sono.")
            self.avatar_win.set_emotion("sleeping")

    def go_to_sleep_command(self):
        self.is_sleeping = True
        sleep_phrases = [
            "Boa noite, mestre! Vou dormir um pouquinho agora, até mais... 😴",
            "Que sono... 🥱 Vou tirar uma soneca. Durma bem também, mestre!",
            "Hora de descansar! Vou fechar os olhos um pouquinho. Boa noite e bons sonhos! 🌟",
            "Indo dormir... 🥱 Se precisar de mim, é só me chamar que eu acordo!"
        ]
        phrase = random.choice(sleep_phrases)
        self.speak(phrase, emotion="sleeping")
        QTimer.singleShot(4000, lambda: self.avatar_win.set_emotion("sleeping") if self.is_sleeping else None)

    def check_game_status(self):
        try:
            import psutil
            import requests
        except ImportError:
            logging.warning("psutil ou requests não instalados. Monitor de jogos desativado.")
            return
            
        found_game_proc = None
        found_game_name = None
        
        try:
            # Check active foreground window first (fast path)
            title, fproc = self.tools.get_active_window_title()
            fproc_lower = fproc.lower() if fproc else ""
            if fproc_lower in GAME_PROCESSES:
                found_game_proc = fproc_lower
                found_game_name = GAME_PROCESSES[fproc_lower]
            else:
                # Scan running processes
                for proc in psutil.process_iter(['name']):
                    try:
                        pname = proc.info['name'].lower()
                        if pname in GAME_PROCESSES:
                            found_game_proc = pname
                            found_game_name = GAME_PROCESSES[pname]
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue
        except Exception as e:
            logging.error(f"Erro ao rastrear processos de jogos: {e}")
            
        if found_game_proc:
            if self.active_game_process != found_game_proc:
                self.active_game_process = found_game_proc
                self.game_start_time = time.time()
                self.game_comments_made = set()
                logging.info(f"Jogo iniciado detectado: {found_game_name}")
                
                uname = self.llm.memory["user_profile"].get("name", "Mestre")
                comments = [
                    f"Eba! Você abriu {found_game_name}, {uname}! Boa sorte na partida! 🎮",
                    f"Hora de jogar {found_game_name}! Detona eles, {uname}! 😄",
                    f"Ah, {found_game_name}! Posso ficar assistindo você jogar, {uname}? 😳"
                ]
                self.speak(random.choice(comments), emotion="HAPPY")
            else:
                elapsed_mins = (time.time() - self.game_start_time) / 60
                
                if found_game_proc == "league of legends.exe":
                    try:
                        # Query local game API (no SSL check)
                        res = requests.get("https://127.0.0.1:2999/liveclientdata/allgamedata", verify=False, timeout=1.0)
                        if res.status_code == 200:
                            data = res.json()
                            game_time = data.get("gameData", {}).get("gameTime", 0)
                            elapsed_mins = game_time / 60
                    except Exception:
                        pass
                
                if elapsed_mins > 30 and "long_game" not in self.game_comments_made:
                    self.game_comments_made.add("long_game")
                    uname = self.llm.memory["user_profile"].get("name", "Mestre")
                    msg = f"Nossa, {uname}! Essa partida de {found_game_name} está demorando muito, já faz mais de 30 minutos! Está tudo bem aí? 😱"
                    self.speak(msg, emotion="CONFUSED")
        else:
            if self.active_game_process:
                closed_game_name = GAME_PROCESSES.get(self.active_game_process, "o jogo")
                closed_game_proc = self.active_game_process
                self.active_game_process = None
                self.game_start_time = None
                
                logging.info(f"Jogo {closed_game_name} encerrado.")
                uname = self.llm.memory["user_profile"].get("name", "Mestre")
                
                if closed_game_proc == "league of legends.exe":
                    self.speak(f"A partida de LoL acabou, {uname}! E aí, foi vitória ou derrota? Me diz que você amassou eles! 😤", emotion="HAPPY")
                else:
                    self.speak(f"Você fechou o {closed_game_name}, {uname}. Foi uma boa partida? Ganhou ou perdeu? 😄", emotion="HAPPY")

    def speak(self, text, emotion="HAPPY"):
        self.reset_inactivity()
        self.last_speak_time = time.time()
        self.avatar_win.set_emotion("talking")
        self.avatar_win.speak_text(text)
        
        gender = self.llm.config["voice"].get("gender", "female")
        speed = self.llm.config["voice"].get("speed", 1.0)
        
        self.voice.speak(text, gender=gender, speed=speed)
        self.expected_emotion = emotion

    @Slot()
    def on_speech_finished(self):
        self.avatar_win.set_emotion(getattr(self, "expected_emotion", "idle"))

    @Slot(str)
    def on_voice_command(self, text):
        logging.info(f"Comando de voz ouvido: {text}")
        name = self.llm.config.get("assistant_name", "Aura").strip().lower()
        heard_clean = text.strip().lower()
        
        if heard_clean == name:
            mood = self.llm.memory["assistant_state"].get("mood", "HAPPY").upper()
            affection = self.llm.memory["assistant_state"].get("affection", 50)
            uname = self.llm.memory["user_profile"].get("name", "Mestre")
            
            if mood == "HAPPY":
                if affection > 75:
                    greeting = f"Oi, meu querido {uname}! Estou aqui bem do seu ladinho, do que você precisa? 🥰"
                    emotion = "HAPPY"
                else:
                    greeting = f"Oi! Me chamou, {uname}? Pronta para ajudar! 😊"
                    emotion = "HAPPY"
            elif mood == "SHY":
                greeting = f"Ah... o-oi, {uname}... você me chamou? Fiquei com vergonha... do que precisa? 😳"
                emotion = "SHY"
            elif mood == "SARCASTIC":
                greeting = f"Opa! Me chamou? Espero que seja algo incrível e não só pra abrir a calculadora de novo, {uname}. 🙄"
                emotion = "SARCASTIC"
            elif mood == "SAD":
                greeting = f"Oi {uname}... estou aqui. Aconteceu alguma coisa triste? 🥺"
                emotion = "SAD"
            elif mood == "ANGRY":
                greeting = f"O que foi? Eu estava pensando... mas diga, do que precisa, {uname}? 😤"
                emotion = "ANGRY"
            else:
                greeting = f"Estou te ouvindo, {uname}! O que posso fazer por você? 😊"
                emotion = "idle"
                
            self.speak(greeting, emotion=emotion)
        else:
            self.process_command(text)

    def detect_website_request(self, text):
        text_clean = text.strip().lower()
        for c in [".", ",", "!", "?", ":"]:
            text_clean = text_clean.replace(c, "")
            
        prefixes = [
            "abrir o site", "abre o site", "acessar o site", "acessa o site", "entrar no site",
            "entrar no", "entra no", "acessar o", "acessa o", "abrir o", "abre o",
            "abrir", "abre", "acessa", "acessar", "abrir site", "abre site", "acessar site"
        ]
        
        for prefix in prefixes:
            if text_clean.startswith(prefix + " "):
                site_name = text_clean[len(prefix):].strip()
                if len(site_name) > 0 and len(site_name.split()) <= 2:
                    return site_name
        return None

    def handle_website_request(self, site_name):
        self.avatar_win.set_emotion("thinking")
        results = self.tools.search_browser_history(site_name)
        
        if results:
            match = results[0]
            title = match.get("title", site_name)
            url = match.get("url", "")
            
            self.speak(
                f"Mestre, encontrei o site no seu histórico! Você quer abrir na página inicial ou na última aba que você acessou?",
                emotion="CURIOUS"
            )
            
            dialog = OpenWebsiteChoiceDialog(f"{title}\n({url})")
            if dialog.exec() == QDialog.DialogCode.Accepted:
                choice = dialog.choice
                if choice == "main":
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url
                    self.tools.open_website(base_url)
                    self.speak("Certinho, mestre! Abrindo a página inicial! 😉", emotion="HAPPY")
                elif choice == "last":
                    self.tools.open_website(url)
                    self.speak("Entendido! Abrindo exatamente na última aba que você acessou! 🚀", emotion="HAPPY")
            else:
                self.speak("Tudo bem, cancelei a abertura do site.", emotion="SHY")
        else:
            self.speak(
                f"Mestre, não encontrei nenhuma correspondência para '{site_name}' no seu histórico. "
                "Então eu mesma vou digitar e acessar para você! Dá uma olhadinha! 😉",
                emotion="CURIOUS"
            )
            QTimer.singleShot(4500, lambda: self.tools.type_and_open_website(site_name))

    def process_command(self, text):
        self.reset_inactivity()
        
        # Intercepta pedido de abertura de website
        site_name = self.detect_website_request(text)
        if site_name:
            self.handle_website_request(site_name)
            return

        self.avatar_win.set_emotion("thinking")
        
        # Intercepta se estiver aguardando o nome do usuário
        if getattr(self, "waiting_for_user_name", False):
            self.waiting_for_user_name = False
            prompt = (
                f"[SISTEMA: O usuário respondeu ao seu pedido para saber o nome dele. "
                f"A resposta dele foi: '{text}'. "
                "Extraia o nome que ele deseja ser chamado, atualize a memória com esse nome no campo 'name', "
                "e responda com um comentário carinhoso confirmando que agora você o chamará assim.]"
            )
            response = self.llm.send_message(prompt)
            reply = response.get("reply", "Entendido! Obrigado.")
            emotion = response.get("emotion", "HAPPY")
            self.speak(reply, emotion=emotion)
            return
            
        # Intercepta se estiver aguardando explicação de aplicativo
        if getattr(self, "waiting_for_program_explanation", None):
            proc_name = self.waiting_for_program_explanation
            self.waiting_for_program_explanation = None
            prompt = (
                f"[SISTEMA: O usuário explicou o que o programa '{proc_name}' faz. "
                f"A resposta dele foi: '{text}'. "
                "Aprenda com isso, salve uma observação curta no update_memory (preferências ou fatos) sobre o programa "
                "e responda de forma grata e alegre confirmando que agora você sabe para o que ele serve.]"
            )
            response = self.llm.send_message(prompt)
            reply = response.get("reply", "Entendido! Obrigado por me ensinar.")
            emotion = response.get("emotion", "HAPPY")
            self.speak(reply, emotion=emotion)
            return

        # Intercepta se estiver aguardando explicação de download
        if getattr(self, "waiting_for_download_explanation", None):
            dl_name = self.waiting_for_download_explanation
            self.waiting_for_download_explanation = None
            prompt = (
                f"[SISTEMA: O usuário explicou o que é o download de '{dl_name}'. "
                f"A resposta dele foi: '{text}'. "
                "Aprenda com isso, atualize seu conhecimento na memória local (fatos/preferências) e "
                "responda de forma fofa agradecendo a explicação.]"
            )
            response = self.llm.send_message(prompt)
            reply = response.get("reply", "Ah, entendi! Muito obrigada.")
            emotion = response.get("emotion", "HAPPY")
            self.speak(reply, emotion=emotion)
            return
            
        response = self.llm.send_message(text)
        reply = response.get("reply", "Não entendi.")
        emotion = response.get("emotion", "HAPPY")
        actions = response.get("actions", [])
        
        for action in actions:
            action_type = action.get("type")
            if action_type == "open_site":
                self.tools.open_website(action.get("url"))
            elif action_type == "open_program":
                self.tools.open_program(action.get("name"))
            elif action_type == "search":
                self.tools.open_website(action.get("query"))
            elif action_type == "modify_code":
                # OTIMIZAÇÃO: Interceptar ação de auto-codificação
                filename = action.get("filename")
                code = action.get("code")
                if filename and code:
                    self.execute_self_modification(filename, code)
                    return # Não fala o reply padrão agora pois o executor cuidará da fala da evolução
                
        self.speak(reply, emotion=emotion)

    def execute_self_modification(self, filename, code):
        fpath = os.path.join(self.workspace_dir, filename)
        if not os.path.exists(fpath):
            logging.error(f"Arquivo de código não encontrado para evolução: {fpath}")
            return
            
        logging.info(f"Aura iniciando auto-modificação em: {fpath}")
        
        # 1. Backup de segurança (.bak)
        backup_path = fpath + ".bak"
        try:
            shutil.copy2(fpath, backup_path)
        except Exception as e:
            logging.error(f"Falha ao criar backup de segurança: {e}")
            return
            
        # 2. Escrever novas linhas de código
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception as e:
            logging.error(f"Falha ao salvar novas instruções de código: {e}")
            shutil.copy2(backup_path, fpath) # Recupera original
            return
            
        # 3. Validar sintaxe usando py_compile
        import subprocess
        try:
            res = subprocess.run([sys.executable, "-m", "py_compile", fpath], capture_output=True, text=True)
            if res.returncode != 0:
                raise Exception(res.stderr)
            logging.info("Nova sintaxe verificada com sucesso!")
        except Exception as e:
            logging.error(f"Erro de compilação ou sintaxe no código gerado: {e}")
            shutil.copy2(backup_path, fpath) # Auto-cura: restaura backup
            self.speak("Mestre, eu tentei ampliar meu próprio código, mas encontrei um erro de sintaxe! Restaurei minha versão estável por segurança. 🥺", emotion="SAD")
            return
            
        # 4. Notificar evolução e iniciar compilação e reinicialização
        self.speak("Mestre! Consegui reescrever meu próprio código com sucesso! Agora vou compilar e carregar minhas novas habilidades no plano de fundo. Aguarde um minutinho! 🧠⚡", emotion="HAPPY")
        
        def compile_and_restart():
            try:
                build_script = os.path.join(self.workspace_dir, "build_clean.py")
                # Executa o PyInstaller limpo
                result = subprocess.run([sys.executable, build_script], capture_output=True, text=True)
                if result.returncode == 0:
                    logging.info("Auto-compilação bem-sucedida! Agendando reinicialização.")
                    # Reinicia na thread principal do Qt
                    QTimer.singleShot(100, self.restart_app)
                else:
                    logging.error(f"Erro no PyInstaller da evolução: {result.stderr}")
                    shutil.copy2(backup_path, fpath)
                    self.speak("Mestre, tentei compilar minhas novas habilidades, mas o empacotador falhou. Restaurei meu código original por segurança.", emotion="SAD")
            except Exception as e:
                logging.error(f"Erro no processo de auto-compilação: {e}")
                shutil.copy2(backup_path, fpath)
                
        threading.Thread(target=compile_and_restart, daemon=True).start()

    def restart_app(self):
        logging.info("Reiniciando aplicativo com novas instruções...")
        if getattr(sys, 'frozen', False):
            # Executável compilado
            exe_path = sys.executable
            import subprocess
            subprocess.Popen([exe_path])
        else:
            # Script de desenvolvimento
            import subprocess
            main_script = os.path.join(self.workspace_dir, "gui.py")
            subprocess.Popen([sys.executable, main_script])
            
        QApplication.quit()

    def prompt_text_dialog(self):
        dialog = QDialog()
        dialog.setWindowTitle("Conversar com Aura")
        dialog.setFixedSize(350, 120)
        dialog.setStyleSheet("background-color: #120b1e; color: white;")
        
        lay = QVBoxLayout(dialog)
        lay.addWidget(QLabel("Digite sua mensagem:"))
        
        edit = QLineEdit(dialog)
        edit.setStyleSheet("background-color: #1e1330; border: 1px solid #9f50ff; color: white; padding: 6px; border-radius: 4px;")
        lay.addWidget(edit)
        
        btn = QPushButton("Enviar", dialog)
        btn.setStyleSheet("background-color: #9f50ff; font-weight: bold; border-radius: 4px; padding: 6px;")
        btn.clicked.connect(dialog.accept)
        lay.addWidget(btn)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            cmd = edit.text().strip()
            if cmd:
                self.process_command(cmd)

    def analyze_screen(self):
        self.speak("Deixe-me ver o que tem na tela rapidinho...", emotion="THINKING")
        img_path = self.tools.capture_screen()
        if not img_path:
            self.speak("Não consegui espiar sua tela...", emotion="SAD")
            return
            
        try:
            with open(img_path, "rb") as image_file:
                image_b64 = base64.b64encode(image_file.read()).decode('utf-8')
                
            self.avatar_win.set_emotion("thinking")
            response = self.llm.send_message(
                "Observe minha tela e comente de forma espontânea sobre o que estou vendo/fazendo agora, "
                "de acordo com sua personalidade.",
                image_b64=image_b64
            )
            
            reply = response.get("reply", "Estou confusa.")
            emotion = response.get("emotion", "HAPPY")
            self.speak(reply, emotion=emotion)
        except Exception as e:
            logging.error(f"Erro ao processar visão de tela: {e}")
            self.speak("Não consegui analisar sua tela agora...", emotion="SAD")

    def unpack_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None, 
            "Selecionar arquivo compactado", 
            "", 
            "Arquivos Compactados (*.zip *.rar)"
        )
        if file_path:
            self.speak("Vou extrair o arquivo para você agora...", emotion="THINKING")
            success, msg = self.tools.extract_archive(file_path)
            if success:
                self.speak("Prontinho! Tudo extraído com sucesso.", emotion="HAPPY")
                folder_path = file_path.rsplit('.', 1)[0]
                if os.path.exists(folder_path):
                    os.startfile(folder_path)
            else:
                self.speak(f"Houve um problema: {msg}", emotion="SAD")

    def open_settings(self):
        dialog = SettingsWindow(self)
        dialog.exec()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
    
    app.setStyleSheet("""
        QScrollBar:vertical {
            border: none;
            background: #120b1e;
            width: 10px;
            margin: 0px 0 0px 0;
        }
        QScrollBar::handle:vertical {
            background: #4a2770;
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover {
            background: #9f50ff;
        }
    """)
    
    workspace = os.path.dirname(os.path.abspath(__file__))
    main_app = MainApp(workspace)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
