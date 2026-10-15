import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({ viewer: null, jump: vi.fn(), zoom: vi.fn() }));
vi.mock('@react-pdf-viewer/core', () => ({ SpecialZoomLevel: { PageWidth: 'PageWidth' }, Worker: ({ children }) => children,
  Viewer: props => {
    state.viewer = props;
    React.useEffect(() => { props.plugins.forEach(plugin => plugin.install({ jumpToPage: state.jump, zoom: state.zoom })); }, [props.plugins]);
    return <div data-testid="source-pdf" />;
  } }));
vi.mock('../services/taskResearchApi', () => ({ taskResearchApi: { sourceFile: vi.fn() } }));
import { taskResearchApi } from '../services/taskResearchApi';
import ExternalResearchReader from './ExternalResearchReader';

const source = { taskId: 'task', runId: 'run', sourceId: 'source', title: 'Public paper', pageIndex: 4,
  contentHash: 'a'.repeat(64), url: 'https://arxiv.org/abs/2601.00001v2' };
beforeEach(() => {
  state.jump.mockReset(); state.zoom.mockReset(); taskResearchApi.sourceFile.mockReset();
  URL.createObjectURL = vi.fn(() => 'blob:saved-pdf'); URL.revokeObjectURL = vi.fn();
});

it('reads the saved version at its cited page and only adds materials on explicit action', async () => {
  taskResearchApi.sourceFile.mockResolvedValue(new Blob(['%PDF-fixture'], { type: 'application/pdf' }));
  const add = vi.fn().mockResolvedValue({ paperId: 'added.pdf' });
  const open = vi.fn();
  const view = render(<ExternalResearchReader source={source} onAddSource={add} onOpenPaper={open} />);
  await screen.findByTestId('source-pdf');
  expect(taskResearchApi.sourceFile).toHaveBeenCalledWith('task', 'run', 'source', expect.any(AbortSignal));
  expect(add).not.toHaveBeenCalled(); expect(open).not.toHaveBeenCalled();
  expect(state.viewer.initialPage).toBe(4);
  act(() => state.viewer.onDocumentLoad({ doc: { numPages: 18 } }));
  expect(state.jump).toHaveBeenLastCalledWith(4);
  fireEvent.click(screen.getByRole('button', { name: '下一页' }));
  expect(state.jump).toHaveBeenLastCalledWith(5);
  fireEvent.click(screen.getByRole('button', { name: '加入任务材料' }));
  await screen.findByRole('button', { name: '打开任务论文' });
  expect(add).toHaveBeenCalledTimes(1); expect(add).toHaveBeenCalledWith('task', 'run', 'source');
  fireEvent.click(screen.getByRole('button', { name: '打开任务论文' }));
  expect(open).toHaveBeenCalledWith('added.pdf');
  view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:saved-pdf');
});

it('ignores late bytes from the previous task and aborts its request', async () => {
  let finishFirst;
  taskResearchApi.sourceFile.mockImplementationOnce(() => new Promise(resolve => { finishFirst = resolve; }))
    .mockResolvedValueOnce(new Blob(['%PDF-current'], { type: 'application/pdf' }));
  const view = render(<ExternalResearchReader source={source} />);
  const firstSignal = taskResearchApi.sourceFile.mock.calls[0][3];
  view.rerender(<ExternalResearchReader source={{ ...source, taskId: 'other', runId: 'new', sourceId: 'new-source' }} />);
  await screen.findByTestId('source-pdf');
  expect(firstSignal.aborted).toBe(true);
  await act(async () => finishFirst(new Blob(['%PDF-old'], { type: 'application/pdf' })));
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
});

it('has an explicit read retry and keeps missing fulltext as an error', async () => {
  taskResearchApi.sourceFile.mockRejectedValueOnce(new Error('全文未保存'))
    .mockResolvedValueOnce(new Blob(['%PDF-current'], { type: 'application/pdf' }));
  render(<ExternalResearchReader source={source} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('全文未保存');
  expect(taskResearchApi.sourceFile).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: '重新打开' }));
  await screen.findByTestId('source-pdf');
  await waitFor(() => expect(taskResearchApi.sourceFile).toHaveBeenCalledTimes(2));
});
