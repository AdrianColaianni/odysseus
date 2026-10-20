// Unicode-aware text statistics shared by source and rich-text documents.

const WORD_SEGMENTER = new Intl.Segmenter(undefined, { granularity: 'word' });
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, { granularity: 'grapheme' });

export function countDocumentWords(value) {
  const text = String(value ?? '');
  if (!text.trim()) return 0;
  let count = 0;
  for (const segment of WORD_SEGMENTER.segment(text)) {
    if (segment.isWordLike) count += 1;
  }
  return count;
}

export function countDocumentCharacters(value) {
  return Array.from(GRAPHEME_SEGMENTER.segment(String(value ?? ''))).length;
}

export function getDocumentStats(value) {
  const text = String(value ?? '').replace(/\r\n?/g, '\n');
  const words = countDocumentWords(text);
  const characters = countDocumentCharacters(text);
  const charactersNoSpaces = countDocumentCharacters(text.replace(/\s/gu, ''));
  const lineText = text.replace(/\n+$/u, '');
  const lines = lineText ? lineText.split('\n').length : 0;
  return {
    words,
    characters,
    charactersNoSpaces,
    lines,
    readingMinutes: words ? Math.max(1, Math.ceil(words / 225)) : 0,
  };
}
