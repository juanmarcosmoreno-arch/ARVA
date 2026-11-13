const { chromium } = require('playwright');
(async () => {
  const [, , htmlPath, base, scale] = process.argv;
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: Number(scale || 3) });
  await p.goto('file://' + htmlPath);
  const el = await p.$('svg');
  const box = await el.boundingBox();
  await p.setViewportSize({ width: Math.ceil(box.width), height: Math.ceil(box.height) });
  await el.screenshot({ path: base + '.png' });
  await p.pdf({ path: base + '.pdf', width: Math.ceil(box.width) + 'px', height: Math.ceil(box.height) + 'px', printBackground: true, pageRanges: '1' });
  await b.close();
})();
