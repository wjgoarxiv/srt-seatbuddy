// SRT 자동 예매 매크로 앱 스크립트

// 저장된 기본 값 로드 및 설정
document.addEventListener('DOMContentLoaded', () => {
    // Load stored values
    const stored = JSON.parse(localStorage.getItem('srtMacroSettings') || '{}');
    for (const [key, value] of Object.entries(stored)) {
        const el = document.getElementById(key);
        if (!el) continue;
        if (key === 'password') continue; // 비밀번호는 로드하지 않음
        if (el.type === 'radio') {
            // radio buttons are handled later
            continue;
        }
        el.value = value;
    }
    if (stored.mode) {
        const radio = document.querySelector(`input[name="mode"][value="${stored.mode}"]`);
        if (radio) radio.checked = true;
    }

    // Set default date to today
    const dateInput = document.getElementById('date');
    if (!dateInput.value) {
        const today = new Date();
        const year = today.getFullYear();
        const month = String(today.getMonth() + 1).padStart(2, '0');
        const day = String(today.getDate()).padStart(2, '0');
        dateInput.value = `${year}-${month}-${day}`;
    }

    // Sidebar toggle state restore
    const sidebar = document.getElementById('sidebar');
    const toggleBtn = document.getElementById('toggleSidebarBtn');
    const open = localStorage.getItem('sidebarOpen');
    const mobileDefaultOpen = !isMobile(); // 모바일이면 기본 닫힘, 데스크톱은 기본 열림
    const isOpen = open == null ? mobileDefaultOpen : open !== 'false';
    setSidebarOpen(isOpen);
    toggleBtn.addEventListener('click', () => {
        const now = !document.getElementById('sidebar').classList.contains('hidden');
        setSidebarOpen(!now);
    });
    function setSidebarOpen(val) {
        if (val) {
            sidebar.classList.remove('hidden');
            toggleBtn.textContent = '🙈';
            toggleBtn.setAttribute('aria-expanded', 'true');
        } else {
            sidebar.classList.add('hidden');
            toggleBtn.textContent = 'ℹ️';
            toggleBtn.setAttribute('aria-expanded', 'false');
        }
        localStorage.setItem('sidebarOpen', String(val));
    }

    // Haptics for mobile buttons
    setupHaptics();
});

function isMobile() {
    const mq = window.matchMedia('(pointer: coarse)');
    return mq.matches || /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

function hapticTap() {
    try {
        if (navigator.vibrate) navigator.vibrate(15);
    } catch (_) { /* ignore */ }
}

function setupHaptics() {
    if (!isMobile()) return;
    const buttons = document.querySelectorAll('button');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            hapticTap();
        }, { passive: true });
    });
}

const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const logEl = document.getElementById('log');
const DEFAULT_SERVER_URL = 'http://localhost:3000';

let intervalId = null;
let attemptCount = 0;

// 로그에 메시지를 추가하는 함수
function appendLog(message, kind = 'info', time = new Date()) {
    const ts = new Date(time);
    const t = ts.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    const badgeClass = kind === 'success' ? 'badge-success' : kind === 'warn' ? 'badge-warn' : kind === 'error' ? 'badge-error' : 'badge-info';
    const div = document.createElement('div');
    div.className = 'log-entry';
    div.innerHTML = `<div class="log-time">${t}</div><div class="log-text"><span class="badge ${badgeClass}">${labelFor(kind)}</span>${escapeHtml(message)}</div>`;
    logEl.appendChild(div);
    logEl.scrollTop = logEl.scrollHeight;
}

function labelFor(kind) {
    switch (kind) {
        case 'success': return '성공';
        case 'warn': return '안내';
        case 'error': return '오류';
        default: return '진행';
    }
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

// 알림 보내기
function notifyUser(title, body) {
    // 예약/알림 기능은 추후 단계에서 확장
    if (Notification.permission === 'granted') {
        new Notification(title, { body });
    }
}

// 비프음 생성
function beep(duration = 1000, frequency = 660, volume = 0.5, type = 'sine') {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        oscillator.type = type;
        oscillator.frequency.value = frequency;
        oscillator.start();
        gainNode.gain.setValueAtTime(volume, audioCtx.currentTime);
        oscillator.stop(audioCtx.currentTime + duration / 1000);
    } catch (e) {
        console.warn('Web Audio API not supported');
    }
}

