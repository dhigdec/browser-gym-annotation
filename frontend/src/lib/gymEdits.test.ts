import { describe, expect, it } from "vitest";
import { parseStateEdits } from "./gymEdits";

describe("parseStateEdits", () => {
  it("parses dot-path = value lines with type coercion", () => {
    const edits = parseStateEdits(
      "shop.orders.ORD_1.payment_id = pm_personal\nshop.cart.applied_promo = null\nshop.step = 7\nshop.orders = {}",
    );
    expect(edits["shop.orders.ORD_1.payment_id"]).toBe("pm_personal");
    expect(edits["shop.cart.applied_promo"]).toBeNull();
    expect(edits["shop.step"]).toBe(7);
    expect(edits["shop.orders"]).toEqual({});
  });

  it("ignores free-text notes and blank lines", () => {
    const edits = parseStateEdits("the agent should have used the personal card\n\n  ");
    expect(Object.keys(edits)).toHaveLength(0);
  });
});
