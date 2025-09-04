import { Builder, By, Key, until } from 'selenium-webdriver';
import chrome from 'selenium-webdriver/chrome.js';

const URLS = {
  login: 'https://etk.srail.co.kr/cmc/01/selectLoginForm.do',
  search: 'https://etk.srail.kr/hpg/hra/01/selectScheduleList.do',
};

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

export async function runSrtAutomation(params, log, isCancelled) {
  const {
    userId,
    password,
    departureStation,
    arrivalStation,
    date, // YYYY-MM-DD
    time, // HH:mm
    numToCheck = 3,
    mode = 'reserve', // or 'waitlist'
    headless = false,
  } = params;

  const yyyymmdd = (date || '').replace(/-/g, '');
  const [selHH = '', selMM = '00'] = (time || '').split(':');
  // 1) 12:00 선택 시 24로 매핑 (사이트 표기 호환)
  const rawHH = selHH === '12' && selMM === '00' ? '24' : selHH;
  // 2) 짝수시 기준으로 내림(예: 19:xx → 18)
  const rawNum = Math.min(24, Math.max(0, parseInt(rawHH || '0', 10) || 0));
  const evenNum = rawNum === 24 ? 24 : rawNum - (rawNum % 2);
  const targetHH = String(evenNum).padStart(2, '0');

  const options = new chrome.Options();
  if (headless) options.addArguments('--headless=new');
  options.addArguments('--disable-gpu');
  // Codespaces/컨테이너 환경 안정화 옵션
  options.addArguments('--no-sandbox');
  options.addArguments('--disable-dev-shm-usage');
  options.addArguments('--window-size=1280,1000');

  let driver;
  try {
    driver = await new Builder().forBrowser('chrome').setChromeOptions(options).build();

    log('로그인 페이지로 이동...');
    await driver.get(URLS.login);
    await driver.manage().setTimeouts({ implicit: 10000 });

    await driver.findElement(By.id('srchDvNm01')).sendKeys(userId);
    await driver.findElement(By.id('hmpgPwdCphd01')).sendKeys(password);
    await driver.findElement(By.css('input.loginSubmit')).click();
    await sleep(1500);

    if (isCancelled()) throw new Error('사용자 중지');

    log('열차 조회 페이지로 이동...');
    await driver.get(URLS.search);
    await driver.manage().setTimeouts({ implicit: 8000 });

    const depField = await driver.findElement(By.id('dptRsStnCdNm'));
    await depField.clear();
    await depField.sendKeys(departureStation);

    const arrField = await driver.findElement(By.id('arvRsStnCdNm'));
    await arrField.clear();
    await arrField.sendKeys(arrivalStation);

    // 날짜 (select by value: YYYYMMDD)
    const dateSel = await driver.findElement(By.id('dptDt'));
    await driver.executeScript("arguments[0].setAttribute('style','display: True;')", dateSel);
    await driver.executeScript(
      "const v=arguments[1]; const el=arguments[0]; const opt=[...el.options].find(o=>o.value===v); if(opt){el.value=opt.value; el.dispatchEvent(new Event('change',{bubbles:true}));}",
      dateSel,
      yyyymmdd,
    );

    // 시간 (select by visible text startsWith HH)
    const timeSel = await driver.findElement(By.id('dptTm'));
    await driver.executeScript("arguments[0].setAttribute('style','display: True;')", timeSel);
    // 시간 옵션 선택: 텍스트가 HH로 시작하거나 value에 HH가 포함된 항목 우선 선택
    const selected = await driver.executeScript(
      "const hh=arguments[1]; const el=arguments[0];\n" +
      "let opt=[...el.options].find(o=>o.textContent.trim().startsWith(hh));\n" +
      "if(!opt){ opt=[...el.options].find(o=>String(o.value||'').includes(hh)); }\n" +
      "if(opt){ el.value=opt.value; el.dispatchEvent(new Event('change',{bubbles:true})); return opt.textContent.trim(); }\n" +
      "return null;",
      timeSel,
      targetHH,
    );
    if (selected) {
      log(`요청 시간 ${selHH}:${selMM} → 적용 시간 ${targetHH}시 (짝수 기준)`);
    } else {
      log(`시간 옵션 선택 실패: ${targetHH}시. 기본값으로 진행합니다.`);
    }

    log('조건 입력 완료. 조회합니다...');
    // 조회하기 클릭
    const queryBtn = await driver.findElement(By.xpath("//input[@value='조회하기']"));
    await driver.executeScript('arguments[0].click();', queryBtn);
    await driver.manage().setTimeouts({ implicit: 10000 });
    await sleep(800);

    let refreshCount = 0;
    while (true) {
      if (isCancelled()) throw new Error('사용자 중지');

      // 상위 N개 행 확인
      const rows = await driver.findElements(By.css('#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr'));
      if (rows.length === 0) {
        log('조회 결과가 없습니다. 계속 재조회합니다.');
      }
      let acted = false;
      for (let i = 1; i <= numToCheck; i++) {
        if (isCancelled()) throw new Error('사용자 중지');
        let seatTxt = '';
        let waitTxt = '';
        try {
          seatTxt = (await driver.findElement(By.css(`#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child(${i}) > td:nth-child(7)`))).getText();
          waitTxt = (await driver.findElement(By.css(`#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child(${i}) > td:nth-child(8)`))).getText();
        } catch (_) {
          // 행이 부족하거나 DOM 갱신
          continue;
        }
        seatTxt = await seatTxt; waitTxt = await waitTxt;

        if (mode !== 'waitlist' && seatTxt.includes('예약하기')) {
          log(`행 ${i}: 예약하기 시도`);
          const a = await driver.findElement(By.css(`#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child(${i}) > td:nth-child(7) > a`));
          try {
            await a.click();
          } catch (_) {
            await a.sendKeys(Key.ENTER);
          }

          // alert 수락 시도
          try {
            await driver.wait(until.alertIsPresent(), 1500);
            const alert = await driver.switchTo().alert();
            log(`알림창: ${await alert.getText()}`);
            await alert.accept();
          } catch (_) {}

          await driver.manage().setTimeouts({ implicit: 3000 });
          const ok = (await driver.findElements(By.id('isFalseGotoMain'))).length > 0;
          if (ok) {
            log('예약 성공! 결제 화면으로 이동했습니다.');
            return { ok: true, type: 'reserve' };
          }
          log('자리 없음. 결과 페이지로 되돌아갑니다.');
          await driver.navigate().back();
          await driver.manage().setTimeouts({ implicit: 5000 });
          acted = true;
        } else if (mode === 'waitlist' && waitTxt.includes('신청하기')) {
          log(`행 ${i}: 예약대기 신청 시도`);
          const a = await driver.findElement(By.css(`#result-form > fieldset > div.tbl_wrap.th_thead > table > tbody > tr:nth-child(${i}) > td:nth-child(8) > a`));
          await a.click();
          return { ok: true, type: 'waitlist' };
        }
      }

      // 다음 조회
      refreshCount += 1;
      log(`재조회 ${refreshCount}회`);
      try {
        const refreshBtn = await driver.findElement(By.xpath("//input[@value='조회하기']"));
        await driver.executeScript('arguments[0].click();', refreshBtn);
      } catch (_) {}
      await driver.manage().setTimeouts({ implicit: 10000 });
      await sleep(2000 + Math.floor(Math.random() * 1500));
    }
  } finally {
    try { if (driver) await driver.quit(); } catch (_) {}
  }
}
