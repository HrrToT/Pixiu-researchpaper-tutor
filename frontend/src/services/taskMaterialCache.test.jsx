import { expect, it, vi } from 'vitest';
import { loadTaskMaterial } from './taskMaterialCache';

function cache(initial = {}) {
  const values = new Map(Object.entries(initial));
  return { get: vi.fn(async (store, id) => values.get(`${store}:${id}`)), values,
    put: vi.fn(async (store, value, id) => values.set(`${store}:${id}`, value)),
    transaction: vi.fn(() => ({ done: Promise.resolve(), objectStore: store => ({ put: async (value, id) => values.set(`${store}:${id}`, value) }) })) };
}
it('restores a file and its analysis to an empty independent client cache', async () => {
  const db = cache();
  const blob = new Blob(['%PDF-1.4']);
  const analysis = { pdfId: 'paper', title: 'Title' };
  const api = { getMaterialFile: vi.fn(async () => blob), getMaterialAnalysis: vi.fn(async () => analysis) };
  const result = await loadTaskMaterial(db, api, 'task', 'paper');
  expect(result.record.blob).toBe(blob);
  expect(result.deconstruct).toEqual(analysis);
  expect(api.getMaterialFile).toHaveBeenCalledWith('task', 'paper');
  expect(db.values.get('pdfStore:paper')).toBe(blob);
  await loadTaskMaterial(db, api, 'task', 'paper');
  expect(api.getMaterialFile).toHaveBeenCalledTimes(1);
});
it('does not cache mismatched analysis or discard existing annotations', async () => {
  const db = cache({ 'highlightStore:paper': [{ id: 'annotation' }] });
  const api = { getMaterialFile: async () => new Blob(['pdf']), getMaterialAnalysis: async () => ({ pdfId: 'outside' }) };
  await expect(loadTaskMaterial(db, api, 'task', 'paper')).rejects.toThrow('不匹配');
  expect(db.transaction).not.toHaveBeenCalled();
  expect(db.values.get('highlightStore:paper')).toEqual([{ id: 'annotation' }]);
});
it('keeps a usable local file when the missing remote analysis fails', async () => {
  const blob = new Blob(['pdf']);
  const db = cache({ 'pdfStore:paper': blob });
  const api = { getMaterialFile: vi.fn(), getMaterialAnalysis: async () => { throw new Error('offline'); } };
  await expect(loadTaskMaterial(db, api, 'task', 'paper')).rejects.toThrow('offline');
  expect(api.getMaterialFile).not.toHaveBeenCalled();
  expect(db.values.get('pdfStore:paper')).toBe(blob);
});

it('backs up a legacy named file once without invoking analysis', async () => {
  const file = new File(['%PDF-old'], 'old.pdf', { type: 'application/pdf' });
  const analysis = { pdfId: 'old.pdf', status: 'success' };
  const db = cache({ 'pdfStore:old.pdf': file, 'deconstructStore:old.pdf': analysis });
  const api = { importMaterialCache: vi.fn(async () => ({ status: 'success' })) };
  await loadTaskMaterial(db, api, 'task', 'old.pdf');
  await loadTaskMaterial(db, api, 'task', 'old.pdf');
  expect(api.importMaterialCache).toHaveBeenCalledExactlyOnceWith('task', 'old.pdf', file, 'old.pdf', analysis);
});

it('keeps legacy reading available when backup fails and retries on the next open', async () => {
  const file = new File(['%PDF-old'], 'old.pdf');
  const db = cache({ 'pdfStore:old.pdf': file, 'deconstructStore:old.pdf': { pdfId: 'old.pdf', status: 'success' } });
  const api = { importMaterialCache: vi.fn().mockRejectedValue(new Error('offline')) };
  const result = await loadTaskMaterial(db, api, 'task', 'old.pdf');
  expect(result.record.blob).toBe(file);
  expect(result.cacheWarning).toContain('备份未完成');
  await loadTaskMaterial(db, api, 'task', 'old.pdf');
  expect(api.importMaterialCache).toHaveBeenCalledTimes(2);
});

it('uses the authoritative filename when an old browser normalized the name', async () => {
  const file = new File(['%PDF-old'], 'normalized.pdf');
  const analysis = { pdfId: 'paper', status: 'success' };
  const db = cache({ 'pdfStore:paper': file, 'deconstructStore:paper': analysis });
  const api = { listMaterials: vi.fn(async () => [{ id: 'paper', filename: 'Original: title.pdf' }]),
    importMaterialCache: vi.fn(async () => ({})) };
  const result = await loadTaskMaterial(db, api, 'task', 'paper');
  expect(api.importMaterialCache).toHaveBeenCalledExactlyOnceWith('task', 'paper', file, 'Original: title.pdf', analysis);
  expect(result.cacheWarning).toBe('');
});

it('adopts an existing server copy and preserves the prior legacy cache', async () => {
  const file = new File(['%PDF-old'], 'normalized.pdf');
  const analysis = { pdfId: 'paper', status: 'success', title: 'old' };
  const blob = new Blob(['%PDF-server']);
  const result = { ...analysis, title: 'server' };
  const db = cache({ 'pdfStore:paper': file, 'deconstructStore:paper': analysis, 'highlightStore:paper': [{ id: 'h' }] });
  const api = { listMaterials: async () => [{ id: 'paper', filename: 'Original.pdf', fileAvailable: true }],
    getMaterialFile: async () => blob, getMaterialAnalysis: async () => result, importMaterialCache: vi.fn() };
  const restored = await loadTaskMaterial(db, api, 'task', 'paper');
  expect(api.importMaterialCache).not.toHaveBeenCalled();
  expect(restored.record.blob).toBe(blob);
  expect(restored.deconstruct).toEqual(result);
  expect(restored.highlights).toEqual([{ id: 'h' }]);
  expect(db.values.get('metaStore:materialLegacyBackup:paper')).toEqual({ pdf: file, analysis });
  expect(restored.cacheWarning).toBe('');
});
