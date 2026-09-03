"""
loader.py - Video loading and welcome screen widget
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QFileDialog, QGroupBox,
    QComboBox
)
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QPixmap
import sys
import os
import tempfile

# Import from core module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core import get_video_duration

class VideoLoaderWidget(QWidget):
    """Modular widget for video loading with welcome screen."""
    
    video_loaded = Signal(str)  # Emits video path when loaded

    def __init__(self):
        super().__init__()
        
        self._setup_ui()
        self.video_path = None
        self.metadata = {}

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setLayout(layout)
        
        # === LOGO SECTION ===
        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setMaximumHeight(120)
        
        # Logo paths to search 
        logo_paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', 'logo.png'),
            os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'logo.png'),
            os.path.join(os.path.dirname(__file__), 'logo.png'),
        ]
        
        for logo_path in logo_paths:
            if os.path.exists(logo_path):
                pixmap = QPixmap(logo_path)
                scaled = pixmap.scaled(
                    800, 160, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
                self.logo_label.setPixmap(scaled)
                break
        # If no logo found, label remains empty 
        layout.addWidget(self.logo_label)
        
        # === WELCOME MESSAGE WITH USER MANUAL ===
        welcome_text = """
        <div style="text-align: center; margin-bottom: 20px;">
                Welcome to Windblown-s-RTA2LRT, 
                a community tool to help users and the <a href="https://www.speedrun.com/Windblown" style="color: #F2009D;">speedrun.com</a> 
                moderation team detect loading times with minimal effort.
        </div>
        
        <div style="background-color: #1A0B28; padding: 15px; border-radius: 0px; border: 2px solid #9432a1; text-align: left; margin-bottom: 20px;">
            <span style="font-size: 14px; font-weight: 700; color: #F2009D;">User Manual:</span><br><br>
            
            <span style="color: #cc33ba;">1.</span> <b>Provide a video</b> and load it below.<br>
            <span style="color: #cc33ba;">2.</span> Using the <b>Spectrogram</b>, find the loading regions and click on them. 
            Only mark segments where the in-game timer is active. If you were not talking during them, they should appear quiet (black).<br>
            <span style="color: #cc33ba;">3.</span> Let the tool <b>auto-detect</b> the approximate boundaries.<br>
            <span style="color: #cc33ba;">4.</span> For each <b>start/end frame</b> pair, locate the first visible <b>"purple loading frame"</b> 
            using <b>h/j</b> (previous) and <b>k/l</b> (next) keys. If no clear purple frame exists, select the earliest frame showing the loading screen.<br>
            <span style="color: #cc33ba;">5.</span> <b>Export!</b> The files in the output directory help moderation verify proper tool usage.<br><br>
            
            <span style="color: #7e8791; font-size: 12px;"><i>Note: Windblown-s-RTA2LRT is an assist tool and cannot replace human verification.</i></span>
        </div>
        """
        
        self.welcome_label = QLabel(welcome_text)
        self.welcome_label.setOpenExternalLinks(True)
        self.welcome_label.setWordWrap(True)
        self.welcome_label.setStyleSheet("color: #D5F4F5; padding: 0;")
        self.welcome_label.setMinimumHeight(350)
        layout.addWidget(self.welcome_label)
        
        # === VIDEO SOURCE INPUT SECTION ===
        input_group = QGroupBox("Video Source")
        input_layout = QVBoxLayout(input_group)
        
        # Local file row
        local_row = QHBoxLayout()
        self.local_edit = QLineEdit()
        self.local_edit.setPlaceholderText("Select video file...")
        self.local_edit.setEnabled(False)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.setProperty("secondary", "true")
        browse_btn.clicked.connect(self.browse_local)
        
        local_row.addWidget(self.local_edit, 1)
        local_row.addWidget(browse_btn)
        input_layout.addLayout(local_row)
        
        # URL row
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://youtube.com/watch?v=...")
        
        url_btn = QPushButton("Use URL")
        url_btn.setProperty("secondary", "true")
        url_btn.clicked.connect(self.use_url)
        
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(url_btn)
        input_layout.addLayout(url_row)

        # Browser cookie selector
        browser_row = QHBoxLayout()
        browser_label = QLabel("Your web browser:")
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["firefox", "chrome", "chromium", "edge", "brave", "opera", "safari", "vivaldi", "whale"])
        browser_row.addWidget(browser_label)
        browser_row.addWidget(self.browser_combo)
        browser_row.addStretch()
        input_layout.addLayout(browser_row)
        
        # Load button
        self.load_btn = QPushButton("Load Video")
        self.load_btn.setProperty("primary", "true")
        self.load_btn.clicked.connect(self.load_video)
        self.load_btn.setEnabled(False)
        input_layout.addWidget(self.load_btn)
        
        layout.addWidget(input_group)

    def browse_local(self):
        """Open file dialog and populate local path."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select video file", "",
            "Video Files (*.mp4 *.mkv *.webm *.avi);;All Files (*)"
        )
        if file_path:
            self.local_edit.setText(file_path)
            self.url_edit.clear()
            self._update_load_state()

    def use_url(self):
        """Enable URL mode, disable local file mode."""
        self.local_edit.clear()
        self.local_edit.setEnabled(False)
        self.url_edit.setEnabled(True)
        self._update_load_state()

    def _update_load_state(self):
        """Enable/disable load button based on inputs."""
        has_local = bool(self.local_edit.text())
        has_url = bool(self.url_edit.text().strip())
        self.load_btn.setEnabled(has_local or has_url)

    def load_video(self):
        """Load video (local or download from URL) and show metadata."""
        source = self.local_edit.text() or self.url_edit.text().strip()

        # Handle local file
        if os.path.exists(source):
            self.video_path = source
            self._fetch_metadata(source)
            self.video_loaded.emit(source)
            return

        # Handle URL (download in background)
        try:
            from cli import download_video
            self.load_btn.setEnabled(False)
            self.load_btn.setText("Downloading...")
            
            output_path = os.path.join(tempfile.gettempdir(), f"cached_{__import__('time').strftime('%Y%m%d-%H%M%S')}.mp4")
            self.video_path = download_video(source, output_path, browser=self.browser_combo.currentText())
            
            self._fetch_metadata(self.video_path)
            self.video_loaded.emit(self.video_path)
            self.load_btn.setEnabled(True)
            self.load_btn.setText("Load Video")

        except Exception as e:
            self.load_btn.setEnabled(True)
            self.load_btn.setText("Load Video")
            self.welcome_label.append(f"<br><span style='color: red;'>Download failed: {e}</span>")

    def _fetch_metadata(self, video_path: str):
        """Fetch and validate video metadata."""
        try:
            duration = get_video_duration(video_path)

            if duration < 100:
                self.welcome_label.append(
                    f"<br><span style='color: orange;'>Damn you so fast. GG, next.</span>"
                )

        except Exception as e:
            self.welcome_label.append(f"<br><span style='color: orange;'>Could not validate video: {e}</span>")

    def get_video_path(self) -> str:
        """Return the loaded video path."""
        return self.video_path
