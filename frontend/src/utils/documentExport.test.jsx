import { expect, it } from 'vitest';
import { documentMarkdownExport } from './documentExport';
it('exports the live draft while retaining original paper identities', () => {
  const document = { text: '旧正文', sources: [{ pdfId: 'A', sourceId: 'A-chunk-2', pageIndex: 1 }] };
  const result = documentMarkdownExport(document, '当前正文', [{ id: 'A', title: '论文甲' }]);
  expect(result.startsWith('当前正文\n')).toBe(true);
  expect(result).toContain('论文甲，第 2 页，A-chunk-2');
  expect(document.text).toBe('旧正文');
});
it('does not infer sources when no saved material association exists', () => {
  expect(documentMarkdownExport({}, '', [{ id: 'B', title: '当前阅读论文' }])).toBe('');
});
