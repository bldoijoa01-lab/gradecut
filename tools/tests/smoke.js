// 사이트 기능 점검 (Playwright). 하나라도 실패하면 종료 코드 1.
// 실행: tools/tests/run.sh   (또는 서버를 띄운 뒤 BASE=http://localhost:8765/ node tools/tests/smoke.js)
// 실제 cuts.json 값에 기대는 검사(예: 화법과 언어 73.1점 → 2등급 확정)는 컷이 바뀌면 같이 고쳐야 함
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const BASE = process.env.BASE || 'http://localhost:8765/';
const ROOT = path.join(__dirname, '..', '..');

const results = [];
const check = (name, ok, info = '') => { results.push({ name, ok: !!ok, info }); console.log(`${ok ? '✓' : '✗'} ${name}${info ? ' — ' + info : ''}`); };

// 새 페이지: 저장값을 깨끗이 하고 원하는 값만 넣음
async function open(b, { width = 375, store = {}, scheme = 'light', reduce = 'no-preference', url = '' } = {}) {
  const ctx = await b.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, reducedMotion: reduce, acceptDownloads: true });
  const p = await ctx.newPage(); p.errs = [];
  p.on('pageerror', e => p.errs.push(e.message));
  await p.addInitScript(s => { if (!sessionStorage.getItem('__t')) { sessionStorage.setItem('__t', 1); localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); } }, store);
  await p.goto(BASE + url); await p.waitForSelector(url.includes('updates') ? '.day' : '.row', { state: 'attached' });
  return p;
}
const scores = o => JSON.stringify(Object.fromEntries(Object.entries(o).map(([k, v]) => [k, { my: v }])));
const sel = a => JSON.stringify(a);
const rowOf = (p, name) => p.evaluateHandle(n => [...document.querySelectorAll('.row')].find(e => e.innerText.includes(n)), name);
const scrollW = p => p.evaluate(() => document.documentElement.scrollWidth);

