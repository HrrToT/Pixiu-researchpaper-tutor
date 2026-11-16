import { test, expect } from '@playwright/test';

// Actual Java/H2 storage, synthetic loopback upstream, no research/model calls.
test('published research survives browser edit, reload, original restore and stale write', async ({ page, request }, testInfo) => {
  test.skip(!process.env.PIXIU_ISOLATED_RESEARCH_URL, 'Requires the owned empty-database runner');
  const base = process.env.PIXIU_ISOLATED_RESEARCH_URL;
  expect(base).toBe('http://127.0.0.1:8188');
  const taskPath = '/api/task-workspaces/isolated-shared-report';
  const read = async () => (await request.get(base + taskPath)).json();
  const initial = await read();
  const latest = task => task.artifacts.find(item => item.origin === 'latest');
  const machine = task => task.artifacts.find(item => item.origin === 'machine');
  const original = latest(initial).text;
  expect(machine(initial).text).toBe(original);
  const unexpected = [], writes = [];
  await page.setViewportSize({ width: 1366, height: 768 });
  page.setDefaultTimeout(15000);
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) { unexpected.push(req.url()); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const allowedRead = req.method() === 'GET' && (url.pathname.startsWith('/api/task-workspaces') || url.pathname === '/api/papers');
    const allowedWrite = req.method() === 'PUT' && url.pathname === taskPath;
    if (allowedRead || allowedWrite) {
      const response = await request.fetch(base + url.pathname + url.search, { method: req.method(),
        ...(allowedWrite ? { data: req.postDataJSON() } : {}) });
      if (allowedWrite) writes.push(response.status());
      return route.fulfill({ response });
    }
    unexpected.push(req.method() + ' ' + url.pathname);
    return route.fulfill({ status: 501, json: { message: 'Not available in isolated research persistence test' } });
  });
  await page.goto('/');
  const open = async () => {
    await expect(page.getByRole('button', { name: '切换任务' })).toContainText('独立研究成果演练');
    await page.getByRole('article', { name: '研究结果' }).getByRole('button', { name: '打开报告' }).click();
    await expect(page.getByRole('heading', { level: 1, name: '实验方案（尚未执行）' })).toBeVisible();
  };
  await open();
  await expect(page.getByText('暂时无法确认结果', { exact: true })).toHaveCount(0);
  const article = page.getByRole('article', { name: '成果正文' });
  await expect(article.getByRole('columnheader', { name: '组别' })).toBeVisible();
  await article.getByRole('button', { name: /查看引用/ }).click();
  const citation = page.getByRole('dialog', { name: '引用依据' });
  await expect(citation).toContainText('An exact public source statement.');
  await page.screenshot({ path: testInfo.outputPath('exact-evidence.png') });
  await page.keyboard.press('Escape');
  await page.getByRole('heading', { level: 1, name: '实验方案（尚未执行）' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('published-document.png') });
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const revised = original + '\n\n我的补充：先核对实验资源。';
  await page.getByRole('textbox', { name: '编辑笔记与成果' }).fill(revised);
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect.poll(async () => latest(await read()).text).toBe(revised);
  let saved = await read();
  expect(latest(saved).edited).toBe(true);
  expect(latest(saved).sourceRunId).toBe(latest(initial).sourceRunId);
  expect(latest(saved).sources).toEqual(latest(initial).sources);
  expect(machine(saved).text).toBe(original);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await open();
  await expect(article).toContainText('我的补充：先核对实验资源。');
  await article.getByRole('button', { name: /查看引用/ }).click();
  await expect(citation).toContainText('An exact public source statement.');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '成果更多操作' }).click();
  await page.getByRole('button', { name: '历史版本（1）' }).click();
  const history = page.getByRole('dialog', { name: '历史版本' });
  await history.getByRole('combobox', { name: '选择历史版本' }).selectOption('0');
  await history.getByRole('button', { name: '恢复这个版本' }).click();
  await expect.poll(async () => latest(await read()).text).toBe(original);
  saved = await read();
  expect(latest(saved).versions.at(-1).text).toBe(revised);
  expect(machine(saved).text).toBe(original);
  const stale = await request.put(base + taskPath, { data: { ...initial, title: '过期写入不得覆盖' } });
  expect(stale.status()).toBe(409);
  expect(writes.length).toBeGreaterThanOrEqual(2);
  expect(writes.every(status => status === 200)).toBe(true);
  expect(unexpected).toEqual([]);
});
