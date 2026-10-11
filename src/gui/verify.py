"""
verify.py - Manual boundary verification with keyboard navigation
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QFrame, QMessageBox, QApplication, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap, QFont
import sys
import os
import subprocess
import json
import datetime
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from core import LoadingSegment, format_timestamp


class BoundaryWidget(QFrame):
    """Single boundary frame with image, timestamp, and keyboard controls."""

    def __init__(self, video_path: str, segment_idx: int, boundary_type: str, initial_ts: float):
        super().__init__()
        self.video_path = video_path
        self.segment_idx = segment_idx
        self.boundary_type = boundary_type
        self.timestamp = initial_ts
        self.fps = cv2.VideoCapture(video_path).get(cv2.CAP_PROP_FPS)
        
        self._setup_ui()
        self._load_frame()

    def _setup_ui(self):
        self.setObjectName("BoundaryWidget")
        self.setFocusPolicy(Qt.StrongFocus)
        
        self.setStyleSheet("""
            #BoundaryWidget {
                background-color: transparent;
                border: none;
                padding: 0;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        # Frame label with timestamp
        self.label = QLabel(f"#{self.segment_idx + 1} {self.boundary_type.upper()} | {format_timestamp(self.timestamp)}")
        self.label.setProperty("accent", "true")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        # Frame display area
        self.image_label = QLabel("Loading...")
        self.image_label.setMinimumSize(320, 180)
        self.image_label.setMaximumSize(640, 360)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.mousePressEvent = lambda e: self.setFocus()
        layout.addWidget(self.image_label)

        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusIn:
            self.setStyleSheet("""
                #BoundaryWidget {
                    background-color: transparent;
                    border: 3px solid #F2009D;
                    border-radius: 0px;
                    padding: 10px;
                }
            """)
        elif event.type() == event.Type.FocusOut:
            self.setStyleSheet("""
                #BoundaryWidget {
                    background-color: transparent;
                    border: none;
                    padding: 0;
                }
            """)
        return super().eventFilter(obj, event)

    def _load_frame(self):
        cmd = [
            'ffmpeg', '-y', '-ss', f'{self.timestamp:.3f}',
            '-i', self.video_path,
            '-vframes', '1',
            '-vf', 'scale=640:360,setsar=1',
            '-f', 'image2pipe', '-vcodec', 'ppm', '-'
        ]
        result = subprocess.run(cmd, capture_output=True)
        
        if result.returncode != 0 or len(result.stdout) == 0:
            self.image_label.setText("Failed")
            return
        
        pixmap = QPixmap()
        pixmap.loadFromData(result.stdout, 'PPM')
        
        if pixmap.isNull():
            self.image_label.setText("Failed")
        else:
            scaled = pixmap.scaled(640, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled)

    def step(self, frames: int):
        self.timestamp = max(0, self.timestamp + frames / self.fps)
        self.label.setText(f"#{self.segment_idx + 1} {self.boundary_type.upper()} | {format_timestamp(self.timestamp)}")
        self._load_frame()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_H):
            self.step(-5)
        elif key in (Qt.Key_Left, Qt.Key_J):
            self.step(-1)
        elif key in (Qt.Key_Right, Qt.Key_K):
            self.step(1)
        elif key in (Qt.Key_Down, Qt.Key_L):
            self.step(5)
        else:
            super().keyPressEvent(event)

    def get_timestamp(self):
        return self.timestamp


