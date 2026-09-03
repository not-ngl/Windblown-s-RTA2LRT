"""
anchors.py - Anchor input with spectrogram and frame preview
"""

import sys
import os
import tempfile
import subprocess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QListWidget, QListWidgetItem, QMessageBox, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QScrollArea
)
from PySide6.QtCore import Qt, Signal, Slot, QThread, QTimer, QObject, QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QWheelEvent
import numpy as np

import math
import time
import threading

import pyqtgraph as pg

from scipy.io import wavfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

class SpectrogramGenerator:
    """Extract audio to a memory-mappable WAV file."""

    SAMPLE_RATE = 22050

    @staticmethod
    def extract_audio(video_path: str) -> str | None:
        if not video_path or not os.path.exists(video_path):
            return None

        fd, temp_wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", video_path,
            "-vn",
            "-ac", "1",
            "-ar", str(SpectrogramGenerator.SAMPLE_RATE),
            "-c:a", "pcm_s16le",
            temp_wav,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"[spec] ffmpeg failed: {result.stderr}")
                os.unlink(temp_wav)
                return None

            return temp_wav

        except FileNotFoundError:
            print("[spec] ffmpeg was not found")
            os.unlink(temp_wav)
            return None

class SpectrogramWorker(QObject):
    rendered = Signal(object, float, float, int)
    failed = Signal(str)

    def __init__(self, audio, sample_rate):
        super().__init__()
        self.audio = audio
        self.sample_rate = sample_rate

    @staticmethod
    def choose_fft_size(visible_seconds: float, sample_rate: int) -> int:
        # Short windows when zoomed in, longer windows when zoomed out.
        desired_window = visible_seconds / 1400.0 * 4.0
        desired_window = np.clip(desired_window, 0.020, 2.0)

        desired_samples = int(desired_window * sample_rate)

        nfft = 256
        while nfft < desired_samples:
            nfft *= 2

        return int(np.clip(nfft, 256, 8192))

    @Slot(float, float, int)
    def render(self, start_time: float, end_time: float, request_id: int):
        try:
            duration = len(self.audio) / self.sample_rate

            start_time = max(0.0, start_time)
            end_time = min(duration, end_time)

            if end_time <= start_time:
                return

            visible_seconds = end_time - start_time
            nfft = self.choose_fft_size(
                visible_seconds,
                self.sample_rate,
            )

            columns = 1400

            all_frequencies = np.fft.rfftfreq(
                nfft,
                1.0 / self.sample_rate,
            )
            rows = min(700, len(all_frequencies))
            frequencies = all_frequencies[:rows]

            image = np.empty(
                (rows, columns),
                dtype=np.float32,
            )

            window = np.hanning(nfft).astype(np.float32)
            half_window = nfft // 2
            audio_length = len(self.audio)

            centers = np.linspace(
                start_time,
                end_time,
                columns,
                endpoint=False,
            )
            centers += visible_seconds / columns / 2.0

            for x, center_time in enumerate(centers):
                center_sample = int(center_time * self.sample_rate)

                left = center_sample - half_window
                right = left + nfft

                segment = np.zeros(nfft, dtype=np.float32)

                source_left = max(0, left)
                source_right = min(audio_length, right)

                if source_right > source_left:
                    dest_left = source_left - left
                    dest_right = dest_left + source_right - source_left

                    samples = self.audio[source_left:source_right]

                    if np.issubdtype(samples.dtype, np.integer):
                        samples = samples.astype(np.float32) / 32768.0
                    else:
                        samples = samples.astype(np.float32)

                    segment[dest_left:dest_right] = samples

                segment *= window

                spectrum = np.abs(np.fft.rfft(segment))
                spectrum = spectrum[:rows]

                image[:, x] = 20.0 * np.log10(
                    spectrum + 1e-10
                )

            high = np.percentile(image, 99.5)
            low = high - 80.0

            image = np.clip(image, low, high)
            image = (image - low) / max(high - low, 1.0)

            self.rendered.emit(
                image,
                start_time,
                end_time,
                request_id,
            )

        except Exception as exc:
            self.failed.emit(str(exc))

