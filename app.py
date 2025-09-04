import threading
import time
import random
from datetime import datetime, date, time as dtime

import streamlit as st

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

# Driver manager (auto download chromedriver)
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
try:
    # webdriver_manager is convenient locally; on some hosted platforms it may be restricted
    from webdriver_manager.chrome import ChromeDriverManager
    _HAS_WDM = True
except Exception:
    _HAS_WDM = False


st.set_page_config(page_title="SRT 자동 예매 매크로", layout="wide")


URLS = {
    "login": "https://etk.srail.co.kr/cmc/01/selectLoginForm.do",
    "search": "https://etk.srail.kr/hpg/hra/01/selectScheduleList.do",
}


def _ts():
    return datetime.now().strftime("%H:%M:%S")


class LogBuffer:
    def __init__(self):
        self._lock = threading.Lock()
        self._items = []

    def add(self, msg: str, kind: str = "info"):
        with self._lock:
            self._items.append({"t": datetime.now().isoformat(), "msg": msg, "kind": kind})

    def snapshot(self, max_items: int = 300):
        with self._lock:
            return list(self._items[-max_items:])


def add_log(msg: str, kind: str = "info"):
    buf = st.session_state.get("log_buffer")
    if buf is None:
        buf = LogBuffer()
        st.session_state.log_buffer = buf
    buf.add(msg, kind)


def is_cancelled():
    ev = st.session_state.get("cancel_event")
    return ev.is_set() if ev else False


def setup_chrome(headless: bool) -> webdriver.Chrome:
    opts = ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1000")
    # Some environments require explicit binary path via CHROME_BIN
    import os, shutil
    chrome_bin = os.environ.get("CHROME_BIN")
    if not chrome_bin:
        for cand in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
            if os.path.exists(cand):
                chrome_bin = cand
                break
    if chrome_bin:
        opts.binary_location = chrome_bin

    # Prefer system-installed chromedriver if present (Streamlit Cloud via packages.txt)
    system_driver = None
    for cand in ("/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"):
        if os.path.exists(cand):
            system_driver = cand
            break

    if system_driver:
        service = ChromeService(system_driver)
        driver = webdriver.Chrome(service=service, options=opts)
    elif _HAS_WDM:
        # Fallback to webdriver_manager (works locally, may be blocked in some hosts)
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
    else:
        # Last resort: Selenium Manager (needs Chromium/Chrome available)
        driver = webdriver.Chrome(options=opts)

    # Implicit wait helps with minor DOM delays
    driver.implicitly_wait(8)
    return driver


def even_hour_bucket(hh: str, mm: str) -> str:
    # Map 12:00 to 24, otherwise floor to even hour (like JS logic)
    if hh == "12" and (mm or "00") == "00":
        return "24"
    try:
        raw = max(0, min(24, int(hh)))
    except Exception:
        raw = 0
    if raw == 24:
        return "24"
    even = raw - (raw % 2)
    return f"{even:02d}"


