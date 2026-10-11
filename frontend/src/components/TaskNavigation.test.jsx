import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TaskNavigation from './TaskNavigation';

const props = () => ({ tasks: [{ id: 'a', title: '任务 A' }, { id: 'b', title: '任务 B' }],
  activeTask: { id: 'a', paperIds: ['p1'], notes: [], artifacts: [] },
  papers: [{ id: 'p1', title: '论文一' }, { id: 'p2', title: '论文二' }], collapsed: false,
  onToggle: vi.fn(), onSelectTask: vi.fn(), onCreateTask: vi.fn(), onOpenPaper: vi.fn(),
  onAddPaper: vi.fn(), onRemovePaper: vi.fn(), onOpenArtifact: vi.fn() });

describe('task navigation', () => {
  it('distinguishes opening a paper from adding a task material', async () => {
    const handlers = props();
    render(<TaskNavigation {...handlers} />);
    fireEvent.click(screen.getByRole('button', { name: '论文一' }));
    expect(handlers.onOpenPaper).toHaveBeenCalledWith('p1');
    expect(handlers.onAddPaper).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('添加已有论文'));
    fireEvent.click(screen.getByRole('button', { name: '论文二' }));
    await waitFor(() => expect(handlers.onAddPaper).toHaveBeenCalledWith('p2'));
  });
  it('shows a persistence failure instead of hiding it', async () => {
    render(<TaskNavigation {...props()} onCreateTask={async () => { throw new Error('保存失败'); }} />);
    fireEvent.click(screen.getByLabelText('新任务'));
    expect(await screen.findByRole('alert')).toHaveTextContent('保存失败');
  });
  it('keeps an accessible restore control when collapsed', () => {
    const handlers = props();
    render(<TaskNavigation {...handlers} collapsed />);
    fireEvent.click(screen.getByLabelText('展开导航'));
    expect(handlers.onToggle).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('当前任务')).not.toBeInTheDocument();
  });
  it('distinguishes duplicate saved results and opens the selected original document', () => {
    const handlers = props();
    const old = { id: 'old', title: '第4页译文', createdAt: '2026-10-08T12:00:00Z', pageIndex: 3, text: '旧译文' };
    const recent = { id: 'recent', title: '第4页译文', createdAt: '2026-10-09T12:00:00Z', pageIndex: 3, text: '新译文' };
    const task = { ...handlers.activeTask, artifacts: [old, recent] };
    const snapshot = JSON.stringify(task);
    render(<TaskNavigation {...handlers} activeTask={task} />);
    const results = screen.getAllByRole('button', { name: /第4页译文/ });
    expect(results[0]).toHaveTextContent('10/09');
    expect(results[1]).toHaveTextContent('10/08');
    fireEvent.click(results[0]);
    expect(handlers.onOpenArtifact).toHaveBeenCalledWith(recent);
    expect(JSON.stringify(task)).toBe(snapshot);
  });
  it('keeps undated notes distinguishable without inventing save times', () => {
    const handlers = props();
    const notes = [{ id: 'n1', title: '原文笔记', source: { text: '第一处选区' } },
      { id: 'n2', title: '原文笔记', createdAt: 'invalid', source: { text: '第二处选区', sourcePageIndex: 2 } }];
    render(<TaskNavigation {...handlers} activeTask={{ ...handlers.activeTask, notes }} />);
    const results = screen.getAllByRole('button', { name: /原文笔记/ });
    expect(results[0]).toHaveTextContent('第一处选区');
    expect(results[1]).toHaveTextContent('第二处选区');
    expect(results[1]).not.toHaveTextContent('Invalid Date');
    fireEvent.click(results[1]);
    expect(handlers.onOpenArtifact).toHaveBeenCalledWith(notes[1]);
  });
});


it('searches document bodies and opens the retained document with the current identity', () => {
  const handlers=props();
  const document={id:'report',type:'research',title:'实验报告',text:'正文中的消融对比'};
  render(<TaskNavigation {...handlers} activeTask={{...handlers.activeTask,artifacts:[document]}} selectedDocumentId="report"/>);
  fireEvent.change(screen.getByRole('textbox',{name:'搜索材料与记录'}),{target:{value:'消融对比'}});
  const link=screen.getByRole('button',{name:'实验报告 · 报告'});
  expect(link).toHaveAttribute('aria-current','page');
  fireEvent.click(link);
  expect(handlers.onOpenArtifact).toHaveBeenCalledWith(document);
  expect(screen.queryByRole('button',{name:'论文一'})).not.toBeInTheDocument();
});

it('opens matching learning questions, answers and feedback independently of document filters', () => {
  const handlers=props(),open=vi.fn();
  const activity={activityId:'learning',pdfId:'p1',status:'paused',concepts:[{id:'c',question:'如何解释稀疏性？'}],
    turns:[{conceptId:'c',action:'answer',text:'计算资源会减少',feedback:'需要补充误差边界'}]};
  render(<TaskNavigation {...handlers} learningRecords={[activity]} onOpenLearning={open} selectedLearningId="learning"/>);
  fireEvent.click(screen.getByRole('button', { name: '筛选成果' }));
  fireEvent.change(screen.getByRole('combobox',{name:'成果类型'}),{target:{value:'translation'}});
  const search=screen.getByRole('textbox',{name:'搜索材料与记录'});
  for(const query of ['稀疏性','计算资源','误差边界']) {
    fireEvent.change(search,{target:{value:query}});
    const link=screen.getByRole('button',{name:'精读 · 论文一 · 已暂停'});
    expect(link.closest('details')).toHaveAttribute('open');
    expect(link).toHaveAttribute('aria-current','page');
    fireEvent.click(link);
    expect(open).toHaveBeenLastCalledWith(activity);
  }
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('does not infer translation from a page anchor and shows a global empty search state', () => {
  const handlers=props();
  const anchored={id:'evidence',pageIndex:3,title:'方法证据',text:'正文'};
  const translation={id:'old-translation',pageIndex:3,title:'第4页译文',text:'中文'};
  render(<TaskNavigation {...handlers} activeTask={{...handlers.activeTask,artifacts:[anchored,translation]}}/>);
  fireEvent.click(screen.getByRole('button', { name: '筛选成果' }));
  fireEvent.change(screen.getByRole('combobox',{name:'成果类型'}),{target:{value:'translation'}});
  expect(screen.getByRole('button',{name:'第4页译文 · 译文'})).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:/方法证据/})).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox',{name:'搜索材料与记录'}),{target:{value:'不存在的关键词'}});
  expect(screen.getByRole('status')).toHaveTextContent('没有匹配的论文、成果或学习记录');
  expect(screen.getByRole('combobox',{name:'成果类型'})).not.toHaveTextContent('学习');
});
