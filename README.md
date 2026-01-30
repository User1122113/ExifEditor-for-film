# Film EXIF Writer (ExifEditor-for-film)

필름 스캔 **JPG** 이미지에 **필름/카메라 정보**, **날짜/시간**, **GPS 좌표**를 **EXIF 메타데이터**로 기록하는 Tkinter GUI 도구입니다.  
선택적으로 사진 **우측 하단에 날짜 스탬프(픽셀 오버레이)** 를 추가해 **새 파일로 저장**할 수 있습니다.

> 실행 파일(.exe/.app)로 배포하더라도 `fonts/`, `Camera Profile/` 폴더는 **사용자가 파일을 자유롭게 추가/삭제/교체**할 수 있도록 앱 옆(또는 앱이 위치한 폴더)에 **외부 폴더로 유지**됩니다.

---

## 빠른 시작 (ZIP 다운로드 기준)

### 1) ZIP 다운로드 & 압축 해제
- 배포 버전의 FilmWriter.zip을 다운받아서 압축해제합니다.

압축 해제 후 폴더 안에 아래 파일 및 폴더가 있어야 합니다.
- `Film_Writer.exe`
- `fonts/`
- `Camera Profile/`

> 처음 실행 시 `fonts/`, `Camera Profile/` 폴더가 없다면 자동 생성됩니다(필요 시 기본 리소스가 seed될 수 있음).



### 2) 소스코드로 직접 실행 방법
### 2-1) Python 설치 확인
- Windows: **Python 3.10+** 권장(개발은 Python 3.13 기준)
- macOS: **python3** 사용 권장

터미널/PowerShell에서 확인:
```bash
python --version
# 또는 macOS
python3 --version
```

### 2-2) 가상환경 생성/활성화 & 의존성 설치
#### Windows (PowerShell)
```powershell
cd "압축 푼 폴더 경로"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

#### macOS / Linux (Terminal)
```bash
cd "압축 푼 폴더 경로"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

### 3) 실행
```bash
python Film_Writer.py
```

---

## 사용 방법 (GUI)

### 1) JPG 목록 추가/정리
- **JPG 추가**: 여러 JPG(또는 JPEG)를 선택해 목록에 추가
- **선택 제거 / 모두 제거**: 목록 정리

> JPEG만 지원합니다(`.jpg`, `.jpeg`).

### 2) 날짜/시간 적용
- 우측 상단에 **날짜(YYYY-MM-DD)** 입력
- **기준 시작 시간(HH:MM)** 입력 (기본 `12:00`)
- 왼쪽 목록에서 파일을 선택한 뒤 **「선택된 사진에 날짜/위치정보 적용」** 클릭  
  - 선택된 파일들에 날짜가 할당됩니다.
  - 실제 EXIF 기록은 **마지막에 “EXIF 기록 및 저장”**을 눌렀을 때 수행됩니다.

### 3) 위치(GPS 좌표) 적용
다음 중 하나로 좌표를 입력합니다.
- **클립보드 붙여넣기**: 구글지도에서 좌표 복사 → 버튼 클릭  
  (예: `37.5665, 126.9780`)
- **지도에서 불러오기**: 지도 창에서 클릭한 위치를 자동 반영 (OpenStreetMap 타일 사용)

좌표 입력 후 **「선택된 사진에 날짜/위치정보 적용」**을 눌러 선택된 파일에 적용합니다.

### 4) 필름/카메라 정보
- **카메라 기종 / 렌즈 / 필름 정보** 입력
- **내보내기**: `Camera Profile` 폴더에 JSON 프로파일 저장
- **불러오기**: 저장된 프로파일을 불러와 입력값 자동 채움

### 5) 날짜 스탬프(선택)
- **우측 하단 날짜 스탬프** 체크 시:
  - 날짜 스탬프가 이미지에 오버레이되며 **새 파일로 저장**됩니다.
  - **출력 폴더 선택**이 필수입니다.
  - 스탬프 형식/블러/크기/오프셋을 조정할 수 있습니다.
  - 폰트는 **폰트 파일 선택**으로 바꿀 수 있습니다.

### 6) 미리보기 → EXIF 기록 및 저장
- **미리보기**로 결과를 확인한 뒤
- **EXIF 기록 및 저장**을 눌러 최종 기록/저장을 수행합니다.

---

## 저장 동작/파일명 규칙

### 스탬프 OFF (기본)
- 이미지를 다시 인코딩하지 않고 **원본 JPG 파일에 EXIF만 기록**합니다.  
  (원본 파일이 수정됩니다)

### 스탬프 ON
- 스탬프가 들어간 **새 JPG 파일을 출력 폴더에 저장**합니다.
- 파일명: `YYYYMMDDHHMM.jpg`  
  - 같은 날짜 그룹에서 파일 순서대로 **1분 단위로 시간 증가**하여 저장합니다.
- 동일 파일명이 이미 있으면 `..._1.jpg`, `..._2.jpg`처럼 자동으로 피합니다.

---

## 폴더 구성 (사용자 수정 가능)

앱은 실행 위치(소스 실행 시 `.py`가 있는 폴더 / exe 실행 시 exe가 있는 폴더)에 아래 폴더를 사용합니다.

- `fonts/`  
  - 기본 폰트: `fonts/E1234.ttf` (있으면 기본값으로 사용)
  - 사용자가 자유롭게 폰트를 추가/교체할 수 있습니다.
- `Camera Profile/`  
  - 카메라/렌즈/필름 정보를 JSON으로 저장/불러오기 합니다.
  - 사용자가 자유롭게 파일을 추가/삭제할 수 있습니다.

> **권한 주의:** `Program Files` 같은 보호된 경로에 exe/app을 두면 폴더 수정이 막힐 수 있습니다.  
> 이 경우 사용자 문서 폴더 같은 **쓰기 가능한 위치**로 옮겨 사용하세요.

---

## 요구 사항 (requirements)
`requirements.txt` 기준:
- Pillow
- piexif
- pywebview

Windows에서 “지도에서 불러오기(웹뷰)”가 동작하려면 보통 **Microsoft Edge WebView2 Runtime**이 필요할 수 있습니다.

---

## 지도(좌표 선택) 및 OpenStreetMap 라이선스
- 지도 창은 Leaflet + OpenStreetMap 타일을 사용합니다.
- © OpenStreetMap contributors / Open Database License (ODbL) 1.0

---

## 문제 해결 (FAQ)

### Q1. “지도에서 불러오기”가 안 뜹니다.
- Windows: WebView2 Runtime 설치 여부를 확인하세요.
- pywebview 백엔드/보안 정책에 따라 환경별 이슈가 있을 수 있습니다.

### Q2. 폰트가 적용되지 않습니다.
- `fonts/E1234.ttf`가 존재하는지 확인하거나, GUI의 **폰트 파일 선택**으로 직접 지정하세요.

### Q3. 스탬프 ON인데 저장이 안 됩니다.
- 스탬프 ON일 때는 **출력 폴더 선택**이 필수입니다.
