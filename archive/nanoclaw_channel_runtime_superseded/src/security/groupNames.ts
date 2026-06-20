const GROUP_NAME_RE = /^[a-zA-Z0-9_-]+$/;

export function validateGroupName(name: string): boolean {
  if (!name || name.length === 0 || name.length > 64) return false;
  if (!GROUP_NAME_RE.test(name)) return false;
  if (name.includes('..') || name.includes('./') || name.includes('//')) return false;
  return true;
}
