import type { JsonValue } from './types.js';

function searchableText(value: JsonValue): string {
  if (value === null) {
    return '';
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value).toLocaleLowerCase('en-US');
  }
  if (Array.isArray(value)) {
    return value.map(searchableText).join(' ');
  }
  return Object.values(value).map(searchableText).join(' ');
}

export function localFilter(
  items: JsonValue[],
  needles: readonly (string | undefined)[],
): JsonValue[] {
  const active = needles
    .filter((needle): needle is string => Boolean(needle))
    .map((needle) => needle.toLocaleLowerCase('en-US'));
  if (active.length === 0) {
    return items;
  }
  return items.filter((item) => {
    const haystack = searchableText(item);
    return active.every((needle) => haystack.includes(needle));
  });
}
