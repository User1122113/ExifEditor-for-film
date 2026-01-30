from __future__ import annotations

# 실행 방법:
#   python -m venv .venv
#   (Windows) .venv\Scripts\activate
#   (macOS/Linux) source .venv/bin/activate
#   pip install -r requirements.txt
#   python film_exif_gui.py

import json
import os
import re
import multiprocessing as mp
import queue
from fractions import Fraction
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import floor
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk  # noqa: F401
import piexif
import piexif.helper
import webview

EXIF_DT_FMT = "%Y:%m:%d %H:%M:%S"
# 기본 폰트 경로: fonts 폴더에 E1234.ttf를 배치하세요.
DEFAULT_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "E1234.ttf")
DEFAULT_BLUR_STRENGTH = 0.15
DEFAULT_FONT_RATIO = 0.03
DEFAULT_OFFSET_X = -20
DEFAULT_OFFSET_Y = -20

_DEC_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


class _Tooltip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self._tip_window: tk.Toplevel | None = None
        self.widget.bind("<Enter>", self._show)
        self.widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self._tip_window is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tip,
            text=self.text,
            justify="left",
            background="#ffffe0",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=4,
        )
        label.pack()
        self._tip_window = tip

    def _hide(self, _event=None):
        if self._tip_window is None:
            return
        self._tip_window.destroy()
        self._tip_window = None

