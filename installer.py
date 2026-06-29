import os
import sys
import shutil
import logging
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFileDialog, QProgressBar, QMessageBox
)
from PySide6.QtGui import QFont, QColor, QIcon
from PySide6.QtCore import Qt, QThread, Signal

class InstallWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished_ok = Signal()
    error = Signal(str)
    
    def __init__(self, install_dir):
        super().__init__()
        self.install_dir = install_dir
        
    def run(self):
        try:
            if getattr(sys, 'frozen', False):
                src_dir = getattr(sys, '_MEIPASS', '')
            else:
                src_dir = os.path.dirname(os.path.abspath(__file__))
                
            self.status.emit("Criando diretório de destino...")
            self.progress.emit(10)
            os.makedirs(self.install_dir, exist_ok=True)
            
            src_exe = os.path.join(src_dir, "Aura.exe")
            if not os.path.exists(src_exe):
                src_exe = os.path.join(src_dir, "dist", "Aura.exe")
                
            src_assets = os.path.join(src_dir, "assets")
            src_assets_wolf = os.path.join(src_dir, "assets_wolf")
            
            if not os.path.exists(src_exe):
                raise FileNotFoundError(f"Executável da Aura não encontrado em: {src_exe}")
                
            self.status.emit("Copiando executável da Aura...")
            self.progress.emit(30)
            shutil.copy2(src_exe, os.path.join(self.install_dir, "Aura.exe"))
            
            self.status.emit("Copiando recursos (Menina Chibi)...")
            self.progress.emit(50)
            dest_assets = os.path.join(self.install_dir, "assets")
            if os.path.exists(dest_assets):
                shutil.rmtree(dest_assets)
            if os.path.exists(src_assets):
                shutil.copytree(src_assets, dest_assets)
                
            self.status.emit("Copiando recursos (Lobinho Chibi)...")
            self.progress.emit(70)
            dest_assets_wolf = os.path.join(self.install_dir, "assets_wolf")
            if os.path.exists(dest_assets_wolf):
                shutil.rmtree(dest_assets_wolf)
            if os.path.exists(src_assets_wolf):
                shutil.copytree(src_assets_wolf, dest_assets_wolf)
                
            self.status.emit("Criando atalhos no computador...")
            self.progress.emit(90)
            self.create_shortcuts()
            
            self.progress.emit(100)
            self.status.emit("Instalação concluída com sucesso!")
            self.finished_ok.emit()
        except Exception as e:
            self.error.emit(str(e))
            
    def create_shortcuts(self):
        try:
            import winshell
            from win32com.client import Dispatch
            
            desktop = winshell.desktop()
            path_link = os.path.join(desktop, "Aura.lnk")
            target = os.path.join(self.install_dir, "Aura.exe")
            wDir = self.install_dir
            icon = target
            
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(path_link)
            shortcut.Targetpath = target
            shortcut.WorkingDirectory = wDir
            shortcut.IconLocation = icon
            shortcut.save()
            
            start_menu = winshell.start_menu()
            path_link_sm = os.path.join(start_menu, "Programs", "Aura.lnk")
            os.makedirs(os.path.dirname(path_link_sm), exist_ok=True)
            shortcut_sm = shell.CreateShortCut(path_link_sm)
            shortcut_sm.Targetpath = target
            shortcut_sm.WorkingDirectory = wDir
            shortcut_sm.IconLocation = icon
            shortcut_sm.save()
        except Exception as e:
            logging.error(f"Erro ao criar atalhos: {e}")

class InstallerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Instalador da Aura Assistant")
        self.setFixedSize(500, 320)
        self.setStyleSheet("""
            QWidget {
                background-color: #120b1e;
                color: #ffffff;
                font-family: 'Outfit', 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #e2d7f5;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #1e1330;
                border: 1px solid #783cb0;
                border-radius: 6px;
                color: #ffffff;
                padding: 6px 10px;
                font-size: 13px;
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
            QProgressBar {
                border: 1px solid #4a2770;
                border-radius: 5px;
                text-align: center;
                background-color: #1e1330;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #9f50ff;
                width: 10px;
            }
        """)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)
        
        title = QLabel("Instalador da Aura Assistant")
        title.setFont(QFont("Outfit", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #9f50ff;")
        layout.addWidget(title)
        
        desc = QLabel("Selecione a pasta onde deseja instalar a assistente no seu computador:")
        layout.addWidget(desc)
        
        h_fold = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        default_path = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Aura")
        self.path_edit.setText(default_path)
        h_fold.addWidget(self.path_edit)
        
        self.browse_btn = QPushButton("Procurar...")
        self.browse_btn.clicked.connect(self.browse_folder)
        h_fold.addWidget(self.browse_btn)
        layout.addLayout(h_fold)
        
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        self.status_lbl = QLabel("")
        self.status_lbl.hide()
        layout.addWidget(self.status_lbl)
        
        layout.addStretch()
        
        h_btns = QHBoxLayout()
        h_btns.addStretch()
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setStyleSheet("background-color: #3e2e50;")
        self.cancel_btn.clicked.connect(self.close)
        
        self.install_btn = QPushButton("Instalar")
        self.install_btn.clicked.connect(self.start_install)
        
        h_btns.addWidget(self.cancel_btn)
        h_btns.addWidget(self.install_btn)
        layout.addLayout(h_btns)
        
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Instalação", self.path_edit.text())
        if folder:
            self.path_edit.setText(os.path.join(folder, "Aura"))
            
    def start_install(self):
        install_dir = self.path_edit.text().strip()
        if not install_dir:
            QMessageBox.warning(self, "Aviso", "Por favor, especifique uma pasta de instalação válida!")
            return
            
        self.browse_btn.setEnabled(False)
        self.path_edit.setEnabled(False)
        self.install_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        
        self.progress_bar.show()
        self.status_lbl.show()
        
        self.worker = InstallWorker(install_dir)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.status_lbl.setText)
        self.worker.finished_ok.connect(self.on_success)
        self.worker.error.connect(self.on_error)
        self.worker.start()
        
    def on_success(self):
        QMessageBox.information(self, "Instalação Concluída", "A Aura Assistant foi instalada com sucesso!\nUm atalho foi criado na sua Área de Trabalho.")
        self.close()
        
    def on_error(self, err_msg):
        QMessageBox.critical(self, "Erro na Instalação", f"Ocorreu um erro durante a instalação:\n{err_msg}")
        self.browse_btn.setEnabled(True)
        self.path_edit.setEnabled(True)
        self.install_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_lbl.hide()

def main():
    app = QApplication(sys.argv)
    window = InstallerWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
