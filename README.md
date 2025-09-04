# srt-seatbuddy

친근하고 가벼운 SRT 자동 예매 웹앱이에요.

## 스트림릿 서비스(권장)

- 바로 사용: https://srt-seatbuddy.streamlit.app/
- 특징: 프론트(UI)와 자동화가 한 앱에 통합되어 별도 백엔드 없이 실행돼요.
- 사용 방법: 아이디/비밀번호와 조건을 입력하고 “자동 예매 시작”을 누르면 로그가 실시간으로 표시됩니다. “중지”로 즉시 취소할 수 있어요.

### 배포 시(스트림릿 클라우드에서 Selenium 오류 해결)

호스팅 환경에서는 크롬과 드라이버가 기본 제공되지 않아, 다음 파일이 필요합니다.

- `packages.txt` — 시스템 패키지 설치 목록(이미 포함됨)
  - 포함: `chromium`, `chromium-driver`, `fonts-nanum`
- 앱 코드는 시스템의 크롬/드라이버를 우선 사용하도록 구성되어 있어요(`app.py`).

추가 팁:

- 환경변수로 크롬 경로를 강제하려면 `CHROME_BIN=/usr/bin/chromium`를 설정하세요.
- 헤드리스 환경에서는 기본적으로 `--no-sandbox`, `--disable-dev-shm-usage` 플래그를 사용하도록 설정돼 있습니다.

### 로컬 실행(스트림릿)

```bash
pip install -r requirements.txt
streamlit run app.py
```

- 필요: Python 3.9+, Google Chrome/Chromium
- 참고: 서버/컨테이너 환경에서 크롬 경로가 특이하면 `CHROME_BIN` 환경변수로 바이너리 경로를 지정하세요.

## 주요 기능

- 자동 예약/예약대기: 로그인 → 조건 입력 → 상위 N개 열차 탐색 → “예약하기/신청하기” 시도 → 성공 시 종료
- 실시간 로그 확인, 중지 버튼으로 즉시 취소
- 헤드리스(브라우저 숨김) 모드 선택 가능

## 정적 페이지(선택) — 미리보기용

- URL: https://wjgoarxiv.github.io/srt-seatbuddy/

---

## 로컬 실행(내 PC에서 백엔드 구동, 선택)

이 경로는 정적 프론트(`index.html`) + Node 백엔드(`server/`)를 분리해 구동하는 방법이에요. 스트림릿 앱을 사용한다면 이 섹션은 건너뛰어도 됩니다.

### 사전 준비

- Node.js 18+ (권장: 20)
- Google Chrome 설치
- ChromeDriver (자동으로 못 찾을 때 필요)
  - macOS: `brew install chromedriver`
  - Windows: `https://sites.google.com/chromium.org/driver/`

### 백엔드 실행

```bash
cd server
npm install
npm start
# 기본 포트: 3000 (변경 시: PORT=3001 npm start)
```

서버가 `http://localhost:3000`에서 대기합니다.

### 프론트엔드 열기

- 방법 A: `index.html`을 브라우저로 직접 열기
- 방법 B(권장): 간단 서버로 정적 서빙

```bash
# 저장소 루트에서
python3 -m http.server 8000
# 브라우저에서 http://localhost:8000 접속
```

페이지의 “서버 주소” 입력란에 `http://localhost:3000`을 넣고, 정보 입력 후 “자동 예매 시작”을 눌러요.

### API 엔드포인트

- `POST /start` — 자동화 시작(바디에 아이디/비번/조건)
- `POST /stop` — 실행 중단
- `GET /status` — 실행 상태 + 최근 로그 확인

## 문제 해결 팁

- ChromeDriver 오류: 드라이버 설치/업데이트(`brew install chromedriver`), Chrome과 버전 일치 확인
- 헤드리스 문제: 헤드리스를 끄고(브라우저 표시) 동작 과정을 확인
- CORS/연결 실패: 백엔드가 켜져 있고 “서버 주소” 포트가 일치하는지 확인
- 포트 충돌: 다른 `PORT`로 백엔드를 실행하고 페이지의 주소를 맞춰 입력

## 폴더 구조

- 스트림릿 앱: `app.py` (UI+자동화 통합)
- 프론트엔드(정적): `index.html`, `app.js`, `train-bg.png`
- 백엔드(API): `server/index.js`(Express), `server/srt.js`(Selenium)
- CI 설정(선택): `.github/workflows/` — GitHub Actions 용으로, 로컬 실행과는 무관

## 참고 사항

- 스트림릿/정적 버전 모두 비밀번호는 저장하지 않아요. 필요한 최소 정보(역/날짜 등)만 브라우저에 저장될 수 있어요.
