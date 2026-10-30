import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
}));

import FarmActionPlan from "./FarmActionPlan";

const action = (over = {}) => ({
  category: "irrigation",
  action: "Irrigate the tomato field tomorrow before 8 AM.",
  reason: "Soil moisture 22% is below the 42% threshold for flowering tomato.",
  priority: "critical",
  supporting_data: { soil_moisture: 22, threshold: 42 },
  assumptions: [],
  warnings: [],
  ...over,
});

const plan = (over = {}) => ({
  summary: "2 actions need attention today.",
  action_count: 2,
  critical_count: 1,
  high_count: 1,
  actions: [action()],
  data_inputs: {
    farm_name: "Green Valley Farm",
    crop: "Tomato",
    location: "Nashik",
    sensor_available: true,
    weather_available: true,
  },
  weather_summary: null,
  sensor_summary: null,
  generated_at: "2026-10-29T06:15:00Z",
  ...over,
});

describe("FarmActionPlan", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
  });

  it("reads the plan from the existing decision-engine endpoint", async () => {
    apiGetMock.mockResolvedValue(plan());

    render(<FarmActionPlan />);

    expect(await screen.findByText("Today's action plan")).toBeInTheDocument();
    expect(apiGetMock).toHaveBeenCalledWith("/api/dashboard/plan");
  });

  it("shows the priority, the action and the reasoning behind it", async () => {
    apiGetMock.mockResolvedValue(plan());

    render(<FarmActionPlan />);

    expect(await screen.findByText("Critical")).toBeInTheDocument();
    expect(screen.getByText(/Irrigate the tomato field tomorrow/)).toBeInTheDocument();
    expect(screen.getByText(/below the 42% threshold/)).toBeInTheDocument();
    expect(screen.getByText("2 actions need attention today.")).toBeInTheDocument();
    expect(screen.getByText("1 critical")).toBeInTheDocument();
  });

  it("reveals the supporting evidence on request", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(plan());

    render(<FarmActionPlan />);

    await user.click(
      await screen.findByRole("button", { name: /Show evidence/ }),
    );

    expect(screen.getByText(/soil moisture:/)).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Hide evidence/ })).toBeInTheDocument();
  });

  it("links each action to the tool that owns it", async () => {
    const user = userEvent.setup();
    const openModule = vi.fn();
    apiGetMock.mockResolvedValue(plan());

    render(<FarmActionPlan openModule={openModule} />);

    await user.click(
      await screen.findByRole("button", { name: /Open Smart Irrigation/ }),
    );
    expect(openModule).toHaveBeenCalledWith("irrigation");
  });

  it("does not invent a link for a category that has no tool", async () => {
    apiGetMock.mockResolvedValue(
      plan({
        actions: [
          action({
            category: "weather",
            action: "Cover the seedlings before the cold night.",
          }),
        ],
      }),
    );

    render(<FarmActionPlan />);

    await screen.findByText(/Cover the seedlings/);
    expect(screen.queryByRole("button", { name: /^Open / })).not.toBeInTheDocument();
  });

  it("expands past five actions instead of navigating away", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(
      plan({
        action_count: 6,
        actions: Array.from({ length: 6 }, (_, i) =>
          action({ action: `Action number ${i + 1}`, category: "soil" }),
        ),
      }),
    );

    render(<FarmActionPlan />);

    await screen.findByText("Action number 5");
    expect(screen.queryByText("Action number 6")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Show 1 more action/ }));
    expect(screen.getByText("Action number 6")).toBeInTheDocument();
  });

  it("states plainly what the plan could not assess", async () => {
    apiGetMock.mockResolvedValue(
      plan({
        data_inputs: {
          crop: null,
          location: null,
          sensor_available: false,
          weather_available: false,
        },
      }),
    );

    render(<FarmActionPlan />);

    expect(
      await screen.findByText("What this plan could not assess"),
    ).toBeInTheDocument();
    expect(screen.getByText(/No sensor readings/)).toBeInTheDocument();
    expect(screen.getByText(/No weather data/)).toBeInTheDocument();
    expect(screen.getByText(/No current crop set/)).toBeInTheDocument();
    expect(screen.getByText(/Farm location not set/)).toBeInTheDocument();
  });

  it("shows no gap list when the engine had everything it needed", async () => {
    apiGetMock.mockResolvedValue(plan());

    render(<FarmActionPlan />);

    await screen.findByText("Today's action plan");
    expect(
      screen.queryByText("What this plan could not assess"),
    ).not.toBeInTheDocument();
  });

  it("offers farm setup when there is nothing to plan for", async () => {
    const user = userEvent.setup();
    const openModule = vi.fn();
    apiGetMock.mockResolvedValue(plan({ actions: [], summary: "No farm yet." }));

    render(<FarmActionPlan openModule={openModule} />);

    expect(await screen.findByText("No recommendations yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Add a farm/ }));
    expect(openModule).toHaveBeenCalledWith("farm-management");
  });

  it("surfaces a backend failure with a retry instead of an empty plan", async () => {
    const user = userEvent.setup();
    apiGetMock
      .mockRejectedValueOnce(new Error("Plan service unavailable"))
      .mockResolvedValueOnce(plan());

    render(<FarmActionPlan />);

    await user.click(await screen.findByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Today's action plan")).toBeInTheDocument();
    expect(apiGetMock).toHaveBeenCalledTimes(2);
  });
});
