import { describe, expect, it } from "vitest";
import { toValue } from "./arrival";
import {
  DAY_COUNT, HOURS, MINUTES, clampSelection, dateToSelection, dayLabel, dayLabels, describeValue, earliest, initialSelection,
  selectionToDate, selectionToValue,
} from "./wheel";

const at = (hours: number, minutes: number, seconds = 0) => new Date(2026, 9, 21, hours, minutes, seconds); // Wed Oct 21

describe("the wheels", () => {
  it("have 24 hours and minutes in steps of five", () => {
    expect(HOURS).toHaveLength(24);
    expect(HOURS[0]).toBe("00");
    expect(HOURS[23]).toBe("23");
    expect(MINUTES).toHaveLength(12);
    expect(MINUTES.slice(0, 3)).toEqual(["00", "05", "10"]);
    expect(MINUTES[11]).toBe("55");
  });

  it("show today, tomorrow and then dates", () => {
    const labels = dayLabels(at(17, 34));
    expect(labels).toHaveLength(DAY_COUNT);
    expect(labels.slice(0, 4)).toEqual(["Today", "Tomorrow", "Fri Oct 23", "Sat Oct 24"]);
  });

  it("roll the date over a month end", () => {
    expect(dayLabel(2, new Date(2026, 9, 31, 10, 0))).toBe("Mon Nov 2");
  });
});

describe("earliest", () => {
  it("is the next five minutes", () => {
    expect(toValue(earliest(at(17, 34)))).toBe("2026-10-21T17:35");
  });

  it("is never the current moment", () => {
    expect(toValue(earliest(at(17, 35)))).toBe("2026-10-21T17:40");
    expect(toValue(earliest(at(17, 35, 20)))).toBe("2026-10-21T17:40");
  });

  it("crosses midnight", () => {
    expect(toValue(earliest(at(23, 58)))).toBe("2026-10-22T00:00");
  });
});

describe("selection and date", () => {
  const now = at(17, 34);

  it("round trip", () => {
    const selection = { day: 2, hour: 9, minute: 45 };
    expect(dateToSelection(selectionToDate(selection, now), now)).toEqual(selection);
  });

  it("builds the datetime-local value", () => {
    expect(selectionToValue({ day: 1, hour: 7, minute: 5 }, now)).toBe("2026-10-22T07:05");
  });

  it("reads minutes that are not on a step down to the step", () => {
    expect(dateToSelection(at(18, 38), now).minute).toBe(35);
  });
});

describe("clampSelection", () => {
  const now = at(17, 34);

  it("moves a time in the past to the earliest choosable time", () => {
    expect(clampSelection({ day: 0, hour: 9, minute: 0 }, now)).toEqual({ day: 0, hour: 17, minute: 35 });
  });

  it("moves the current minute forward", () => {
    expect(clampSelection({ day: 0, hour: 17, minute: 30 }, now)).toEqual({ day: 0, hour: 17, minute: 35 });
  });

  it("keeps a time that is ahead", () => {
    const selection = { day: 0, hour: 17, minute: 35 };
    expect(clampSelection(selection, now)).toBe(selection);
  });

  it("keeps earlier hours on another day", () => {
    const selection = { day: 1, hour: 6, minute: 0 };
    expect(clampSelection(selection, now)).toBe(selection);
  });

  it("goes to tomorrow when the earliest time is after midnight", () => {
    expect(clampSelection({ day: 0, hour: 0, minute: 0 }, at(23, 58))).toEqual({ day: 1, hour: 0, minute: 0 });
  });
});

describe("initialSelection", () => {
  const now = at(17, 34);

  it("opens on the current value", () => {
    expect(initialSelection("2026-10-22T09:15", now)).toEqual({ day: 1, hour: 9, minute: 15 });
  });

  it("opens one hour from now when there is no value", () => {
    expect(initialSelection("", now)).toEqual({ day: 0, hour: 18, minute: 35 });
  });

  it("does not open on a time that has passed", () => {
    expect(initialSelection("2026-10-21T08:00", now)).toEqual({ day: 0, hour: 17, minute: 35 });
  });

  it("ignores a value that is not a date", () => {
    expect(initialSelection("soon", now)).toEqual({ day: 0, hour: 18, minute: 35 });
  });
});

describe("describeValue", () => {
  const now = at(17, 34);

  it("names today and tomorrow", () => {
    expect(describeValue("2026-10-21T18:35", now)).toBe("Today 18:35");
    expect(describeValue("2026-10-22T09:00", now)).toBe("Tomorrow 09:00");
  });

  it("names the date after that", () => {
    expect(describeValue("2026-10-23T09:05", now)).toBe("Fri Oct 23 09:05");
  });
});