def run_srt_automation(params: dict, log, cancelled):
    user_id = params.get("userId")
    password = params.get("password")
    dep = params.get("departureStation")
    arr = params.get("arrivalStation")
    date_str = params.get("date")  # YYYY-MM-DD
    time_str = params.get("time")  # HH:mm
    num_to_check = int(params.get("numToCheck") or 3)
    mode = params.get("mode") or "reserve"  # reserve | waitlist
    headless = bool(params.get("headless"))

    yyyymmdd = (date_str or "").replace("-", "")
    hh, mm = (time_str or "").split(":") if time_str else ("", "00")
    target_hh = even_hour_bucket(hh, mm)

    driver = None
    try:
        log("로그인 페이지로 이동...", "info")
        driver = setup_chrome(headless=headless)
        driver.get(URLS["login"]) 

        # Login
        driver.find_element(By.ID, "srchDvNm01").send_keys(user_id)
        driver.find_element(By.ID, "hmpgPwdCphd01").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "input.loginSubmit").click()
        time.sleep(1.5)

        if cancelled():
            raise RuntimeError("사용자 중지")

        log("열차 조회 페이지로 이동...", "info")
        driver.get(URLS["search"]) 

        # Fill conditions
        dep_el = driver.find_element(By.ID, "dptRsStnCdNm")
        dep_el.clear(); dep_el.send_keys(dep)

        arr_el = driver.find_element(By.ID, "arvRsStnCdNm")
        arr_el.clear(); arr_el.send_keys(arr)

        # Date select by value (YYYYMMDD)
        try:
            sel_date = Select(driver.find_element(By.ID, "dptDt"))
            sel_date.select_by_value(yyyymmdd)
        except Exception:
            # Fallback: use JS to set value if Select fails
            el = driver.find_element(By.ID, "dptDt")
            driver.execute_script(
                "const v=arguments[1]; const el=arguments[0]; const opt=[...el.options].find(o=>o.value===v); if(opt){el.value=opt.value; el.dispatchEvent(new Event('change',{bubbles:true}));}",
                el, yyyymmdd,
            )

        # Time select: option text startswith target HH
        selected_text = None
        try:
            sel_time = Select(driver.find_element(By.ID, "dptTm"))
            # try visible text first
            for o in sel_time.options:
                t = (o.text or "").strip()
                if t.startswith(target_hh):
                    sel_time.select_by_visible_text(o.text)
                    selected_text = o.text
                    break
            if not selected_text:
                # fallback by value contains
                for o in sel_time.options:
                    v = (o.get_attribute("value") or "")
                    if target_hh in v:
                        sel_time.select_by_value(v)
                        selected_text = o.text
                        break
        except Exception:
            pass

        if selected_text:
            log(f"요청 시간 {hh}:{mm} → 적용 시간 {target_hh}시 (짝수 기준)")
        else:
            log(f"시간 옵션 선택 실패: {target_hh}시. 기본값으로 진행합니다.")

        log("조건 입력 완료. 조회합니다...", "info")
        try:
            query_btn = driver.find_element(By.XPATH, "//input[@value='조회하기']")
            driver.execute_script('arguments[0].click();', query_btn)
        except Exception:
            pass

        # Main polling loop
        refresh_count = 0
        while True:
            if cancelled():
                raise RuntimeError("사용자 중지")

            # Fetch result rows
            rows = driver.find_elements(By.CSS_SELECTOR, "#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr")
            if len(rows) == 0:
                log("조회 결과가 없습니다. 계속 재조회합니다.")

            acted = False
            for i in range(1, num_to_check + 1):
                if cancelled():
                    raise RuntimeError("사용자 중지")
                seat_text = ""
                wait_text = ""
                try:
                    seat_el = driver.find_element(By.CSS_SELECTOR, f"#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child({i}) > td:nth-child(7)")
                    wait_el = driver.find_element(By.CSS_SELECTOR, f"#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child({i}) > td:nth-child(8)")
                    seat_text = seat_el.text
                    wait_text = wait_el.text
                except Exception:
                    continue

                if mode != "waitlist" and ("예약하기" in seat_text):
                    log(f"행 {i}: 예약하기 시도")
                    try:
                        a = driver.find_element(By.CSS_SELECTOR, f"#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child({i}) > td:nth-child(7) > a")
                        try:
                            a.click()
                        except Exception:
                            a.send_keys(Keys.ENTER)

                        # Accept alert if exists
                        try:
                            WebDriverWait(driver, 1.5).until(EC.alert_is_present())
                            alert = driver.switch_to.alert
                            log(f"알림창: {alert.text}")
                            alert.accept()
                        except Exception:
                            pass

                        driver.implicitly_wait(3)
                        ok = len(driver.find_elements(By.ID, "isFalseGotoMain")) > 0
                        if ok:
                            log("예약 성공! 결제 화면으로 이동했습니다.", "success")
                            return {"ok": True, "type": "reserve"}
                        log("자리 없음. 결과 페이지로 되돌아갑니다.")
                        driver.back()
                        driver.implicitly_wait(5)
                        acted = True
                    except Exception as e:
                        log(f"예약 시도 중 오류: {e}", "error")

                elif mode == "waitlist" and ("신청하기" in wait_text):
                    log(f"행 {i}: 예약대기 신청 시도")
                    try:
                        a = driver.find_element(By.CSS_SELECTOR, f"#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child({i}) > td:nth-child(8) > a")
                        a.click()
                        log("예약대기 신청 성공!", "success")
                        return {"ok": True, "type": "waitlist"}
                    except Exception as e:
                        log(f"예약대기 시도 중 오류: {e}", "error")

            # Refresh query
            refresh_count += 1
            log(f"재조회 {refresh_count}회")
            try:
                refresh_btn = driver.find_element(By.XPATH, "//input[@value='조회하기']")
                driver.execute_script('arguments[0].click();', refresh_btn)
            except Exception:
                pass
            # Randomized sleep
            time.sleep(2.0 + random.uniform(0.0, 1.5))

    except RuntimeError as e:
        log(f"오류 발생: {e}", "error")
        return {"ok": False, "error": str(e)}
    except WebDriverException as e:
        log(f"웹드라이버 오류: {e}", "error")
        return {"ok": False, "error": str(e)}
    except Exception as e:
        log(f"예상치 못한 오류: {e}", "error")
        return {"ok": False, "error": str(e)}
    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass
    # If loop exits without explicit return
    return {"ok": False, "error": "정상 종료되지 않았습니다."}


