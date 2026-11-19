import { describe, expect, it } from "vitest";

import { confidence, formatMoney, formatNumber, formatPercent, humanize, initials } from "@/lib/format";
import { cn } from "@/lib/utils";

describe("format helpers", () => {
  it("formats money with currency and two decimals", () => {
    expect(formatMoney("1234.5", "USD")).toMatch(/1,234\.50/);
    expect(formatMoney(null, "USD")).toBe("—");
  });

  it("formats percentages, confidence and counts", () => {
    expect(formatPercent(12.345)).toBe("12.3%");
    expect(confidence(0.876)).toBe("88%");
    expect(formatNumber(1500)).toMatch(/1,500|1.500/);
  });

  it("humanizes enum values and derives initials", () => {
    expect(humanize("MISSING_PURCHASE_ORDER")).toBe("Missing Purchase Order");
    expect(initials("Narin Chai")).toBe("NC");
  });

  it("merges class names deterministically", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
    const hidden = false as boolean;
    expect(cn("text-sm", hidden && "hidden", "font-semibold")).toContain("font-semibold");
  });
});
