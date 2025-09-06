import threading
import time
import random
from datetime import datetime, date, time as dtime

import streamlit as st
from streamlit.components.v1 import html as st_html
import json, urllib.request

# Selenium imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, UnexpectedAlertPresentException

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


# --- Notification helpers (UI-side and backend sends) ---
def _ui_beep():
    # Play a short beep using AudioContext to avoid hosting media files
    st_html(
        """
        <script>
        (function(){
          try{
            const ctx = new (window.AudioContext||window.webkitAudioContext)();
            const o = ctx.createOscillator();
            const g = ctx.createGain();
            o.connect(g); g.connect(ctx.destination);
            o.type = 'sine'; o.frequency.value = 880;
            g.gain.setValueAtTime(0.0001, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime+0.01);
            o.start();
            g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime+0.5);
            o.stop(ctx.currentTime+0.55);
          }catch(e){}
        })();
        </script>
        """,
        height=0,
    )


def _ui_desktop_notify(title: str, body: str):
    st_html(
        f"""
        <script>
        (async function(){{
          try{{
            if (Notification && Notification.permission !== 'granted') {{
              await Notification.requestPermission();
            }}
            if (Notification && Notification.permission === 'granted') {{
              const n = new Notification({json.dumps(title)}, {{ body: {json.dumps(body)} }});
              n.onclick = () => window.focus();
            }}
          }}catch(e){{}}
        }})();
        </script>
        """,
        height=0,
    )


def _send_webhook(url: str, payload: dict, log=lambda *a, **k: None):
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            _ = resp.read()
        log("웹훅 전송 완료", "success")
    except Exception as e:
        log(f"웹훅 전송 실패: {e}", "warn")


# removed email sending to keep setup simple


def is_cancelled():
    ev = st.session_state.get("cancel_event")
    return ev.is_set() if ev else False


def setup_chrome(headless: bool, debug_port: int | None = None) -> webdriver.Chrome:
    opts = ChromeOptions()
    if headless:
        # Prefer new headless; container fallbacks handled below
        opts.add_argument("--headless=new")
        # Needed to avoid DevToolsActivePort errors in containers; use unique port in parallel
        if debug_port is None:
            try:
                # base 9222 + small random offset
                debug_port = 9222 + random.randint(0, 399)
            except Exception:
                debug_port = 9222
        opts.add_argument(f"--remote-debugging-port={int(debug_port)}")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1000")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--hide-scrollbars")
    # Some environments require explicit binary path via CHROME_BIN
    import os, tempfile
    chrome_bin = os.environ.get("CHROME_BIN")
    if not chrome_bin:
        for cand in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
            if os.path.exists(cand):
                chrome_bin = cand
                break
    if chrome_bin:
        opts.binary_location = chrome_bin

    # Use an isolated, writable user data dir in containers
    user_data_dir = os.environ.get("CHROME_USER_DATA_DIR") or tempfile.mkdtemp(prefix="chrome-data-")
    opts.add_argument(f"--user-data-dir={user_data_dir}")

    # Prefer system-installed chromedriver if present (Streamlit Cloud via packages.txt)
    system_driver = None
    for cand in ("/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"):
        if os.path.exists(cand):
            system_driver = cand
            break

    def _build_with(service_path: str | None):
        if service_path:
            return webdriver.Chrome(service=ChromeService(service_path), options=opts)
        return webdriver.Chrome(options=opts)

    last_err = None
    for service_path in [system_driver, None if not _HAS_WDM else ChromeDriverManager().install(), None]:
        try:
            driver = _build_with(service_path)
            break
        except WebDriverException as e:
            last_err = e
            # Retry once with legacy headless if new headless fails to start Chrome
            msg = str(e)
            if "DevToolsActivePort" in msg or "failed to start" in msg:
                try:
                    # Switch to legacy headless flag and retry
                    try:
                        opts.arguments.remove("--headless=new")
                    except ValueError:
                        pass
                    opts.add_argument("--headless")
                    driver = _build_with(service_path)
                    break
                except Exception as e2:
                    last_err = e2
                    continue
            else:
                continue
    else:
        # If loop didn't break with a driver
        raise last_err if last_err else RuntimeError("Failed to start Chrome driver")

    # Implicit wait helps with minor DOM delays
    driver.implicitly_wait(8)
    return driver


