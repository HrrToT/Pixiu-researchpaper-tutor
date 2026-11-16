import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import ResearchReportText from './ResearchReportText';
import fixture from './__fixtures__/sharedExperimentReport.json';

// Produced through the Python compiler/audit/publication path with synthetic
// input and mocked verdicts. This checks the interface, never scientific quality.
it('opens the published experiment as a document and restores its exact evidence after an edit', () => {
  const jump = vi.fn();
  const props = { sources: fixture.sources, researchContext: fixture.researchContext, onJumpToSource: jump };
  const view = render(<ResearchReportText {...props} text={fixture.report} />);
  expect(screen.getByRole('heading', { level: 1, name: '实验方案（尚未执行）' })).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: '组别' })).toBeInTheDocument();
  const openEvidence = () => fireEvent.click(screen.getByRole('button', { name: /查看引用/ }));
  openEvidence();
  const dialog = screen.getByRole('dialog', { name: '引用依据' });
  const id = fixture.sources[0].evidenceIds[0];
  expect(within(dialog).getByText(fixture.sources[0].evidenceQuotes[id].quote)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: '查看论文原文' }));
  expect(jump).toHaveBeenCalledWith(expect.objectContaining({ pdfId: fixture.sources[0].pdfId, evidenceId: id }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  view.unmount();
  render(<ResearchReportText {...props} text={`${fixture.report}\n\n我的补充：先核对实验资源。`} />);
  expect(screen.getByText('我的补充：先核对实验资源。')).toBeInTheDocument();
  openEvidence();
  expect(within(screen.getByRole('dialog')).getByText(fixture.sources[0].evidenceQuotes[id].quote)).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(screen.getByRole('button', { name: /查看引用/ })).toHaveFocus();
});
