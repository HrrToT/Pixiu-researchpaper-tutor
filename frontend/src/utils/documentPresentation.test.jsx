import { describe, expect, it } from 'vitest';
import { documentDisplayTitle, questionTopic } from './documentPresentation';
import { taskDocumentNavigation } from './taskDocumentNavigation';

describe('document names and identities', () => {
  const papers = [{ id: 'light', title: 'LightGaussian: Unbounded Compression' }];
  it('derives different generic result names from their retained original questions without changing records', () => {
    const first = { id: 'one', title: '对话成果', capability: 'critique', paperIds: ['light'], critique: { question: { original: '/批判 帮我核对画质保持的条件？' } } };
    const second = { id: 'two', title: '对话成果', capability: 'research', question: '/研究 剪枝与 SH 降阶的消融实验方案' };
    const task = { artifacts: [first, second], messages: [], notes: [] };
    const before = JSON.stringify(task);
    expect(taskDocumentNavigation(task, papers).map(entry => entry.title)).toEqual(['LightGaussian：核对画质保持的条件', '剪枝与 SH 降阶的消融实验方案']);
    expect(JSON.stringify(task)).toBe(before);
  });
  it('preserves user names even when they look generic and falls back honestly when no question was retained', () => {
    expect(documentDisplayTitle({ title: '对话成果', titleOrigin: 'user' }, {}, papers)).toBe('对话成果');
    expect(documentDisplayTitle({ title: '对话成果', capability: 'critique', paperIds: ['light'], text: '质量始终没有损失。' }, {}, papers)).toBe('LightGaussian · 批判阅读');
  });
  it('uses the original question of the saved message instead of a later unrelated question', () => {
    const item = { id: 'result', title: '对话成果', sourceMessageId: 'reply' };
    const task = { messages: [{ id: 'question', role: 'user', content: '/比较 请比较压缩与质量的取舍' },
      { id: 'reply', role: 'ai', content: '回答' }, { id: 'later', role: 'user', content: '另一个问题' }] };
    expect(documentDisplayTitle(item, task)).toBe('比较压缩与质量的取舍');
  });
  it('removes command and material syntax but preserves the question rather than inventing a conclusion', () => {
    expect(questionTopic('/批判 @{LightGaussian} 请画质几乎不变可信吗？')).toBe('画质几乎不变可信吗');
  });
});