(async () => {
  const b = await chromium.launch();

  // 1. 데이터 파일
  const cuts = JSON.parse(fs.readFileSync(path.join(ROOT, 'cuts.json'), 'utf8'));
  const upd = JSON.parse(fs.readFileSync(path.join(ROOT, 'updates.json'), 'utf8'));
  check('cuts.json: 과목마다 id·exam·subject·c(4칸)', cuts.subjects.every(s => s.id && s.exam && s.subject && Array.isArray(s.c) && s.c.length === 4));
  check('cuts.json: 추정 컷(?)마다 90% 범위', cuts.subjects.every(s => s.c.every((v, i) => !String(v).includes('?') || (s.cut_ranges || {})[i + 1])));
  check('updates.json: 항목마다 시각·종류·제목', upd.items.every(i => !isNaN(new Date(i.at)) && ['data', 'feature'].includes(i.kind) && i.title));
  check('updates.json: 미래 시각 없음', upd.items.every(i => new Date(i.at) <= new Date(Date.now() + 5 * 60e3)));

  // 2. 화면 폭마다 오류·가로 넘침·말풍선
  for (const width of [360, 375, 414]) {
    const p = await open(b, { width, store: { 'gradecut-my-electives': sel(['물질과 에너지', '역학과 에너지', '경제']), 'gradecut-my-scores': scores({ '2026-2mid-chem': '48', '2026-2mid-calc': '88.4', '2026-2mid-hwaeon': '73.1' }) } });
    await p.waitForTimeout(2900);
    let worst = await scrollW(p);
    for (const el of await p.$$('[data-tip]')) { if (!(await el.isVisible())) continue; await el.focus(); worst = Math.max(worst, await scrollW(p)); }
    check(`${width}px: 가로 넘침 없음(말풍선 포함)`, worst <= width, `최대 ${worst}`);
    check(`${width}px: 콘솔 오류 없음`, !p.errs.length, p.errs.join(' / '));
    await p.context().close();
  }

  // 3. 등급 확률·확정·입력 검사
  {
    const p = await open(b, { reduce: 'reduce', store: { 'gradecut-my-electives': sel(['물질과 에너지']), 'gradecut-my-scores': scores({ '2026-2mid-chem': '48', '2026-2mid-hwaeon': '73.1' }) } });
    const chem = await rowOf(p, '물질과'), hw = await rowOf(p, '화법과');
    check('화학 48점: 등급 확률 표시', /\d+%\s*\d등급일 확률/.test(await chem.$eval('.gprob', e => e.innerText.replace(/\n/g, ' '))));
    check('화법과 언어 73.1점: 2등급 확정', /2등급\s*확정/.test(await hw.$eval('.gprob', e => e.innerText.replace(/\n/g, ' '))));
    check('확정에도 확률 막대(100%)', (await hw.$$('.gprob .sp-bar i')).length === 5);
    await p.fill('#my-2026-2mid-chem', '150'); await p.press('#my-2026-2mid-chem', 'Enter'); await p.waitForTimeout(150);
    check('150점: 빨간 칸 + 계산 안 함', await p.$eval('#my-2026-2mid-chem', e => e.classList.contains('bad')) && !(await (await rowOf(p, '물질과')).$('.gprob')));
    await p.fill('#my-2026-2mid-chem', '-5'); await p.press('#my-2026-2mid-chem', 'Enter'); await p.waitForTimeout(150);
    check('-5점: 5점으로 읽지 않음', await p.$eval('#my-2026-2mid-chem', e => e.classList.contains('bad')));
    check('요약 카드: 평균 등급', await p.$eval('#summary', e => !e.hidden && /평균 등급/.test(e.innerText)));
    await p.context().close();
  }

  // 4. 값이 바뀌면 이어서 움직임 (확률 막대 칸 합 100%, 중간값 존재)
  {
    const p = await open(b, { width: 390, store: { 'gradecut-my-electives': '[]', 'gradecut-my-scores': scores({ '2026-2mid-hwaeon': '73.1' }) } });
    await p.waitForTimeout(2900);
    const segs = () => p.evaluate(() => { const bar = [...document.querySelectorAll('.row')].find(e => e.innerText.includes('화법')).querySelector('.gprob .sp-bar'); const W = bar.getBoundingClientRect().width; return [...bar.children].map(i => i.getBoundingClientRect().width / W * 100); });
    await p.fill('[data-score="2026-2mid-hwaeon"]', '58'); await p.press('[data-score="2026-2mid-hwaeon"]', 'Enter');
    const seq = []; for (let i = 0; i < 16; i++) { seq.push(await segs()); await p.waitForTimeout(50); }   // 다시 그린 뒤 시작하므로 여러 번 재 봄
    const end = seq[seq.length - 1], mids = seq.filter(x => x[1] < 99 && x[1] > end[1] + 1);
    check('확률 막대: 움직이는 중에도 합 100%', seq.every(x => Math.abs(x.reduce((a, b) => a + b, 0) - 100) < 1.5));
    check('확률 막대: 2등급 100% → 중간값 → 끝값', mids.length > 0, `중간 ${mids.map(x => Math.round(x[1])).join(',')} 끝 ${Math.round(end[1])}`);
    await p.context().close();
  }

  // 5. 기말 목표 계산기
  {
    const p = await open(b, { store: { 'gradecut-my-electives': '[]', 'gradecut-my-scores': scores({ '2026-2mid-calc': '80' }) } });
    check('기말 배너 보임', await p.$eval('#promo', e => !e.hidden));
    await p.click('#promo [data-goexam]'); await p.waitForSelector('.sem');
    const R = '.row:nth-of-type(2)';
    check('기말 탭: 학기말 확률', /학기말 1등급 확률/.test(await p.$eval(`${R} .sp`, e => e.innerText)));
    check('기말 탭: 등급별 목표 칸 펼쳐 있음', await p.$eval(`${R} .needs`, e => e.offsetHeight > 0));
    await p.click(`${R} button.nb.g1`); await p.waitForTimeout(700);
    const goal = await p.$eval('[data-score="semr-2026-2mid-calc"]', e => e.value);
    check('1등급 목표 칸 → 목표 등수·슬라이더 반영', goal && goal === await p.$eval(`${R} .semrange`, e => e.value), `목표 ${goal}등`);
    await p.click('[data-semmode="score"]'); await p.waitForTimeout(200);
    check('목표 점수 모드 전환', /기말 목표 점수/.test(await p.$eval(`${R} .semin`, e => e.innerText)));
    await p.fill('[data-score="perf-2026-2mid-calc"]', '60'); await p.press('[data-score="perf-2026-2mid-calc"]', 'Enter'); await p.waitForTimeout(150);
    check('수행 60점: 빨간 칸', await p.$eval('[data-score="perf-2026-2mid-calc"]', e => e.classList.contains('bad')));
    check('기말 탭 콘솔 오류 없음', !p.errs.length, p.errs.join(' / '));
    await p.context().close();
  }

  // 6. 기말 데이터가 들어온 경우(가짜 데이터): 중간 → 기말 비교
  {
    const ctx = await b.newContext({ viewport: { width: 375, height: 900 } }); const p = await ctx.newPage();
    const j = JSON.parse(JSON.stringify(cuts)); const m = j.subjects.find(s => s.id === '2026-2mid-calc');
    j.subjects.push({ ...m, id: '2026-2fin-calc', exam: '2026 2학기 기말' });
    await p.route('**/cuts.json', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify(j) }));
    await p.addInitScript(s => { localStorage.setItem('gradecut-my-electives', '[]'); localStorage.setItem('gradecut-my-scores', s); }, scores({ '2026-2mid-calc': '70', '2026-2fin-calc': '90' }));
    await p.goto(BASE); await p.waitForSelector('.row', { state: 'attached' });
    await p.click('.chip >> text=2026 2학기 기말'); await p.waitForTimeout(200);
    check('가짜 기말: 중간 → 기말 비교(▲)', /▲/.test(await p.$eval('.cmp', e => e.innerText).catch(() => '')));
    await ctx.close();
  }

  // 7. 다른 기기로 옮기기·테마·추정 숨김
  {
    const p = await open(b, { store: { 'gradecut-my-electives': sel(['경제']), 'gradecut-my-scores': scores({ '2026-2mid-calc': '77' }) } });
    await p.click('#moveBtn'); const link = await p.$eval('#moveLink', e => e.value);
    const q = await (await b.newContext()).newPage(); await q.goto(link); await q.waitForSelector('.row', { state: 'attached' });
    check('옮기기 링크로 점수 복원', await q.$eval('#my-2026-2mid-calc', e => e.value) === '77');
    await q.context().close();
    await p.click('[data-theme-set="dark"]'); await p.waitForTimeout(600); await p.reload(); await p.waitForSelector('.row', { state: 'attached' });
    check('다크 테마 기억', await p.evaluate(() => document.documentElement.dataset.theme) === 'dark');
    const econ = await rowOf(p, '경제');
    check('경제: 추정 숨김 기본', /추정 컷 보기/.test(await econ.$eval('.acts', e => e.innerText)));
    await p.context().close();
  }

  // 8. 업데이트 내역 페이지·링크 미리보기·앱 설치
  {
    const p = await open(b, { url: 'updates.html' });
    check('내역 페이지: 항목 표시', (await p.$$('.day li')).length === upd.items.length);
    await p.click('[data-k="data"]'); check('내역 페이지: 등급컷 필터', (await p.$$('.day li')).length === upd.items.filter(i => i.kind === 'data').length);
    await p.context().close();
    const q = await open(b, {});
    const og = await q.$$eval('meta[property="og:image"], meta[property="og:title"]', ms => ms.length);
    check('링크 미리보기 태그(og:title·og:image)', og === 2);
    const cdp = await q.context().newCDPSession(q); const man = await cdp.send('Page.getAppManifest');
    check('앱 manifest 오류 없음', !man.errors.length && JSON.parse(man.data || '{}').icons?.length >= 2, JSON.stringify(man.errors));
    for (const f of ['og.png', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png']) check(`${f} 있음`, (await q.request.get(BASE + f)).ok());
    await q.context().close();
  }

  await b.close();
  const bad = results.filter(r => !r.ok);
  console.log(`\n${results.length - bad.length}/${results.length} 통과`);
  process.exit(bad.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