# --- Map Picker (pywebview + Leaflet) ---
MAP_PICKER_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    html, body { height: 100%; margin: 0; }
    #map { height: 100%; }
    .panel {
      position: absolute; right: 16px; bottom: 16px; z-index: 9999;
      background: rgba(20,20,20,0.85); color: #fff; padding: 10px 12px;
      border-radius: 10px; font-family: sans-serif; min-width: 260px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    }
    .row { display: flex; justify-content: space-between; gap: 8px; align-items: center; }
    button {
      width: 100%; margin-top: 8px; padding: 10px 12px;
      border: 0; border-radius: 10px; cursor: pointer;
      font-weight: 700;
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .coord { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <div class="row">
      <div>선택 좌표</div>
      <div class="coord" id="coordText">아직 선택 안됨</div>
    </div>
    <button id="saveBtn" disabled>위치 저장</button>
  </div>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const initLat = __INIT_LAT__;
    const initLon = __INIT_LON__;

    const map = L.map('map').setView([initLat, initLon], 14);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    let marker = null;
    let selected = null;

    function setSelected(lat, lon) {
      selected = { lat, lon };
      document.getElementById('coordText').textContent =
        lat.toFixed(6) + ', ' + lon.toFixed(6);
      document.getElementById('saveBtn').disabled = false;
      if (marker) marker.remove();
      marker = L.marker([lat, lon]).addTo(map);
    }

    map.on('click', (e) => {
      setSelected(e.latlng.lat, e.latlng.lng);
    });

    document.getElementById('saveBtn').addEventListener('click', async () => {
      if (!selected) return;
      try {
        await window.pywebview.api.save_location(selected.lat, selected.lon);
      } catch (err) {
        alert('저장 실패: ' + err);
      }
    });
  </script>
</body>
</html>
"""


@dataclass
class FileItem:
    path: str
    assigned_date: date | None = None
    location: str = ""
    lat_dd: float | None = None
    lon_dd: float | None = None
    lat_deg: int | None = None
    lat_min: int | None = None
    lat_sec: float | None = None
    lat_ref: str = "N"
    lon_deg: int | None = None
    lon_min: int | None = None
    lon_sec: float | None = None
    lon_ref: str = "E"


def parse_date_yyyy_mm_dd(s: str) -> date:
    s = s.strip()
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_time_hh_mm(s: str) -> time:
    s = s.strip()
    return datetime.strptime(s, "%H:%M").time()


def parse_decimal_latlon(text: str) -> tuple[float, float]:
    s = (text or "").strip()
    nums = _DEC_RE.findall(s)
    if len(nums) < 2:
        raise ValueError("좌표에서 위도/경도 숫자 2개를 찾지 못했습니다.")
    lat = float(nums[0])
    lon = float(nums[1])
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("위도 범위 오류(-90~90)")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("경도 범위 오류(-180~180)")
    return lat, lon


def decimal_to_dms_abs(x: float) -> tuple[int, int, float]:
    ax = abs(x)
    deg = int(floor(ax))
    min_float = (ax - deg) * 60.0
    minute = int(floor(min_float))
    sec = (min_float - minute) * 60.0
    return deg, minute, sec


def dms_to_rational(
    deg: int,
    minute: int,
    sec: float,
    scale: int = 10**7,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    if sec >= 60.0:
        carry = int(sec // 60.0)
        sec -= 60.0 * carry
        minute += carry
    if minute >= 60:
        carry = minute // 60
        minute %= 60
        deg += carry
    sec_num = int(round(sec * scale))
    return ((deg, 1), (minute, 1), (sec_num, scale))


def lat_ref(lat: float) -> str:
    return "N" if lat >= 0 else "S"


def lon_ref(lon: float) -> str:
    return "E" if lon >= 0 else "W"


def format_dms(deg: int, minute: int, sec: float, ref: str) -> str:
    return f"{deg}° {minute}′ {sec:.6f}″ {ref}"


class MapPickerAPI:
    def __init__(self, queue: mp.Queue):
        self.queue = queue

    def save_location(self, lat: float, lon: float) -> None:
        lat = float(lat)
        lon = float(lon)
        if not (-90.0 <= lat <= 90.0):
            raise ValueError("위도 범위 오류(-90~90)")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError("경도 범위 오류(-180~180)")
        self.queue.put((lat, lon))
        try:
            if webview.windows:
                webview.windows[0].destroy()
        except Exception:
            pass


def run_map_picker(queue: mp.Queue, initial_lat: float | None = None, initial_lon: float | None = None) -> None:
    lat = 37.5665 if initial_lat is None else float(initial_lat)
    lon = 126.9780 if initial_lon is None else float(initial_lon)
    html = MAP_PICKER_HTML.replace("__INIT_LAT__", str(lat)).replace("__INIT_LON__", str(lon))
    api = MapPickerAPI(queue)
    webview.create_window("지도에서 위치 선택", html=html, js_api=api, width=980, height=700)
    webview.start(debug=False)


def is_jpeg_path(p: str) -> bool:
    ext = os.path.splitext(p)[1].lower()
    return ext in (".jpg", ".jpeg")


def safe_out_path(out_dir: str, basename: str) -> str:
    root, ext = os.path.splitext(basename)
    candidate = os.path.join(out_dir, basename)
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        candidate = os.path.join(out_dir, f"{root}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


def load_existing_exif_bytes_from_file(src_path: str) -> bytes | None:
    try:
        with open(src_path, "rb") as handle:
            data = handle.read()
        exif_dict = piexif.load(data)
        return piexif.dump(exif_dict)
    except Exception:
        return None


def build_exif_bytes(
    existing_exif: bytes | None,
    dt: datetime | None,
    film_info: str,
    camera_model: str,
    lens: str,
    location: str,
    gps_lat: tuple[int, int, float, str] | None,
    gps_lon: tuple[int, int, float, str] | None,
    lat_dd: float | None,
    lon_dd: float | None,
) -> bytes:
    if existing_exif:
        exif_dict = piexif.load(existing_exif)
    else:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    if dt is not None:
        dt_str = dt.strftime(EXIF_DT_FMT).encode("ascii")
        exif_dict["0th"][piexif.ImageIFD.DateTime] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str

    film_info = (film_info or "").strip()
    if film_info:
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = film_info.encode("utf-8", errors="replace")
        exif_dict["0th"][piexif.ImageIFD.XPKeywords] = film_info.encode("utf-16le") + b"\x00\x00"
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(
            film_info,
            encoding="unicode",
        )

    camera_model = (camera_model or "").strip()
    if camera_model:
        exif_dict["0th"][piexif.ImageIFD.Model] = camera_model.encode("utf-8", errors="replace")

    lens = (lens or "").strip()
    if lens:
        exif_dict["Exif"][piexif.ExifIFD.LensModel] = lens.encode("utf-8", errors="replace")

    location = (location or "").strip()
    if lat_dd is not None and lon_dd is not None:
        lat_deg, lat_min, lat_sec = decimal_to_dms_abs(lat_dd)
        lon_deg, lon_min, lon_sec = decimal_to_dms_abs(lon_dd)
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref(lat_dd).encode("ascii")
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = dms_to_rational(lat_deg, lat_min, lat_sec)
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref(lon_dd).encode("ascii")
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = dms_to_rational(lon_deg, lon_min, lon_sec)
    elif location:
        exif_dict["GPS"][piexif.GPSIFD.GPSAreaInformation] = location.encode("utf-8", errors="replace")

    return piexif.dump(exif_dict)


def _to_rational(value: float, max_denominator: int = 100000000) -> tuple[int, int]:
    frac = Fraction(value).limit_denominator(max_denominator)
    return frac.numerator, frac.denominator


def resolve_font(font_path: str | None, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path:
        try:
            return ImageFont.truetype(font_path, font_size)
        except OSError:
            pass
    else:
        try:
            return ImageFont.truetype(DEFAULT_FONT_PATH, font_size)
        except OSError:
            pass

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Menlo.ttc",
        "/Library/Fonts/Andale Mono.ttf",
        "C:\\Windows\\Fonts\\consola.ttf",
        "C:\\Windows\\Fonts\\consolab.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, font_size)
            except OSError:
                continue
    return ImageFont.load_default()


def _render_stamp_with_settings(
    img: Image.Image,
    text: str,
    font_path: str | None,
    blur_strength: float,
    font_ratio: float,
    offset_x: int,
    offset_y: int,
) -> Image.Image:
    width, height = img.size
    base_length = min(width, height)
    margin = max(int(base_length * 0.02), 12)
    font_size = max(int(base_length * font_ratio), 18)
    font = resolve_font(font_path, font_size)

    temp_draw = ImageDraw.Draw(Image.new("L", (1, 1), 0))
    bbox = temp_draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = width - margin - text_w + offset_x
    y = height - margin - text_h + offset_y

    blur_pad = max(int(font_size * 0.3), 6)
    left = max(x - blur_pad, 0)
    top = max(y - blur_pad, 0)
    right = min(x + text_w + blur_pad, width)
    bottom = min(y + text_h + blur_pad, height)

    patch_w = max(right - left, 1)
    patch_h = max(bottom - top, 1)

    mask = Image.new("L", (patch_w, patch_h), 0)
    draw = ImageDraw.Draw(mask)
    draw.text((x - left, y - top), text, fill=255, font=font)

    main_alpha = mask
    glow_alpha = mask.filter(
        ImageFilter.GaussianBlur(radius=max(font_size * 0.18 * blur_strength, 1))
    )

    base = img.convert("RGBA")
    base_patch = base.crop((left, top, right, bottom))
    blurred_patch = base_patch.filter(
        ImageFilter.GaussianBlur(radius=max(font_size * 0.12 * blur_strength, 1))
    )

    softened_patch = Image.composite(blurred_patch, base_patch, glow_alpha)

    text_layer = Image.new("RGBA", (patch_w, patch_h), (255, 110, 40, 0))
    text_layer.putalpha(main_alpha)

    combined_patch = ImageChops.screen(softened_patch, text_layer)
    final_patch = Image.composite(combined_patch, base_patch, glow_alpha)

    base.paste(final_patch, (left, top))
    return base.convert(img.mode)


def overlay_dateback_stamp(img: Image.Image, text: str, font_path: str | None) -> Image.Image:
    return _render_stamp_with_settings(
        img,
        text,
        font_path,
        DEFAULT_BLUR_STRENGTH,
        DEFAULT_FONT_RATIO,
        DEFAULT_OFFSET_X,
        DEFAULT_OFFSET_Y,
    )


def apply_exif_orientation(img: Image.Image) -> tuple[Image.Image, bool]:
    try:
        exif = img.getexif()
    except (AttributeError, ValueError):
        return img, False
    orientation = exif.get(274)
    if orientation in (3, 6, 8):
        return ImageOps.exif_transpose(img), True
    return img, False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Film EXIF Writer")
        self.geometry("1000x680")
        self.minsize(1000, 680)

        self.items: list[FileItem] = []
        self.out_dir: str | None = None

        self.var_date = tk.StringVar(value="")
        self.var_time = tk.StringVar(value="12:00")
        self.var_film = tk.StringVar(value="")
        self.var_lat_dd = tk.StringVar(value="")
        self.var_lon_dd = tk.StringVar(value="")
        self.var_gps_preview = tk.StringVar(value="")
        self.var_lat_deg = tk.StringVar(value="")
        self.var_lat_min = tk.StringVar(value="")
        self.var_lat_sec = tk.StringVar(value="")
        self.var_lat_ref = tk.StringVar(value="N")
        self.var_lon_deg = tk.StringVar(value="")
        self.var_lon_min = tk.StringVar(value="")
        self.var_lon_sec = tk.StringVar(value="")
        self.var_lon_ref = tk.StringVar(value="E")
        self.var_camera_model = tk.StringVar(value="")
        self.var_lens = tk.StringVar(value="")
        self.var_stamp = tk.BooleanVar(value=False)
        self.var_stamp_fmt = tk.StringVar(value="'YY MM DD")
        self.var_blur_strength = tk.DoubleVar(value=0.15)
        self.var_font_ratio = tk.DoubleVar(value=0.03)
        self.var_offset_x = tk.IntVar(value=-20)
        self.var_offset_y = tk.IntVar(value=-20)

        self.font_path: str | None = None
        self.var_font_label = tk.StringVar(value="E1234.ttf")
        self._map_queue: mp.Queue | None = None
        self._map_proc: mp.Process | None = None

        self._build_ui()
        self._load_default_camera_profile()

    def _build_ui(self):
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left panel
        left = ttk.Frame(paned, width=330)
        paned.add(left, weight=1)

        self.listbox = tk.Listbox(left, selectmode=tk.EXTENDED, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(btns, text="JPG 추가", command=self._add_files).pack(side=tk.LEFT)
        ttk.Button(btns, text="선택 제거", command=self._remove_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="모두 제거", command=self._remove_all).pack(side=tk.LEFT, padx=(8, 0))

        # Right panel
        right = ttk.Frame(paned, width=840)
        paned.add(right, weight=2)
        self.after_idle(lambda: paned.sashpos(0, 330))

        form = ttk.Frame(right)
        form.pack(fill=tk.X)

        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=0)

        ttk.Label(form, text="선택 항목 날짜 (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.var_date, width=20).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(form, text="기준 시작 시간 (HH:MM)").grid(row=1, column=0, sticky="w", pady=(10, 0))
        time_apply = ttk.Frame(form)
        time_apply.grid(row=1, column=1, columnspan=2, sticky="w", padx=8, pady=(10, 0))
        ttk.Entry(time_apply, textvariable=self.var_time, width=20).pack(side=tk.LEFT)

        ttk.Label(form, text="위치 좌표").grid(row=3, column=0, sticky="w", pady=(10, 0))
        decimal_frame = ttk.Frame(form)
        decimal_frame.grid(row=3, column=1, sticky="w", padx=8, pady=(10, 0))
        ttk.Label(decimal_frame, text="위도").pack(side=tk.LEFT)
        ttk.Entry(decimal_frame, width=12, textvariable=self.var_lat_dd).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(decimal_frame, text="경도").pack(side=tk.LEFT)
        ttk.Entry(decimal_frame, width=12, textvariable=self.var_lon_dd).pack(side=tk.LEFT, padx=(4, 10))
        btn_paste = ttk.Button(decimal_frame, text="클립보드 붙여넣기", command=self._paste_decimal_coords)
        btn_paste.pack(side=tk.LEFT)
        _Tooltip(btn_paste, "구글지도 원하는 위치 우클릭 \n- 이 위치 공유 - 좌표값 복사 후 이 버튼 클릭")
        ttk.Button(decimal_frame, text="지도에서 불러오기", command=self._open_map_picker).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        gps_apply_row = ttk.Frame(form)
        gps_apply_row.grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="w",
            padx=8,
            pady=(6, 0),
        )
        ttk.Label(gps_apply_row, textvariable=self.var_gps_preview).pack(side=tk.LEFT)

        apply_row = ttk.Frame(form)
        apply_row.grid(row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 0))
        apply_font = tkfont.nametofont("TkDefaultFont").copy()
        apply_font.configure(size=int(apply_font.cget("size") * 1.5))
        ttk.Style().configure("Apply.TButton", font=apply_font)
        ttk.Button(
            apply_row,
            text="선택된 사진에 날짜/위치정보 적용",
            command=self._apply_selected,
            style="Apply.TButton",
        ).pack(
            fill=tk.X,
            ipadx=12,
            ipady=8,
        )

        cam_prof = ttk.Frame(right)
        cam_prof.pack(fill=tk.X, pady=(12, 0))
        profile_label_width = 10
        ttk.Label(cam_prof, text="카메라 기종", width=profile_label_width, anchor="w").pack(side=tk.LEFT)
        ttk.Entry(cam_prof, textvariable=self.var_camera_model, width=20).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(cam_prof, text="렌즈").pack(side=tk.LEFT)
        ttk.Entry(cam_prof, textvariable=self.var_lens, width=20).pack(side=tk.LEFT, padx=(6, 12))

        film_row = ttk.Frame(right)
        film_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(film_row, text="필름 정보", width=profile_label_width, anchor="w").pack(side=tk.LEFT)
        ttk.Entry(film_row, textvariable=self.var_film, width=20).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Button(film_row, text="내보내기", command=self._export_camera_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(film_row, text="불러오기", command=self._import_camera_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        self.stamp_row = ttk.Frame(right)
        self.stamp_row.pack(fill=tk.X, pady=(14, 0))
        ttk.Checkbutton(
            self.stamp_row,
            text="우측 하단 날짜 스탬프(선택 시 출력폴더 선택 필수)",
            variable=self.var_stamp,
            command=self._toggle_stamp_options,
        ).pack(side=tk.LEFT)

        self.stamp_fmt_row = ttk.Frame(right)
        self.stamp_fmt_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(self.stamp_fmt_row, text="스탬프 날짜 형식").pack(side=tk.LEFT)
        ttk.Combobox(
            self.stamp_fmt_row,
            textvariable=self.var_stamp_fmt,
            width=12,
            state="readonly",
            values=["'YY MM DD", "YYYY MM DD"],
        ).pack(side=tk.LEFT, padx=6)

        self.stamp_opt_container = ttk.Frame(right)

        stamp_opts = ttk.Frame(self.stamp_opt_container)
        stamp_opts.pack(fill=tk.X)
        ttk.Label(stamp_opts, text="Blur 강도").grid(row=0, column=0, sticky="w")
        ttk.Scale(
            stamp_opts,
            from_=0.1,
            to=1.0,
            orient=tk.HORIZONTAL,
            variable=self.var_blur_strength,
        ).grid(row=0, column=1, sticky="we", padx=8)
        ttk.Label(stamp_opts, textvariable=self.var_blur_strength, width=6).grid(
            row=0,
            column=2,
            sticky="e",
        )

        ttk.Label(stamp_opts, text="폰트 크기 비율").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            stamp_opts,
            from_=0.02,
            to=0.08,
            orient=tk.HORIZONTAL,
            variable=self.var_font_ratio,
        ).grid(row=1, column=1, sticky="we", padx=8, pady=(8, 0))
        ttk.Label(stamp_opts, textvariable=self.var_font_ratio, width=6).grid(
            row=1,
            column=2,
            sticky="e",
            pady=(8, 0),
        )

        offset_row = ttk.Frame(self.stamp_opt_container)
        offset_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(offset_row, text="가로 오프셋").pack(side=tk.LEFT)
        tk.Spinbox(
            offset_row,
            from_=-50,
            to=50,
            textvariable=self.var_offset_x,
            width=6,
        ).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(offset_row, text="세로 오프셋").pack(side=tk.LEFT)
        tk.Spinbox(
            offset_row,
            from_=-50,
            to=50,
            textvariable=self.var_offset_y,
            width=6,
        ).pack(side=tk.LEFT, padx=6)

        stamp_opts.columnconfigure(1, weight=1)

        font_row = ttk.Frame(self.stamp_opt_container)
        font_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(font_row, text="폰트 파일 선택", command=self._choose_font).pack(side=tk.LEFT)
        try:
            font_label_font = tkfont.Font(file=DEFAULT_FONT_PATH, size=12)
        except Exception:
            font_label_font = None
        ttk.Label(font_row, textvariable=self.var_font_label, font=font_label_font).pack(side=tk.LEFT, padx=10)

        self.run_row = ttk.Frame(right)
        self.run_row.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(self.run_row, text="미리보기", command=self._preview).pack(side=tk.LEFT)
        ttk.Button(self.run_row, text="출력 폴더 선택", command=self._choose_out_dir).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.lbl_out = ttk.Label(self.run_row, text="(미지정)")
        self.lbl_out.pack(side=tk.LEFT, padx=(8, 0))

        self.run_apply_row = ttk.Frame(right)
        self.run_apply_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(
            self.run_apply_row,
            text="EXIF 기록 및 저장",
            command=self._run,
            style="Apply.TButton",
        ).pack(
            fill=tk.X,
            ipadx=12,
            ipady=8,
        )

        self._toggle_stamp_options()

        self.progress = ttk.Progressbar(right, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 0))
        self.lbl_status = ttk.Label(right, text="")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

    def _format_item_label(self, item: FileItem) -> str:
        filename = os.path.basename(item.path)
        has_date = item.assigned_date is not None
        has_coords = item.lat_dd is not None and item.lon_dd is not None
        if has_date and has_coords:
            tag_text = f"{item.assigned_date.strftime('%Y-%m-%d')}, 좌표 적용됨"
        elif has_date:
            tag_text = item.assigned_date.strftime("%Y-%m-%d")
        elif has_coords:
            tag_text = "좌표 적용됨"
        else:
            tag_text = "미지정"
        location_text = f" / {item.location}" if item.location else ""
        return f"{filename}   [{tag_text}]{location_text}"

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for item in self.items:
            self.listbox.insert(tk.END, self._format_item_label(item))

    def _add_files(self):
        file_paths = filedialog.askopenfilenames(
            title="JPG 파일 선택",
            filetypes=[("JPG Images", "*.jpg *.jpeg"), ("All files", "*.*")],
        )
        if not file_paths:
            return
        existing = {item.path for item in self.items}
        for path in file_paths:
            if path not in existing:
                self.items.append(FileItem(path=path))
                existing.add(path)
        self._refresh_list()

    def _remove_selected(self):
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            return
        for index in sorted(selected_indices, reverse=True):
            del self.items[index]
        self._refresh_list()
        self.var_date.set("")

    def _remove_all(self):
        if not self.items:
            return
        self.items.clear()
        self._refresh_list()
        self.var_date.set("")
        messagebox.showinfo("안내", "모든 파일이 목록에서 제거되었습니다.")

    def _on_select(self):
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            return
        selected_dates = []
        selected_decimal = []
        for index in selected_indices:
            selected_dates.append(self.items[index].assigned_date)
            selected_decimal.append((self.items[index].lat_dd, self.items[index].lon_dd))
        first = selected_dates[0]
        if all(date_value == first for date_value in selected_dates) and first is not None:
            self.var_date.set(first.strftime("%Y-%m-%d"))
        decimal_first = selected_decimal[0]
        if all(decimal_value == decimal_first for decimal_value in selected_decimal):
            if decimal_first[0] is not None and decimal_first[1] is not None:
                self._set_decimal_fields(decimal_first[0], decimal_first[1])

    def _apply_selected(self):
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            messagebox.showwarning("안내", "왼쪽 목록에서 파일을 선택하세요.")
            return

        date_text = self.var_date.get().strip()
        new_date = None
        if date_text:
            try:
                new_date = parse_date_yyyy_mm_dd(date_text)
            except ValueError:
                messagebox.showerror("오류", "날짜 형식이 올바르지 않습니다. 예: 2020-01-02")
                return

        lat_text = self.var_lat_dd.get().strip()
        lon_text = self.var_lon_dd.get().strip()
        lat_dd = None
        lon_dd = None
        if lat_text or lon_text:
            if not (lat_text and lon_text):
                messagebox.showerror("오류", "좌표를 적용하려면 위도/경도를 모두 입력해야 합니다.")
                return
            try:
                lat_dd = float(lat_text)
                lon_dd = float(lon_text)
            except ValueError:
                messagebox.showerror(
                    "오류",
                    "좌표는 소수(float) 형태로 입력해야 합니다. 예: 37.206935, 127.096444",
                )
                return
            if not (-90.0 <= lat_dd <= 90.0):
                messagebox.showerror("오류", "위도 범위 오류(-90~90)")
                return
            if not (-180.0 <= lon_dd <= 180.0):
                messagebox.showerror("오류", "경도 범위 오류(-180~180)")
                return

        if new_date is None and lat_dd is None:
            messagebox.showwarning(
                "안내",
                "적용할 날짜 또는 좌표를 입력하세요. (비어있음은 적용되지 않습니다)",
            )
            return

        if new_date is not None:
            for index in selected_indices:
                self.items[index].assigned_date = new_date

        if lat_dd is not None and lon_dd is not None:
            lat_deg, lat_min, lat_sec = decimal_to_dms_abs(lat_dd)
            lon_deg, lon_min, lon_sec = decimal_to_dms_abs(lon_dd)
            lat_ref_value = lat_ref(lat_dd)
            lon_ref_value = lon_ref(lon_dd)
            self._update_gps_preview(lat_dd, lon_dd)
            for index in selected_indices:
                item = self.items[index]
                item.lat_dd = lat_dd
                item.lon_dd = lon_dd
                item.lat_deg = lat_deg
                item.lat_min = lat_min
                item.lat_sec = lat_sec
                item.lat_ref = lat_ref_value
                item.lon_deg = lon_deg
                item.lon_min = lon_min
                item.lon_sec = lon_sec
                item.lon_ref = lon_ref_value

        self._refresh_list()
        self.listbox.selection_clear(0, tk.END)
        for index in selected_indices:
            self.listbox.select_set(index)
        if selected_indices:
            self.listbox.activate(selected_indices[0])
            self.listbox.see(selected_indices[0])

    def _set_decimal_fields(self, lat_dd: float, lon_dd: float) -> None:
        self.var_lat_dd.set(str(lat_dd))
        self.var_lon_dd.set(str(lon_dd))
        self._update_gps_preview(lat_dd, lon_dd)

    def _parse_decimal_fields(self) -> tuple[float, float]:
        lat_text = self.var_lat_dd.get().strip()
        lon_text = self.var_lon_dd.get().strip()
        if not lat_text or not lon_text:
            raise ValueError("소수점 좌표가 비어 있습니다.")
        lat_value = float(lat_text)
        lon_value = float(lon_text)
        if not (-90.0 <= lat_value <= 90.0):
            raise ValueError("위도 범위 오류(-90~90)")
        if not (-180.0 <= lon_value <= 180.0):
            raise ValueError("경도 범위 오류(-180~180)")
        return lat_value, lon_value

    def _decimal_filled(self) -> bool:
        return bool(self.var_lat_dd.get().strip()) and bool(self.var_lon_dd.get().strip())

    def _get_gps_input_source(self) -> str:
        return "decimal" if self._decimal_filled() else "none"

    def _update_gps_preview(self, lat_dd: float, lon_dd: float) -> None:
        lat_deg, lat_min, lat_sec = decimal_to_dms_abs(lat_dd)
        lon_deg, lon_min, lon_sec = decimal_to_dms_abs(lon_dd)
        preview = (
            f"위도: {format_dms(lat_deg, lat_min, lat_sec, lat_ref(lat_dd))} / "
            f"경도: {format_dms(lon_deg, lon_min, lon_sec, lon_ref(lon_dd))}"
        )
        self.var_gps_preview.set(preview)

    def _paste_decimal_coords(self):
        try:
            txt = self.clipboard_get()
            lat_value, lon_value = parse_decimal_latlon(txt)
            self.var_lat_dd.set(str(lat_value))
            self.var_lon_dd.set(str(lon_value))
            self._update_gps_preview(lat_value, lon_value)
        except Exception as exc:
            messagebox.showerror("오류", f"클립보드 좌표 파싱 실패: {exc}")

    def _open_map_picker(self):
        if self._map_proc is not None and self._map_proc.is_alive():
            messagebox.showwarning("안내", "지도 창이 이미 열려 있습니다.")
            return
        init_lat = None
        init_lon = None
        try:
            if self.var_lat_dd.get().strip() and self.var_lon_dd.get().strip():
                init_lat = float(self.var_lat_dd.get().strip())
                init_lon = float(self.var_lon_dd.get().strip())
                if not (-90.0 <= init_lat <= 90.0):
                    raise ValueError
                if not (-180.0 <= init_lon <= 180.0):
                    raise ValueError
        except Exception:
            init_lat = None
            init_lon = None
        ctx = mp.get_context("spawn")
        self._map_queue = ctx.Queue()
        self._map_proc = ctx.Process(
            target=run_map_picker,
            args=(self._map_queue, init_lat, init_lon),
            daemon=True,
        )
        self._map_proc.start()
        self.after(200, self._poll_map_picker_queue)

    def _poll_map_picker_queue(self):
        if self._map_queue is None or self._map_proc is None:
            return
        try:
            lat_value, lon_value = self._map_queue.get_nowait()
            self.var_lat_dd.set(f"{lat_value:.6f}")
            self.var_lon_dd.set(f"{lon_value:.6f}")
            self._update_gps_preview(lat_value, lon_value)
            try:
                if self._map_proc.is_alive():
                    self._map_proc.join(timeout=0.2)
            except Exception:
                pass
            self._map_queue = None
            self._map_proc = None
            return
        except queue.Empty:
            pass
        if not self._map_proc.is_alive():
            self._map_queue = None
            self._map_proc = None
            return
        self.after(200, self._poll_map_picker_queue)


    def _export_camera_profile(self):
        profile = {
            "camera_model": self.var_camera_model.get().strip(),
            "lens": self.var_lens.get().strip(),
            "film_info": self.var_film.get().strip(),
        }
        profile_dir = Path(__file__).resolve().parent / "Camera Profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        safe_camera = (profile["camera_model"] or "camera").strip().replace(" ", "_")
        safe_lens = (profile["lens"] or "lens").strip().replace(" ", "_")
        filename = f"{safe_camera}-{safe_lens}.json"
        path = profile_dir / filename
        with path.open("w", encoding="utf-8") as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2)
        messagebox.showinfo("완료", f"카메라 프로파일을 저장했습니다: {path}")

    def _import_camera_profile(self):
        profile_dir = Path(__file__).resolve().parent / "Camera Profile"
        file_path = filedialog.askopenfilename(
            initialdir=str(profile_dir),
            title="카메라 프로파일 선택",
            filetypes=[("JSON", "*.json")],
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                profile = json.load(handle)
            self.var_camera_model.set(profile.get("camera_model", ""))
            self.var_lens.set(profile.get("lens", ""))
            self.var_film.set(profile.get("film_info", ""))
            self.var_film.set(profile.get("film_info", ""))
        except Exception as exc:
            messagebox.showerror("오류", f"프로파일 불러오기 실패: {exc}")

    def _load_default_camera_profile(self):
        profile_dir = Path(__file__).resolve().parent / "Camera Profile"
        if not profile_dir.exists():
            return
        try:
            profiles = sorted(profile_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
            if not profiles:
                return
            with profiles[0].open("r", encoding="utf-8") as handle:
                profile = json.load(handle)
            self.var_camera_model.set(profile.get("camera_model", ""))
            self.var_lens.set(profile.get("lens", ""))
        except Exception:
            return

    def _choose_out_dir(self):
        out_dir = filedialog.askdirectory(title="출력 폴더 선택")
        if not out_dir:
            return
        self.out_dir = out_dir
        self.lbl_out.config(text=out_dir)

    def _choose_font(self):
        font_path = filedialog.askopenfilename(
            title="폰트 파일 선택",
            filetypes=[("Font files", "*.ttf *.otf *.ttc"), ("All files", "*.*")],
        )
        if not font_path:
            return
        self.font_path = font_path
        self.var_font_label.set(os.path.basename(font_path))

    def _get_item_gps_lat(self, item: FileItem) -> tuple[int, int, float, str] | None:
        if item.lat_deg is None or item.lat_min is None or item.lat_sec is None:
            return None
        return item.lat_deg, item.lat_min, item.lat_sec, item.lat_ref

    def _get_item_gps_lon(self, item: FileItem) -> tuple[int, int, float, str] | None:
        if item.lon_deg is None or item.lon_min is None or item.lon_sec is None:
            return None
        return item.lon_deg, item.lon_min, item.lon_sec, item.lon_ref

    def _toggle_stamp_options(self):
        if self.var_stamp.get():
            self.stamp_fmt_row.pack(after=self.stamp_row, fill=tk.X, pady=(6, 0))
            self.stamp_opt_container.pack(after=self.stamp_fmt_row, fill=tk.X, pady=(12, 0))
            self.run_row.pack(after=self.stamp_opt_container, fill=tk.X, pady=(18, 0))
        else:
            self.stamp_opt_container.pack_forget()
            self.stamp_fmt_row.pack_forget()
            self.run_row.pack_forget()

    def _make_stamp_text(self, dt: datetime) -> str:
        if self.var_stamp_fmt.get() == "YYYY MM DD":
            return dt.strftime("%Y %m %d")
        if self.var_stamp_fmt.get() in ("'YY MM DD", "YY MM DD"):
            return f"'{dt.strftime('%y %m %d')}"
        return dt.strftime("%y %m %d")

    def _get_preview_item(self) -> FileItem | None:
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            messagebox.showwarning("안내", "왼쪽 목록에서 미리보기할 파일을 선택하세요.")
            return None
        return self.items[selected_indices[0]]

    def _preview(self):
        item = self._get_preview_item()
        if item is None:
            return
        do_stamp = bool(self.var_stamp.get())
        current_dt = None
        if do_stamp and item.assigned_date is not None:
            try:
                start_time = parse_time_hh_mm(self.var_time.get())
            except ValueError:
                start_time = None
            if start_time is not None:
                current_dt = datetime.combine(item.assigned_date, start_time)
            else:
                do_stamp = False
        else:
            do_stamp = False

        try:
            with Image.open(item.path) as img:
                img.load()
                oriented_img, _ = apply_exif_orientation(img)
                preview_img = oriented_img.copy()
                if do_stamp and current_dt is not None:
                    stamp_text = self._make_stamp_text(current_dt)
                    preview_img = _render_stamp_with_settings(
                        preview_img,
                        stamp_text,
                        self.font_path,
                        float(self.var_blur_strength.get()),
                        float(self.var_font_ratio.get()),
                        int(self.var_offset_x.get()),
                        int(self.var_offset_y.get()),
                    )
        except Exception as exc:
            messagebox.showerror("오류", f"미리보기 생성 실패: {exc}")
            return

        preview_win = tk.Toplevel(self)
        preview_win.title("미리보기")

        preview_img = preview_img.copy()
        preview_img.thumbnail((860, 600))
        img_width, img_height = preview_img.size

        preview_win.geometry(f"{img_width + 40}x{img_height + 80}")

        canvas = tk.Canvas(preview_win, bg="#111")
        canvas.pack(pady=(12, 0))
        canvas.config(width=img_width, height=img_height)

        photo = ImageTk.PhotoImage(preview_img)
        canvas.image = photo
        preview_win.update_idletasks()
        x = max(0, (canvas.winfo_width() - photo.width()) // 2)
        y = max(0, (canvas.winfo_height() - photo.height()) // 2)
        canvas.create_image(x, y, anchor="nw", image=photo)

        ttk.Button(preview_win, text="닫기", command=preview_win.destroy).pack(pady=8)

    def _run(self):
        if not self.items:
            messagebox.showwarning("안내", "처리할 JPG 파일이 없습니다.")
            return
        if self.var_stamp.get() and not self.out_dir:
            messagebox.showwarning("안내", "출력 폴더를 선택하세요.")
            return
        start_time: time | None = None
        if any(item.assigned_date is not None for item in self.items):
            try:
                start_time = parse_time_hh_mm(self.var_time.get())
            except ValueError:
                messagebox.showerror("오류", "기준 시작 시간 형식이 올바르지 않습니다. 예: 12:00")
                return

        film_info = self.var_film.get().strip()
        camera_model = self.var_camera_model.get().strip()
        lens = self.var_lens.get().strip()
        do_stamp = bool(self.var_stamp.get())

        items_by_date: dict[date | None, list[FileItem]] = {}
        for item in self.items:
            items_by_date.setdefault(item.assigned_date, []).append(item)

        total = len(self.items)
        self.progress.config(maximum=total, value=0)
        self.lbl_status.config(text="처리 시작...")
        self.update_idletasks()

        processed = 0
        failures = 0
        def _date_sort_key(value: date | None) -> tuple[int, date]:
            if value is None:
                return 1, date.min
            return 0, value

        for group_date in sorted(items_by_date.keys(), key=_date_sort_key):
            group_items = items_by_date[group_date]
            group_items.sort(key=lambda it: os.path.basename(it.path).lower())
            base_dt = None
            if group_date is not None and start_time is not None:
                base_dt = datetime.combine(group_date, start_time)
            for idx, item in enumerate(group_items):
                current_dt = None
                if base_dt is not None:
                    current_dt = base_dt + timedelta(minutes=idx)
                basename = (
                    current_dt.strftime("%Y%m%d%H%M") if current_dt else "exif"
                ) + ".jpg"
                if do_stamp:
                    out_path = safe_out_path(self.out_dir, basename)
                else:
                    out_path = item.path
                try:
                    if not is_jpeg_path(item.path):
                        raise ValueError("JPEG 파일만 처리할 수 있습니다.")
                    gps_lat = self._get_item_gps_lat(item)
                    gps_lon = self._get_item_gps_lon(item)
                    if not do_stamp:
                        existing_exif = load_existing_exif_bytes_from_file(item.path)
                        exif_bytes = build_exif_bytes(
                            existing_exif,
                            current_dt,
                            film_info,
                            camera_model,
                            lens,
                            item.location,
                            gps_lat,
                            gps_lon,
                            item.lat_dd,
                            item.lon_dd,
                        )
                        piexif.insert(exif_bytes, item.path, out_path)
                    else:
                        if current_dt is None:
                            raise ValueError("날짜가 지정되지 않아 스탬프를 적용할 수 없습니다.")
                        with Image.open(item.path) as img:
                            img.load()
                            oriented_img, did_orient = apply_exif_orientation(img)
                            stamp_text = self._make_stamp_text(current_dt)
                            stamped = _render_stamp_with_settings(
                                oriented_img,
                                stamp_text,
                                self.font_path,
                                float(self.var_blur_strength.get()),
                                float(self.var_font_ratio.get()),
                                int(self.var_offset_x.get()),
                                int(self.var_offset_y.get()),
                            )
                            if stamped.mode != "RGB":
                                stamped = stamped.convert("RGB")
                            existing_exif = img.info.get("exif")
                            new_exif = build_exif_bytes(
                                existing_exif,
                                current_dt,
                                film_info,
                                camera_model,
                                lens,
                                item.location,
                                gps_lat,
                                gps_lon,
                                item.lat_dd,
                                item.lon_dd,
                            )
                            if did_orient:
                                exif_dict = piexif.load(new_exif)
                                exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
                                new_exif = piexif.dump(exif_dict)
                            icc_profile = img.info.get("icc_profile")
                            stamped.save(
                                out_path,
                                quality=95,
                                subsampling=0,
                                exif=new_exif,
                                icc_profile=icc_profile,
                            )
                except Exception as exc:
                    failures += 1
                    messagebox.showerror("오류", f"처리 실패: {basename}\n{exc}")
                    self.lbl_status.config(text="오류 발생")
                    return
                processed += 1
                self.progress.config(value=processed)
                self.lbl_status.config(text=f"{processed}/{total} 처리 중…")
                self.update_idletasks()

        success = total - failures
        out_label = self.out_dir if do_stamp else "원본 파일"
        self.lbl_status.config(text=f"완료: {success}개 성공 / {failures}개 실패 ({out_label})")
        messagebox.showinfo("완료", f"EXIF 기록 및 저장 완료: {success}개 성공, {failures}개 실패")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
