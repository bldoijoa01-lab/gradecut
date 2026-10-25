// og.png(링크 미리보기)와 앱 아이콘(icon-192/512.png, apple-touch-icon.png)을 tools/og.html에서 찍어 저장소 루트에 만듦
// 실행: node tools/make_assets.js  (Playwright 필요)
const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const root = path.join(__dirname, '..'), b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1300, height: 1300 } });
  await p.goto('file://' + path.join(__dirname, 'og.html')); await p.evaluate(() => document.fonts.ready);
  await (await p.$('#og')).screenshot({ path: path.join(root, 'og.png') });
  const icon = await (await p.$('#icon')).screenshot();
  for (const [name, size] of [['icon-512.png', 512], ['icon-192.png', 192], ['apple-touch-icon.png', 180]]) {
    const q = await b.newPage({ viewport: { width: size, height: size } });
    await q.setContent(`<body style="margin:0"><img src="data:image/png;base64,${icon.toString('base64')}" style="width:${size}px;height:${size}px;display:block">`);
    await q.screenshot({ path: path.join(root, name) }); await q.close();
  }
  await b.close(); console.log('og.png, icon-512.png, icon-192.png, apple-touch-icon.png 만듦');
})();
