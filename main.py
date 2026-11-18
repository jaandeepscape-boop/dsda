"""HypeClipper - find and cut the hypest moments from a video.

Dependencies: Python standard library + customtkinter.
External tools (must be on PATH): ffmpeg, ffprobe, yt-dlp.

API notes (FreeLLMAPI):
  - Whisper endpoint only supports response_format="verbose_json" (not srt/vtt).
    We request JSON then convert locally to SRT before burning with ffmpeg.
  - TTS endpoint only supports model="auto" (not "tts-1").
"""
import glob
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from tkinter import filedialog, messagebox

import customtkinter as ctk

# --windowed PyInstaller builds have no stdin; without this every child process
# (ffmpeg / yt-dlp) can fail with "[WinError 6] The handle is invalid".
_RealPopen = subprocess.Popen


class _SafePopen(_RealPopen):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        if os.name == "nt":
            kwargs.setdefault("creationflags", 0x08000000)
        super().__init__(*args, **kwargs)


subprocess.Popen = _SafePopen

APP_NAME = "HypeClipper"
DEFAULT_API = "http://127.0.0.1:31415/v1"
WHISPER_MODEL = "whisper-large-v3-turbo"
# caption language menu -> (whisper language code, optional style prompt)
CAPTION_LANGS = {
    "Auto-detect": (None, None),
    "English": ("en", None),
    "Hindi": ("hi", None),
    "Punjabi": ("pa", None),
    "Hinglish (Hindi in English letters)": (
        "hi", "Yeh video Hinglish mein hai. Hindi words ko Roman letters mein likho, "
              "jaise: kya haal hai bhai."),
}
CAPTION_STYLES = {
    "Pop": {
        "title": "Pop",
        "sample": "THIS CHANGED\nEVERYTHING",
        "sample_color": "#FFDE00",
        "sample_bg": "#1e293b",
        "primary": "&H0000FFFF",  # Bright Yellow (BGR)
        "outline": "&H00000000",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 4,
        "shadow": 2,
        "font": "Impact",
        "all_caps": True,
    },
    "Spotlight": {
        "title": "Spotlight",
        "sample": "THE REAL\nSECRET",
        "sample_color": "#FFFFFF",
        "sample_bg": "#6b21a8",
        "primary": "&H00FFFFFF",
        "outline": "&H00800080",
        "back": "&HA0800080",  # Purple box
        "border_style": 3,
        "outline_w": 0,
        "shadow": 0,
        "font": "Arial Black",
        "all_caps": True,
    },
    "Impact": {
        "title": "Impact",
        "sample": "TEN MILLION",
        "sample_color": "#FBBF24",
        "sample_bg": "#18181b",
        "primary": "&H0024BFFB",  # Gold Yellow
        "outline": "&H00000000",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 4,
        "shadow": 2,
        "font": "Impact",
        "all_caps": True,
    },
    "Glow": {
        "title": "Glow",
        "sample": "LEVEL UP NOW",
        "sample_color": "#34D399",
        "sample_bg": "#064e3b",
        "primary": "&H0099D334",  # Neon Green
        "outline": "&H00003300",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 4,
        "shadow": 3,
        "font": "Impact",
        "all_caps": True,
    },
    "Boxed": {
        "title": "Boxed",
        "sample": "SHIP IT\nFASTER TODAY",
        "sample_color": "#FFFFFF",
        "sample_bg": "#09090b",
        "primary": "&H00FFFFFF",
        "outline": "&H00000000",
        "back": "&HA0000000",
        "border_style": 3,
        "outline_w": 0,
        "shadow": 0,
        "font": "Arial Black",
        "all_caps": True,
    },
    "Sweep": {
        "title": "Sweep",
        "sample": "SING ALONG\nNOW",
        "sample_color": "#F43F5E",
        "sample_bg": "#881337",
        "primary": "&H005E3FF4",  # Hot pink
        "outline": "&H00000000",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 4,
        "shadow": 2,
        "font": "Impact",
        "all_caps": True,
    },
    "Editorial": {
        "title": "Editorial",
        "sample": "and that is\nwhy it works",
        "sample_color": "#F1F5F9",
        "sample_bg": "#1c1917",
        "primary": "&H00F9F5F1",
        "outline": "&H00222222",
        "back": "&H00000000",
        "border_style": 1,
        "outline_w": 2,
        "shadow": 1,
        "font": "Georgia",
        "all_caps": False,
    },
    "Hype": {
        "title": "Hype",
        "sample": "LET'S GO NOW",
        "sample_color": "#A3E635",
        "sample_bg": "#14532d",
        "primary": "&H0035E6A3",  # Lime / Spring
        "outline": "&H00000000",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 4,
        "shadow": 2,
        "font": "Impact",
        "all_caps": True,
    },
    "Punch": {
        "title": "Punch",
        "sample": "BOOM",
        "sample_color": "#FFFFFF",
        "sample_bg": "#0f172a",
        "primary": "&H00FFFFFF",
        "outline": "&H00000000",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 5,
        "shadow": 3,
        "font": "Arial Black",
        "all_caps": True,
    },
    "Neon": {
        "title": "Neon",
        "sample": "FEEL THE BEAT",
        "sample_color": "#38BDF8",
        "sample_bg": "#0c4a6e",
        "primary": "&H00F8BD38",  # Electric Cyan
        "outline": "&H00800080",
        "back": "&H80000000",
        "border_style": 1,
        "outline_w": 4,
        "shadow": 2,
        "font": "Impact",
        "all_caps": True,
    },
    "Headline": {
        "title": "Headline",
        "sample": "THIS JUST IN",
        "sample_color": "#EF4444",
        "sample_bg": "#450a0a",
        "primary": "&H004444EF",  # Bright Red
        "outline": "&H00FFFFFF",
        "back": "&HA0000088",
        "border_style": 1,
        "outline_w": 3,
        "shadow": 2,
        "font": "Impact",
        "all_caps": True,
    },
    "Subtle": {
        "title": "Subtle",
        "sample": "i think that's fair",
        "sample_color": "#94A3B8",
        "sample_bg": "#1e2430",
        "primary": "&H00B8A394",
        "outline": "&H00181818",
        "back": "&H00000000",
        "border_style": 1,
        "outline_w": 2,
        "shadow": 1,
        "font": "Arial",
        "all_caps": False,
    },
}
# Backward compatibility aliases
CAPTION_STYLES["Viral Yellow (MrBeast)"] = CAPTION_STYLES["Pop"]
CAPTION_STYLES["Hormozi Lime"] = CAPTION_STYLES["Glow"]
CAPTION_STYLES["TikTok White"] = CAPTION_STYLES["Punch"]
CAPTION_STYLES["Cyber Cyan"] = CAPTION_STYLES["Neon"]
CAPTION_STYLES["Fire Orange"] = CAPTION_STYLES["Headline"]
CAPTION_STYLES["Black Box Pill"] = CAPTION_STYLES["Boxed"]
CAPTION_STYLES["Minimal Clean"] = CAPTION_STYLES["Subtle"]
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE = base_dir()
# tools may sit next to HypeClipper.exe or in the auto-install folder
TOOLS_DIRS = [os.path.join(BASE, "tools"),
              os.path.join(os.environ.get("LOCALAPPDATA") or BASE, "HypeClipper", "tools")]
os.environ["PATH"] = os.pathsep.join([BASE] + TOOLS_DIRS) + os.pathsep + os.environ.get("PATH", "")
TEMP_DIR = os.path.join(BASE, "temp")
OUT_DIR = os.path.join(BASE, "output_clips")
VIDEOS_DIR = os.path.join(BASE, "videos")
LOG_FILE = os.path.join(BASE, "hypeclipper.log")
SETTINGS_FILE = os.path.join(BASE, "hypeclipper_settings.json")


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    data = load_settings()
    data.update(kw)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# API key: environment variable first, then the settings file next to the .exe
API_KEY = (os.environ.get("FREELLMAPI_KEY") or load_settings().get("api_key") or "").strip()


def set_api_key(key):
    global API_KEY
    API_KEY = (key or "").strip()


def auth_headers(extra=None):
    h = dict(extra or {})
    if API_KEY:
        h["Authorization"] = "Bearer " + API_KEY
    return h


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def sanitize(title, maxlen=60):
    s = re.sub(r"[^\w\- ]+", "", str(title), flags=re.UNICODE).strip()
    s = re.sub(r"\s+", "_", s)
    return (s[:maxlen] or "clip")


def fmt_time(t):
    t = int(max(0, t))
    return "%d:%02d" % (t // 60, t % 60)


def format_srt_time(seconds):
    """Convert float seconds to SRT timestamp HH:MM:SS,mmm."""
    s = max(0.0, float(seconds))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    ms = int(round((s - int(s)) * 1000))
    if ms >= 1000:
        ms = 999
    return "%02d:%02d:%02d,%03d" % (h, m, sec, ms)


def json_to_srt(data, words_per_chunk=3, uppercase=True, min_duration=0.35, max_duration=2.5):
    """Convert Whisper verbose_json response to SRT text.

    Groups words into chunks of `words_per_chunk` for readable subtitle lines.
    Handles both word-level timestamps and segment-level timestamps.
    """
    srt_blocks = []
    idx = 1

    def clean_text(t):
        t = (t or "").strip()
        if uppercase:
            t = t.upper()
        # Clean trailing periods from punchy shorts lines so it reads crisper
        if words_per_chunk <= 4 and t.endswith(".") and not t.endswith("..."):
            t = t[:-1].strip()
        return t

    # Try word-level timestamps first (more precise)
    words = data.get("words") or []
    if not words:
        # Some models put words inside segments
        for seg in (data.get("segments") or []):
            words.extend(seg.get("words") or [])

    if words:
        # Group words into chunks
        for i in range(0, len(words), words_per_chunk):
            chunk = words[i:i + words_per_chunk]
            if not chunk:
                continue
            start = chunk[0].get("start")
            if start is None:
                start = 0
            end = chunk[-1].get("end")
            if end is None:
                end = start + min_duration
            # Enforce minimum / maximum duration
            if end - start < min_duration:
                end = start + min_duration
            if end - start > max_duration:
                end = start + max_duration
            raw = " ".join((w.get("word") or "").strip() for w in chunk).strip()
            text = clean_text(raw)
            if not text:
                continue
            srt_blocks.append(
                "%d\n%s --> %s\n%s\n"
                % (idx, format_srt_time(start), format_srt_time(end), text))
            idx += 1
    else:
        # Fall back to segment-level timestamps
        for seg in (data.get("segments") or []):
            start = seg.get("start")
            if start is None:
                start = 0
            end = seg.get("end")
            if end is None:
                end = start + 2
            raw = (seg.get("text") or "").strip()
            if not raw:
                continue
            # Split long segments into smaller subtitle blocks
            seg_words = raw.split()
            if len(seg_words) <= words_per_chunk:
                text = clean_text(raw)
                srt_blocks.append(
                    "%d\n%s --> %s\n%s\n"
                    % (idx, format_srt_time(start), format_srt_time(end), text))
                idx += 1
            else:
                seg_dur = end - start
                total_words = len(seg_words)
                for j in range(0, total_words, words_per_chunk):
                    sub_words = seg_words[j:j + words_per_chunk]
                    frac_start = start + seg_dur * (j / total_words)
                    frac_end = start + seg_dur * (min(j + words_per_chunk, total_words)
                                                   / total_words)
                    text = clean_text(" ".join(sub_words))
                    srt_blocks.append(
                        "%d\n%s --> %s\n%s\n"
                        % (idx, format_srt_time(frac_start),
                           format_srt_time(frac_end),
                           text))
                    idx += 1

    if not srt_blocks:
        # Last resort: just use the top-level text
        text = clean_text(data.get("text", ""))
        if text:
            srt_blocks.append("1\n00:00:00,000 --> 00:00:05,000\n%s\n" % text)

    return "\n".join(srt_blocks)


def run_stream(cmd, log, cwd=None, collect=None):
    """Run a command, streaming merged stdout/stderr lines to log. Returns exit code."""
    log("$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        log("ERROR: '%s' not found. Install it and make sure it is on PATH." % cmd[0])
        return -1
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(line)
            if collect is not None:
                collect.append(line)
    proc.wait()
    return proc.returncode


def run_capture(cmd):
    try:
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
        )
    except (FileNotFoundError, OSError) as e:
        return subprocess.CompletedProcess(cmd, 127, "", "could not run %s: %s" % (cmd[0], e))


# --------------------------------------------------------------------------
# Input: download or local file
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Auto-install of ffmpeg / ffprobe / yt-dlp / deno (Windows)
# --------------------------------------------------------------------------
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
    "ffmpeg-master-latest-win64-gpl.zip",
]
DENO_URL = ("https://github.com/denoland/deno/releases/latest/download/"
            "deno-x86_64-pc-windows-msvc.zip")