def even_hour_bucket(hh: str, mm: str) -> str:
    # Round UP to the next 2-hour boundary. Examples:
    # 15:31 -> 16, 15:00 -> 16, 14:00 -> 14, 14:01 -> 16, 23:30 -> 24
    try:
        h = int(hh or 0)
    except Exception:
        h = 0
    try:
        m = int(mm or 0)
    except Exception:
        m = 0
    total = max(0, min(24 * 60, h * 60 + m))
    if total >= 24 * 60:
        return "24"
    # Ceil to 120-minute bucket
    bucket_minutes = ((total + 119) // 120) * 120
    if bucket_minutes >= 24 * 60:
        return "24"
    return f"{bucket_minutes // 60:02d}"


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
    seat_pref = params.get("seatPref") or "both"  # economy | first | both

    yyyymmdd = (date_str or "").replace("-", "")
    hh, mm = (time_str or "").split(":") if time_str else ("", "00")

    driver = None
    try:
        log("로그인 페이지로 이동...", "info")
        worker_idx = int(params.get("workerIndex") or 0)
        # Assign a unique remote debugging port per worker to avoid collisions
        debug_port = 9222 + (worker_idx % 400)
        driver = setup_chrome(headless=headless, debug_port=debug_port)
        driver.get(URLS["login"]) 

        # Login with one retry on spurious alert
        for attempt in range(2):
            # Fill and submit
            try:
                driver.find_element(By.ID, "srchDvNm01").clear()
            except Exception:
                pass
            driver.find_element(By.ID, "srchDvNm01").send_keys(user_id)
            driver.find_element(By.ID, "hmpgPwdCphd01").send_keys(password)
            driver.find_element(By.CSS_SELECTOR, "input.loginSubmit").click()
            # Immediately handle possible login alert (ex: 존재하지않는 회원입니다)
            try:
                WebDriverWait(driver, 2.5).until(EC.alert_is_present())
                alert = driver.switch_to.alert
                txt = alert.text
                log(f"로그인 알림: {txt}", "warn")
                alert.accept()
                # If known spurious message, retry once
                if attempt == 0 and ("존재하지않는 회원" in txt or "회원" in txt):
                    time.sleep(0.4 + random.uniform(0,0.3))
                    continue
                raise RuntimeError(f"로그인 실패: {txt}")
            except TimeoutException:
                break
            except UnexpectedAlertPresentException:
                try:
                    alert = driver.switch_to.alert
                    txt = alert.text
                    log(f"로그인 알림: {txt}", "warn")
                    alert.accept()
                    if attempt == 0 and ("존재하지않는 회원" in txt or "회원" in txt):
                        time.sleep(0.4 + random.uniform(0,0.3))
                        continue
                    raise RuntimeError(f"로그인 실패: {txt}")
                except Exception:
                    raise RuntimeError("로그인 중 알림 처리 실패")
        time.sleep(0.6)

        if cancelled():
            raise RuntimeError("사용자 중지")

        log("열차 조회 페이지로 이동...", "info")
        try:
            driver.get(URLS["search"]) 
        except UnexpectedAlertPresentException:
            try:
                alert = driver.switch_to.alert
                txt = alert.text
                log(f"페이지 이동 중 알림: {txt}", "warn")
                alert.accept()
                raise RuntimeError(f"로그인/접속 제한: {txt}")
            except Exception:
                raise

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

        # Time select: parse all options and choose the nearest at-or-after target
        selected_text = None
        try:
            import re
            def parse_minutes(text: str) -> int:
                try:
                    m = re.search(r"(\d{1,2}):(\d{2})", text or "")
                    if m:
                        H = int(m.group(1)); M = int(m.group(2))
                        if H >= 24:
                            return 24*60
                        return max(0, min(24*60, H*60 + M))
                except Exception:
                    pass
                return -1

            def value_minutes(val: str) -> int:
                s = (val or "").strip()
                try:
                    if len(s) >= 4 and s[:4].isdigit():
                        H = int(s[:2]); M = int(s[2:4])
                        if H >= 24:
                            return 24*60
                        return max(0, min(24*60, H*60 + M))
                    if len(s) == 2 and s.isdigit():
                        H = int(s)
                        if H >= 24:
                            return 24*60
                        return H*60
                except Exception:
                    pass
                return -1

            def pick_option(select_el: Select, opts):
                # target minutes from user input
                try:
                    th = int(hh or 0); tm = int(mm or 0)
                except Exception:
                    th, tm = 0, 0
                target_min = max(0, min(24*60, th*60 + tm))
                # Build candidates list
                cands = []
                for o in opts:
                    tmin = parse_minutes((o.text or "").strip())
                    if tmin < 0:
                        tmin = value_minutes(o.get_attribute("value") or "")
                    if tmin >= 0:
                        cands.append((tmin, o))
                if not cands:
                    return None
                cands.sort(key=lambda x: x[0])
                # Prefer exact match
                for tmin, o in cands:
                    if tmin == target_min:
                        try:
                            select_el.select_by_visible_text(o.text)
                        except Exception:
                            select_el.select_by_value(o.get_attribute("value") or "")
                        return (tmin, o)
                # Else choose first option >= target
                for tmin, o in cands:
                    if tmin >= target_min:
                        try:
                            select_el.select_by_visible_text(o.text)
                        except Exception:
                            select_el.select_by_value(o.get_attribute("value") or "")
                        return (tmin, o)
                # Else choose the latest available
                tmin, o = cands[-1]
                try:
                    select_el.select_by_visible_text(o.text)
                except Exception:
                    select_el.select_by_value(o.get_attribute("value") or "")
                return (tmin, o)

            sel_time = Select(driver.find_element(By.ID, "dptTm"))
            picked = pick_option(sel_time, sel_time.options)
            if picked:
                tmin, o = picked
                selected_text = (o.text or "").strip() or (o.get_attribute("value") or "")
        except Exception as e:
            log(f"시간 선택 오류: {e}", "warn")

        if selected_text:
            log(f"요청 시간 {hh}:{mm} → 적용 시간 {selected_text}")
        else:
            log(f"시간 옵션 선택 실패: {hh}:{mm}. 기본값으로 진행합니다.")

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

            for i in range(1, num_to_check + 1):
                if cancelled():
                    raise RuntimeError("사용자 중지")
                wait_text = ""
                try:
                    # Read commonly used cells; actual seat type layout may vary across site versions
                    # Col 8 often used for 특실 or 예약대기; keep as wait column for legacy behavior
                    td8 = driver.find_element(By.CSS_SELECTOR, f"#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child({i}) > td:nth-child(8)")
                    wait_text = td8.text
                except Exception:
                    continue

                if mode != "waitlist":
                    # Try reservation based on seat preference. We attempt multiple columns conservatively.
                    # Heuristic mapping: col7(일반) and possibly col6(특실) on some layouts. Retain col7 as default.
                    candidates: list[tuple[int, str]] = []
                    if seat_pref == "economy":
                        candidates = [(7, "일반석"), (6, "일반/대체")]
                    elif seat_pref == "first":
                        candidates = [(6, "특실"), (7, "특실/대체")]
                    else:  # both
                        candidates = [(7, "일반석"), (6, "특실")]

                    for col_idx, label in candidates:
                        try:
                            td = driver.find_element(By.CSS_SELECTOR, f"#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child({i}) > td:nth-child({col_idx})")
                            txt = (td.text or "").strip()
                            if "예약하기" in txt:
                                log(f"행 {i} {label}: 예약하기 시도")
                                a = td.find_element(By.CSS_SELECTOR, "a")
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
                                    return {"ok": True, "type": "reserve", "seatPref": seat_pref}
                                log("자리 없음. 결과 페이지로 되돌아갑니다.")
                                driver.back()
                                driver.implicitly_wait(5)
                                # If tried one column and failed, try next candidate
                        except Exception:
                            continue

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
    ss.setdefault("notified", False)
    ss.setdefault("notify_config", {
        "sound": True,
        "desktop": False,
        "webhook_url": "",
    })


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
        # Handle parallel workers with staggered start to avoid simultaneous logins
        count = int(params.get("parallelCount") or 1)
        count = max(1, min(20, count))
        stagger = float(params.get("parallelStaggerSec") or 0.5)
        if not (stagger >= 0.0):
            stagger = 0.0
        stagger = min(5.0, max(0.0, stagger))

        # Shared state for inner workers
        best_result = {"value": None}

        def make_logger(idx: int):
            def _log(msg: str, kind: str = "info"):
                prefix = f"[{idx}] " if idx is not None else ""
                try:
                    log_buf.add(f"[{idx}] {msg}", kind)
                except Exception:
                    log_buf.add(f"{prefix}{msg}", kind)
            return _log

        def one_worker(idx: int):
            # Stagger login time: 2s per index + small jitter
            try:
                delay = idx * stagger + random.uniform(0.0, 0.2)
                time.sleep(delay)
            except Exception:
                pass
            # Wrap logger with worker id prefix
            wlog = make_logger(idx)
            # If cancelled already (another worker succeeded or user stopped), exit early
            if cancel_ev.is_set():
                return
            # copy params and annotate worker index
            p = dict(params)
            p["workerIndex"] = idx
            res = run_srt_automation(p, wlog, cancel_ev.is_set)
            if res and res.get("ok") and not cancel_ev.is_set():
                # Winner: set cancel to stop others
                cancel_ev.set()
                best_result["value"] = res

        if count == 1:
            # Single worker path (preserve previous behavior)
            res = run_srt_automation(params, log_buf.add, cancel_ev.is_set)
            best_result["value"] = res
        else:
            log_buf.add(f"병렬 매크로 {count}개를 시작합니다. (로그인 간격 {stagger:.2f}s)")
            threads = []
            for idx in range(count):
                t = threading.Thread(target=one_worker, args=(idx,), daemon=True)
                threads.append(t)
                t.start()
            # Wait until all done or cancelled
            for t in threads:
                try:
                    t.join()
                except Exception:
                    pass

        result = best_result["value"]
        # Emit final message based on result
        if result and result.get("ok"):
            if result.get("type") == "waitlist":
                log_buf.add("예약대기 성공! 결제 또는 안내를 확인하세요.", "success")
            else:
                seat_label = {"economy": "일반석", "first": "특실", "both": "좌석 무관"}.get(params.get("seatPref") or "both")
                log_buf.add(f"예약 성공! ({seat_label}) 결제 화면을 확인하세요.", "success")
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

            with st.expander("고급 설정 (헤드리스/병렬)"):
                headless = st.selectbox("헤드리스(브라우저 숨김) 실행", options=["끄기", "켜기"], index=0) == "켜기"
                parallel_stagger_sec = st.number_input(
                    "병렬 로그인 간격(초)", min_value=0.0, max_value=5.0, value=0.5, step=0.1,
                    help="여러 매크로를 동시에 실행할 때 각 로그인 시작 간격"
                )
            with st.expander("알림 설정"):
                nc = st.session_state.get("notify_config", {})
                sound_on = st.checkbox("성공 시 소리 재생", value=bool(nc.get("sound", True)))
                desktop_on = st.checkbox("성공 시 데스크탑 알림(브라우저 권한 필요)", value=bool(nc.get("desktop", False)))
                webhook_url = st.text_input("웹훅 URL(선택)", value=str(nc.get("webhook_url", "")))

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

            c7a, c7b = st.columns([1, 1])
            with c7a:
                seat_type_label = st.selectbox("좌석 종류", options=["일반석", "특실", "둘 다"], index=2)
            with c7b:
                parallel_count = st.number_input("동시 매크로 개수", min_value=1, max_value=20, value=1, help="동일 계정 동시 로그인은 순차 지연으로 분산됩니다.")

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
                    # Save notify config for later use on success
                    st.session_state.notify_config = {
                        "sound": bool(sound_on),
                        "desktop": bool(desktop_on),
                        "webhook_url": webhook_url.strip(),
                    }
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
                        "seatPref": "economy" if seat_type_label == "일반석" else ("first" if seat_type_label == "특실" else "both"),
                        "parallelCount": int(parallel_count),
                        "parallelStaggerSec": float(parallel_stagger_sec),
                    }
                    # Reset notified flag and stash params for notifications
                    st.session_state.notified = False
                    st.session_state.last_params = params
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
    # If finished and success, trigger notifications once
    result = st.session_state.get("result")
    if result and result.get("ok") and not st.session_state.get("notified"):
        cfg = st.session_state.get("notify_config") or {}
        params = st.session_state.get("last_params") or {}
        title = "SRT 예약 성공"
        body = f"{params.get('departureStation','?')}→{params.get('arrivalStation','?')} {params.get('date','')} {params.get('time','')}"
        if cfg.get("sound"):
            _ui_beep()
        if cfg.get("desktop"):
            _ui_desktop_notify(title, body)
        # Fire-and-forget webhook in background thread
        def _bg_send():
            if cfg.get("webhook_url"):
                payload = {"title": title, "body": body, "params": params, "result": result}
                _send_webhook(cfg.get("webhook_url"), payload, add_log)
        threading.Thread(target=_bg_send, daemon=True).start()
        st.session_state.notified = True
    # Auto refresh logs while running (avoid tight loop)
    if st.session_state.running:
        time.sleep(1.5)
        st.rerun()


if __name__ == "__main__":
    main()
