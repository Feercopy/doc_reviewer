import { describe, expect, it } from "vitest";

import { usefulnessForFeedbackRating } from "./feedbackDisplay";

describe("feedback display helpers", () => {
  it("maps the five-point feedback rating onto the existing usefulness contract", () => {
    expect(usefulnessForFeedbackRating(1)).toBe("useless");
    expect(usefulnessForFeedbackRating(2)).toBe("useless");
    expect(usefulnessForFeedbackRating(3)).toBe("partially_useful");
    expect(usefulnessForFeedbackRating(4)).toBe("useful");
    expect(usefulnessForFeedbackRating(5)).toBe("useful");
  });
});
