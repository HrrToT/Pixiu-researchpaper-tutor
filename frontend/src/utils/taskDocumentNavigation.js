const titleOf = item => item.title?.trim() || item.text?.slice(0, 30) || '笔记';
const savedTime = item => {
  for (const value of [item.updatedAt, item.createdAt, item.timestamp]) {
    if (value === null || value === undefined || value === '') continue;
    const time = new Date(value).getTime();
    if (Number.isFinite(time)) return time;
  }
  return null;
};

// Presentation only: keep the persisted documents, their titles and their order intact.
export function taskDocumentNavigation(task) {
  const items = [...(task?.notes || []), ...(task?.artifacts || [])];
  const counts = new Map();
  items.forEach(item => counts.set(titleOf(item), (counts.get(titleOf(item)) || 0) + 1));
  const occurrences = new Map();
  return items.map((item, index) => {
    const title = titleOf(item);
    const occurrence = (occurrences.get(title) || 0) + 1;
    occurrences.set(title, occurrence);
    const time = savedTime(item);
    const details = [];
    if (counts.get(title) > 1) {
      details.push(`记录 ${occurrence}`);
      const page = item.pageIndex ?? item.source?.sourcePageIndex ?? item.sources?.[0]?.pageIndex;
      if (Number.isInteger(page) && page >= 0) details.push(`第 ${page + 1} 页`);
      if (time !== null) {
        details.push(new Date(time).toLocaleString('zh-CN', {
          year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
        }));
      } else {
        const excerpt = item.source?.text || item.sources?.[0]?.text;
        if (excerpt?.trim()) details.push(excerpt.replace(/\s+/g, ' ').trim().slice(0, 36));
      }
    }
    return { item, title, detail: details.join(' · '), time, index };
  }).sort((a, b) => {
    if (a.time !== null && b.time !== null) return b.time - a.time || a.index - b.index;
    if (a.time !== null) return -1;
    if (b.time !== null) return 1;
    return a.index - b.index;
  });
}
