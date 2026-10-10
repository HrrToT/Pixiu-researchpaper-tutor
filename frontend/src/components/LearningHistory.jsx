import React from 'react';
import { ChevronRight } from 'lucide-react';

const statusLabel = activity => activity.imported ? '已保存'
  : activity.status === 'finished' ? '已结束' : activity.status === 'paused' ? '已暂停' : '已保存';
const feedbackLabels = { hint: '提示', remediate: '补课', ask: '追问反馈', skip: '跳过反馈' };

export default function LearningHistory({ activities, papers }) {
  if (!activities.length) return null;
  return <details className="unified-learning-history">
    <summary className="unified-learning-history-toggle"><ChevronRight size={14} aria-hidden="true" />学习记录（{activities.length}）</summary>
    <div className="unified-learning-history-list">
      {activities.map((activity, index) => {
        const paperId = activity.pdfId || activity.primaryPaperId;
        const paper = papers.find(item => item.id === paperId);
        const title = paper?.title || paper?.filename || '论文';
        const shortTitle = title.split(/[:：]/u)[0].trim() || title;
        const mode = activity.mode === 'quiz' ? '自测' : '精读';
        const concepts = activity.concepts || [];
        const turns = activity.turns || [];
        return <details className="unified-learning-record" key={activity.activityId || activity.id || index}>
          <summary className="unified-learning-record-toggle">
            <ChevronRight size={13} aria-hidden="true" />
            <span className="unified-learning-record-mode">{mode}</span>
            <span className="unified-learning-record-title" title={title}>{shortTitle}</span>
            <span className="unified-learning-record-status">{statusLabel(activity)}</span>
          </summary>
          <div className="unified-learning-record-body">
            <p className="unified-learning-record-paper">{title}</p>
            {concepts.length ? concepts.map((concept, conceptIndex) => <section key={concept.id || conceptIndex}>
              <h3>问题{concepts.length > 1 ? ` ${conceptIndex + 1}` : ''}</h3>
              <p>{concept.question || concept.label || activity.goal || '已保存学习记录'}</p>
              {turns.filter(turn => turn.conceptId === concept.id).map((turn, turnIndex) => <LearningTurn key={turnIndex} turn={turn} />)}
            </section>) : activity.goal && <p>{activity.goal}</p>}
            {turns.filter(turn => !concepts.some(concept => concept.id === turn.conceptId)).map((turn, turnIndex) => <LearningTurn key={`other-${turnIndex}`} turn={turn} />)}
          </div>
        </details>;
      })}
    </div>
  </details>;
}

function LearningTurn({ turn }) {
  return <div className="unified-learning-record-turn">
    {turn.text && ['answer', 'ask'].includes(turn.action) && <><h3>{turn.action === 'ask' ? '你的追问' : '你的回答'}</h3><p>{turn.text}</p></>}
    {turn.feedback && <><h3>{feedbackLabels[turn.action] || '反馈'}</h3><p>{turn.feedback}</p></>}
  </div>;
}
