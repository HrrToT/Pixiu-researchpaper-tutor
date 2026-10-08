export type MentionMaterial = { id: string; title?: string; filename?: string };

/** Completion replaces only the current mention, leaving the question intact. */
export function pendingMaterialMention(text: string) {
  const match = /(?:^|\s)@([^{}@\n]*)$/u.exec(text);
  return match ? { start: text.lastIndexOf('@'), query: match[1].trim().toLocaleLowerCase() } : null;
}

export function completeMaterialMention(text: string, material: MentionMaterial, materials: MentionMaterial[]) {
  const pending = pendingMaterialMention(text);
  if (!pending) return text;
  const label = material.title || material.filename || material.id;
  const ambiguous = materials.some(other => other.id !== material.id && [other.title, other.filename, other.id].includes(label));
  const reference = ambiguous || /[{}]/u.test(label) ? material.id : label;
  return `${text.slice(0, pending.start)}@{${reference}} `;
}
