import { describe, expect, it } from "vitest";
import { calendarDateError } from "../calendar-date-field";

describe("calendar date validation", () => {
  it.each(["2026 02 2", "2026-02-29", "2026-04-31", "0000-01-01", "2026-13-01"])(
    "rejects %s",
    value => expect(calendarDateError(value)).toBe("Enter a valid date or choose one from the calendar."),
  );

  it.each(["0001-01-01", "2028-02-29", "2027-01-01", "9999-12-31"])(
    "accepts %s as a calendar date",
    value => expect(calendarDateError(value)).toBeUndefined(),
  );

  it("requires a decision date and allows an empty action due date", () => {
    expect(calendarDateError("", true)).toBe("Select a decision date.");
    expect(calendarDateError("")).toBeUndefined();
  });
});
