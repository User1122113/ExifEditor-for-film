from __future__ import annotations

# 실행 방법:
#   python -m venv .venv
#   (Windows) .venv\Scripts\activate
#   (macOS/Linux) source .venv/bin/activate
#   pip install -r requirements.txt
#   python film_exif_gui.py

import json
import os
from fractions import Fraction
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# (Prompt 2에서 실제로 사용)
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageTk  # noqa: F401
import piexif
import piexif.helper

EXIF_DT_FMT = "%Y:%m:%d %H:%M:%S"
# 기본 폰트 경로: fonts 폴더에 E1234.ttf를 배치하세요.
DEFAULT_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "E1234.ttf")
DEFAULT_BLUR_STRENGTH = 0.15
DEFAULT_FONT_RATIO = 0.03
DEFAULT_OFFSET_X = -20
DEFAULT_OFFSET_Y = -20


@dataclass
class FileItem:
    path: str
    assigned_date: date | None = None
    location: str = ""
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
    if gps_lat and gps_lon:
        lat_deg, lat_min, lat_sec, lat_ref = gps_lat
        lon_deg, lon_min, lon_sec, lon_ref = gps_lon
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref.encode("ascii")
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref.encode("ascii")
        exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = [
            (lat_deg, 1),
            (lat_min, 1),
            _to_rational(lat_sec),
        ]
        exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = [
            (lon_deg, 1),
            (lon_min, 1),
            _to_rational(lon_sec),
        ]
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
        self.geometry("1020x600")

        self.items: list[FileItem] = []
        self.out_dir: str | None = None

        self.var_date = tk.StringVar(value="")
        self.var_time = tk.StringVar(value="12:00")
        self.var_film = tk.StringVar(value="")
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
        self.var_font_label = tk.StringVar(value="(미지정)")
        self.var_continue_on_error = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_default_camera_profile()

    def _build_ui(self):
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left panel
        left = ttk.Frame(paned)
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
        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        form = ttk.Frame(right)
        form.pack(fill=tk.X)

        ttk.Label(form, text="선택 항목 날짜 (YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.var_date, width=20).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(form, text="선택 항목에 날짜 적용", command=self._apply_date).grid(row=0, column=2, sticky="w")

        ttk.Label(form, text="기준 시작 시간 (HH:MM)").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(form, textvariable=self.var_time, width=20).grid(
            row=1,
            column=1,
            sticky="w",
            padx=8,
            pady=(10, 0),
        )

        ttk.Label(form, text="필름 정보").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(form, textvariable=self.var_film, width=54).grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="we",
            padx=8,
            pady=(10, 0),
        )

        ttk.Label(form, text="위도 (φ) D/M/S").grid(row=3, column=0, sticky="w", pady=(10, 0))
        lat_frame = ttk.Frame(form)
        lat_frame.grid(row=3, column=1, sticky="w", padx=8, pady=(10, 0))
        tk.Spinbox(lat_frame, from_=0, to=90, width=5, textvariable=self.var_lat_deg).pack(
            side=tk.LEFT
        )
        ttk.Label(lat_frame, text="°").pack(side=tk.LEFT, padx=(2, 6))
        tk.Spinbox(lat_frame, from_=0, to=59, width=5, textvariable=self.var_lat_min).pack(
            side=tk.LEFT
        )
        ttk.Label(lat_frame, text="′").pack(side=tk.LEFT, padx=(2, 6))
        ttk.Entry(lat_frame, width=8, textvariable=self.var_lat_sec).pack(side=tk.LEFT)
        ttk.Label(lat_frame, text="″").pack(side=tk.LEFT, padx=(2, 6))
        ttk.Combobox(
            lat_frame,
            width=3,
            textvariable=self.var_lat_ref,
            values=["N", "S"],
            state="readonly",
        ).pack(side=tk.LEFT)

        ttk.Label(form, text="경도 (λ) D/M/S").grid(row=4, column=0, sticky="w", pady=(10, 0))
        lon_frame = ttk.Frame(form)
        lon_frame.grid(row=4, column=1, sticky="w", padx=8, pady=(10, 0))
        tk.Spinbox(lon_frame, from_=0, to=180, width=5, textvariable=self.var_lon_deg).pack(
            side=tk.LEFT
        )
        ttk.Label(lon_frame, text="°").pack(side=tk.LEFT, padx=(2, 6))
        tk.Spinbox(lon_frame, from_=0, to=59, width=5, textvariable=self.var_lon_min).pack(
            side=tk.LEFT
        )
        ttk.Label(lon_frame, text="′").pack(side=tk.LEFT, padx=(2, 6))
        ttk.Entry(lon_frame, width=8, textvariable=self.var_lon_sec).pack(side=tk.LEFT)
        ttk.Label(lon_frame, text="″").pack(side=tk.LEFT, padx=(2, 6))
        ttk.Combobox(
            lon_frame,
            width=3,
            textvariable=self.var_lon_ref,
            values=["E", "W"],
            state="readonly",
        ).pack(side=tk.LEFT)

        ttk.Button(form, text="선택 항목에 좌표 적용", command=self._apply_gps).grid(
            row=3,
            column=2,
            sticky="w",
            padx=(0, 4),
            pady=(10, 0),
        )

        cam_prof = ttk.Frame(right)
        cam_prof.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(cam_prof, text="카메라 기종").pack(side=tk.LEFT)
        ttk.Entry(cam_prof, textvariable=self.var_camera_model, width=20).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(cam_prof, text="렌즈").pack(side=tk.LEFT)
        ttk.Entry(cam_prof, textvariable=self.var_lens, width=20).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Button(cam_prof, text="내보내기", command=self._export_camera_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        ttk.Button(cam_prof, text="불러오기", command=self._import_camera_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        stamp = ttk.Frame(right)
        stamp.pack(fill=tk.X, pady=(14, 0))
        ttk.Checkbutton(
            stamp,
            text="우측 하단 날짜 스탬프(픽셀 오버레이)",
            variable=self.var_stamp,
            command=self._toggle_stamp_options,
        ).pack(side=tk.LEFT)
        ttk.Label(stamp, text="포맷").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Combobox(
            stamp,
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
        ttk.Button(font_row, text="폰트 파일 선택(선택)", command=self._choose_font).pack(side=tk.LEFT)
        ttk.Label(font_row, textvariable=self.var_font_label).pack(side=tk.LEFT, padx=10)

        ttk.Checkbutton(
            right,
            text="오류 발생 시 무시하고 계속(선택)",
            variable=self.var_continue_on_error,
        ).pack(anchor="w", pady=(10, 0))

        self.run_row = ttk.Frame(right)
        self.run_row.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(self.run_row, text="미리보기", command=self._preview).pack(side=tk.LEFT)
        ttk.Button(self.run_row, text="EXIF 기록 및 저장", command=self._run).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(self.run_row, text="출력 폴더 선택", command=self._choose_out_dir).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.lbl_out = ttk.Label(self.run_row, text="(미지정)")
        self.lbl_out.pack(side=tk.LEFT, padx=(8, 0))

        self._toggle_stamp_options()

        self.progress = ttk.Progressbar(right, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(10, 0))
        self.lbl_status = ttk.Label(right, text="")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

    def _format_item_label(self, item: FileItem) -> str:
        filename = os.path.basename(item.path)
        if item.assigned_date is None:
            date_text = "미지정"
        else:
            date_text = item.assigned_date.strftime("%Y-%m-%d")
        location_text = f" / {item.location}" if item.location else ""
        return f"{filename}   [{date_text}]{location_text}"

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
        selected_lat = []
        selected_lon = []
        for index in selected_indices:
            selected_dates.append(self.items[index].assigned_date)
            selected_lat.append(
                (
                    self.items[index].lat_deg,
                    self.items[index].lat_min,
                    self.items[index].lat_sec,
                    self.items[index].lat_ref,
                )
            )
            selected_lon.append(
                (
                    self.items[index].lon_deg,
                    self.items[index].lon_min,
                    self.items[index].lon_sec,
                    self.items[index].lon_ref,
                )
            )
        first = selected_dates[0]
        if all(date_value == first for date_value in selected_dates) and first is not None:
            self.var_date.set(first.strftime("%Y-%m-%d"))
        lat_first = selected_lat[0]
        if all(lat_value == lat_first for lat_value in selected_lat):
            if any(value is not None for value in lat_first[:3]):
                self._set_lat_fields(lat_first)
        lon_first = selected_lon[0]
        if all(lon_value == lon_first for lon_value in selected_lon):
            if any(value is not None for value in lon_first[:3]):
                self._set_lon_fields(lon_first)

    def _apply_date(self):
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            messagebox.showwarning("안내", "왼쪽 목록에서 파일을 선택하세요.")
            return
        try:
            new_date = parse_date_yyyy_mm_dd(self.var_date.get())
        except ValueError:
            messagebox.showerror("오류", "날짜 형식이 올바르지 않습니다. 예: 2020-01-02")
            return
        for index in selected_indices:
            self.items[index].assigned_date = new_date
        self._refresh_list()
        self.listbox.selection_clear(0, tk.END)
        for index in selected_indices:
            self.listbox.select_set(index)
        if selected_indices:
            self.listbox.activate(selected_indices[0])
            self.listbox.see(selected_indices[0])

    def _apply_gps(self):
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            messagebox.showwarning("안내", "왼쪽 목록에서 파일을 선택하세요.")
            return

        try:
            lat_deg, lat_min, lat_sec, lat_ref = self._parse_lat_fields()
            lon_deg, lon_min, lon_sec, lon_ref = self._parse_lon_fields()
        except ValueError as exc:
            messagebox.showerror("오류", f"좌표 입력 오류: {exc}")
            return

        for index in selected_indices:
            item = self.items[index]
            item.lat_deg = lat_deg
            item.lat_min = lat_min
            item.lat_sec = lat_sec
            item.lat_ref = lat_ref
            item.lon_deg = lon_deg
            item.lon_min = lon_min
            item.lon_sec = lon_sec
            item.lon_ref = lon_ref
        self._refresh_list()
        self.listbox.selection_clear(0, tk.END)
        for index in selected_indices:
            self.listbox.select_set(index)
        if selected_indices:
            self.listbox.activate(selected_indices[0])
            self.listbox.see(selected_indices[0])

    def _set_lat_fields(self, values: tuple[int | None, int | None, float | None, str]):
        lat_deg, lat_min, lat_sec, lat_ref = values
        self.var_lat_deg.set("" if lat_deg is None else str(lat_deg))
        self.var_lat_min.set("" if lat_min is None else str(lat_min))
        self.var_lat_sec.set("" if lat_sec is None else str(lat_sec))
        if lat_ref:
            self.var_lat_ref.set(lat_ref)

    def _set_lon_fields(self, values: tuple[int | None, int | None, float | None, str]):
        lon_deg, lon_min, lon_sec, lon_ref = values
        self.var_lon_deg.set("" if lon_deg is None else str(lon_deg))
        self.var_lon_min.set("" if lon_min is None else str(lon_min))
        self.var_lon_sec.set("" if lon_sec is None else str(lon_sec))
        if lon_ref:
            self.var_lon_ref.set(lon_ref)

    def _parse_lat_fields(self) -> tuple[int, int, float, str]:
        lat_ref = self.var_lat_ref.get().strip().upper() or "N"
        if lat_ref not in ("N", "S"):
            raise ValueError("위도 방향은 N 또는 S여야 합니다.")
        lat_deg = self._require_int(self.var_lat_deg.get(), "위도 도")
        lat_min = self._require_int(self.var_lat_min.get(), "위도 분")
        lat_sec = self._require_float(self.var_lat_sec.get(), "위도 초")
        self._validate_dms(lat_deg, lat_min, lat_sec, is_lat=True)
        return lat_deg, lat_min, lat_sec, lat_ref

    def _parse_lon_fields(self) -> tuple[int, int, float, str]:
        lon_ref = self.var_lon_ref.get().strip().upper() or "E"
        if lon_ref not in ("E", "W"):
            raise ValueError("경도 방향은 E 또는 W여야 합니다.")
        lon_deg = self._require_int(self.var_lon_deg.get(), "경도 도")
        lon_min = self._require_int(self.var_lon_min.get(), "경도 분")
        lon_sec = self._require_float(self.var_lon_sec.get(), "경도 초")
        self._validate_dms(lon_deg, lon_min, lon_sec, is_lat=False)
        return lon_deg, lon_min, lon_sec, lon_ref

    @staticmethod
    def _require_int(value: str, label: str) -> int:
        value = value.strip()
        if value == "":
            raise ValueError(f"{label} 값이 비어 있습니다.")
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{label} 값이 숫자가 아닙니다.") from exc

    @staticmethod
    def _require_float(value: str, label: str) -> float:
        value = value.strip()
        if value == "":
            raise ValueError(f"{label} 값이 비어 있습니다.")
        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"{label} 값이 숫자가 아닙니다.") from exc

    @staticmethod
    def _validate_dms(deg: int, minute: int, second: float, is_lat: bool) -> None:
        max_deg = 90 if is_lat else 180
        if not (0 <= deg <= max_deg):
            raise ValueError(f"도 값은 0~{max_deg} 범위여야 합니다.")
        if not (0 <= minute <= 59):
            raise ValueError("분 값은 0~59 범위여야 합니다.")
        if not (0 <= second < 60):
            raise ValueError("초 값은 0~59.999 범위여야 합니다.")

    def _export_camera_profile(self):
        profile = {
            "camera_model": self.var_camera_model.get().strip(),
            "lens": self.var_lens.get().strip(),
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
            self.stamp_opt_container.pack(before=self.run_row, fill=tk.X, pady=(12, 0))
        else:
            self.stamp_opt_container.pack_forget()

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
        continue_on_error = bool(self.var_continue_on_error.get())

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
                    if not continue_on_error:
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
