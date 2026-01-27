from __future__ import annotations

# 실행 방법:
#   python -m venv .venv
#   (Windows) .venv\Scripts\activate
#   (macOS/Linux) source .venv/bin/activate
#   pip install -r requirements.txt
#   python film_exif_gui.py

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# (Prompt 2에서 실제로 사용)
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont  # noqa: F401
import piexif
import piexif.helper

EXIF_DT_FMT = "%Y:%m:%d %H:%M:%S"
# 기본 폰트 경로: fonts 폴더에 E1234.ttf를 배치하세요.
DEFAULT_FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "E1234.ttf")


@dataclass
class FileItem:
    path: str
    assigned_date: date | None = None


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


def build_exif_bytes(existing_exif: bytes | None, dt: datetime, film_info: str) -> bytes:
    if existing_exif:
        exif_dict = piexif.load(existing_exif)
    else:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    dt_str = dt.strftime(EXIF_DT_FMT).encode("ascii")
    exif_dict["0th"][piexif.ImageIFD.DateTime] = dt_str
    exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt_str
    exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = dt_str

    film_info = (film_info or "").strip()
    if film_info:
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = film_info.encode("utf-8", errors="replace")
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif.helper.UserComment.dump(
            film_info,
            encoding="unicode",
        )

    return piexif.dump(exif_dict)


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


