# srt-seatbuddy

친근하고 가벼운 SRT 자동 예매 웹앱 소스코드에요.

## 주요 기능

- 자동 예약/예약대기: 로그인 → 조건 입력 → 상위 N개 열차 탐색 → “예약하기/신청하기” 시도 → 성공 시 종료
- 실시간 로그 확인, 중지 버튼으로 즉시 취소
- 헤드리스(브라우저 숨김) 모드 선택 가능

## 사이트 주소 (현재 정적 페이지 preview만 제공돼요)

- URL: https://wjgoarxiv.github.io/srt-seatbuddy/

---

## 로컬 실행(내 PC에서 백엔드 구동)

이 웹앱은 프론트엔드(정적 페이지)와 백엔드(자동화 API)로 구성돼요. 프론트는 `index.html`만으로 열 수 있고, 자동화는 `server/`의 Node 서버가 담당해요.

### 사전 준비

- Node.js 18+ (권장: 20)
- Google Chrome 설치
- ChromeDriver (자동으로 못 찾을 때 필요)
  - macOS: `brew install chromedriver`

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

- 프론트엔드: `index.html`, `app.js`, `train-bg.png`
- 백엔드(API): `server/index.js`(Express), `server/srt.js`(Selenium)
- CI 설정(선택): `.github/workflows/` — GitHub Actions 용으로, 로컬 실행과는 무관

## 참고 사항

- 비밀번호는 저장하지 않아요. 로컬 스토리지에는 역/날짜 같은 비민감 정보만 보관됩니다.

