import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
}));

import ModuleScreen from "./ModuleScreen";

describe("ModuleScreen admin gate", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiGetMock.mockResolvedValue({});
  });

  it("refuses an administrative tool to a farmer", () => {
    render(
      <ModuleScreen
        moduleKey="mlops"
        onBack={vi.fn()}
        user={{ role: "farmer" }}
      />,
    );

    expect(screen.getByText("Restricted")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This tool is for administrators and agricultural experts.",
      ),
    ).toBeInTheDocument();
    // The tool's own panel header is never mounted for an unauthorised role.
    expect(
      screen.queryByText("Settings & Administration"),
    ).not.toBeInTheDocument();
  });

  it("lets an authorised agricultural expert through", async () => {
    render(
      <ModuleScreen
        moduleKey="soil"
        onBack={vi.fn()}
        user={{ role: "agricultural_expert" }}
      />,
    );

    expect(await screen.findByText("Soil Health")).toBeInTheDocument();
    expect(screen.queryByText("Restricted")).not.toBeInTheDocument();
  });

  it("labels a module with its consolidated section, not its old group", async () => {
    render(<ModuleScreen moduleKey="soil" onBack={vi.fn()} />);

    expect(await screen.findByText("My Farm")).toBeInTheDocument();
  });

  it("keeps a plain farm tool open to a farmer", async () => {
    render(
      <ModuleScreen
        moduleKey="soil"
        onBack={vi.fn()}
        user={{ role: "farmer" }}
      />,
    );

    expect(await screen.findByText("Soil Health")).toBeInTheDocument();
    expect(screen.queryByText("Restricted")).not.toBeInTheDocument();
  });
});
