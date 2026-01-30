# Windows build guide (PyInstaller)

## 1) Create and activate venv

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## 2) Install requirements

```powershell
python -m pip install -r requirements.txt
```

## 3) Install PyInstaller

```powershell
python -m pip install pyinstaller
```

## 4) Build commands

### OneFile (recommended for distribution)

```powershell
python -m PyInstaller `
  --name "Film_Writer" `
  --noconfirm `
  --clean `
  --onefile `
  --icon "Film_Writer_icon.ico" `
  --add-data "Film_Writer_icon.ico;." `
  --collect-submodules webview `
  "Film_Writer.py"
```

### OneDir (optional)

```powershell
python -m PyInstaller `
  --name "Film_Writer" `
  --noconfirm `
  --clean `
  --icon "Film_Writer_icon.ico" `
  --add-data "Film_Writer_icon.ico;." `
  --collect-submodules webview `
  "Film_Writer.py"
```

## 5) Package layout

The app expects user-editable resources next to the EXE.

```
Film_Writer.exe
Film_Writer_icon.ico
fonts\
Camera Profile\
```

### OneFile

- Output: `dist/Film_Writer.exe`
- After build, create folders next to the EXE:

```powershell
mkdir dist\fonts
mkdir "dist\Camera Profile"
copy fonts\* dist\fonts\
copy "Camera Profile\*" "dist\Camera Profile\"
copy Film_Writer_icon.ico dist\
```

### OneDir

- Output: `dist/Film_Writer/Film_Writer.exe`
- Copy editable folders and icon into the same folder:

```powershell
mkdir dist\Film_Writer\fonts
mkdir "dist\Film_Writer\Camera Profile"
copy fonts\* dist\Film_Writer\fonts\
copy "Camera Profile\*" "dist\Film_Writer\Camera Profile\"
copy Film_Writer_icon.ico dist\Film_Writer\
```

## 6) Checks

1) Windows Explorer EXE icon is `Film_Writer_icon.ico`
2) Running EXE shows the same icon on the Tkinter title bar/taskbar
3) `python Film_Writer.py` also shows the icon
4) Editing files in `fonts`/`Camera Profile` persists across runs

## 7) Notes

- Avoid placing the EXE in a restricted folder (e.g., Program Files). Use a writable location (e.g., Desktop or `%LOCALAPPDATA%`).
- On first launch, missing `fonts`/`Camera Profile` folders are created and optionally seeded from the source tree if available.
