export const MAX_PREFERENCES_LENGTH = 500;

export interface PreferenceTag {
  emoji: string;
  label: string;
  term: string; // what is written into the field; the agent reads it as free text
}

export const PREFERENCE_TAGS: PreferenceTag[] = [
  { emoji: "☕", label: "Coffee", term: "coffee" },
  { emoji: "🌳", label: "Nature", term: "nature" },
  { emoji: "🎨", label: "Culture", term: "culture" },
  { emoji: "👨‍👩‍👧", label: "Kids-friendly", term: "kids-friendly" },
  { emoji: "🤫", label: "Quiet", term: "quiet" },
];

// The field is read as comma-separated phrases; a tag is on when it is one of them, so "quiet places" does not count.
function phrases(text: string): string[] {
  return text
    .split(",")
    .map((phrase) => phrase.trim())
    .filter((phrase) => phrase !== "");
}

export function hasTerm(text: string, term: string): boolean {
  return phrases(text).some((phrase) => phrase.toLowerCase() === term.toLowerCase());
}

// Adds the term after what the traveller wrote, or removes it again, leaving every other phrase as typed.
export function toggleTerm(text: string, term: string): string {
  if (hasTerm(text, term)) {
    return phrases(text)
      .filter((phrase) => phrase.toLowerCase() !== term.toLowerCase())
      .join(", ");
  }
  const kept = phrases(text).join(", ");
  const next = kept === "" ? term : `${kept}, ${term}`;
  return next.length > MAX_PREFERENCES_LENGTH ? text : next;
}