def ensure_state():
    ss = st.session_state
    ss.setdefault("running", False)
    ss.setdefault("result", None)
    ss.setdefault("thread", None)
    ss.setdefault("cancel_event", threading.Event())
    ss.setdefault("log_buffer", LogBuffer())
    ss.setdefault("result_holder", {"value": None})


def stop_job():
    if st.session_state.running and st.session_state.cancel_event:
        st.session_state.cancel_event.set()
        add_log("중지 요청을 보냈습니다. 정리 중...", "warn")


def start_job(params: dict):
    if st.session_state.running:
        st.warning("이미 실행 중입니다.")
        return
    # Reset state
    st.session_state.log_buffer = LogBuffer()
    st.session_state.result = None
    st.session_state.cancel_event = threading.Event()
    st.session_state.running = True
    # fresh result holder (shared plain dict)
    result_holder = {"value": None}
    st.session_state.result_holder = result_holder

    add_log("자동화를 시작합니다.")

    # Capture references in main thread to avoid touching st.* inside worker
    cancel_ev = st.session_state.cancel_event
    log_buf = st.session_state.log_buffer

    def _worker():
        nonlocal result_holder
        result = run_srt_automation(params, log_buf.add, cancel_ev.is_set)
        # Emit final message based on result
        if result and result.get("ok"):
            if result.get("type") == "waitlist":
                log_buf.add("예약대기 성공! 결제 또는 안내를 확인하세요.", "success")
            else:
                log_buf.add("예약 성공! 결제 화면을 확인하세요.", "success")
        else:
            log_buf.add("자동화가 종료되었습니다.")
        # Save result for the UI to read (on main thread later)
        result_holder["value"] = result

    th = threading.Thread(target=_worker, daemon=True)
    st.session_state.thread = th
    th.start()


def render_logs():
    # Pretty badges using simple HTML
    kind_map = {
        "success": ("성공", "#16a34a"),
        "warn": ("안내", "#f59e0b"),
        "error": ("오류", "#ef4444"),
        "info": ("진행", "#6366f1"),
    }
    buf = st.session_state.get("log_buffer")
    logs = buf.snapshot() if buf else []
    if not logs:
        st.info("아직 로그가 없습니다.")
        return

    html_lines = []
    for line in logs:
        when = datetime.fromisoformat(line["t"]) if isinstance(line.get("t"), str) else datetime.now()
        t = when.strftime("%H:%M")
        msg = str(line.get("msg", ""))
        kind = line.get("kind", "info")
        label, color = kind_map.get(kind, kind_map["info"])
        html_lines.append(
            f"<div style='display:flex;gap:8px;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.06)'>"
            f"<div style='min-width:52px;color:#aaa;text-align:right;font-variant-numeric:tabular-nums'>{t}</div>"
            f"<div><span style='display:inline-block;padding:2px 8px;border-radius:999px;background:{color}22;border:1px solid {color}66;color:{color};font-size:12px;margin-right:6px'>{label}</span>"
            f"<span style='color:#eee'>{msg}</span></div></div>"
        )
    html = "".join(html_lines)
    st.markdown(
        f"<div style='background:rgba(255,255,255,0.06);border-radius:10px;max-height:320px;overflow:auto'>{html}</div>",
        unsafe_allow_html=True,
    )