class TimeAxis(pg.AxisItem):
    """Format X-axis values as mm:ss.sss or hh:mm:ss.sss."""

    def __init__(self, show_hours=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.show_hours = show_hours

    def set_show_hours(self, show_hours: bool):
        self.show_hours = show_hours
        self.picture = None
        self.update()

    def tickStrings(self, values, scale, spacing):
        labels = []

        for value in values:
            total_seconds = max(0.0, float(value))

            milliseconds = int(round(total_seconds * 1000))
            hours, remainder = divmod(milliseconds, 3_600_000)
            minutes, remainder = divmod(remainder, 60_000)
            seconds, milliseconds = divmod(remainder, 1000)

            if self.show_hours:
                labels.append(
                    f"{hours:02d}:{minutes:02d}:"
                    f"{seconds:02d}.{milliseconds:03d}"
                )
            else:
                total_minutes = int(total_seconds // 60)

                labels.append(
                    f"{total_minutes:02d}:"
                    f"{seconds:02d}.{milliseconds:03d}"
                )

        return labels

class SpectrogramViewer(QWidget):
    """Interactive, dynamically rendered spectrogram."""

    anchor_added = Signal(float)
    anchor_clicked = Signal(float)

    request_render = Signal(float, float, int)

    def __init__(self, video_path: str = "", parent=None):
        super().__init__(parent)

        self.video_path = video_path
        self.anchors = []
        self.selected_timestamp = 0.0

        self.wav_path = None
        self.audio = None
        self.sample_rate = None
        self.duration = 0.0

        self.request_id = 0
        self.anchor_lines = []

        self.worker_thread = None
        self.worker = None

        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(100)
        self.render_timer.timeout.connect(self.render_visible_region)

        self._setup_ui()

        if video_path:
            self.set_video(video_path)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        time_axis = TimeAxis(
            orientation="bottom",
            show_hours=False,
        )
        
        self.plot = pg.PlotWidget(
            axisItems={
                "bottom": time_axis,
            }
        )
        
        self.time_axis = time_axis

        self.plot.setBackground("#0B0B28")

        self.plot.setLabel("bottom", "Time")
        self.plot.setLabel("left", "Frequency", units="kHz")

        self.plot.showGrid(
            x=True,
            y=True,
            alpha=0.25,
        )

        self.plot.setMouseEnabled(
            x=True,
            y=False,
        )

        self.image_item = pg.ImageItem(
            axisOrder="row-major"
        )
        self.image_item.setAutoDownsample(True)

        magma = pg.colormap.get("magma")

        self.image_item.setLookupTable(
            magma.getLookupTable(
                start=0.0,
                stop=1.0,
                nPts=256,
                alpha=True,
            )
        )

        self.plot.addItem(self.image_item)

        self.plot.getPlotItem().sigRangeChanged.connect(
            self.on_range_changed
        )

        # pyqtgraph scene click handling.
        self.plot.scene().sigMouseClicked.connect(
            self.on_scene_clicked
        )

        layout.addWidget(self.plot)

        self.status = QLabel(
            "Click spectrogram to add anchors | "
            "Mouse wheel to zoom | Drag to pan"
        )
        self.status.setStyleSheet(
            "color: #7e8791; padding: 5px; font-size: 11px;"
        )
        layout.addWidget(self.status)

    def set_video(self, video_path: str):
        if not video_path or not os.path.exists(video_path):
            self.status.setText("Invalid video path")
            return False

        self.video_path = video_path

        self.stop_worker()

        if self.wav_path and os.path.exists(self.wav_path):
            try:
                os.unlink(self.wav_path)
            except OSError:
                pass

        self.status.setText("Extracting audio...")

        self.wav_path = SpectrogramGenerator.extract_audio(video_path)

        if not self.wav_path:
            self.status.setText("Could not extract audio")
            return False

        try:
            self.sample_rate, self.audio = wavfile.read(
                self.wav_path,
                mmap=True,
            )

            if self.audio.ndim > 1:
                self.audio = self.audio[:, 0]

            self.duration = len(self.audio) / self.sample_rate
            self.time_axis.set_show_hours(
                    self.duration >= 3600.0
                    )

        except Exception as exc:
            self.status.setText(f"Could not read audio: {exc}")
            return False

        self.worker_thread = QThread(self)
        self.worker = SpectrogramWorker(
            self.audio,
            self.sample_rate,
        )
        self.worker.moveToThread(self.worker_thread)

        self.request_render.connect(
            self.worker.render,
            Qt.ConnectionType.QueuedConnection,
        )

        self.worker.rendered.connect(
            self.apply_rendered_image
        )
        self.worker.failed.connect(
            self.show_error
        )

        self.worker_thread.start()

        self.plot.setLimits(
            xMin=0,
            xMax=self.duration,
            yMin=0,
            yMax=self.sample_rate / 2,
        )

        initial_end = min(10 * 60.0, self.duration)

        self.plot.setXRange(
            0.0,
            initial_end,
            padding=0,
        )
        self.plot.setYRange(
            0.0,
            self.sample_rate / 2,
            padding=0,
        )

        self.status.setText(
            "Loaded | Click spectrogram to add anchors"
        )

        self.render_visible_region()
        return True

    def stop_worker(self):
        if self.worker_thread is not None:
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
            self.worker = None

    def on_range_changed(self):
        self.render_timer.start()

    def render_visible_region(self):
        if self.worker is None:
            return

        view_range = self.plot.getPlotItem().getViewBox().viewRange()
        start_time, end_time = view_range[0]

        start_time = max(0.0, start_time)
        end_time = min(self.duration, end_time)

        if end_time <= start_time:
            return

        self.request_id += 1

        self.request_render.emit(
            start_time,
            end_time,
            self.request_id,
        )

    @Slot(object, float, float, int)
    def apply_rendered_image(
        self,
        image: np.ndarray,
        start_time: float,
        end_time: float,
        request_id: int,
    ):
        if request_id != self.request_id:
            return

        self.image_item.setImage(
            image,
            autoLevels=False,
            levels=(0.0, 1.0),
        )

        self.image_item.setRect(
            QRectF(
                start_time,
                0.0,
                end_time - start_time,
                self.sample_rate / 2.0,
            )
        )

    @Slot(str)
    def show_error(self, message: str):
        print(f"[spectrogram] {message}")
        self.status.setText(f"Spectrogram error: {message[:100]}")

    def on_scene_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        view_box = self.plot.getPlotItem().getViewBox()
        point = view_box.mapSceneToView(event.scenePos())

        timestamp = float(np.clip(
            point.x(),
            0.0,
            self.duration,
        ))

        tolerance = 10.0
        matching_anchor = next(
            (
                anchor
                for anchor in self.anchors
                if abs(anchor - timestamp) <= tolerance
            ),
            None,
        )

        if matching_anchor is not None:
            self.remove_anchor(matching_anchor)
            self.anchor_added.emit(timestamp)
            self.anchor_clicked.emit(-1.0)
            return

        self.selected_timestamp = timestamp
        self.anchors.append(timestamp)
        self.anchors.sort()

        self.add_anchor_line(timestamp)

        self.anchor_added.emit(timestamp)
        self.anchor_clicked.emit(timestamp)

    def add_anchor_line(self, timestamp: float):
        line = pg.InfiniteLine(
            pos=timestamp,
            angle=90,
            movable=False,
            pen=pg.mkPen(
                "#F2009D",
                width=2,
            ),
        )

        self.plot.addItem(line)
        self.anchor_lines.append(line)

    def clear_anchor_lines(self):
        for line in self.anchor_lines:
            self.plot.removeItem(line)

        self.anchor_lines.clear()

    def pixel_to_time(self, screen_x: int) -> float:
        """Compatibility helper for existing code."""
        point = self.plot.getPlotItem().getViewBox().mapSceneToView(
            self.plot.mapToScene(screen_x, 0)
        )

        return float(np.clip(point.x(), 0.0, self.duration))

    def get_selected_timestamp(self) -> float:
        return self.selected_timestamp

    def get_anchors(self) -> list:
        return sorted(self.anchors)

    def remove_anchor(self, timestamp: float):
        if timestamp in self.anchors:
            self.anchors.remove(timestamp)

            self.clear_anchor_lines()
            for anchor in self.anchors:
                self.add_anchor_line(anchor)

    def clear_anchors(self):
        self.anchors.clear()
        self.clear_anchor_lines()

    def closeEvent(self, event):
        self.stop_worker()

        if self.wav_path and os.path.exists(self.wav_path):
            try:
                os.unlink(self.wav_path)
            except OSError:
                pass

        super().closeEvent(event)

class FramePreviewWidget(QWidget):
    """Display video frame preview with timestamp label."""

    def __init__(self, video_path: str, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.last_timestamp = 0.0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        # Scroll area for frame
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMaximumHeight(400)
        self.scroll_area.setMinimumWidth(450)
        self.scroll_area.setStyleSheet("border: 2px solid #9432a1; border-radius: 0px; background-color: #0B0B28;")

        # Frame display widget
        self.frame_widget = QWidget()
        self.frame_layout = QVBoxLayout()
        self.frame_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_widget.setLayout(self.frame_layout)

        self.frame_label = QLabel("Click spectrogram to load frame")
        self.frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_label.setMinimumSize(320, 180)
        self.frame_label.setMaximumWidth(960)
        self.frame_label.setStyleSheet("color: #7e8791;")
        self.frame_layout.addWidget(self.frame_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.scroll_area.setWidget(self.frame_widget)
        layout.addWidget(self.scroll_area)

        # Timestamp label (compact)
        self.timestamp_label = QLabel("t = 0.000s")
        self.timestamp_label.setStyleSheet("color: #cc33ba; font-size: 11px; font-weight: 600;")
        self.timestamp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.timestamp_label)

    def set_frame(self, pixmap: QPixmap, timestamp: float):
        """Update displayed frame."""
        self.last_timestamp = timestamp

        if pixmap.isNull():
            self.frame_label.setText("Failed to load frame")
            self.frame_label.setStyleSheet("color: #7e8791;")
        else:
            # Scale to fit
            target_w = min(640, self.frame_label.maximumWidth())
            target_h = int(target_w * 9 / 16)
            scaled = pixmap.scaled(
                target_w, target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.frame_label.setPixmap(scaled)
            self.frame_label.setText("")

        self.timestamp_label.setText(f"t = {timestamp:.3f}s")

    def clear(self):
        """Clear preview."""
        self.frame_label.setText("Click spectrogram to load frame")
        self.timestamp_label.setText("t = 0.000s")


def extract_frame(video_path: str, timestamp: float, width=320, height=180) -> QPixmap:
    """Extract single frame from video at timestamp."""
    try:
        cmd = [
            'ffmpeg', '-y', '-ss', f'{timestamp:.3f}',
            '-i', video_path,
            '-vframes', '1',
            '-vf', f'scale={width}:{height},setsar=1',
            '-f', 'image2pipe', '-vcodec', 'ppm', '-'
        ]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0 or len(result.stdout) == 0:
            print(f"[frame] Failed at {timestamp}: {result.stderr[:100]}")
            return QPixmap()

        # Qt handles PPM native
        pixmap = QPixmap()
        pixmap.loadFromData(result.stdout, 'PPM')

        if pixmap.isNull():
            print(f"[frame] QPixmap creation failed at {timestamp}")
            return QPixmap()

        return pixmap

    except Exception as e:
        print(f"[frame] Error at {timestamp}: {e}")
        return QPixmap()

class AnchorInputWidget(QWidget):
    """Combined widget: spectrogram + frame preview + anchor controls."""
    
    anchors_confirmed = Signal(list)
    back_requested = Signal() 

    def __init__(self, video_path: str = ""):
        super().__init__()
        self.video_path = video_path
        self._setup_ui()
        
        if self.video_path and os.path.exists(self.video_path):
            self.set_video_path(self.video_path)

    def set_video_path(self, video_path: str):
        self.video_path = video_path
        self.spectrogram_viewer.set_video(video_path)
        self.frame_preview.video_path = video_path

    def reset_for_new_video(self):
        """Reset widget for starting a fresh video workflow."""
        self.spectrogram_viewer.clear_anchors()
        self.anchor_list.clear()
        self.confirm_btn.setEnabled(False)
        self.frame_preview.clear()
        self.status.setText("Click spectrogram to add anchors")

    def _setup_ui(self):
        """Layout: Title → Spectrogram (full width) → Preview (60%) + Anchors (40%) → Confirm"""
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        self.setLayout(layout)

        # ========== TITLE (Compact) ==========
        title = QLabel("Manual anchoring of relevant loading")
        title.setProperty("heading", "true")
        layout.addWidget(title)

        # ========== CREATE WIDGETS FIRST ==========
        self.spectrogram_viewer = SpectrogramViewer("")
        self.spectrogram_viewer.anchor_added.connect(self.on_anchor_added)
        self.spectrogram_viewer.anchor_clicked.connect(self.update_frame_preview)
        self.spectrogram_viewer.setMinimumHeight(300)
        
        self.frame_preview = FramePreviewWidget(self.video_path if os.path.exists(self.video_path) else "")

        # ========== SPECTROGRAM (FULL WIDTH) ==========
        layout.addWidget(self.spectrogram_viewer, stretch=1)

        # ========== BOTTOM ROW: Preview + Anchors ==========
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(15)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        
        # --- LEFT: Frame Preview ---
        preview_container = QVBoxLayout()
        preview_container.setSpacing(8)
        preview_container.setContentsMargins(0, 0, 0, 0)
        preview_container.addWidget(self.frame_preview, stretch=1)
        
        # --- RIGHT: Anchor List Panel ---
        anchor_panel = QVBoxLayout()
        anchor_panel.setSpacing(8)
        anchor_panel.setContentsMargins(0, 0, 0, 0)
        
        # Anchor list widget
        self.anchor_list = QListWidget()
        self.anchor_list.itemClicked.connect(self.on_anchor_selected)
        self.anchor_list.setMinimumHeight(150)
        self.anchor_list.setStyleSheet(
            "QListWidget { background-color: #1A0B28; border: 2px solid #9432a1; border-radius: 0px; color: #D5F4F5; }"
            "QListWidget::item { padding: 6px; border-radius: 0px; color: #D5F4F5; }"
            "QListWidget::item:selected { background-color: rgba(242, 0, 157, 0.25); border: 0px solid #F2009D; color: #fff; font-weight: 600; }"
            "QListWidget::item:hover:!selected { background-color: rgba(242, 0, 157, 0.15); }"
        )
        anchor_panel.addWidget(self.anchor_list, stretch=1)
        
        # Button row (full width below list, aligned with preview buttons)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        
        rem_btn = QPushButton("Remove Selected")
        rem_btn.setProperty("secondary", "true")
        rem_btn.clicked.connect(self._remove_selected)
        rem_btn.setMinimumHeight(36)
        btn_layout.addWidget(rem_btn, stretch=1)
        
        clr_btn = QPushButton("Clear All")
        clr_btn.setProperty("secondary", "true")
        clr_btn.clicked.connect(self._clear_all)
        clr_btn.setMinimumHeight(36)
        btn_layout.addWidget(clr_btn, stretch=1)
        
        anchor_panel.addLayout(btn_layout)
        
        # Add both columns to bottom row with stretch factors for 60/40 split
        bottom_row.addLayout(preview_container, stretch=3)
        bottom_row.addLayout(anchor_panel, stretch=2)
        
        layout.addLayout(bottom_row, stretch=1)

        # ========== STATUS BAR ==========
        self.status = QLabel("Click spectrogram to add anchors")
        self.status.setStyleSheet(
            "color: #7e8791; font-size: 11px; padding: 8px 8px; "
            "border-top: 1px solid #444; border-bottom: 1px solid #444; "
            "background-color: #0B0B28;"
        )
        layout.addWidget(self.status)

        # ========== BUTTON ROW ==========
        btn_row = QHBoxLayout()
        
        # BACK BUTTON  (loader)
        self.back_btn = QPushButton("Back")
        self.back_btn.setProperty("secondary", "true")
        self.back_btn.clicked.connect(self.back_requested.emit)
        self.back_btn.setMinimumHeight(40)
        btn_row.addWidget(self.back_btn)
        
        btn_row.addStretch()
        
        # CONFIRM BUTTON (detection)
        self.confirm_btn = QPushButton("Confirm Anchors")
        self.confirm_btn.setProperty("primary", "true")
        self.confirm_btn.clicked.connect(self._confirm)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setMinimumHeight(44)
        btn_row.addWidget(self.confirm_btn, stretch=1)
        
        layout.addLayout(btn_row)

    def update_frame_preview(self, timestamp: float):
        """Update frame preview at clicked timestamp."""
        if timestamp < 0:
            self.frame_preview.clear()
            return
        frame = extract_frame(self.video_path, timestamp, width=320, height=180)
        self.frame_preview.set_frame(frame, timestamp)

    def on_anchor_selected(self, item):
        """Load frame when anchor selected from list."""
        ts = item.data(Qt.ItemDataRole.UserRole)
        frame = extract_frame(self.video_path, ts, width=320, height=180)
        self.frame_preview.set_frame(frame, ts)

    def on_anchor_added(self, ts: float):
        self._update_list()
        self.confirm_btn.setEnabled(len(self.spectrogram_viewer.get_anchors()) > 0)
        self.status.setText(f"Added anchor at {ts:.2f}s")

    def _update_list(self):
        self.anchor_list.clear()
        anchors = self.spectrogram_viewer.get_anchors()[::-1]
        N = len(anchors)
        for i, ts in enumerate(anchors):
            item = QListWidgetItem(f"#{N-i}  {format_timestamp_short(ts)}  ({ts:.2f}s)")
            item.setData(Qt.ItemDataRole.UserRole, ts)
            self.anchor_list.addItem(item)

    def _remove_selected(self):
        item = self.anchor_list.currentItem()
        if item:
            ts = item.data(Qt.ItemDataRole.UserRole)
            self.anchor_list.takeItem(self.anchor_list.currentRow())
            self.spectrogram_viewer.remove_anchor(ts)
            self.confirm_btn.setEnabled(len(self.spectrogram_viewer.get_anchors()) > 0)
            if not self.spectrogram_viewer.get_anchors():
                self.frame_preview.clear()
            self.status.setText(f"Removed anchor at {ts:.2f}s")

    def _clear_all(self):
        if self.spectrogram_viewer.get_anchors():
            self.spectrogram_viewer.clear_anchors()
            self.anchor_list.clear()
            self.confirm_btn.setEnabled(False)
            self.frame_preview.clear()
            self.status.setText("Cleared all anchors")

    def _confirm(self):
        anchors = self.spectrogram_viewer.get_anchors()
        if not anchors:
            QMessageBox.warning(self, "No Anchors", "Add at least one anchor point")
            return
        self.anchors_confirmed.emit(anchors)

    def get_anchors(self) -> list:
        return self.spectrogram_viewer.get_anchors()

def format_timestamp_short(sec: float) -> str:
    """Short time format for list display."""
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"
