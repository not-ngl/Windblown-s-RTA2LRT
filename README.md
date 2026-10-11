# Windblown-s-RTA2LRT

A tool designed to help speedrun.com moderators identify and remove loading times from *Windblown* run submissions. Combines automated detection with manual verification workflows for timing extraction. Can also be used by users.

> **Note:** Windblown-s-RTA2LRT is an assist tool and cannot replace human verification.

## Features

- **GUI support** — Simple GUI to run including the entire workflow
- **Dynamic Spectrogram** — Real-time rendering with zoom/pan support for smooth navigation
- **Automatic Boundary Expansion** — Expands anchor points into start/end timestamps using color analysis
- **Frame-Accurate Verification** — Keyboard navigation for sub-second precision (30fps video support)
- **Multi-Segment Support** — Process multiple loading times in a single submission
- **Cross-Platform** — Tested on Linux; Windows supported (macOS compatibility pending user reports)
- **Standardized Export** — Generates output files that could be used for quick moderation verification
- **YouTube Integration** — Download videos directly from URLs via yt-dlp

## System Requirements

### Mandatory System Tools

| Tool | Purpose | Installation Method |
|------|---------|---------------------|
| **Python** | 3.10+ (type hints and async) | python.org / pyenv / distro package |
| **FFmpeg** | Video/audio processing | See platform sections below |
| **Deno** | JS runtime for yt-dlp ejs support | See platform sections below |

### Python Packages

Install via `pip install -r requirements.txt`:

- `PySide6` — GUI framework
- `Pillow` — Image processing and text overlays
- `opencv-python` — Spectrogram rendering
- `scipy` — Audio signal processing
- `numpy` — Numerical computations
- `yt-dlp` — YouTube video downloader using URL and your cookies
- `pyqtgraph` — Dynamic display of the spectrogram

---

## Installation

### Linux

```bash
# Get the repo
git clone https://github.com/not-ngl/Windblown-s-RTA2LRT.git
cd Windblown-s-RTA2LRT

# Setup a virtual environment
python3 -m venv [A new virtual environment]
source [A new virtual environment]/bin/activate
pip3 install -r requirements

# Ensure you have ffmpeg, deno installed
ffmpeg -version 
deno --version 

# Run the GUI
python3 run_gui.py
```

### Windows

#### Step 1: Install Python
Download from `python.org` using the PyInstaller. Ensure to check the box Add Python to PART during the installation process.

#### Step 2: Install ffmpeg
Download from `ffmpeg.org` the latest stable release of ffmpeg. 
Or directly on https://www.gyan.dev/ffmpeg/builds/ (`ffmpeg-git-full.7z`).
Extract to `C:\ffmpeg`. Add `C:\ffmpeg\bin` to your PATH environment variable.

#### Step 3: Install Deno
Visit https://deno.land/manual/getting_started/installation.
In a PowerShell
```
irm https://deno.land/install.ps1 | iex
```

#### Step 4: Install this project!
```bash
git clone https://github.com/not-ngl/Windblown-s-RTA2LRT.git 
cd Windblown-s-RTA2LRT
pip install -r requirements.txt
```

It is morelikely that you will need to include `C:\Users\[username]\AppData\Local\Python\pythoncore-X.Y-N\Scripts` to your PATH.

And finally, run the GUI:
```bash
python3 run_gui.py
```

#### Troubleshooting
Ensure `ffmpeg`, `deno`  executables are in your system PATH. Verify with commands:
```
ffmpeg -version 
deno --version 
```

Ensure to be connected to a YouTube account.

## Usage

1. **Launch the GUI**: `python run_gui.py`
2. **Provide a video** via local file or URL (ensure to select the browser you are using)
3. **Navigate the Spectrogram**: zoom with mouse wheel, drag to pan. Find loading regions (they appear quiet/black)
4. **Let the tool auto-detect** the approximate boundaries
5. **Locate precise frames** using h/j/k/l keys to find the first visible purple loading frame
6. **Export** — output files help moderators verify the results

> **Note:** Windblown-s-RTA2LRT is an assist tool and cannot replace human verification.

## License

This project is licensed under the **MIT License**, see the LICENSE file for full details.

### Important Notes

- **"Windblown"** is the property of Motion Twin and is not affiliated with this project.
- **Windblown-s-RTA2LRT** is a community tool. It is not affiliated with or endorsed by the game studio.
- **yt-dlp** should be used solely for downloading submitted runs for moderation purposes.
- This tool is provided **as-is, without warranty**. It is an assist tool and cannot replace human verification during moderation.
