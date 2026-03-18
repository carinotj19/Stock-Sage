import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../src/App";


describe("Dashboard rendering", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => []
      })
    );
  });

  it("renders all major dashboard sections", async () => {
    render(<App />);

    expect(await screen.findByText("Low Stock Alerts")).toBeInTheDocument();
    expect(await screen.findByText("Predicted Stockout Timeline")).toBeInTheDocument();
    expect(await screen.findByText("Price Comparison Results")).toBeInTheDocument();
    expect(screen.queryByText("Sales Trend")).not.toBeInTheDocument();
  });
});
