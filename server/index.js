import express from 'express';
import cors from 'cors';
import { runSrtAutomation } from './srt.js';

const app = express();
app.use(cors());
app.use(express.json({ limit: '200kb' }));

let job = {
  running: false,
  logs: [],
  state: 'idle',
  cancel: null,
  result: null,
};

function addLog(...args) {
  const ts = new Date().toISOString();
  const line = `[${ts}] ${args.join(' ')}`;
  job.logs.push(line);
  if (job.logs.length > 5000) job.logs.splice(0, job.logs.length - 5000);
  console.log(line);
}

app.post('/start', async (req, res) => {
  if (job.running) {
    return res.status(409).json({ ok: false, message: '이미 실행 중입니다.' });
  }
  const {
    userId,
    password,
    departureStation,
    arrivalStation,
    date, // YYYY-MM-DD
    time, // HH:mm
    numToCheck,
    mode, // 'reserve' | 'waitlist'
    headless = false,
  } = req.body || {};

  if (!userId || !password) {
    return res.status(400).json({ ok: false, message: '아이디/비밀번호는 필수입니다.' });
  }
  if (!departureStation || !arrivalStation) {
    return res.status(400).json({ ok: false, message: '출발역/도착역을 입력하세요.' });
  }
  if (!date || !time) {
    return res.status(400).json({ ok: false, message: '출발일자/시간을 입력하세요.' });
  }

  job.running = true;
  job.logs = [];
  job.state = 'starting';
  job.result = null;
  let cancelled = false;
  job.cancel = () => { cancelled = true; };

  addLog('자동화를 시작합니다.');

  runSrtAutomation(
    {
      userId,
      password,
      departureStation,
      arrivalStation,
      date,
      time,
      numToCheck: Number(numToCheck) || 3,
      mode,
      headless: !!headless,
    },
    (msg) => addLog(msg),
    () => cancelled,
  )
    .then((result) => {
      job.result = result;
      job.state = 'finished';
      // 사용자용 로그에는 결과 JSON을 노출하지 않습니다.
      addLog('자동화가 완료되었습니다.');
    })
    .catch((err) => {
      job.result = { ok: false, error: String(err && err.message ? err.message : err) };
      job.state = 'error';
      addLog('오류 발생:', String(err && err.stack ? err.stack : err));
    })
    .finally(() => {
      job.running = false;
      job.cancel = null;
    });

  res.json({ ok: true, message: '백그라운드에서 시작했습니다.' });
});

app.post('/stop', async (_req, res) => {
  if (job.running && typeof job.cancel === 'function') {
    job.cancel();
    addLog('중지 요청을 보냈습니다. 정리 중...');
    return res.json({ ok: true });
  }
  return res.status(409).json({ ok: false, message: '실행 중이 아닙니다.' });
});

app.get('/status', async (_req, res) => {
  const last = job.logs.slice(-200);
  res.json({
    running: job.running,
    state: job.state,
    logs: last,
    result: job.result,
  });
});

const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`SRT autoreserver backend on http://localhost:${port}`);
});