class VerificationWidget(QWidget):
    """Verification screen with vertical segment stacking and improved layout."""
    
    finish_requested = Signal(dict)
    back_requested = Signal()
    restart_requested = Signal()  # Class-level signal for full restart

    def __init__(self, video_path: str, segments: list):
        super().__init__()
        self.video_path = video_path
        self.segments = segments
        self.boundary_widgets = []
        self.segment_count = len(segments)
        
        self._setup_ui()
        QTimer.singleShot(50, self._set_focus_to_first)

    def _setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)
        self.setLayout(main_layout)

        # ========== PAGE TITLE ==========
        title = QLabel("Manual frame picking")
        title.setProperty("heading", "true")
        main_layout.addWidget(title)

        # ========== KEYBOARD HINTS ==========
        hints_text = "[Tab/Shift+Tab] navigate frames | [j/k] ±1 frame | [h/l] ±5 frames | [↑/↓] ±5 frames | [←/→] ±1 frame | [Enter] finish"
        hints = QLabel(hints_text)
        hints.setProperty("muted", "true")
        main_layout.addWidget(hints)

        # ========== SCROLLABLE SEGMENT AREA ==========
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(0, 10, 0, 0)

        for idx, seg in enumerate(self.segments):
            box = self._build_segment_box(idx, seg)
            content_layout.addWidget(box)

        content_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

        # ========== BUTTON ROW ==========
        btn_row = QHBoxLayout()
        
        # BACK BUTTON (go to detection screen)
        self.back_btn = QPushButton("Back")
        self.back_btn.setProperty("secondary", "true")
        self.back_btn.setMinimumHeight(40)
        self.back_btn.clicked.connect(self.back_requested.emit)
        btn_row.addWidget(self.back_btn)
        
        # RESTART BUTTON (reset to video loader)
        self.restart_btn = QPushButton("Restart")
        self.restart_btn.setProperty("secondary", "true")
        self.restart_btn.setMinimumHeight(40)
        self.restart_btn.clicked.connect(self._restart_app)
        btn_row.addWidget(self.restart_btn)
        
        btn_row.addStretch()

        # FINISH BUTTON (export and complete)
        self.finish_btn = QPushButton("Finish/Export")
        self.finish_btn.setProperty("primary", "true")
        self.finish_btn.setMinimumHeight(40)
        self.finish_btn.clicked.connect(self._finish_dialog)
        btn_row.addWidget(self.finish_btn, stretch=1)
        
        # EXIT BUTTON (close application)
        self.exit_btn = QPushButton("Exit")
        self.exit_btn.setProperty("secondary", "true")
        self.exit_btn.setProperty("danger", "true")
        self.exit_btn.setMinimumHeight(40)
        self.exit_btn.clicked.connect(self._exit_app)
        btn_row.addWidget(self.exit_btn)

        main_layout.addLayout(btn_row)
        self.setFocusPolicy(Qt.StrongFocus)

    def _exit_app(self):
        """Close the application immediately."""
        QApplication.instance().quit()

    def _restart_app(self):
        """Emit restart signal to MainWindow for full reset."""
        self.restart_requested.emit()

    def _build_segment_box(self, idx: int, seg: LoadingSegment):
        box = QGroupBox(f"#{idx + 1} (of {self.segment_count})")
        box.setProperty("segment-box", "true")
        
        layout = QHBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(12, 12, 12, 12)
        box.setLayout(layout)

        # Start frame (left)
        start_w = BoundaryWidget(self.video_path, idx, "start", seg.start_sec)
        self.boundary_widgets.append(start_w)
        layout.addWidget(start_w, stretch=1)

        # End frame (right)
        end_w = BoundaryWidget(self.video_path, idx, "end", seg.end_sec)
        self.boundary_widgets.append(end_w)
        layout.addWidget(end_w, stretch=1)

        return box

    def _set_focus_to_first(self):
        if self.boundary_widgets:
            self.boundary_widgets[0].setFocus()
            self._scroll_to_widget(self.boundary_widgets[0])

    def _scroll_to_widget(self, widget):
        scroll_area = self.findChild(QScrollArea)
        if scroll_area:
            scroll_area.ensureWidgetVisible(widget, 10, 10)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Tab:
            event.accept()
            focused = QApplication.focusWidget()
            if focused in self.boundary_widgets:
                idx = self.boundary_widgets.index(focused)
                next_idx = (idx + 1) % len(self.boundary_widgets)
                self.boundary_widgets[next_idx].setFocus()
                self._scroll_to_widget(self.boundary_widgets[next_idx])
                return
        elif key == Qt.Key_Backtab:
            event.accept()
            focused = QApplication.focusWidget()
            if focused in self.boundary_widgets:
                idx = self.boundary_widgets.index(focused)
                prev_idx = (idx - 1) % len(self.boundary_widgets)
                self.boundary_widgets[prev_idx].setFocus()
                self._scroll_to_widget(self.boundary_widgets[prev_idx])
                return
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._finish_dialog()
            return
        super().keyPressEvent(event)

    def _finish_dialog(self):
        """Auto-export to timestamped directory in output/ folder."""
        corrected = []
        for i in range(0, len(self.boundary_widgets), 2):
            start_ts = self.boundary_widgets[i].get_timestamp()
            end_ts = self.boundary_widgets[i + 1].get_timestamp()
            corrected.append(LoadingSegment(start_sec=start_ts, end_sec=end_ts))
    
        total = sum(s.duration for s in corrected)
    
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_output_dir = os.path.normpath(os.path.join(script_dir, "..", "..", "output"))
        os.makedirs(base_output_dir, exist_ok=True)
    
        timestamp_str = datetime.datetime.now().strftime("%y%m%d%H%M%S")
        run_dir = os.path.join(base_output_dir, timestamp_str)
        os.makedirs(run_dir, exist_ok=True)
    
        hybrid_json_path = os.path.join(run_dir, "hybrid.json")
        frames_dir = os.path.join(run_dir, "frames")
        cmd_script_path = os.path.join(run_dir, "command_lines.sh")
    
        with open(hybrid_json_path, 'w') as f:
            json.dump({
                "video": self.video_path,
                "segments": [s.to_dict() for s in corrected],
                "segment_count": len(corrected),
                "total_loading_sec": round(total, 3),
                "verification_mode": "gui_manual",
                "export_timestamp": datetime.datetime.now().isoformat()
            }, f, indent=2)
    
        os.makedirs(frames_dir, exist_ok=True)
    
        ffmpeg_extract_cmds = ["#!/bin/bash", f"# Video: {self.video_path}", f"# Output dir: {run_dir}", ""]
    
        for i, seg in enumerate(corrected):
            start_ts = seg.start_sec
            start_img_name = f"start{i+1}.png"
            start_img_path = os.path.join(frames_dir, start_img_name)
    
            ffmpeg_start_cmd = f'ffmpeg -ss {start_ts:.3f} -i "{self.video_path}" -vframes 1 -vf "scale=640:360" "{start_img_path}"'
            ffmpeg_extract_cmds.append(f"# Segment {i+1} START")
            ffmpeg_extract_cmds.append(ffmpeg_start_cmd)
            self._save_annotated_frame(start_ts, start_img_path, i+1, "START")
    
            end_ts = seg.end_sec
            end_img_name = f"end{i+1}.png"
            end_img_path = os.path.join(frames_dir, end_img_name)
    
            ffmpeg_end_cmd = f'ffmpeg -ss {end_ts:.3f} -i "{self.video_path}" -vframes 1 -vf "scale=640:360" "{end_img_path}"'
            ffmpeg_extract_cmds.append(f"# Segment {i+1} END")
            ffmpeg_extract_cmds.append(ffmpeg_end_cmd)
            self._save_annotated_frame(end_ts, end_img_path, i+1, "END")
    
        with open(cmd_script_path, 'w') as f:
            f.write("\n".join(ffmpeg_extract_cmds))
            f.write("\n")
    
        os.chmod(cmd_script_path, 0o755)
    
        QMessageBox.information(self, "Export Complete",
            f"Saved to:\n{run_dir}\n\n"
            f"Files:\n- hybrid.json\n"
            f"- frames/start1.png, end1.png, ...\n"
            f"- command_lines.sh (executable)")
    
        self.finish_requested.emit({
            "hybrid_json_path": hybrid_json_path,
            "frames_dir": frames_dir,
            "cmd_script_path": cmd_script_path
        })

    def _save_annotated_frame(self, timestamp: float, output_path: str,
                               segment_num: int, boundary_type: str):
        """Extract frame and add text overlay."""
        from PIL import Image, ImageDraw, ImageFont

        cmd = [
            'ffmpeg', '-y', '-ss', f'{timestamp:.3f}',
            '-i', self.video_path,
            '-vframes', '1',
            '-vf', 'scale=640:360,setsar=1',
            '-f', 'image2pipe', '-vcodec', 'ppm', '-'
        ]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0:
            print(f"[warn] Failed to extract frame at {timestamp}")
            return

        try:
            img = Image.frombytes('RGB', (640, 360), result.stdout, 'raw', 'RGB', 0, 0)
        except:
            tmp_path = '/tmp/temp_frame.png'
            with open(tmp_path, 'wb') as f:
                f.write(result.stdout)
            img = Image.open(tmp_path)
            img.save(output_path)
            return

        draw = ImageDraw.Draw(img)

        text_top = f"{os.path.basename(self.video_path)}"
        text_mid = f"Segment {segment_num} - {boundary_type} @ {format_timestamp(timestamp)}"
        text_bot = f"ffmpeg -ss {timestamp:.3f} -i input.mp4 -vframes 1 frame.png"

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
            small_font = font

        bg_height = 70
        draw.rectangle([(0, 360-bg_height), (640, 360)], fill=(0, 0, 0, 180))

        draw.text((10, 360-55), text_top, fill=(255, 255, 255), font=small_font)
        draw.text((10, 360-35), text_mid, fill=(109, 74, 255), font=font)
        draw.text((10, 360-15), text_bot, fill=(200, 200, 200), font=small_font)

        img.save(output_path)
