# ExifEditor-for-film

필름 스캔 JPG 이미지에 날짜/시간과 필름 정보를 EXIF 메타데이터로 기록하고, 필요 시 우측 하단에 날짜 스탬프(픽셀 오버레이)를 추가하는 Tkinter GUI 도구입니다. GUI에서 파일 선택, 날짜/시간 지정, 필름 정보 입력, 스탬프 옵션 설정, 출력 폴더 선택까지 한 번에 처리할 수 있습니다.

## 주요 기능

- 여러 JPG 파일에 날짜/시간(EXIF `DateTime`, `DateTimeOriginal`, `DateTimeDigitized`)을 일괄 기록
- 필름 정보 저장(EXIF `ImageDescription`, `UserComment`)
- 날짜 스탬프(픽셀 오버레이): 포맷 선택(`'YY MM DD`, `YYYY MM DD`), 글자 크기/블러/오프셋 조절
- 미리보기: 현재 설정으로 스탬프가 적용된 결과를 별도 창에서 확인
- EXIF Orientation 처리로 세로 사진도 올바르게 표시
- 진행 표시(ProgressBar), 오류 처리 및 오류 무시 옵션

## 설치 방법 (Installation)

### 1) 가상 환경 생성
```bash
python -m venv .venv
```

### 2) 가상 환경 활성화

- Windows
```bat
.venv\Scripts\activate
```

- macOS/Linux
```bash
source .venv/bin/activate
```

### 3) 의존성 설치
```bash
pip install -r requirements.txt
```

### 4) 폰트(선택)

- 기본 폰트 안내: 프로젝트 루트의 `fonts` 폴더에 `E1234.ttf`를 배치하면 기본 폰트로 사용됩니다.
- 폰트를 지정하지 않으면 시스템 폰트 목록에서 자동으로 선택합니다.

## 사용 방법 (Usage)

```bash
python film_exif_gui.py
```

1. 좌측에서 JPG 파일을 추가합니다.
2. 우측에서 날짜(YYYY-MM-DD)와 기준 시간(HH:MM), 필름 정보를 입력합니다.
3. 출력 폴더를 선택합니다.
4. 스탬프 옵션을 설정합니다.
5. “미리보기”로 결과를 확인한 뒤 “EXIF 기록 및 저장”을 클릭합니다.

### 스탬프 ON/OFF 동작

- 스탬프 OFF: 이미지 품질은 그대로 유지되고 EXIF만 수정됩니다.
- 스탬프 ON: 이미지가 재인코딩되며 우측 하단에 날짜가 오버레이됩니다.

## 출력 파일 이름

출력 파일은 각 파일의 할당 날짜/시간을 기준으로 `YYYYMMDDhhmm.jpg` 형식으로 저장됩니다.

## 구조 설명 (Structure)

- [`film_exif_gui.py`](film_exif_gui.py)
  - `FileItem` 데이터 클래스
  - 날짜/시간 파싱 함수
  - EXIF 처리 함수 (`build_exif_bytes`, `load_existing_exif_bytes_from_file`)
  - 스탬프 오버레이 함수 ([`overlay_dateback_stamp()`](film_exif_gui.py:184))
  - GUI 클래스 [`App`](film_exif_gui.py:207) 및 주요 이벤트 메서드 (`_add_files`, `_apply_date`, `_preview`, `_run`)

## 제약 사항 및 참고

- JPEG 파일만 지원합니다.
- 폰트가 지정되지 않으면 기본 폰트 또는 시스템 폰트를 사용합니다.
- 대량 처리 중 오류가 발생하면 기본적으로 작업이 중단되며, “오류 발생 시 무시하고 계속” 옵션으로 계속 진행할 수 있습니다.

## requirements.txt

```text
Pillow>=10.0.0
piexif>=1.1.3
```

## 라이선스 및 기여 (License & Contributing)

- 라이선스가 아직 명시되지 않았습니다. 필요 시 `LICENSE` 파일을 추가해주세요.
- 기여/문의: Issue 또는 PR로 남겨주세요.
