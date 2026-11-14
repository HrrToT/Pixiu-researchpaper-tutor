import { test, expect } from '@playwright/test';

// Opt-in: the runner owns an empty H2 database and a loopback-only Java process.
// Model routes are never forwarded. This tests user-authored artifacts, not research provenance.
test('artifact edits, history restore and stale-write protection use real Java persistence', async ({ page, request }, testInfo) => {
  test.skip(!process.env.PIXIU_ISOLATED_PERSISTENCE_URL, 'Requires an isolated test database');
  const base = process.env.PIXIU_ISOLATED_PERSISTENCE_URL;
  expect(base).toBe('http://127.0.0.1:8187');
  const path = '/api/task-workspaces';
  const original = '合成笔记正文：用于验证保存，不包含真实论文或用户数据。';
  const revised = original + '\n\n我的补充：独立持久化验证。';
  const title = '独立持久化验收笔记';
  await page.setViewportSize({ width: 1366, height: 768 });
  page.setDefaultTimeout(10000);
  expect(await (await request.get(base + path)).json()).toEqual([]);
  const created = await request.post(base + path, { data: {
    id: 'isolated-persistence-20261112', title: '独立持久化测试', paperIds: [], messages: [], notes: [],
    artifacts: [{ id: 'isolated-note', title, text: original, type: 'note', paperIds: [], sources: [], versions: [] }],
    activityHistory: [], researchRuns: [], activeActivity: null,
  } });
  expect(created.status()).toBe(201);
  const initial = await created.json();
  const unexpected = [], writes = [];
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.hostname !== '127.0.0.1') { unexpected.push(req.url()); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const taskPath = `${path}/${initial.id}`;
    if ((req.method() === 'GET' && [path, taskPath].includes(url.pathname)) ||
        (req.method() === 'PUT' && url.pathname === taskPath)) {
      const response = await request.fetch(base + url.pathname, { method: req.method(),
        ...(req.method() === 'PUT' ? { data: req.postDataJSON() } : {}) });
      if (req.method() === 'PUT') writes.push(response.status());
      return route.fulfill({ response });
    }
    if (req.method() === 'GET' && [taskPath + '/materials', taskPath + '/operations'].includes(url.pathname))
      return route.fulfill({ json: [] });
    if (req.method() === 'GET' && url.pathname === taskPath + '/research/capabilities')
      return route.fulfill({ json: { enabled: false, externalSearch: false } });
    unexpected.push(req.method() + ' ' + url.pathname);
    return route.fulfill({ status: 501, json: { message: 'Not permitted in isolated persistence test' } });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '切换任务' })).toContainText('独立持久化测试');
  if (await page.getByRole('button', { name: '展开导航', exact: true }).isVisible())
    await page.getByRole('button', { name: '展开导航', exact: true }).click();
  await page.getByRole('region', { name: '笔记与成果列表' }).getByRole('button', { name: new RegExp('^' + title + ' · ') }).click();
  await expect(page.getByRole('article', { name: '成果正文' })).toContainText(original);
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByRole('textbox', { name: '编辑笔记与成果' }).fill(revised);
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect.poll(async () => (await (await request.get(base + path + '/' + initial.id)).json()).artifacts[0].text).toBe(revised);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await expect(page.getByRole('button', { name: '切换任务' })).toContainText('独立持久化测试');
  if (await page.getByRole('button', { name: '展开导航', exact: true }).isVisible())
    await page.getByRole('button', { name: '展开导航', exact: true }).click();
  await page.getByRole('region', { name: '笔记与成果列表' }).getByRole('button', { name: new RegExp('^' + title + ' · ') }).click();
  await expect(page.getByRole('article', { name: '成果正文' })).toContainText('我的补充');
  await page.getByRole('button', { name: '成果更多操作' }).click();
  await page.getByRole('button', { name: '历史版本（1）' }).click();
  const history = page.getByRole('dialog', { name: '历史版本' });
  await history.getByRole('combobox', { name: '选择历史版本' }).selectOption('0');
  await expect(history).toContainText(original);
  await history.getByRole('button', { name: '恢复这个版本' }).click();
  await expect.poll(async () => (await (await request.get(base + path + '/' + initial.id)).json()).artifacts[0].text).toBe(original);
  const saved = await (await request.get(base + path + '/' + initial.id)).json();
  expect(saved.artifacts[0].versions.at(-1).text).toBe(revised);
  await history.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(page.getByRole('article', { name: '成果正文' })).toContainText(original);
  await expect(page.getByRole('article', { name: '成果正文' })).not.toContainText('我的补充');
  const stale = await request.put(base + path + '/' + initial.id, { data: { ...initial, title: '过期写入不得覆盖' } });
  expect(stale.status()).toBe(409);
  expect((await (await request.get(base + path + '/' + initial.id)).json()).title).toBe('独立持久化测试');
  expect(writes.length).toBeGreaterThanOrEqual(2);
  expect(writes.every(status => status === 200)).toBe(true);
  expect(unexpected).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('persisted-artifact-restored.png') });
});
