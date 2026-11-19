import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge, Button, EmptyState, StatusBadge } from "@/components/ui";

describe("shared UI primitives", () => {
  it("renders an accessible empty state with an action", () => {
    render(<EmptyState title="No exceptions" body="Adjust the filters." action={<Button>Reset</Button>} />);
    expect(screen.getByText("No exceptions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset" })).toBeEnabled();
  });

  it("maps statuses to semantic badges", () => {
    render(
      <div>
        <StatusBadge status="AWAITING_APPROVAL" />
        <StatusBadge status="FAILED" />
        <Badge tone="success">validated</Badge>
      </div>,
    );
    expect(screen.getByText("Awaiting Approval")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("validated")).toBeInTheDocument();
  });
});