def overlay_dateback_stamp(img: Image.Image, text: str, font_path: str | None) -> Image.Image:
    width, height = img.size
    margin = max(int(width * 0.02), 12)
    font_size = max(int(width * 0.035), 18)
    font = resolve_font(font_path, font_size)

    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = width - margin - text_w
    y = height - margin - text_h
    draw.text((x, y), text, fill=255, font=font)

    main_alpha = mask
    glow_alpha = mask.filter(ImageFilter.GaussianBlur(radius=max(font_size * 0.4, 2)))
    smear_alpha = mask.filter(ImageFilter.BoxBlur(radius=max(font_size * 0.15, 1)))

    def colorize(alpha_mask: Image.Image, color: tuple[int, int, int], alpha_scale: float) -> Image.Image:
        rgba = Image.new("RGBA", img.size, color + (0,))
        alpha = alpha_mask.point(lambda p: int(p * alpha_scale))
        rgba.putalpha(alpha)
        return rgba

    main_layer = colorize(main_alpha, (255, 110, 40), 0.9)
    glow_layer = colorize(glow_alpha, (255, 80, 10), 0.55)
    smear_layer = colorize(smear_alpha, (255, 130, 60), 0.35)

    combined = Image.alpha_composite(glow_layer, smear_layer)
    combined = Image.alpha_composite(combined, main_layer)

    base = img.convert("RGBA")
    stamped = ImageChops.screen(base, combined)
    return stamped.convert(img.mode)


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
        self.var_stamp = tk.BooleanVar(value=False)
        self.var_stamp_fmt = tk.StringVar(value="YY MM DD")

        self.font_path: str | None = None
        self.var_font_label = tk.StringVar(value="(미지정)")
        self.var_continue_on_error = tk.BooleanVar(value=False)

        self._build_ui()

    def _build_ui(self):
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left panel
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        self.listbox = tk.Listbox(left, selectmode=tk.EXTENDED)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(btns, text="JPG 추가", command=self._add_files).pack(side=tk.LEFT)
        ttk.Button(btns, text="선택 제거", command=self._remove_selected).pack(side=tk.LEFT, padx=(8, 0))

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

        out = ttk.Frame(right)
        out.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(out, text="출력 폴더 선택", command=self._choose_out_dir).pack(side=tk.LEFT)
        self.lbl_out = ttk.Label(out, text="(미지정)")
        self.lbl_out.pack(side=tk.LEFT, padx=10)

        stamp = ttk.Frame(right)
        stamp.pack(fill=tk.X, pady=(14, 0))
        ttk.Checkbutton(
            stamp,
            text="우측 하단 날짜 스탬프(픽셀 오버레이)",
            variable=self.var_stamp,
        ).pack(side=tk.LEFT)
        ttk.Label(stamp, text="포맷").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Combobox(
            stamp,
            textvariable=self.var_stamp_fmt,
            width=12,
            state="readonly",
            values=["YY MM DD", "YYYY-MM-DD"],
        ).pack(side=tk.LEFT, padx=6)

        font_row = ttk.Frame(right)
        font_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(font_row, text="폰트 파일 선택(선택)", command=self._choose_font).pack(side=tk.LEFT)
        ttk.Label(font_row, textvariable=self.var_font_label).pack(side=tk.LEFT, padx=10)

        ttk.Checkbutton(
            right,
            text="오류 발생 시 무시하고 계속(선택)",
            variable=self.var_continue_on_error,
        ).pack(anchor="w", pady=(10, 0))

        run = ttk.Frame(right)
        run.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(run, text="EXIF 기록 및 저장", command=self._run).pack(side=tk.LEFT)

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
        return f"{filename}   [{date_text}]"

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

    def _on_select(self):
        selected_indices = list(self.listbox.curselection())
        if not selected_indices:
            self.var_date.set("")
            return
        selected_dates = []
        for index in selected_indices:
            selected_dates.append(self.items[index].assigned_date)
        first = selected_dates[0]
        if all(date_value == first for date_value in selected_dates) and first is not None:
            self.var_date.set(first.strftime("%Y-%m-%d"))
        elif all(date_value == first for date_value in selected_dates) and first is None:
            self.var_date.set("")
        else:
            self.var_date.set("")

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

    def _make_stamp_text(self, dt: datetime) -> str:
        if self.var_stamp_fmt.get() == "YYYY-MM-DD":
            return dt.strftime("%Y-%m-%d")
        return dt.strftime("%y %m %d")

    def _run(self):
        if not self.items:
            messagebox.showwarning("안내", "처리할 JPG 파일이 없습니다.")
            return
        if not self.out_dir:
            messagebox.showwarning("안내", "출력 폴더를 선택하세요.")
            return
        missing = [item for item in self.items if item.assigned_date is None]
        if missing:
            messagebox.showerror(
                "오류",
                "날짜가 미지정인 파일이 있습니다. 각 파일(또는 선택 항목)에 날짜를 적용하세요.",
            )
            return
        try:
            start_time = parse_time_hh_mm(self.var_time.get())
        except ValueError:
            messagebox.showerror("오류", "기준 시작 시간 형식이 올바르지 않습니다. 예: 12:00")
            return

        film_info = self.var_film.get().strip()
        do_stamp = bool(self.var_stamp.get())
        continue_on_error = bool(self.var_continue_on_error.get())

        items_by_date: dict[date, list[FileItem]] = {}
        for item in self.items:
            assert item.assigned_date is not None
            items_by_date.setdefault(item.assigned_date, []).append(item)

        total = len(self.items)
        self.progress.config(maximum=total, value=0)
        self.lbl_status.config(text="처리 시작...")
        self.update_idletasks()

        processed = 0
        failures = 0
        for group_date in sorted(items_by_date.keys()):
            group_items = items_by_date[group_date]
            group_items.sort(key=lambda it: os.path.basename(it.path).lower())
            base_dt = datetime.combine(group_date, start_time)
            for idx, item in enumerate(group_items):
                current_dt = base_dt + timedelta(minutes=idx)
                basename = os.path.basename(item.path)
                out_path = safe_out_path(self.out_dir, basename)
                try:
                    if not is_jpeg_path(item.path):
                        raise ValueError("JPEG 파일만 처리할 수 있습니다.")
                    if not do_stamp:
                        existing_exif = load_existing_exif_bytes_from_file(item.path)
                        exif_bytes = build_exif_bytes(existing_exif, current_dt, film_info)
                        piexif.insert(exif_bytes, item.path, out_path)
                    else:
                        with Image.open(item.path) as img:
                            img.load()
                            stamp_text = self._make_stamp_text(current_dt)
                            stamped = overlay_dateback_stamp(img, stamp_text, self.font_path)
                            if stamped.mode != "RGB":
                                stamped = stamped.convert("RGB")
                            existing_exif = img.info.get("exif")
                            new_exif = build_exif_bytes(existing_exif, current_dt, film_info)
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
        self.lbl_status.config(text=f"완료: {success}개 성공 / {failures}개 실패 ({self.out_dir})")
        messagebox.showinfo("완료", f"EXIF 기록 및 저장 완료: {success}개 성공, {failures}개 실패")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
