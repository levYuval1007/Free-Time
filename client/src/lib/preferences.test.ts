import { describe, expect, it } from "vitest";
import { MAX_PREFERENCES_LENGTH, PREFERENCE_TAGS, hasTerm, toggleTerm } from "./preferences";

describe("hasTerm", () => {
  it("finds a phrase on its own, ignoring case and spaces", () => {
    expect(hasTerm("Quiet places,  Coffee ", "coffee")).toBe(true);
  });

  it("does not count a word inside a longer phrase", () => {
    expect(hasTerm("quiet places", "quiet")).toBe(false);
  });

  it("is false for an empty field", () => {
    expect(hasTerm("", "coffee")).toBe(false);
  });
});

describe("toggleTerm", () => {
  it("fills an empty field", () => {
    expect(toggleTerm("", "coffee")).toBe("coffee");
  });

  it("adds after what the traveller wrote", () => {
    expect(toggleTerm("good views", "quiet")).toBe("good views, quiet");
  });

  it("copes with a trailing comma or spaces", () => {
    expect(toggleTerm("good views, ", "quiet")).toBe("good views, quiet");
  });

  it("removes a term that is already there and keeps the rest as typed", () => {
    expect(toggleTerm("good views, coffee, Quiet", "coffee")).toBe("good views, Quiet");
    expect(toggleTerm("coffee", "coffee")).toBe("");
  });

  it("adds twice and removes twice", () => {
    const once = toggleTerm("a", "nature");
    expect(toggleTerm(once, "nature")).toBe("a");
  });

  it("leaves the text alone when it would pass the length limit", () => {
    const long = "x".repeat(MAX_PREFERENCES_LENGTH - 3);
    expect(toggleTerm(long, "coffee")).toBe(long);
  });
});

describe("PREFERENCE_TAGS", () => {
  it("have a distinct term each", () => {
    const terms = PREFERENCE_TAGS.map((tag) => tag.term);
    expect(new Set(terms).size).toBe(terms.length);
  });
});