def main():
    ensure_state()

    st.title("필요한 순간, SRT 좌석을 자동으로")
    st.caption("원하는 시간대의 잔여 좌석을 빠르게 찾아 예약까지 이어주는 자동 예매 도우미입니다.")

    col_main, col_side = st.columns([2, 1])

    with col_main:
        with st.form("form", clear_on_submit=False):
            st.subheader("로그인 및 조건")
            c1, c2 = st.columns(2)
            with c1:
                user_id = st.text_input("SRT 아이디", key="user_id")
            with c2:
                password = st.text_input("비밀번호", type="password", key="password")

            with st.expander("고급 설정 (헤드리스)"):
                headless = st.selectbox("헤드리스(브라우저 숨김) 실행", options=["끄기", "켜기"], index=0) == "켜기"

            stations_order = [
                "수서", "동탄", "평택지제", "천안아산", "오송", "대전", "김천(구미)", "동대구", "신경주", "울산(통도사)", "부산"
            ]
            c3, c4 = st.columns(2)
            with c3:
                departure = st.selectbox("출발역", options=stations_order, index=0)
            with c4:
                arrival = st.selectbox("도착역", options=list(reversed(stations_order)), index=0)

            c5, c6, c7 = st.columns([1, 1, 1])
            with c5:
                d = st.date_input("출발일자", value=date.today())
            with c6:
                t = st.time_input("출발시간", value=dtime(hour=8, minute=0), step=60)
            with c7:
                num_to_check = st.number_input("조회할 열차 개수", min_value=1, max_value=10, value=3)

            mode = st.radio("모드", options=["예약", "예약 대기"], horizontal=True)

            start_col, stop_col = st.columns([1, 1])
            submitted = start_col.form_submit_button("자동 예매 시작", use_container_width=True)
            stop_clicked = stop_col.form_submit_button("중지", use_container_width=True, disabled=not st.session_state.running)

            if submitted:
                # Validations
                if not user_id or not password:
                    st.error("아이디와 비밀번호를 입력해 주세요.")
                elif departure == arrival:
                    st.error("출발역과 도착역이 같을 수 없습니다.")
                else:
                    params = {
                        "userId": user_id.strip(),
                        "password": password,
                        "departureStation": departure,
                        "arrivalStation": arrival,
                        "date": d.strftime("%Y-%m-%d"),
                        "time": t.strftime("%H:%M"),
                        "numToCheck": int(num_to_check),
                        "mode": "waitlist" if mode == "예약 대기" else "reserve",
                        "headless": headless,
                    }
                    start_job(params)

            if stop_clicked:
                stop_job()

        st.subheader("로그 (서버 상태)")
        render_logs()

    with col_side:
        st.header("안심하고 사용하세요")
        st.markdown(
            "- 이 앱은 아이디/비밀번호를 저장하지 않습니다.\n"
            "- 브라우저에 남는 정보는 역/날짜 같은 비민감 정보뿐이에요.\n"
            "- 자동화는 서버에서 SRT 공식 사이트를 직접 조작합니다.\n"
            "- 언제든 중지를 눌러 즉시 멈출 수 있어요. 로그에서 과정을 확인하세요.")

        st.divider()
        st.markdown(
            "© 2025 SRT 자동 예매 프로그램 · written by "
            "[Woojin Go](https://woojingo.notion.site)  ",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<a href=\"https://www.buymeacoffee.com/woojingo\" target=\"_blank\">"
            "<img src=\"https://cdn.buymeacoffee.com/buttons/v2/default-red.png\" alt=\"Buy Me A Coffee\" style=\"height: 40px; width: 145px;\"></a>",
            unsafe_allow_html=True,
        )

    # Watch worker lifecycle: when thread stops, mark not running
    th = st.session_state.get("thread")
    if th and not th.is_alive() and st.session_state.running:
        st.session_state.running = False
        # bring result from holder
        holder = st.session_state.get("result_holder")
        if holder:
            st.session_state.result = holder.get("value")
    # Auto refresh logs while running (avoid tight loop)
    if st.session_state.running:
        time.sleep(1.5)
        st.rerun()


if __name__ == "__main__":
    main()