CORE_TOOLS = ("ffmpeg", "ffprobe", "yt-dlp")


def missing_tools():
    return [t for t in CORE_TOOLS if not shutil.which(t)]


def writable_tools_dir():
    for d in TOOLS_DIRS:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".write_test")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return d
        except OSError:
            continue
    raise OSError("no writable folder for tools")


def download_file(url, dest, log, status=None, label="file"):
    req = urllib.request.Request(url, headers={"User-Agent": "HypeClipper/1.0"})
    part = dest + ".part"
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last_pct = 0, -10
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = int(done * 100 / total)
                if status:
                    status("Downloading %s... %d%%" % (label, pct), "#4da3ff")
                if pct >= last_pct + 10:
                    last_pct = pct
                    log("  %s: %d%% (%.1f / %.1f MB)" % (label, pct, done / 1e6, total / 1e6))
    os.replace(part, dest)


def extract_from_zip(zip_path, wanted, dest_dir):
    """Extract files whose base name is in `wanted`, flattening folders."""
    got = []
    wanted = set(w.lower() for w in wanted)
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            base = os.path.basename(name)
            if base.lower() in wanted:
                with z.open(name) as src, open(os.path.join(dest_dir, base), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                got.append(base)
    return got


def _install_zip(urls, wanted, dest_dir, log, status, label):
    last_err = None
    for url in urls:
        zpath = os.path.join(dest_dir, label + ".zip")
        try:
            log("Downloading %s from %s" % (label, url))
            download_file(url, zpath, log, status, label)
            got = extract_from_zip(zpath, wanted, dest_dir)
            if len(got) >= len(wanted):
                return True
            last_err = "archive did not contain %s" % ", ".join(wanted)
        except Exception as e:
            last_err = e
            log("  failed: %s" % e)
        finally:
            for junk in (zpath, zpath + ".part"):
                try:
                    if os.path.isfile(junk):
                        os.remove(junk)
                except OSError:
                    pass
    log("ERROR: could not install %s (%s)" % (label, last_err))
    return False


def install_tools(log, status=None):
    """Download whatever is missing. Returns True if all core tools are present afterwards."""
    if os.name != "nt":
        log("Auto-install is for Windows. Install ffmpeg and yt-dlp with your package "
            "manager (e.g. brew install ffmpeg yt-dlp / apt install ffmpeg yt-dlp).")
        return not missing_tools()
    try:
        dest = writable_tools_dir()
    except OSError as e:
        log("ERROR: %s" % e)
        return False
    log("Installing tools into: " + dest)
    need = missing_tools()
    if "yt-dlp" in need:
        try:
            log("Downloading yt-dlp...")
            download_file(YTDLP_URL, os.path.join(dest, "yt-dlp.exe"), log, status, "yt-dlp")
        except Exception as e:
            log("ERROR: could not download yt-dlp (%s)" % e)
    if "ffmpeg" in need or "ffprobe" in need:
        _install_zip(FFMPEG_URLS, ("ffmpeg.exe", "ffprobe.exe"), dest, log, status, "ffmpeg")
    if not shutil.which("deno"):
        # yt-dlp needs a JavaScript runtime for current YouTube; failure here is non-fatal
        _install_zip([DENO_URL], ("deno.exe",), dest, log, status, "deno")
    left = missing_tools()
    if left:
        log("Still missing: %s. Download them manually and put the .exe files next to "
            "HypeClipper.exe." % ", ".join(left))
    else:
        log("All tools installed.")
    return not left


def is_url(s):
    return bool(re.match(r"^https?://", s, re.I))


YTDLP_HINTS = [
    (("sign in to confirm", "not a bot", "cookies"),
     "YouTube wants you signed in. On the Source tab choose your browser under "
     "'Cookies from browser' (be logged into YouTube there), then try again."),
    (("429", "too many requests"),
     "YouTube is rate-limiting you. Wait a few minutes, or use 'Cookies from browser'."),
    (("javascript runtime", "js runtime", "deno", "nsig", "signature"),
     "yt-dlp needs a JavaScript runtime and an up-to-date version. Click 'Update yt-dlp' "
     "and install Deno (winget install DenoLand.Deno), then restart HypeClipper."),
    (("requested format is not available", "unable to extract", "http error 403"),
     "YouTube changed something. Click 'Update yt-dlp' and try again."),
    (("ffmpeg is not installed", "ffmpeg not found", "ffprobe and ffmpeg"),
     "ffmpeg was not found. Install it, or put ffmpeg.exe next to HypeClipper.exe."),
    (("private video", "video unavailable", "members-only", "age"),
     "The video is private, removed, members-only or age-restricted "
     "(age-restricted ones need 'Cookies from browser')."),
]


def explain_ytdlp_failure(lines, log):
    blob = "\n".join(lines).lower()
    shown = False
    for keys, msg in YTDLP_HINTS:
        if any(k in blob for k in keys):
            log("HINT: " + msg)
            shown = True
    if not shown:
        log("HINT: Try 'Update yt-dlp' on the Source tab, or download the video yourself "
            "and use 'Select Local Video'.")


def _find_downloaded(lines, folder=None):
    found = None
    for ln in lines:
        for pat in (r'Merging formats into "(.+?)"',
                    r"\[download\] Destination: (.+\.mp4)\s*$",
                    r"\[download\] (.+\.mp4) has already been downloaded"):
            m = re.search(pat, ln)
            if m and os.path.isfile(m.group(1)):
                found = m.group(1)
    if found:
        return found
    mp4s = glob.glob(os.path.join(folder or TEMP_DIR, "*.mp4"))
    return max(mp4s, key=os.path.getmtime) if mp4s else None


def download_video(url, log, cookies_browser=None, dl_dir=None, quality=None):
    dl_dir = dl_dir or VIDEOS_DIR
    os.makedirs(dl_dir, exist_ok=True)
    log("Saving download to: " + dl_dir)
    if not shutil.which("yt-dlp"):
        log("ERROR: yt-dlp not found. Install it (pip install yt-dlp or the .exe) and make "
            "sure it is on PATH, or put yt-dlp.exe next to HypeClipper.exe.")
        return None

    quality_map = {
        "Maximum (4K/1440p/Best)": "bestvideo+bestaudio/best",
        "1080p Full HD (Crisp)": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "720p HD": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "Auto / Fast": "bv*+ba/b",
    }
    chosen_fmt = quality_map.get(quality, "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best")
    log("Download quality target: %s (%s)" % (quality or "1080p Full HD (Crisp)", chosen_fmt))

    ffmpeg_bin = shutil.which("ffmpeg")
    ffmpeg_dir = os.path.dirname(os.path.abspath(ffmpeg_bin)) if ffmpeg_bin else None

    def build(with_subs, fmt):
        cmd = ["yt-dlp", "--no-playlist", "--newline", "-f", fmt,
               "--format-sort", "res,fps",
               "--merge-output-format", "mp4", "--write-info-json",
               "-o", os.path.join(dl_dir, "%(title).80B [%(id)s].%(ext)s")]
        if ffmpeg_dir:
            cmd += ["--ffmpeg-location", ffmpeg_dir]
        if with_subs:
            cmd += ["--write-auto-subs", "--sub-langs", "en,hi,pa"]
        if cookies_browser and cookies_browser.lower() != "none":
            cmd += ["--cookies-from-browser", cookies_browser.lower()]
        return cmd + [url]

    attempts = [(True, chosen_fmt), (False, chosen_fmt), (False, "bv*+ba/b")]
    all_lines = []
    for n, (subs, fmt) in enumerate(attempts, 1):
        lines = []
        code = run_stream(build(subs, fmt), log, collect=lines)
        all_lines += lines
        video = _find_downloaded(lines, dl_dir)
        if video and os.path.isfile(video):
            if code != 0:
                log("Note: yt-dlp reported a problem (often subtitles being rate-limited) "
                    "but the video downloaded fine - continuing.")
            return video
        if n < len(attempts):
            log("Download failed (code %s). Retrying with simpler settings..." % code)
    log("ERROR: could not download the video.")
    explain_ytdlp_failure(all_lines, log)
    return None


def get_duration(path, info):
    if shutil.which("ffprobe"):
        r = run_capture(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", path])
        try:
            return float(r.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            pass
    if info and info.get("duration"):
        return float(info["duration"])
    return 0.0


# --------------------------------------------------------------------------
# Hype detection
# --------------------------------------------------------------------------
def audio_peaks(path, duration, log, top_n=15, min_gap=10.0):
    """Loudest moments via ffmpeg astats RMS (1.5 s windows)."""
    log("Scanning audio loudness with ffmpeg (this can take a while)...")
    af = ("aresample=16000,asetnsamples=n=8000:p=0,"
          "astats=metadata=1:reset=3,"
          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-v", "error", "-i", path,
           "-vn", "-af", af, "-f", "null", "-"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace",
                                creationflags=CREATE_NO_WINDOW)
    except FileNotFoundError:
        log("ERROR: ffmpeg not found on PATH.")
        return []
    samples = []
    cur_t = None
    for line in proc.stdout:
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            cur_t = float(m.group(1))
            continue
        m = re.search(r"RMS_level=(-?[\d.]+|-inf|inf)", line)
        if m and cur_t is not None:
            v = m.group(1)
            if "inf" not in v:
                samples.append((cur_t, float(v)))
    proc.wait()
    if not samples:
        log("No audio samples parsed (video may have no audio).")
        return []
    samples.sort(key=lambda x: x[1], reverse=True)
    peaks = []
    for t, v in samples:
        if all(abs(t - pt) >= min_gap for pt, _ in peaks):
            peaks.append((t, v))
        if len(peaks) >= top_n:
            break
    peaks.sort()
    log("Found %d audio peaks." % len(peaks))
    return [{"time": round(t, 1), "rms_db": round(v, 1)} for t, v in peaks]


def heatmap_peaks(info, top_n=10):
    hm = (info or {}).get("heatmap")
    if not hm:
        return []
    best = sorted(hm, key=lambda h: h.get("value", 0), reverse=True)[:top_n]
    best.sort(key=lambda h: h.get("start_time", 0))
    return [{"start": round(h["start_time"], 1), "end": round(h["end_time"], 1),
             "intensity": round(h.get("value", 0), 3)} for h in best]


def replayed_clips(info, duration, clip_len, max_clips):
    """Pick the windows with the highest total replay/watch-time from YouTube's heatmap."""
    hm = (info or {}).get("heatmap")
    if not hm:
        return []
    segs = [(float(h["start_time"]), float(h["end_time"]), float(h.get("value", 0)))
            for h in hm if "start_time" in h and "end_time" in h]
    if not segs:
        return []
    if not duration:
        duration = segs[-1][1]
    clip_len = min(clip_len, duration)

    def score(start):
        end = start + clip_len
        total = 0.0
        for a, b, v in segs:
            ov = min(b, end) - max(a, start)
            if ov > 0:
                total += v * ov
        return total / clip_len

    cands = []
    for a, b, v in segs:
        centre = (a + b) / 2.0
        start = min(max(0.0, centre - clip_len / 2.0), max(0.0, duration - clip_len))
        cands.append((score(start), start))
    cands.sort(reverse=True)
    chosen = []
    for sc, st in cands:
        if all(st + clip_len <= c["start_time"] or st >= c["end_time"] for c in chosen):
            chosen.append({"start_time": st, "end_time": st + clip_len,
                           "title": "Top_Replay_%d" % (len(chosen) + 1),
                           "score": round(sc, 3)})
        if len(chosen) >= max_clips:
            break
    chosen.sort(key=lambda c: c["start_time"])
    return chosen


def load_transcript(video_path, limit=6000):
    stem = os.path.splitext(video_path)[0]
    subs = []
    for lang in ("en", "hi", "pa"):
        subs += glob.glob(glob.escape(stem) + "." + lang + "*.vtt")
    if not subs:
        return ""
    lines, last = [], ""
    ts = 0.0
    for raw in open(subs[0], encoding="utf-8", errors="replace"):
        raw = raw.strip()
        m = re.match(r"(\d+):(\d+):([\d.]+)\s+-->", raw)
        if m:
            ts = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            continue
        if not raw or raw.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")) or "-->" in raw:
            continue
        text = re.sub(r"<[^>]+>", "", raw).strip()
        if text and text != last:
            lines.append("[%s] %s" % (fmt_time(ts), text))
            last = text
    out = "\n".join(lines)
    if len(out) > limit:
        step = len(out) / float(limit)
        out = "\n".join(lines[:: max(1, int(step) + 1)])[:limit]
    return out


# --------------------------------------------------------------------------
# Local LLM
# --------------------------------------------------------------------------
def api_base(url):
    url = url.strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def pick_model(base, log):
    req = urllib.request.Request(base + "/v1/models", headers=auth_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    ids = [i for i in ids if "embed" not in i.lower()] or ids
    if not ids:
        raise RuntimeError("No models available at " + base)
    log("Using model: " + ids[0])
    return ids[0]


def parse_clip_json(text):
    """Parse the model's clip list; salvage complete objects if the reply was cut off."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"<think>.*", "", text, flags=re.S) if "</think>" not in text else text
    text = text.replace("```json", "").replace("```", "")
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except ValueError:
            pass
    items = []
    for obj in re.findall(r"\{[^{}]*\}", text):
        try:
            d = json.loads(obj)
        except ValueError:
            continue
        if isinstance(d, dict) and "start_time" in d and "end_time" in d:
            items.append(d)
    if not items:
        raise ValueError("Model did not return usable clips: " + text[:200])
    return items


def ask_llm(base, model, duration, clip_len, max_clips, a_peaks, h_peaks, transcript, log):
    system = ("You are a viral video editor. Reply with ONLY a JSON array, no prose, "
              "no markdown. Each item: {\"start_time\": number, \"end_time\": number, "
              "\"title\": string}. Times are seconds.")
    user = (
        "Video duration: %.0f seconds.\n"
        "Pick up to %d of the best NON-OVERLAPPING clips, each about %d seconds long "
        "(never longer than %d), starting slightly before a peak so the build-up is included.\n"
        "Loudest audio moments (crowd cheers/laughter/drops): %s\n"
        "YouTube replay heatmap peaks: %s\n"
        "Transcript:\n%s\n\n"
        "Return the JSON array now. Titles must be short and catchy using underscores, "
        "e.g. \"Crowd_Goes_Wild\"."
        % (duration, max_clips, clip_len, clip_len + 10,
           json.dumps(a_peaks), json.dumps(h_peaks), transcript or "(none)")
    )
    body = json.dumps({
        "model": model, "temperature": 0.3, "max_tokens": 4096,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers=auth_headers({"Content-Type": "application/json"}))
    log("Asking the model for the best clips...")
    with urllib.request.urlopen(req, timeout=300) as r:
        resp = json.loads(r.read().decode("utf-8"))
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    if choice.get("finish_reason") == "length":
        log("Note: the model's reply was cut off (token limit); using the clips it finished.")
    return parse_clip_json(text)


def clean_clips(raw, duration, clip_len, max_clips):
    clips = []
    for c in raw:
        try:
            s = float(c["start_time"])
            e = float(c["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        s = max(0.0, s)
        if duration:
            e = min(e, duration)
        if e - s > clip_len + 10:
            e = s + clip_len
        if e - s < 3:
            continue
        clips.append({"start_time": s, "end_time": e,
                      "title": sanitize(c.get("title", "clip"))})
    clips.sort(key=lambda c: c["start_time"])
    final = []
    for c in clips:
        if not final or c["start_time"] >= final[-1]["end_time"]:
            final.append(c)
    return final[:max_clips]


def fallback_clips(a_peaks, h_peaks, duration, clip_len, max_clips):
    """Rank moments by loudness AND YouTube replay intensity together."""
    cands = []
    if a_peaks:
        lo = min(p["rms_db"] for p in a_peaks)
        hi = max(p["rms_db"] for p in a_peaks)
        span = (hi - lo) or 1.0
        for p in a_peaks:
            sc = (p["rms_db"] - lo) / span
            boost = max([h["intensity"] for h in h_peaks
                         if h["start"] <= p["time"] <= h["end"]] or [0.0])
            cands.append((sc + boost, p["time"]))
    for h in h_peaks:
        has_audio = any(h["start"] <= p["time"] <= h["end"] for p in a_peaks)
        cands.append((h["intensity"] + (0.5 if has_audio else 0.0),
                      (h["start"] + h["end"]) / 2))
    cands.sort(reverse=True)
    raw = []
    for n, (_, t) in enumerate(cands, 1):
        st = max(0.0, t - clip_len * 0.6)
        raw.append({"start_time": st, "end_time": st + clip_len,
                    "title": "Hype_Moment_%d" % n})
    chosen = []
    for c in raw:
        if all(c["end_time"] <= x["start_time"] or c["start_time"] >= x["end_time"]
               for x in chosen):
            chosen.append(c)
        if len(chosen) >= max_clips:
            break
    return clean_clips(chosen, duration, clip_len, max_clips)


def detect_silences(video, log):
    """Midpoints of natural pauses, used as clean cut points."""
    log("Finding natural pauses so clips don't cut mid-word...")
    r = run_capture(["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-vn",
                     "-af", "silencedetect=noise=-32dB:d=0.3", "-f", "null", "-"])
    starts = re.findall(r"silence_start: (-?[\d.]+)", r.stderr)
    ends = re.findall(r"silence_end: ([\d.]+)", r.stderr)
    mids = [(max(0.0, float(a)) + float(b)) / 2 for a, b in zip(starts, ends)]
    log("Found %d pauses." % len(mids))
    return mids


def snap_clips(clips, mids, duration, clip_len):
    """Nudge each clip's start/end onto the nearest natural pause."""
    if not mids:
        return clips
    out, prev_end = [], 0.0
    for c in sorted(clips, key=lambda c: c["start_time"]):
        s0, e0 = c["start_time"], c["end_time"]
        ns = min((m for m in mids if s0 - 3 <= m <= s0 + 2),
                 key=lambda m: abs(m - s0), default=s0)
        ne = min((m for m in mids if e0 - 2 <= m <= e0 + 4),
                 key=lambda m: abs(m - e0), default=e0)
        if ne - ns < 5 or ne - ns > clip_len + 12:
            ns, ne = s0, e0
        ns = max(ns - 0.1, prev_end, 0.0)
        ne = ne + 0.1
        if duration:
            ne = min(ne, duration)
        if ne - ns < 3:
            continue
        d = dict(c)
        d["start_time"], d["end_time"] = ns, ne
        out.append(d)
        prev_end = ne
    return out


def get_video_size(path):
    try:
        r = run_capture(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path])
        w, h = r.stdout.strip().splitlines()[0].split("x")
        return int(w), int(h)
    except Exception:
        return 0, 0


def pan_keys(frames, W, H, src_w, cw, fps=3, group=4):
    """Motion-weighted horizontal crop positions: [(time_s, crop_x), ...].

    Uses weighted center-of-motion to smoothly follow the action.
    group=4 (down from 6) for more responsive tracking.
    """
    max_x = max(0, src_w - cw)
    prev = max_x / 2.0
    cols = []
    for a, b in zip(frames, frames[1:]):
        col = [0] * W
        for y in range(H):
            row = y * W
            for x in range(W):
                d = a[row + x] - b[row + x]
                col[x] += d if d >= 0 else -d
        cols.append(col)
    keys = []
    for g in range(0, len(cols), group):
        chunk = cols[g:g + group]
        m = [max(0, sum(c[x] for c in chunk) - len(chunk) * 3) for x in range(W)]
        tot = sum(m)
        if tot < 40:
            target = prev
        else:
            cx = sum((x + 0.5) * m[x] for x in range(W)) / tot / W * src_w
            target = min(max(cx - cw / 2.0, 0), max_x)
        delta = target - prev
        # Smoother panning: smaller max delta per step, ignore tiny jitter
        if abs(delta) < 0.05 * cw:
            target = prev
        else:
            target = prev + max(-0.25 * cw, min(0.25 * cw, delta))
        keys.append(((g + len(chunk) / 2.0) / float(fps), target))
        prev = target
    return keys


def pan_expr(keys, dur):
    """ffmpeg expression for crop x that glides between key positions."""
    if not keys:
        return "0"
    xs = [k[1] for k in keys]
    if max(xs) - min(xs) < 4:
        return "%d" % (sum(xs) / len(xs))
    pts = [(0.0, keys[0][1])] + list(keys) + [(dur, keys[-1][1])]
    parts = []
    for (t1, x1), (t2, x2) in zip(pts, pts[1:]):
        if t2 - t1 <= 0.01:
            continue
        parts.append("gte(t,%.2f)*lt(t,%.2f)*(%.1f+(%.1f)*(t-%.2f)/%.2f)"
                     % (t1, t2, x1, x2 - x1, t1, t2 - t1))
    parts.append("gte(t,%.2f)*%.1f" % (pts[-1][0], pts[-1][1]))
    return "+".join(parts)


def analyze_pan(video, start, dur, src_w, src_h):
    """Return (crop_width, x_expression) that follows the action in the clip.

    Uses higher-resolution motion analysis (96x54) and 4 fps for smoother tracking.
    """
    cw = int(src_h * 9 / 16) // 2 * 2
    centre = max(0, src_w - cw) // 2
    W, H = 96, 54
    fps = 4
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", "%.2f" % start, "-t", "%.2f" % dur, "-i", video,
             "-an", "-vf", "fps=%d,scale=%d:%d,format=gray" % (fps, W, H), "-f", "rawvideo", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        data = r.stdout
    except Exception:
        return cw, str(centre)
    fs = W * H
    frames = [data[i * fs:(i + 1) * fs] for i in range(len(data) // fs)]
    if len(frames) < 4:
        return cw, str(centre)
    return cw, pan_expr(pan_keys(frames, W, H, src_w, cw, fps=fps), dur)


# --------------------------------------------------------------------------
# Captions (Whisper via local OpenAI-compatible API)
# --------------------------------------------------------------------------
def extract_audio_mp3(clip, mp3, log):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", clip, "-vn",
           "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", mp3]
    r = run_capture(cmd)
    if r.returncode != 0 or not os.path.isfile(mp3) or os.path.getsize(mp3) == 0:
        log("  audio extraction failed: " + (r.stderr or "").strip()[-200:])
        return False
    return True


def transcribe_whisper(base, mp3, lang=None, prompt=None, timeout=600):
    """POST multipart to /v1/audio/transcriptions, return parsed JSON dict."""
    boundary = "----HypeClipper" + str(int(time.time() * 1000))
    parts = []

    def field(name, value):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, name, value)).encode("utf-8"))

    field("model", WHISPER_MODEL)
    field("response_format", "verbose_json")
    if lang:
        field("language", lang)
    if prompt:
        field("prompt", prompt)
    with open(mp3, "rb") as f:
        data = f.read()
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
                  "filename=\"audio.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n"
                  % boundary).encode("utf-8"))
    parts.append(data)
    parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(
        base + "/v1/audio/transcriptions", data=b"".join(parts),
        headers=auth_headers({"Content-Type": "multipart/form-data; boundary=" + boundary}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def make_srt(base, clip, idx, log, lang=None, prompt=None, words_per_chunk=3, uppercase=True):
    """Return path to a valid .srt in TEMP_DIR, or None (skip captions)."""
    mp3 = os.path.join(TEMP_DIR, "cap_%d.mp3" % idx)
    srt = os.path.join(TEMP_DIR, "cap_%d.srt" % idx)
    try:
        if not extract_audio_mp3(clip, mp3, log):
            return None
        log("  transcribing with %s..." % WHISPER_MODEL)
        data = transcribe_whisper(base, mp3, lang, prompt)
        # Convert JSON response to SRT text
        srt_text = json_to_srt(data, words_per_chunk=words_per_chunk, uppercase=uppercase)
        if "-->" not in srt_text:
            log("  no speech detected (music-only?) - skipping captions.")
            return None
        with open(srt, "w", encoding="utf-8") as f:
            f.write(srt_text + "\n")
        log("  transcription: %d subtitle blocks generated (%d words/chunk)." % (
            srt_text.count("-->"), words_per_chunk))
        return srt
    except Exception as e:  # network, HTTP, timeout, anything
        log("  transcription failed (%s) - skipping captions." % e)
        return None
    finally:
        try:
            if os.path.isfile(mp3):
                os.remove(mp3)
        except OSError:
            pass


def caption_font(srt, preferred="Impact"):
    """Arial has no Hindi/Punjabi glyphs; switch to Nirmala UI when those scripts appear."""
    try:
        text = open(srt, encoding="utf-8", errors="replace").read()
    except OSError:
        return preferred
    if re.search("[\u0900-\u097F\u0A00-\u0A7F]", text):
        return "Nirmala UI"
    return preferred


def build_caption_style(font, size, style_name="Viral Yellow (MrBeast)", position="Bottom (Reels safe)", vertical=True):
    preset = CAPTION_STYLES.get(style_name, CAPTION_STYLES["Viral Yellow (MrBeast)"])
    if "Center" in position or "Middle" in position:
        alignment = 5
        margin_v = 0
    elif "Low" in position:
        alignment = 2
        margin_v = 45 if vertical else 20
    else:  # "Bottom (Reels safe)"
        alignment = 2
        margin_v = 175 if vertical else 45

    margin_lr = 40 if vertical else 30
    return (
        "FontName=%s,FontSize=%d,Bold=1,"
        "PrimaryColour=%s,OutlineColour=%s,BackColour=%s,"
        "BorderStyle=%d,Outline=%d,Shadow=%d,"
        "Alignment=%d,MarginV=%d,MarginL=%d,MarginR=%d"
        % (
            font, size,
            preset["primary"], preset["outline"], preset["back"],
            preset["border_style"], preset["outline_w"], preset["shadow"],
            alignment, margin_v, margin_lr, margin_lr
        )
    )


def burn_captions(clip, srt, vertical, log, size=44, style_name="Viral Yellow (MrBeast)",
                  position="Bottom (Reels safe)", font_name="Impact", preset="fast", crf=18):
    """Burn srt into clip (in place). Returns True on success."""
    tmp_out = clip[:-4] + ".captioned.mp4"
    preset_data = CAPTION_STYLES.get(style_name, {})
    chosen_font = font_name or preset_data.get("font", "Impact")
    actual_font = caption_font(srt, preferred=chosen_font)
    style_str = build_caption_style(actual_font, size, style_name, position, vertical)

    # Run in TEMP_DIR with a bare file name so no drive-letter/colon escaping is needed.
    vf = "subtitles=%s:force_style='%s'" % (os.path.basename(srt), style_str)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", os.path.abspath(clip),
           "-vf", vf, "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p",
           "-c:a", "copy", "-movflags", "+faststart", os.path.abspath(tmp_out)]
    r = subprocess.run(cmd, cwd=os.path.dirname(srt), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, encoding="utf-8",
                       errors="replace", creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0 or not os.path.isfile(tmp_out):
        log("  caption burn failed: " + (r.stderr or "").strip()[-300:])
        try:
            if os.path.isfile(tmp_out):
                os.remove(tmp_out)
        except OSError:
            pass
        return False
    os.replace(tmp_out, clip)
    return True


# --------------------------------------------------------------------------
# Voice-over (AI narration via local /v1/audio/speech, or an imported audio file)
# --------------------------------------------------------------------------
def srt_to_text(srt, limit=800):
    if not srt or not os.path.isfile(srt):
        return ""
    out = []
    for line in open(srt, encoding="utf-8", errors="replace"):
        line = line.strip()
        if line and "-->" not in line and not line.isdigit():
            out.append(line)
    return " ".join(out)[:limit]


def write_narration(base, title, speech, dur, log):
    """Ask the local chat model for a short hype narration line."""
    model = pick_model(base, lambda m: None)
    max_words = max(8, int(dur * 2.2))
    prompt = ("Write a punchy, energetic voice-over line for a short video clip titled \"%s\". "
              "%sUse at most %d words. Output ONLY the spoken text, no quotes, no emojis."
              % (title.replace("_", " "),
                 ("What is said in the clip: %s\n" % speech) if speech else "",
                 max_words))
    body = json.dumps({"model": model, "temperature": 0.7, "max_tokens": 1024,
                       "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers=auth_headers({"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
    return re.sub(r"\s+", " ", text).strip().strip('"')


def tts_to_mp3(base, text, model, voice, mp3):
    body = json.dumps({"model": model, "input": text, "voice": voice,
                       "response_format": "mp3"}).encode("utf-8")
    req = urllib.request.Request(base + "/v1/audio/speech", data=body,
                                 headers=auth_headers({"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if not data:
        raise ValueError("empty audio returned")
    with open(mp3, "wb") as f:
        f.write(data)


def mix_voiceover(clip, vo_audio, log):
    """Duck the original audio and mix the voice-over on top, in place."""
    tmp_out = clip[:-4] + ".vo.mp4"
    fc = ("[0:a]volume=0.4[a0];[1:a]volume=1.0[a1];"
          "[a0][a1]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", clip, "-i", vo_audio,
           "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", tmp_out]
    r = run_capture(cmd)
    if r.returncode != 0 or not os.path.isfile(tmp_out):
        log("  voice-over mix failed: " + (r.stderr or "").strip()[-300:])
        try:
            if os.path.isfile(tmp_out):
                os.remove(tmp_out)
        except OSError:
            pass
        return False
    os.replace(tmp_out, clip)
    return True


# --------------------------------------------------------------------------
# Cutting
# --------------------------------------------------------------------------
QUALITY = {"Fast": ("veryfast", 21), "Balanced": ("medium", 18), "High": ("slow", 16)}
BLUR_FIT = ("split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "boxblur=30:8,eq=brightness=-0.08:saturation=0.7[bg];"
            "[b]scale=1080:-2:flags=lanczos+accurate_rnd[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2")


def build_filters(dur, pre_vf, opts, size=None):
    vf, af = list(pre_vf), []
    speed = float(opts.get("speed", 1.0) or 1.0)
    if abs(speed - 1.0) > 0.01:
        vf.append("setpts=PTS/%.4f" % speed)
        if 0.5 <= speed <= 2.0:
            af.append("atempo=%.4f" % speed)
    if opts.get("zoom"):
        z = 1.15
        vf.append("crop=trunc(iw/%s/2)*2:trunc(ih/%s/2)*2" % (z, z))
        if size:
            vf.append("scale=%d:%d:flags=lanczos" % size)
        else:
            vf.append("scale=trunc(iw*%s/2)*2:trunc(ih*%s/2)*2:flags=lanczos" % (z, z))
    if opts.get("fade") and dur > 2:
        eff_dur = dur / speed if speed else dur
        vf.append("fade=t=in:st=0:d=0.5")
        vf.append("fade=t=out:st=%.2f:d=0.5" % (eff_dur - 0.5))
        af.append("afade=t=in:st=0:d=0.5")
        af.append("afade=t=out:st=%.2f:d=0.5" % (eff_dur - 0.5))
    if opts.get("normalize"):
        af.insert(0, "loudnorm=I=-16:TP=-1.5:LRA=11")
    return vf, af


def framing_filters(video, c, dur, vertical, sw, sh, framing, log):
    if not vertical:
        return []
    if not sw or not sh:
        return ["crop=trunc(ih*9/16/2)*2:ih", "scale=1080:1920:flags=lanczos", "setsar=1"]
    if sh >= sw:  # already portrait
        return ["scale=1080:1920:force_original_aspect_ratio=increase", "crop=1080:1920",
                "setsar=1"]
    if framing.startswith("Blur"):
        return [BLUR_FIT, "setsar=1"]
    if framing.startswith("Smart"):
        cw, expr = analyze_pan(video, c["start_time"], dur, sw, sh)
        log("  smart crop: following the action (hi-res tracking)")
        return ["crop=%d:ih:x='%s':y=0" % (cw, expr),
                "scale=1080:1920:flags=lanczos+accurate_rnd",
                "setsar=1"]
    return ["crop=trunc(ih*9/16/2)*2:ih", "scale=1080:1920:flags=lanczos", "setsar=1"]


def cut_clips(video, clips, vertical, log, opts=None, api_base_url=DEFAULT_API):
    opts = opts or {}
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)
    preset, crf = QUALITY.get(opts.get("quality", "Balanced"), QUALITY["Balanced"])
    framing = opts.get("framing", "Blurred background fit")
    sw, sh = get_video_size(video)
    if vertical:
        size = (1080, 1920)
    else:
        size = (sw // 2 * 2, sh // 2 * 2) if sw and sh else None
    for i, c in enumerate(clips, 1):
        out = os.path.join(OUT_DIR, "%d_%s.mp4" % (i, c["title"]))
        dur = c["end_time"] - c["start_time"]
        log("Cutting clip %d/%d: %s (%s - %s)" % (
            i, len(clips), c["title"], fmt_time(c["start_time"]), fmt_time(c["end_time"])))
        pre = framing_filters(video, c, dur, vertical, sw, sh, framing, log)
        vf, af = build_filters(dur, pre, opts, size)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error",
               "-ss", "%.2f" % c["start_time"], "-i", video, "-t", "%.2f" % dur]
        if vf:
            cmd += ["-vf", ",".join(vf)]
        if af:
            cmd += ["-af", ",".join(af)]
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", out]
        code = run_stream(cmd, log)
        if code != 0:
            log("  -> FAILED (code %s)" % code)
            continue

        speech = ""
        if opts.get("captions"):
            srt = make_srt(
                api_base_url, out, i, log,
                lang=opts.get("cap_lang"),
                prompt=opts.get("cap_prompt"),
                words_per_chunk=opts.get("cap_words", 3),
                uppercase=opts.get("cap_upper", True),
            )
            if srt:
                speech = srt_to_text(srt)
                cap_style = opts.get("cap_style", "Viral Yellow (MrBeast)")
                cap_size = opts.get("caption_size", 44 if vertical else 26)
                log("  burning captions (%s, size %d)..." % (cap_style, cap_size))
                if burn_captions(
                    out, srt, vertical, log,
                    size=cap_size,
                    style_name=cap_style,
                    position=opts.get("cap_pos", "Bottom (Reels safe)"),
                    font_name=opts.get("cap_font", "Impact"),
                    preset=preset,
                    crf=crf,
                ):
                    log("  captions burned.")
                try:
                    os.remove(srt)
                except OSError:
                    pass

        vo_mode = opts.get("vo_mode", "Off")
        vo_file = None
        temp_vo = False
        try:
            if vo_mode.startswith("AI"):
                log("  writing AI narration...")
                text = write_narration(api_base_url, c["title"], speech, dur, log)
                log("  narration: " + text)
                vo_file = os.path.join(TEMP_DIR, "vo_%d.mp3" % i)
                temp_vo = True
                tts_to_mp3(api_base_url, text, opts.get("tts_model", "auto"),
                           opts.get("tts_voice", "alloy"), vo_file)
            elif vo_mode.startswith("Import"):
                vo_file = opts.get("vo_path")
                if not vo_file or not os.path.isfile(vo_file):
                    log("  no voice-over audio file selected - skipping voice-over.")
                    vo_file = None
            if vo_file:
                log("  mixing voice-over...")
                if mix_voiceover(out, vo_file, log):
                    log("  voice-over added.")
        except Exception as e:
            log("  voice-over failed (%s) - keeping clip without it." % e)
        finally:
            if temp_vo and vo_file and os.path.isfile(vo_file):
                try:
                    os.remove(vo_file)
                except OSError:
                    pass
        log("  -> saved " + out)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------
# BridgeClip Studio UI
# --------------------------------------------------------------------------
APP_TITLE = "BridgeClip"

BG_DARK = "#0b0d11"
SIDEBAR_BG = "#11141b"
CARD_BG = "#161922"
CARD_BORDER = "#232836"
CARD_ACTIVE_BG = "#172236"
CARD_ACTIVE_BORDER = "#3b82f6"
TEXT_MAIN = "#f8fafc"
TEXT_MUTED = "#94a3b8"
TEXT_DIM = "#64748b"
ACCENT_BLUE = "#2563eb"
ACCENT_BLUE_HOVER = "#1d4ed8"
ACCENT_GREEN = "#10b981"
BTN_DARK = "#1d212c"
BTN_DARK_HOVER = "#2a3040"

STEP_NAMES = ["Video", "Format", "Clips", "Captions", "Review"]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(APP_TITLE)
        self.configure(fg_color=BG_DARK)

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1200, sw - 40), min(800, sh - 80)
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 2 - 20)))
        self.minsize(1040, 680)

        self.logq = queue.Queue()
        self.busy = False
        self.vo_path = ""
        self.installing = False
        self.current_step = 0
        self.current_view = "Create"

        # Wizard state variables
        self.format_val = "Vertical 9:16"
        self.framing_val = "Smart"
        self.speed_val = 1.0
        self.clipping_mode_val = "Quality"
        self.clip_length_val = "30-60s"
        self.caption_style_val = "Pop"
        self.caption_pacing_val = "Fast (2-3 words)"
        self.caption_pos_val = "Bottom (Reels safe)"
        self.caption_font_val = "Impact"

        self._build_shell()
        self._set_view("Create")
        self.after(100, self._drain)
        self.after(700, self._auto_offer)
        self.bind("<Control-j>", lambda e: self.start())

    def report_callback_exception(self, exc, val, tb):
        self.log("UI ERROR: %r" % (val,))

    # ----------------------------------------------------------------------
    # Shell: Sidebar + Content Area
    # ----------------------------------------------------------------------
    def _build_shell(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 1. Left Sidebar
        self.sidebar = ctk.CTkFrame(self, width=210, fg_color=SIDEBAR_BG, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # Logo row
        logo_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_row.pack(fill="x", padx=16, pady=(18, 16))
        ctk.CTkLabel(logo_row, text="⚡", font=ctk.CTkFont(size=20), text_color="#f59e0b").pack(side="left")
        ctk.CTkLabel(logo_row, text=" BridgeClip", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT_MAIN).pack(side="left")

        # Studio Section
        ctk.CTkLabel(self.sidebar, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(8, 4))
        self.nav_btns = {}
        for name, icon in [("Create", "🪄"), ("Library", "📁"), ("Jobs", "📋")]:
            btn = ctk.CTkButton(self.sidebar, text="  " + icon + "  " + name, anchor="w",
                                height=38, corner_radius=8, font=ctk.CTkFont(size=13, weight="bold"),
                                fg_color="transparent", hover_color=BTN_DARK_HOVER,
                                text_color=TEXT_MUTED, command=lambda n=name: self._set_view(n))
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[name] = btn

        # Workspace Section
        ctk.CTkLabel(self.sidebar, text="WORKSPACE", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(18, 4))
        for name, icon in [("Settings", "⚙️")]:
            btn = ctk.CTkButton(self.sidebar, text="  " + icon + "  " + name, anchor="w",
                                height=38, corner_radius=8, font=ctk.CTkFont(size=13, weight="bold"),
                                fg_color="transparent", hover_color=BTN_DARK_HOVER,
                                text_color=TEXT_MUTED, command=lambda n=name: self._set_view(n))
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[name] = btn

        # Sidebar Footer
        sb_footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        sb_footer.pack(side="bottom", fill="x", padx=16, pady=16)
        status_row = ctk.CTkFrame(sb_footer, fg_color="transparent")
        status_row.pack(fill="x")
        self.sb_dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=14), text_color=ACCENT_GREEN)
        self.sb_dot.pack(side="left")
        self.sb_status = ctk.CTkLabel(status_row, text=" Ready to clip", font=ctk.CTkFont(size=12),
                                      text_color=TEXT_MUTED)
        self.sb_status.pack(side="left")
        ctk.CTkLabel(sb_footer, text="v0.1.20", font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
                     anchor="w").pack(fill="x", pady=(2, 0))

        # 2. Main Content Host
        self.main_host = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self.main_host.grid(row=0, column=1, sticky="nsew", padx=20, pady=16)
        self.main_host.grid_columnconfigure(0, weight=1)
        self.main_host.grid_rowconfigure(1, weight=1)

        # Build view pages
        self._build_create_view()
        self._build_jobs_view()
        self._build_settings_view()
        self._build_library_view()

    def _set_view(self, name):
        self.current_view = name
        for n, btn in self.nav_btns.items():
            if n == name:
                btn.configure(fg_color="#1e2433", text_color="#38bdf8")
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_MUTED)

        for v in (self.view_create, self.view_jobs, self.view_settings, self.view_library):
            v.grid_forget()

        if name == "Create":
            self.view_create.grid(row=0, column=0, sticky="nsew")
        elif name == "Jobs":
            self.view_jobs.grid(row=0, column=0, sticky="nsew")
        elif name == "Settings":
            self.view_settings.grid(row=0, column=0, sticky="nsew")
        elif name == "Library":
            self.view_library.grid(row=0, column=0, sticky="nsew")
            self._refresh_library_list()

    # ----------------------------------------------------------------------
    # View 1: Studio Create Wizard
    # ----------------------------------------------------------------------
    def _build_create_view(self):
        self.view_create = ctk.CTkFrame(self.main_host, fg_color="transparent")
        self.view_create.grid_columnconfigure(0, weight=1)
        self.view_create.grid_rowconfigure(2, weight=1)

        # Header
        top_header = ctk.CTkFrame(self.view_create, fg_color="transparent")
        top_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(top_header, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(top_header, text="Create clips", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(top_header,
                     text="Pick a long video and a few options. BridgeClip finds the strongest moments and cuts them into captioned clips.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x")

        # Stepper bar
        self.stepper_frame = ctk.CTkFrame(self.view_create, fg_color="transparent")
        self.stepper_frame.grid(row=1, column=0, sticky="ew", pady=(12, 16))
        self.step_indicators = []
        for i, name in enumerate(STEP_NAMES):
            step_btn = ctk.CTkButton(self.stepper_frame, text="%d  %s" % (i + 1, name),
                                     height=30, corner_radius=15, font=ctk.CTkFont(size=12, weight="bold"),
                                     fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, text_color=TEXT_MUTED,
                                     command=lambda s=i: self._set_step(s))
            step_btn.pack(side="left", padx=(0, 10))
            self.step_indicators.append(step_btn)

        # Step Cards Container
        self.step_container = ctk.CTkFrame(self.view_create, fg_color=CARD_BG, corner_radius=14,
                                           border_width=1, border_color=CARD_BORDER)
        self.step_container.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        self.step_container.grid_columnconfigure(0, weight=1)
        self.step_container.grid_rowconfigure(0, weight=1)

        # Build each wizard step card
        self._build_step_video()
        self._build_step_format()
        self._build_step_clips()
        self._build_step_captions()
        self._build_step_review()

        # Bottom Action Bar
        self.bot_bar = ctk.CTkFrame(self.view_create, fg_color="transparent")
        self.bot_bar.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        self.btn_back = ctk.CTkButton(self.bot_bar, text="← Back", width=100, height=40,
                                      corner_radius=8, fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER,
                                      font=ctk.CTkFont(size=13, weight="bold"), command=self._prev_step)
        self.btn_back.pack(side="left")

        self.hint_label = ctk.CTkLabel(self.bot_bar, text="Ctrl+J generates from any step",
                                       font=ctk.CTkFont(size=12), text_color=TEXT_DIM)
        self.hint_label.pack(side="left", padx=20)

        self.btn_generate_now = ctk.CTkButton(self.bot_bar, text="Generate now", width=120, height=40,
                                              corner_radius=8, fg_color="transparent", hover_color=BTN_DARK_HOVER,
                                              text_color=TEXT_MUTED, font=ctk.CTkFont(size=13),
                                              command=self.start)
        self.btn_generate_now.pack(side="right", padx=(8, 0))

        self.btn_next = ctk.CTkButton(self.bot_bar, text="Next: Format →", width=150, height=40,
                                      corner_radius=8, fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
                                      font=ctk.CTkFont(size=13, weight="bold"), command=self._next_step)
        self.btn_next.pack(side="right")

    def _set_step(self, idx):
        self.current_step = max(0, min(4, idx))
        for i, ind in enumerate(self.step_indicators):
            if i < self.current_step:
                ind.configure(fg_color="#1e293b", text_color="#38bdf8", text="✓  %s" % STEP_NAMES[i])
            elif i == self.current_step:
                ind.configure(fg_color=ACCENT_BLUE, text_color="#ffffff", text="%d  %s" % (i + 1, STEP_NAMES[i]))
            else:
                ind.configure(fg_color=BTN_DARK, text_color=TEXT_MUTED, text="%d  %s" % (i + 1, STEP_NAMES[i]))

        for page in (self.page_video, self.page_format, self.page_clips, self.page_captions, self.page_review):
            page.grid_forget()

        pages = [self.page_video, self.page_format, self.page_clips, self.page_captions, self.page_review]
        pages[self.current_step].grid(row=0, column=0, sticky="nsew", padx=24, pady=20)

        if self.current_step == 0:
            self.btn_back.configure(state="disabled")
        else:
            self.btn_back.configure(state="normal")

        next_labels = ["Next: Format →", "Next: Clips →", "Next: Captions →", "Next: Review →", "✨ Generate clips"]
        self.btn_next.configure(text=next_labels[self.current_step])
        if self.current_step == 4:
            self.btn_next.configure(fg_color="#3b82f6", hover_color="#2563eb", width=160)
            self._update_review_page()
        else:
            self.btn_next.configure(fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, width=150)

    def _next_step(self):
        if self.current_step == 4:
            self.start()
        else:
            self._set_step(self.current_step + 1)

    def _prev_step(self):
        if self.current_step > 0:
            self._set_step(self.current_step - 1)

    # ----------------------------------------------------------------------
    # Step 1: Video
    # ----------------------------------------------------------------------
    def _build_step_video(self):
        self.page_video = ctk.CTkFrame(self.step_container, fg_color="transparent")
        self.page_video.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_video, text="Choose a video", font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_video,
                     text="A local file, YouTube link or direct video link. Optionally clip only part of it.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 16))

        # Drop Box Card
        drop_box = ctk.CTkFrame(self.page_video, fg_color="#12151d", corner_radius=12,
                                border_width=1, border_color="#222736")
        drop_box.pack(fill="x", pady=(0, 16), ipady=10)

        ctk.CTkLabel(drop_box, text="📥  Add a long video", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN).pack(pady=(12, 2))
        ctk.CTkLabel(drop_box, text="Drop a video file or link here, or paste a link below.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack(pady=(0, 8))

        badges_row = ctk.CTkFrame(drop_box, fg_color="transparent")
        badges_row.pack(pady=(0, 10))
        for b in ["▶ YouTube", "👾 Twitch VODs", "📁 Local MP4/MKV"]:
            ctk.CTkLabel(badges_row, text=b, font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
                         fg_color="#1e2330", corner_radius=6, padx=8, pady=3).pack(side="left", padx=4)

        input_row = ctk.CTkFrame(drop_box, fg_color="transparent")
        input_row.pack(fill="x", padx=18, pady=(4, 10))
        self.src = ctk.CTkEntry(input_row, height=42, corner_radius=8,
                                placeholder_text="YouTube, Twitch VOD or direct video link (or path)",
                                fg_color="#181c26", border_color="#2a3142")
        self.src.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.src.bind("<KeyRelease>", lambda e: self._on_src_changed())

        ctk.CTkButton(input_row, text="📁 Browse", width=95, height=42, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"), command=self.pick_file).pack(side="right")

        # Preview card of selected video
        self.selected_card = ctk.CTkFrame(self.page_video, fg_color="#172236", corner_radius=10,
                                          border_width=1, border_color="#3b82f6")
        card_inner = ctk.CTkFrame(self.selected_card, fg_color="transparent")
        card_inner.pack(fill="x", padx=14, pady=10)
        self.sel_thumb = ctk.CTkLabel(card_inner, text="🎬", font=ctk.CTkFont(size=24))
        self.sel_thumb.pack(side="left", padx=(0, 10))
        self.sel_title = ctk.CTkLabel(card_inner, text="Ready to clip", font=ctk.CTkFont(size=13, weight="bold"),
                                      text_color=TEXT_MAIN, anchor="w")
        self.sel_title.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(card_inner, text="Replace", width=70, height=28, corner_radius=6,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=11),
                      command=self.pick_file).pack(side="right", padx=(6, 0))

        # Part Range Card
        range_card = ctk.CTkFrame(self.page_video, fg_color="#12151d", corner_radius=10,
                                  border_width=1, border_color="#222736")
        range_card.pack(fill="x", pady=(0, 14), padx=0)
        rtop = ctk.CTkFrame(range_card, fg_color="transparent")
        rtop.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(rtop, text="Clip only part of the video", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT_MAIN).pack(side="left")
        self.range_switch = ctk.CTkSwitch(rtop, text="")
        self.range_switch.pack(side="right")

        ctk.CTkLabel(range_card, text="Set a start and end time. Leave either empty for an open range.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(0, 8))

        # Quality Row
        qrow = ctk.CTkFrame(self.page_video, fg_color="transparent")
        qrow.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(qrow, text="YouTube download quality:", font=ctk.CTkFont(size=13),
                     text_color=TEXT_MUTED).pack(side="left")
        self.dl_quality = ctk.CTkOptionMenu(
            qrow, width=200, height=32, corner_radius=6,
            values=["Maximum (4K/1440p/Best)", "1080p Full HD (Crisp)", "720p HD", "Auto / Fast"],
            fg_color="#1b202c", button_color="#242b3b")
        self.dl_quality.set("1080p Full HD (Crisp)")
        self.dl_quality.pack(side="right")

    def _on_src_changed(self):
        val = self.src.get().strip()
        if val:
            name = os.path.basename(val) if os.path.isfile(val) else val
            self.sel_title.configure(text=name[:65] + ("..." if len(name) > 65 else ""))
            self.selected_card.pack(fill="x", pady=(0, 14), before=self.page_video.winfo_children()[-2])
        else:
            self.selected_card.pack_forget()

    # ----------------------------------------------------------------------
    # Step 2: Format
    # ----------------------------------------------------------------------
    def _build_step_format(self):
        self.page_format = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_format.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_format, text="Format, framing and speed",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_format, text="Choose the look and pace of every clip in this job.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 14))

        # 1. Format cards (Vertical 9:16 vs Horizontal 16:9)
        ctk.CTkLabel(self.page_format, text="FORMAT", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 4))
        fmt_row = ctk.CTkFrame(self.page_format, fg_color="transparent")
        fmt_row.pack(fill="x", pady=(0, 12))
        fmt_row.columnconfigure((0, 1), weight=1)

        self.fmt_cards = {}
        for idx, (title, sub, icon) in enumerate([
            ("Vertical 9:16", "Shorts, Reels, TikTok", "📱"),
            ("Horizontal 16:9", "YouTube, X, LinkedIn", "🖥️"),
        ]):
            card = ctk.CTkFrame(fmt_row, fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                cursor="hand2")
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            card.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=12)
            r.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            l1 = ctk.CTkLabel(r, text=icon + "  " + title, font=ctk.CTkFont(size=14, weight="bold"),
                              text_color=TEXT_MAIN)
            l1.pack(anchor="w")
            l1.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            l2 = ctk.CTkLabel(r, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
            l2.pack(anchor="w", pady=(2, 0))
            l2.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            self.fmt_cards[title] = card

        # 2. Framing cards
        ctk.CTkLabel(self.page_format, text="FRAMING", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        frm_row = ctk.CTkFrame(self.page_format, fg_color="transparent")
        frm_row.pack(fill="x", pady=(0, 10))
        frm_row.columnconfigure((0, 1, 2), weight=1)

        self.framing_cards = {}
        for idx, (title, sub) in enumerate([
            ("Smart", "Auto frames each shot"),
            ("Full frame", "Follows the speaker"),
            ("Classic", "Whole frame, blurred"),
        ]):
            card = ctk.CTkFrame(frm_row, fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                cursor="hand2")
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            card.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=10)
            r.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            l1 = ctk.CTkLabel(r, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_MAIN)
            l1.pack(anchor="w")
            l1.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            l2 = ctk.CTkLabel(r, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
            l2.pack(anchor="w", pady=(2, 0))
            l2.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            self.framing_cards[title] = card

        # 3. Pacing switch (Cut dead air)
        ctk.CTkLabel(self.page_format, text="PACING", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        pacing_card = ctk.CTkFrame(self.page_format, fg_color="#12151d", corner_radius=10,
                                   border_width=1, border_color=CARD_BORDER)
        pacing_card.pack(fill="x", pady=(0, 10))
        pinner = ctk.CTkFrame(pacing_card, fg_color="transparent")
        pinner.pack(fill="x", padx=14, pady=10)
        ptext = ctk.CTkFrame(pinner, fg_color="transparent")
        ptext.pack(side="left")
        ctk.CTkLabel(ptext, text="Cut dead air", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(ptext, text="Trims long pauses and filler words, keeps demos.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w")
        self.snap = ctk.CTkSwitch(pinner, text="")
        self.snap.select()
        self.snap.pack(side="right")

        # 4. Video Speed
        ctk.CTkLabel(self.page_format, text="VIDEO SPEED", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        spd_row = ctk.CTkFrame(self.page_format, fg_color="transparent")
        spd_row.pack(fill="x", pady=(0, 4))
        spd_row.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.speed_btns = {}
        speeds = [(1.0, "1x\nNormal"), (1.1, "1.1x\n55s/m"), (1.25, "1.25x\n48s/m"), (1.5, "1.5x\n40s/m"), (1.75, "1.75x\n34s/m"), (2.0, "2x\n30s/m")]

        for idx, (spd, lbl) in enumerate(speeds):
            btn = ctk.CTkButton(spd_row, text=lbl, height=44, corner_radius=8,
                                font=ctk.CTkFont(size=11, weight="bold"),
                                fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                border_width=1, border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                text_color=TEXT_MAIN, command=lambda s=spd: self._select_speed(s))
            btn.grid(row=0, column=idx, sticky="ew", padx=3)
            self.speed_btns[spd] = btn

        ctk.CTkLabel(self.page_format,
                     text="Speeds up every exported clip, keeping voice pitch natural and captions in sync. Faster clips are shorter.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 0))

    def _select_format(self, val):
        self.format_val = val
        for title, card in self.fmt_cards.items():
            if title == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _select_framing(self, val):
        self.framing_val = val
        for title, card in self.framing_cards.items():
            if title == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _select_speed(self, spd):
        self.speed_val = spd
        for s, btn in self.speed_btns.items():
            if s == spd:
                btn.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                btn.configure(fg_color="#12151d", border_color=CARD_BORDER)

    # ----------------------------------------------------------------------
    # Step 3: Clips
    # ----------------------------------------------------------------------
    def _build_step_clips(self):
        self.page_clips = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_clips.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_clips, text="Clip length and count",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_clips, text="Pick one or more lengths, or leave them all off for any length.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 14))

        # 1. Clipping Mode cards
        ctk.CTkLabel(self.page_clips, text="CLIPPING MODE", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 4))
        mode_row = ctk.CTkFrame(self.page_clips, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 12))
        mode_row.columnconfigure((0, 1, 2), weight=1)

        self.mode_cards = {}
        for idx, (title, sub) in enumerate([
            ("Quality", "Opus / Local LLM planning"),
            ("Economy", "Replay Heatmap / Fast"),
            ("Direct", "Peak Energy (Loudest moments)"),
        ]):
            card = ctk.CTkFrame(mode_row, fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                cursor="hand2")
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            card.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=10)
            r.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            l1 = ctk.CTkLabel(r, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_MAIN)
            l1.pack(anchor="w")
            l1.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            l2 = ctk.CTkLabel(r, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
            l2.pack(anchor="w", pady=(2, 0))
            l2.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            self.mode_cards[title] = card

        # 2. Clip Length
        ctk.CTkLabel(self.page_clips, text="CLIP LENGTH", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        len_row = ctk.CTkFrame(self.page_clips, fg_color="transparent")
        len_row.pack(fill="x", pady=(0, 12))
        len_row.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)

        self.len_btns = {}
        lengths = [
            ("10-30s", "Extra short"),
            ("30-60s", "Short"),
            ("1-2m", "Medium"),
            ("2-5m", "Long"),
            ("5-10m", "Extra long"),
            ("10-15m", "Extended"),
            ("15-30m", "Feature"),
        ]
        for idx, (dur, sub) in enumerate(lengths):
            btn = ctk.CTkButton(len_row, text=dur + "\n" + sub, height=48, corner_radius=8,
                                font=ctk.CTkFont(size=11, weight="bold"),
                                fg_color=CARD_ACTIVE_BG if idx == 1 else "#12151d",
                                border_width=1, border_color=CARD_ACTIVE_BORDER if idx == 1 else CARD_BORDER,
                                text_color=TEXT_MAIN, command=lambda d=dur: self._select_clip_length(d))
            btn.grid(row=0, column=idx, sticky="ew", padx=2)
            self.len_btns[dur] = btn

        # 3. Number of Clips
        ctk.CTkLabel(self.page_clips, text="NUMBER OF CLIPS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        count_card = ctk.CTkFrame(self.page_clips, fg_color="#12151d", corner_radius=10,
                                  border_width=1, border_color=CARD_BORDER)
        count_card.pack(fill="x", pady=(0, 10))
        cinner = ctk.CTkFrame(count_card, fg_color="transparent")
        cinner.pack(fill="x", padx=14, pady=10)
        ctext = ctk.CTkFrame(cinner, fg_color="transparent")
        ctext.pack(side="left")
        ctk.CTkLabel(ctext, text="Let AI decide", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(ctext, text="Every moment worth posting.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w")
        self.ai_decide_switch = ctk.CTkSwitch(cinner, text="", command=self._toggle_ai_count)
        self.ai_decide_switch.select()
        self.ai_decide_switch.pack(side="right")

        self.custom_count_row = ctk.CTkFrame(count_card, fg_color="transparent")
        ctk.CTkLabel(self.custom_count_row, text="Exact max clips:", font=ctk.CTkFont(size=12),
                     text_color=TEXT_MUTED).pack(side="left", padx=(14, 8))
        self.max_clips_entry = ctk.CTkEntry(self.custom_count_row, width=80, height=30)
        self.max_clips_entry.insert(0, "3")
        self.max_clips_entry.pack(side="left", pady=(0, 8))

    def _select_clipping_mode(self, val):
        self.clipping_mode_val = val
        for title, card in self.mode_cards.items():
            if title == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _select_clip_length(self, val):
        self.clip_length_val = val
        for dur, btn in self.len_btns.items():
            if dur == val:
                btn.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                btn.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _toggle_ai_count(self):
        if self.ai_decide_switch.get():
            self.custom_count_row.pack_forget()
        else:
            self.custom_count_row.pack(fill="x", padx=14, pady=(0, 8))

    # ----------------------------------------------------------------------
    # Step 4: Captions
    # ----------------------------------------------------------------------
    def _build_step_captions(self):
        self.page_captions = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_captions.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_captions, text="Captions",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_captions, text="Word-by-word captions burned into each clip. Silent videos are clipped without them.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 10))

        # Top toggles card
        top_c = ctk.CTkFrame(self.page_captions, fg_color="#12151d", corner_radius=10,
                             border_width=1, border_color=CARD_BORDER)
        top_c.pack(fill="x", pady=(0, 12))
        tc_inner = ctk.CTkFrame(top_c, fg_color="transparent")
        tc_inner.pack(fill="x", padx=14, pady=10)

        t_left = ctk.CTkFrame(tc_inner, fg_color="transparent")
        t_left.pack(side="left")
        ctk.CTkLabel(t_left, text="Burn in captions", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(t_left, text="Turn off for clean clips without on-screen text.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w")

        self.captions_switch = ctk.CTkSwitch(tc_inner, text="")
        self.captions_switch.select()
        self.captions_switch.pack(side="right")

        # 12 Visual Style Preset Cards (2 rows of 6)
        ctk.CTkLabel(self.page_captions, text="CAPTION STYLE PRESETS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 6))

        grid_frame = ctk.CTkFrame(self.page_captions, fg_color="transparent")
        grid_frame.pack(fill="x", pady=(0, 12))
        for col in range(6):
            grid_frame.columnconfigure(col, weight=1)

        self.caption_cards = {}
        preset_names = ["Pop", "Spotlight", "Impact", "Glow", "Boxed", "Sweep",
                        "Editorial", "Hype", "Punch", "Neon", "Headline", "Subtle"]

        for idx, name in enumerate(preset_names):
            row = idx // 6
            col = idx % 6
            info = CAPTION_STYLES.get(name, {})

            card = ctk.CTkFrame(grid_frame, fg_color=CARD_ACTIVE_BG if name == "Pop" else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if name == "Pop" else CARD_BORDER,
                                height=85, cursor="hand2")
            card.grid(row=row, column=col, sticky="nsew", padx=3, pady=4)
            card.grid_propagate(False)
            card.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            # Sample text preview box
            sample_box = ctk.CTkFrame(card, fg_color=info.get("sample_bg", "#181b22"), corner_radius=6)
            sample_box.pack(fill="both", expand=True, padx=6, pady=(6, 2))
            sample_box.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            s_lbl = ctk.CTkLabel(sample_box, text=info.get("sample", name),
                                 font=ctk.CTkFont(family="Arial Black" if info.get("font") != "Georgia" else "Georgia",
                                                  size=10, weight="bold"),
                                 text_color=info.get("sample_color", "#ffffff"))
            s_lbl.pack(expand=True)
            s_lbl.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            # Bottom name label
            n_lbl = ctk.CTkLabel(card, text=name, font=ctk.CTkFont(size=11, weight="bold"),
                                 text_color=TEXT_MAIN if name == "Pop" else TEXT_MUTED)
            n_lbl.pack(pady=(0, 4))
            n_lbl.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            self.caption_cards[name] = (card, n_lbl)

        # Options Row (Pacing, Position, Size, Language)
        opt_card = ctk.CTkFrame(self.page_captions, fg_color="#12151d", corner_radius=10,
                                border_width=1, border_color=CARD_BORDER)
        opt_card.pack(fill="x", pady=(2, 6))
        opt_card.columnconfigure((0, 1, 2, 3), weight=1)

        # Pacing
        c1 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c1.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c1, text="Pacing (words)", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_pacing = ctk.CTkOptionMenu(
            c1, height=30, values=["Punchy (1-2 words)", "Fast (2-3 words)", "Balanced (3-4 words)", "Sentence (5-7)"],
            fg_color="#1a1f2b", button_color="#242b3b")
        self.cap_pacing.set("Fast (2-3 words)")
        self.cap_pacing.pack(fill="x", pady=(4, 0))

        # Position
        c2 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c2.grid(row=0, column=1, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c2, text="Position", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_pos = ctk.CTkOptionMenu(
            c2, height=30, values=["Bottom (Reels safe)", "Center (Focus)", "Bottom Low"],
            fg_color="#1a1f2b", button_color="#242b3b")
        self.cap_pos.set("Bottom (Reels safe)")
        self.cap_pos.pack(fill="x", pady=(4, 0))

        # Size
        c3 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c3.grid(row=0, column=2, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c3, text="Caption Size", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_size = ctk.CTkSegmentedButton(
            c3, height=30, values=["S", "M", "L", "XL"])
        self.cap_size.set("M")
        self.cap_size.pack(fill="x", pady=(4, 0))

        # Language
        c4 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c4.grid(row=0, column=3, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c4, text="Language", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_lang = ctk.CTkOptionMenu(
            c4, height=30, values=list(CAPTION_LANGS.keys()),
            fg_color="#1a1f2b", button_color="#242b3b")
        self.cap_lang.pack(fill="x", pady=(4, 0))

    def _select_caption_style(self, val):
        self.caption_style_val = val
        for name, (card, n_lbl) in self.caption_cards.items():
            if name == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
                n_lbl.configure(text_color=TEXT_MAIN)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)
                n_lbl.configure(text_color=TEXT_MUTED)

    # ----------------------------------------------------------------------
    # Step 5: Review
    # ----------------------------------------------------------------------
    def _build_step_review(self):
        self.page_review = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_review.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_review, text="Review and generate",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_review, text="Check the run, then generate. You can queue another video right after.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 14))

        self.review_table = ctk.CTkFrame(self.page_review, fg_color="#12151d", corner_radius=12,
                                         border_width=1, border_color=CARD_BORDER)
        self.review_table.pack(fill="x", pady=(0, 14))

        self.review_rows = {}
        fields = [
            ("Video", 0),
            ("Format", 1),
            ("Pacing", 1),
            ("Speed", 1),
            ("Mode", 2),
            ("Clips", 2),
            ("Captions", 3),
        ]
        for idx, (label, target_step) in enumerate(fields):
            row = ctk.CTkFrame(self.review_table, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=8)

            ctk.CTkLabel(row, text=label, width=90, font=ctk.CTkFont(size=13),
                         text_color=TEXT_DIM, anchor="w").pack(side="left")

            val_lbl = ctk.CTkLabel(row, text="--", font=ctk.CTkFont(size=13, weight="bold"),
                                   text_color=TEXT_MAIN, anchor="w")
            val_lbl.pack(side="left", fill="x", expand=True)

            ctk.CTkButton(row, text="Edit", width=55, height=26, corner_radius=6,
                          fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=11),
                          command=lambda s=target_step: self._set_step(s)).pack(side="right")

            if idx < len(fields) - 1:
                sep = ctk.CTkFrame(self.review_table, height=1, fg_color="#1d222e")
                sep.pack(fill="x", padx=14)

            self.review_rows[label] = val_lbl

        ctk.CTkLabel(self.page_review,
                     text="⏱️ Runs on this computer. Local AI model & Whisper used for transcription and hype planning.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 0))

    def _update_review_page(self):
        src_val = self.src.get().strip()
        disp_src = os.path.basename(src_val) if os.path.isfile(src_val) else (src_val or "No video specified")
        self.review_rows["Video"].configure(text=disp_src[:50] + ("..." if len(disp_src) > 50 else ""))

        self.review_rows["Format"].configure(text="%s · %s framing" % (self.format_val, self.framing_val))
        self.review_rows["Pacing"].configure(text="Cut dead air" if self.snap.get() else "Natural timing")
        self.review_rows["Speed"].configure(text="%.2gx · %s" % (self.speed_val, "Normal" if self.speed_val == 1.0 else "Sped up"))
        self.review_rows["Mode"].configure(text="%s · AI Planning" % self.clipping_mode_val)

        clip_str = "%s · %s" % (self.clip_length_val, "AI decides count" if self.ai_decide_switch.get() else ("Max %s clips" % self.max_clips_entry.get()))
        self.review_rows["Clips"].configure(text=clip_str)

        cap_str = "%s (Viral)" % self.caption_style_val if self.captions_switch.get() else "Off"
        self.review_rows["Captions"].configure(text=cap_str)

    # ----------------------------------------------------------------------
    # View 2: Jobs
    # ----------------------------------------------------------------------
    def _build_jobs_view(self):
        self.view_jobs = ctk.CTkFrame(self.main_host, fg_color="transparent")
        self.view_jobs.grid_columnconfigure(0, weight=1)
        self.view_jobs.grid_rowconfigure(2, weight=1)

        # Header
        top_h = ctk.CTkFrame(self.view_jobs, fg_color="transparent")
        top_h.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(top_h, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(top_h, text="Jobs & Progress", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))

        # Status banner card
        stat_card = ctk.CTkFrame(self.view_jobs, fg_color=CARD_BG, corner_radius=12,
                                 border_width=1, border_color=CARD_BORDER)
        stat_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        sc_inner = ctk.CTkFrame(stat_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=16, pady=12)

        self.jobs_status_lbl = ctk.CTkLabel(sc_inner, text="Idle - No active job",
                                            font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT_MAIN, anchor="w")
        self.jobs_status_lbl.pack(fill="x")

        self.progress = ctk.CTkProgressBar(sc_inner, mode="indeterminate", height=6, corner_radius=3,
                                           progress_color=ACCENT_BLUE)
        self.progress.pack(fill="x", pady=(8, 2))
        self.progress.set(0)

        # Console Log Textbox Card
        console_card = ctk.CTkFrame(self.view_jobs, fg_color=CARD_BG, corner_radius=12,
                                    border_width=1, border_color=CARD_BORDER)
        console_card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        console_card.grid_columnconfigure(0, weight=1)
        console_card.grid_rowconfigure(0, weight=1)

        self.console = ctk.CTkTextbox(console_card, font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color="#0e1117", text_color="#cbd5e1", corner_radius=10, wrap="word")
        self.console.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.console.configure(state="disabled")

        # Bottom buttons
        j_btns = ctk.CTkFrame(self.view_jobs, fg_color="transparent")
        j_btns.grid(row=3, column=0, sticky="ew")

        ctk.CTkButton(j_btns, text="📁 Open Output Folder", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_out).pack(side="left", padx=(0, 8))

        ctk.CTkButton(j_btns, text="📁 Open Videos Folder", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_videos).pack(side="left", padx=8)

        ctk.CTkButton(j_btns, text="Clear Log", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self.clear_log).pack(side="left", padx=8)

        ctk.CTkButton(j_btns, text="🪄 Back to Create", height=38, corner_radius=8,
                      fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: self._set_view("Create")).pack(side="right")

    # ----------------------------------------------------------------------
    # View 3: Settings
    # ----------------------------------------------------------------------
    def _build_settings_view(self):
        self.view_settings = ctk.CTkScrollableFrame(self.main_host, fg_color="transparent")
        self.view_settings.grid_columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(self.view_settings, text="PREFERENCES", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.view_settings, text="Settings", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(self.view_settings, text="Changes save automatically to hypeclipper_settings.json.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(0, 14))

        # 1. Status Banner Card
        stat_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                 border_width=1, border_color=CARD_BORDER)
        stat_card.pack(fill="x", pady=(0, 14))
        sc_inner = ctk.CTkFrame(stat_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=16, pady=14)

        top_s = ctk.CTkFrame(sc_inner, fg_color="transparent")
        top_s.pack(fill="x")
        ctk.CTkLabel(top_s, text="✓  Ready to clip", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=ACCENT_GREEN).pack(side="left")
        ctk.CTkLabel(sc_inner, text="BridgeClip runs locally on this computer. Whisper and LLM cover transcription and clip selection.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 10))

        pills_row = ctk.CTkFrame(sc_inner, fg_color="transparent")
        pills_row.pack(fill="x")
        pills_row.columnconfigure((0, 1, 2), weight=1)

        for col, (title, sub) in enumerate([
            ("● Local FreeLLMAPI", "Key saved"),
            ("● Core Tools", "ffmpeg, ffprobe, yt-dlp"),
            ("● Storage", "output_clips ready"),
        ]):
            p = ctk.CTkFrame(pills_row, fg_color="#12151d", corner_radius=8, border_width=1, border_color="#222736")
            p.grid(row=0, column=col, sticky="ew", padx=3)
            ctk.CTkLabel(p, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(p, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w", padx=10, pady=(0, 6))

        # 2. API Keys Card
        api_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                border_width=1, border_color=CARD_BORDER)
        api_card.pack(fill="x", pady=(0, 14))
        ac_inner = ctk.CTkFrame(api_card, fg_color="transparent")
        ac_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(ac_inner, text="🔑  API Configuration", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(ac_inner, text="OpenAI-compatible endpoint for Whisper transcription and clip picking.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(2, 12))

        ctk.CTkLabel(ac_inner, text="API Base URL:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED, anchor="w").pack(fill="x")
        self.api = ctk.CTkEntry(ac_inner, height=38, corner_radius=8, fg_color="#12151d", border_color="#222736")
        self.api.insert(0, load_settings().get("api_url") or DEFAULT_API)
        self.api.pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(ac_inner, text="API Key (FreeLLMAPI):", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED, anchor="w").pack(fill="x")
        self.api_key = ctk.CTkEntry(ac_inner, height=38, corner_radius=8, show="*",
                                    placeholder_text="freellmapi-...", fg_color="#12151d", border_color="#222736")
        if API_KEY:
            self.api_key.insert(0, API_KEY)
        self.api_key.pack(fill="x", pady=(2, 6))

        # 3. Tools Check & Install Card
        tools_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=CARD_BORDER)
        tools_card.pack(fill="x", pady=(0, 14))
        tc_inner = ctk.CTkFrame(tools_card, fg_color="transparent")
        tc_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(tc_inner, text="🛠️  Tools (ffmpeg, ffprobe, yt-dlp)", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")

        t_btns = ctk.CTkFrame(tc_inner, fg_color="transparent")
        t_btns.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(t_btns, text="Install Missing Tools", height=34, corner_radius=8,
                      fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.install_clicked).pack(side="left", padx=(0, 8))
        ctk.CTkButton(t_btns, text="Update yt-dlp", height=34, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self.update_ytdlp).pack(side="left", padx=8)
        ctk.CTkButton(t_btns, text="Check Tools", height=34, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self.check_tools).pack(side="left", padx=8)

        # 4. Storage & Cookies Card
        store_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=CARD_BORDER)
        store_card.pack(fill="x", pady=(0, 14))
        st_inner = ctk.CTkFrame(store_card, fg_color="transparent")
        st_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(st_inner, text="📁  Storage & Cookies", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")

        frow = ctk.CTkFrame(st_inner, fg_color="transparent")
        frow.pack(fill="x", pady=(8, 8))
        ctk.CTkLabel(frow, text="Downloads directory:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w")
        fin = ctk.CTkFrame(frow, fg_color="transparent")
        fin.pack(fill="x", pady=(2, 0))
        self.dl_dir = ctk.CTkEntry(fin, height=36, corner_radius=8, fg_color="#12151d", border_color="#222736")
        self.dl_dir.insert(0, VIDEOS_DIR)
        self.dl_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(fin, text="Browse", width=80, height=36, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, command=self.pick_dl_dir).pack(side="right")

        crow = ctk.CTkFrame(st_inner, fg_color="transparent")
        crow.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(crow, text="Cookies from browser (for age-restricted/bot checks):",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.cookies = ctk.CTkOptionMenu(
            crow, height=34, corner_radius=8, values=["None", "chrome", "edge", "firefox", "brave"],
            fg_color="#12151d", button_color="#242b3b")
        self.cookies.pack(fill="x", pady=(2, 0))

        # Save Button
        ctk.CTkButton(self.view_settings, text="💾 Save Preferences", height=42, corner_radius=8,
                      fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._save_preferences).pack(fill="x", pady=(6, 20))

    def _save_preferences(self):
        set_api_key(self.api_key.get())
        save_settings(api_url=self.api.get().strip() or DEFAULT_API, api_key=API_KEY)
        messagebox.showinfo(APP_TITLE, "Preferences saved successfully!")

    # ----------------------------------------------------------------------
    # View 4: Library
    # ----------------------------------------------------------------------
    def _build_library_view(self):
        self.view_library = ctk.CTkFrame(self.main_host, fg_color="transparent")
        self.view_library.grid_columnconfigure(0, weight=1)
        self.view_library.grid_rowconfigure(1, weight=1)

        top_l = ctk.CTkFrame(self.view_library, fg_color="transparent")
        top_l.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(top_l, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(top_l, text="Library", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(top_l, text="All clipped and captioned moments exported by BridgeClip.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x")

        self.lib_scroll = ctk.CTkScrollableFrame(self.view_library, fg_color=CARD_BG, corner_radius=12,
                                                border_width=1, border_color=CARD_BORDER)
        self.lib_scroll.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.lib_scroll.grid_columnconfigure(0, weight=1)

        bot_l = ctk.CTkFrame(self.view_library, fg_color="transparent")
        bot_l.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(bot_l, text="📁 Open Output Folder", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_out).pack(side="left")
        ctk.CTkButton(bot_l, text="🔄 Refresh Library", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self._refresh_library_list).pack(side="left", padx=8)

    def _refresh_library_list(self):
        for widget in self.lib_scroll.winfo_children():
            widget.destroy()

        mp4s = glob.glob(os.path.join(OUT_DIR, "*.mp4"))
        if not mp4s:
            ctk.CTkLabel(self.lib_scroll, text="No clips generated yet.\nGo to 'Create' to find and cut your first clips!",
                         font=ctk.CTkFont(size=14), text_color=TEXT_DIM).pack(pady=60)
            return

        mp4s.sort(key=os.path.getmtime, reverse=True)
        for path in mp4s:
            name = os.path.basename(path)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            card = ctk.CTkFrame(self.lib_scroll, fg_color="#12151d", corner_radius=8,
                                border_width=1, border_color="#222736")
            card.pack(fill="x", padx=10, pady=4)

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=10)

            ctk.CTkLabel(row, text="🎬", font=ctk.CTkFont(size=20)).pack(side="left", padx=(0, 10))
            t_box = ctk.CTkFrame(row, fg_color="transparent")
            t_box.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(t_box, text=name, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT_MAIN, anchor="w").pack(fill="x")
            ctk.CTkLabel(t_box, text="%.1f MB" % size_mb, font=ctk.CTkFont(size=11),
                         text_color=TEXT_DIM, anchor="w").pack(fill="x")

            ctk.CTkButton(row, text="Open Video", width=90, height=30, corner_radius=6,
                          fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=11, weight="bold"),
                          command=lambda p=path: self._open_file(p)).pack(side="right")

    def _open_file(self, filepath):
        try:
            if os.name == "nt":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", filepath])
            else:
                subprocess.Popen(["xdg-open", filepath])
        except Exception as e:
            self.log("Could not open file: %s" % e)

    # ----------------------------------------------------------------------
    # Status & Logging
    # ----------------------------------------------------------------------
    def log(self, msg):
        msg = str(msg)
        self.logq.put(msg)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
        except OSError:
            pass

    def set_status(self, text, color=None):
        self.logq.put(("status", text, color))

    def _drain(self):
        try:
            while True:
                item = self.logq.get_nowait()
                if isinstance(item, tuple):
                    _, text, color = item
                    self.jobs_status_lbl.configure(text=text, text_color=color or TEXT_MAIN)
                    self.sb_status.configure(text=" " + text[:22], text_color=color or TEXT_MUTED)
                    continue
                self.console.configure(state="normal")
                self.console.insert("end", item + "\n")
                self.console.see("end")
                self.console.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # ----------------------------------------------------------------------
    # Actions & Execution
    # ----------------------------------------------------------------------
    def pick_file(self):
        p = filedialog.askopenfilename(
            title="Select a video",
            filetypes=[("Video files", "*.mp4 *.webm *.mkv"), ("All files", "*.*")])
        if p:
            self.src.delete(0, "end")
            self.src.insert(0, p)
            self._on_src_changed()

    def pick_dl_dir(self):
        d = filedialog.askdirectory(title="Choose download folder")
        if d:
            self.dl_dir.delete(0, "end")
            self.dl_dir.insert(0, d)

    def _open_folder(self, folder):
        os.makedirs(folder, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self.log("Could not open folder: %s" % e)

    def open_out(self):
        self._open_folder(OUT_DIR)

    def open_videos(self):
        self._open_folder(self.dl_dir.get().strip() or VIDEOS_DIR)

    def _auto_offer(self):
        need = missing_tools()
        if need:
            self._offer_install(need)

    def install_clicked(self):
        need = missing_tools()
        if not need:
            messagebox.showinfo(APP_TITLE, "ffmpeg, ffprobe and yt-dlp are already installed.")
            return
        self._offer_install(need)

    def _offer_install(self, need):
        if self.installing or self.busy:
            return
        if os.name != "nt":
            messagebox.showerror(APP_TITLE, "Missing: %s\n\nInstall them with your package manager." % ", ".join(need))
            return
        if messagebox.askyesno(
                APP_TITLE,
                "BridgeClip needs these free tools: %s\n\nDownload and install them automatically now? (~150 MB)" % ", ".join(need)):
            self.installing = True
            self.progress.start()
            threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        ok = False
        try:
            self.set_status("Installing tools...", "#4da3ff")
            ok = install_tools(self.log, self.set_status)
        except Exception as e:
            self.log("INSTALL ERROR: %r" % (e,))
        finally:
            self.installing = False

            def done():
                self.progress.stop()
                self.progress.set(0)
            self.after(0, done)
            if ok:
                self.set_status("Tools installed - you're ready to go", "#3ddc84")
            else:
                self.set_status("Some tools are still missing - see Jobs console", "#ff6b6b")

    def check_tools(self):
        def work():
            self._set_view("Jobs")
            for tool in ("ffmpeg", "ffprobe", "yt-dlp"):
                path = shutil.which(tool)
                if not path:
                    self.log("[tools] %s: NOT FOUND" % tool)
                    continue
                ver = ""
                try:
                    flag = "--version" if tool == "yt-dlp" else "-version"
                    ver = run_capture([tool, flag]).stdout.splitlines()[0]
                except Exception:
                    pass
                self.log("[tools] %s: %s  %s" % (tool, path, ver))
        threading.Thread(target=work, daemon=True).start()

    def update_ytdlp(self):
        def work():
            self._set_view("Jobs")
            if not shutil.which("yt-dlp"):
                self.log("yt-dlp not found, nothing to update.")
                return
            self.log("Updating yt-dlp...")
            lines = []
            run_stream(["yt-dlp", "-U"], self.log, collect=lines)
            if any("pip" in l.lower() for l in lines):
                self.log("yt-dlp was installed with pip. Run:  pip install -U yt-dlp")
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.busy:
            return
        src = self.src.get().strip().strip('"')
        if not src:
            messagebox.showwarning(APP_TITLE, "Please paste a YouTube link or select a local video first.")
            self._set_step(0)
            return
        if not os.path.isfile(src) and not is_url(src):
            messagebox.showwarning(APP_TITLE, "That is not an existing file or a valid http(s) link.")
            self._set_step(0)
            return

        need = missing_tools()
        if not is_url(src):
            need = [t for t in need if t != "yt-dlp"]
        if need:
            self._offer_install(need)
            return

        len_map = {
            "10-30s": 25,
            "30-60s": 45,
            "1-2m": 75,
            "2-5m": 150,
            "5-10m": 300,
            "10-15m": 600,
            "15-30m": 900,
        }
        clip_len = len_map.get(self.clip_length_val, 45)

        if self.ai_decide_switch.get():
            max_clips = 5
        else:
            try:
                max_clips = max(1, int(self.max_clips_entry.get()))
            except ValueError:
                max_clips = 3

        mode_map = {
            "Quality": "Smart Mix (AI + hype + replays)",
            "Economy": "Highest Playtime (Most Replayed)",
            "Direct": "Loudest Moments (no AI)",
        }
        mode = mode_map.get(self.clipping_mode_val, "Smart Mix (AI + hype + replays)")

        framing_map = {
            "Smart": "Smart crop (follow action)",
            "Full frame": "Center crop",
            "Classic": "Blurred background fit",
        }
        framing = framing_map.get(self.framing_val, "Smart crop (follow action)")

        is_vert = self.format_val.startswith("Vertical")

        size_map_vert = {"S": 32, "M": 44, "L": 56, "XL": 70}
        size_map_horiz = {"S": 20, "M": 26, "L": 34, "XL": 44}
        cap_size_code = self.cap_size.get() or "M"
        caption_size = size_map_vert.get(cap_size_code, 44) if is_vert else size_map_horiz.get(cap_size_code, 26)

        pacing_map = {
            "Punchy (1-2 words)": 2,
            "Fast (2-3 words)": 3,
            "Balanced (3-4 words)": 4,
            "Sentence (5-7)": 6,
        }
        words_per_chunk = pacing_map.get(self.cap_pacing.get(), 3)
        lang, prompt = CAPTION_LANGS.get(self.cap_lang.get(), (None, None))

        opts = {
            "captions": bool(self.captions_switch.get()),
            "cap_style": self.caption_style_val,
            "cap_font": CAPTION_STYLES.get(self.caption_style_val, {}).get("font", "Impact"),
            "cap_pos": self.cap_pos.get(),
            "cap_words": words_per_chunk,
            "cap_upper": CAPTION_STYLES.get(self.caption_style_val, {}).get("all_caps", True),
            "caption_size": caption_size,
            "cap_lang": lang,
            "cap_prompt": prompt,
            "fade": True,
            "zoom": False,
            "normalize": True,
            "speed": self.speed_val,
            "vo_mode": "Off",
            "mode": mode,
            "cookies": self.cookies.get(),
            "dl_quality": self.dl_quality.get(),
            "dl_dir": self.dl_dir.get().strip() or VIDEOS_DIR,
            "dl_only": False,
            "snap": bool(self.snap.get()),
            "framing": framing,
            "quality": "Balanced",
        }

        set_api_key(self.api_key.get())
        save_settings(api_url=self.api.get().strip() or DEFAULT_API, api_key=API_KEY)
        args = (src, max_clips, clip_len, is_vert, self.api.get().strip() or DEFAULT_API, opts)

        self.busy = True
        self.btn_next.configure(state="disabled")
        self.progress.start()
        self.set_status("Starting job...", "#4da3ff")
        self._set_view("Jobs")

        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _finish(self):
        self.busy = False

        def reset():
            self.progress.stop()
            self.progress.set(0)
            self.btn_next.configure(state="normal")
            self._refresh_library_list()
        self.after(0, reset)

    def _worker(self, src, max_clips, clip_len, vertical, api_url, opts):
        log = self.log
        mode = opts.get("mode", "Smart Mix (AI + hype + replays)")
        ok = False
        try:
            # 1. input
            if os.path.isfile(src):
                video = src
                log("Using local file: " + video)
            else:
                self.set_status("Downloading video...", "#4da3ff")
                video = download_video(
                    src, log,
                    cookies_browser=opts.get("cookies"),
                    dl_dir=opts.get("dl_dir"),
                    quality=opts.get("dl_quality")
                )
                if not video:
                    return
                log("Downloaded: " + video)

            info = None
            info_path = os.path.splitext(video)[0] + ".info.json"
            if os.path.isfile(info_path):
                try:
                    with open(info_path, encoding="utf-8") as f:
                        info = json.load(f)
                except Exception as e:
                    log("Could not read info.json: %s" % e)

            duration = get_duration(video, info)
            log("Duration: %s" % fmt_time(duration))
            log("Mode: " + mode)

            clips = []
            a_peaks, h_peaks = [], heatmap_peaks(info)

            # 2a. highest playtime (YouTube "Most replayed")
            if "Highest Playtime" in mode:
                self.set_status("Reading replay heatmap...", "#4da3ff")
                clips = replayed_clips(info, duration, clip_len, max_clips)
                if clips:
                    log("Picked %d highest-playtime window(s) from the replay heatmap." % len(clips))
                else:
                    log("No YouTube replay heatmap for this video. Using loudest moments instead.")
                    mode = "Loudest Moments (no AI)"

            # 2b. loudest moments / smart mix
            if not clips:
                self.set_status("Scanning audio for hype...", "#4da3ff")
                a_peaks = audio_peaks(video, duration, log)
                log("Heatmap peaks: %d" % len(h_peaks) if h_peaks else "No YouTube heatmap available.")

            if not clips and "Smart Mix" in mode:
                transcript = load_transcript(video)
                log("Transcript loaded (%d chars)." % len(transcript) if transcript else "No subtitles found.")
                self.set_status("Asking AI for the best moments...", "#4da3ff")
                try:
                    base = api_base(api_url)
                    model = pick_model(base, log)
                    raw = ask_llm(base, model, duration, clip_len, max_clips,
                                  a_peaks, h_peaks, transcript, log)
                    clips = clean_clips(raw, duration, clip_len, max_clips)
                except (urllib.error.URLError, OSError, ValueError, KeyError,
                        RuntimeError, json.JSONDecodeError) as e:
                    log("LLM step failed: %s" % e)

            if not clips:
                log("Selecting loudest / hottest moments directly.")
                clips = fallback_clips(a_peaks, h_peaks, duration, clip_len, max_clips)
            if not clips:
                log("No clips could be determined.")
                return

            if opts.get("snap"):
                self.set_status("Finding clean cut points...", "#4da3ff")
                mids = detect_silences(video, log)
                clips = snap_clips(clips, mids, duration, clip_len) or clips
            log("Selected clips:\n" + json.dumps(clips, indent=2))

            # 3. cut
            self.set_status("Cutting clips...", "#4da3ff")
            cut_clips(video, clips, vertical, log, opts, api_base(api_url))
            log("Done! Clips are in: " + OUT_DIR)
            ok = True
        except Exception as e:
            log("UNEXPECTED ERROR: %r" % e)
        finally:
            if ok:
                self.set_status("Done - clips are in output_clips", "#3ddc84")
            else:
                self.set_status("Stopped - see Jobs console for details", "#ff6b6b")
            self._finish()


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            with open(os.path.join(BASE, "hypeclipper_crash.log"), "w", encoding="utf-8") as f:
                f.write(tb)
        except OSError:
            pass
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror(APP_TITLE, "BridgeClip crashed:\n\n" + tb[-1500:])
        except Exception:
            pass