// 매크로 시작
startBtn.addEventListener('click', async () => {
    // 수집
    const userId = document.getElementById('userId').value.trim();
    const password = document.getElementById('password').value.trim();
    const departureStation = document.getElementById('departureStation').value;
    const arrivalStation = document.getElementById('arrivalStation').value;
    const date = document.getElementById('date').value;
    const time = document.getElementById('time').value;
    const numToCheck = parseInt(document.getElementById('numToCheck').value, 10) || 1;
    const mode = document.querySelector('input[name="mode"]:checked').value;
    const serverUrl = DEFAULT_SERVER_URL;
    const headless = document.getElementById('headless').value === 'true';

    // 검증
    if (!userId || !password) {
        appendLog('아이디와 비밀번호를 입력해 주세요.');
        return;
    }
    if (departureStation === arrivalStation) {
        appendLog('출발역과 도착역이 같을 수 없습니다.');
        return;
    }
    if (!date) {
        appendLog('출발일자를 입력해 주세요.');
        return;
    }
    if (!time) {
        appendLog('출발시간을 입력해 주세요.');
        return;
    }

    // Save values to localStorage for convenience
    localStorage.setItem('srtMacroSettings', JSON.stringify({
        userId,
        headless: String(headless),
        departureStation,
        arrivalStation,
        date,
        time,
        numToCheck,
        mode
    }));

    // 알림 권한은 추후 기능 확장 시 요청 예정

    // 상태 초기화
    attemptCount = 0;
    logEl.innerHTML = '';
    appendLog('백엔드에 자동화를 요청합니다...','info');

    // 버튼 상태
    startBtn.disabled = true;
    stopBtn.disabled = false;

    // 백엔드 호출
    try {
        const resp = await fetch(`${serverUrl.replace(/\/$/, '')}/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId,
                password,
                departureStation,
                arrivalStation,
                date,
                time,
                numToCheck,
                mode,
                headless
            }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
            appendLog(`시작 실패: ${data.message || resp.statusText}`,'error');
            startBtn.disabled = false;
            stopBtn.disabled = true;
            return;
        }
        appendLog('자동화를 시작했습니다. 상태를 모니터링합니다...','info');
        startStatusPolling(serverUrl);
    } catch (e) {
        appendLog('백엔드 연결 실패: ' + (e?.message || e),'error');
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
});

// 매크로 중지
stopBtn.addEventListener('click', () => {
    stopFromServer();
});

function stopMacro(reason) {
    if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
    }
    startBtn.disabled = false;
    stopBtn.disabled = true;
    appendLog(reason);
}

async function stopFromServer() {
    const serverUrl = (document.getElementById('serverUrl').value || '').trim() || 'http://localhost:3000';
    try {
        const resp = await fetch(`${serverUrl.replace(/\/$/, '')}/stop`, { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
            appendLog('중지 요청 실패: ' + (data.message || resp.statusText),'error');
        } else {
            appendLog('중지 요청을 보냈습니다.','warn');
        }
    } catch (e) {
        appendLog('백엔드 연결 실패: ' + (e?.message || e),'error');
    } finally {
        stopMacro('사용자 요청으로 매크로를 중단했습니다.');
    }
}

function startStatusPolling(serverUrl) {
    if (intervalId) clearInterval(intervalId);
    const base = serverUrl.replace(/\/$/, '');
    intervalId = setInterval(async () => {
        try {
            const resp = await fetch(`${base}/status`);
            const data = await resp.json();
            if (Array.isArray(data.logs)) renderServerLogs(data.logs);
            if (!data.running) {
                clearInterval(intervalId);
                intervalId = null;
                startBtn.disabled = false;
                stopBtn.disabled = true;
                if (data.state === 'finished' && data.result?.ok) {
                    const typeKo = data.result.type === 'waitlist' ? '예약대기' : '예약';
                    appendLog(`${typeKo} 성공! 결제 화면을 확인하세요.`,'success');
                    beep(700, 880, 0.6);
                } else if (data.state === 'error') {
                    appendLog('오류로 종료되었습니다. 로그를 확인하세요.','error');
                } else {
                    appendLog('자동화가 종료되었습니다.','warn');
                }
            }
        } catch (e) {
            appendLog('상태 조회 실패: ' + (e?.message || e),'error');
        }
    }, 2000);
}

// 서버 로그를 사용자 친화적으로 변환하여 렌더링
function renderServerLogs(lines) {
    // 기존 로그 비우고 다시 렌더링(간단 명료)
    logEl.innerHTML = '';
    for (const line of lines) {
        // 형식: [ISO] 메시지
        const m = line.match(/^\[(.*?)\]\s*(.*)$/);
        const when = m ? new Date(m[1]) : new Date();
        let msg = m ? m[2] : line;
        // 사용자에게 불필요한 결과 JSON은 제거
        msg = msg.replace(/\s*\{[^}]*\}\s*$/, '');
        const { text, kind } = humanizeMessage(msg);
        appendLog(text, kind, when);
    }
}

function humanizeMessage(msg) {
    // 핵심 메시지를 더 친근하게 변환하고 배지 종류를 지정
    if (msg.includes('자동화를 시작합니다')) return { text: '자동화를 시작했어요.', kind: 'info' };
    if (msg.includes('로그인 페이지로 이동')) return { text: 'SRT 로그인 페이지로 이동 중이에요.', kind: 'info' };
    if (msg.includes('열차 조회 페이지로 이동')) return { text: '열차 조회 페이지로 이동 중이에요.', kind: 'info' };
    if (msg.includes('조건 입력 완료')) return { text: '조회 조건을 입력했고 결과를 확인하고 있어요.', kind: 'info' };
    if (msg.match(/재조회\s+\d+회/)) return { text: msg.replace('재조회', '재조회 진행'), kind: 'info' };
    if (msg.match(/행\s+\d+:\s*예약하기 시도/)) return { text: msg.replace('행', '').replace(': 예약하기 시도', '번째 열차 예약을 시도했어요.'), kind: 'info' };
    if (msg.includes('예약 성공! 결제 화면으로 이동했습니다')) return { text: '예약에 성공했어요! 결제 화면으로 이동했습니다.', kind: 'success' };
    if (msg.includes('조회 결과가 없습니다')) return { text: '아직 조회 결과가 없어요. 잠시 후 다시 확인해요.', kind: 'warn' };
    if (msg.includes('자리 없음')) return { text: '해당 열차는 현재 자리가 없어요. 다시 시도 중...', kind: 'warn' };
    if (msg.includes('오류') || msg.toLowerCase().includes('error')) return { text: `오류: ${msg}`, kind: 'error' };
    return { text: msg, kind: 'info' };
}
