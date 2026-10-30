import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
}));

import HomeScreen from "./HomeScreen";

const EMPTY_SUMMARY = {
  farms: 0,
  devices: 0,
  devices_online: 0,
  recent_readings: 0,
  predictions: 0,
  latest_reading: null,
};

const PLAN = {
  summary: "1 action needs attention today.",
  action_count: 1,
  critical_count: 1,
  high_count: 0,
  actions: [
    {
      category: "irrigation",
      action: "Irrigate the tomato field tomorrow before 8 AM.",
      reason: "Soil moisture is below the flowering threshold.",
      priority: "critical",
      supporting_data: {},
      assumptions: [],
      warnings: [],
    },
  ],
  data_inputs: { crop: "Tomato", location: "Nashik", sensor_available: true, weather_available: true },
  generated_at: "2026-10-29T06:15:00Z",
};

const PREDICTION = {
  id: "p1",
  domain: "crop",
  source: "model",
  output: { prediction: "Chickpea" },
  input: {},
  created_at: "2026-10-29T05:00:00Z",
};

/** Route the mocked GET by endpoint, like the real client would. */
function mockApi({ summary = EMPTY_SUMMARY, alerts = { total: 0, unread: 0, items: [] }, predictions = { total: 0, items: [] }, plan = PLAN } = {}) {
  apiGetMock.mockImplementation((url) => {
    if (url.startsWith("/api/dashboard/summary")) return Promise.resolve(summary);
    if (url.startsWith("/api/alerts")) return Promise.resolve(alerts);
    if (url.startsWith("/api/predictions")) return Promise.resolve(predictions);
    if (url === "/api/dashboard/plan") return Promise.resolve(plan);
    return Promise.resolve({});
  });
}

const setup = (props = {}) =>
  render(
    <HomeScreen
      language="English"
      navigate={vi.fn()}
      onOpenProfile={vi.fn()}
      openLanguages={vi.fn()}
      openModule={props.openModule ?? vi.fn()}
      user={{ full_name: "Anita Patil", role: "farmer" }}
    />,
  );

describe("HomeScreen prioritisation", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
  });

  it("gives a brand-new account a setup workflow instead of zero-valued cards", async () => {
    mockApi();

    setup();

    expect(await screen.findByText("Set up your farm")).toBeInTheDocument();
    expect(screen.getByText("Add your farm")).toBeInTheDocument();
    // No misleading "0" statistics anywhere on the first screen.
    expect(screen.queryByText("Farms")).not.toBeInTheDocument();
    expect(screen.queryByText("Sensors online")).not.toBeInTheDocument();
    expect(screen.queryByText("Predictions")).not.toBeInTheDocument();
    expect(screen.queryByText("Your farm today")).not.toBeInTheDocument();
  });

  it("does not run the decision engine when there is no farm to plan for", async () => {
    mockApi();

    setup();

    await screen.findByText("Set up your farm");
    expect(apiGetMock).not.toHaveBeenCalledWith("/api/dashboard/plan");
  });

  it("starts an account with no farm at farm setup", async () => {
    const user = userEvent.setup();
    const openModule = vi.fn();
    mockApi();

    setup({ openModule });
    await user.click(await screen.findByRole("button", { name: /Add your first farm/ }));

    expect(openModule).toHaveBeenCalledWith("farm-management");
  });

  it("leads with today's action plan once a farm exists", async () => {
    mockApi({ summary: { ...EMPTY_SUMMARY, farms: 1 } });

    setup();

    expect(await screen.findByText("Today's action plan")).toBeInTheDocument();
    expect(screen.queryByText("Set up your farm")).not.toBeInTheDocument();
    expect(screen.getByText(/Irrigate the tomato field/)).toBeInTheDocument();
  });

  it("lists only statistics backed by real records", async () => {
    mockApi({
      summary: { farms: 2, devices: 3, devices_online: 3, recent_readings: 12, predictions: 5, latest_reading: null },
    });

    setup();

    expect(await screen.findByText("Your farm today")).toBeInTheDocument();
    expect(screen.getByText("Farms")).toBeInTheDocument();
    expect(screen.getByText("Sensors online")).toBeInTheDocument();
    expect(screen.getByText("Predictions")).toBeInTheDocument();
  });

  it("surfaces unread alerts and opens the alerts panel", async () => {
    const user = userEvent.setup();
    const openModule = vi.fn();
    mockApi({
      summary: { ...EMPTY_SUMMARY, farms: 1 },
      alerts: {
        total: 1,
        unread: 2,
        items: [{ id: "a1", title: "Soil moisture low", priority: "critical" }],
      },
    });

    setup({ openModule });

    expect(await screen.findByText("2 unread alerts")).toBeInTheDocument();
    expect(screen.getByText("Soil moisture low")).toBeInTheDocument();

    await user.click(screen.getByText("2 unread alerts"));
    expect(openModule).toHaveBeenCalledWith("alerts");
  });

  it("shows no alert banner when everything has been read", async () => {
    mockApi({ summary: { ...EMPTY_SUMMARY, farms: 1 } });

    setup();

    await screen.findByText("Today's action plan");
    expect(screen.queryByText(/unread alert/)).not.toBeInTheDocument();
  });

  it("lists recent predictions from stored records only", async () => {
    mockApi({
      summary: { ...EMPTY_SUMMARY, farms: 1, predictions: 1 },
      predictions: { total: 1, items: [PREDICTION] },
    });

    setup();

    expect(await screen.findByText("Recent predictions")).toBeInTheDocument();
    expect(screen.getByText("Recommended crop: Chickpea")).toBeInTheDocument();
  });

  it("hides the recent predictions block when nothing has been predicted", async () => {
    mockApi({ summary: { ...EMPTY_SUMMARY, farms: 1 } });

    setup();

    await screen.findByText("Today's action plan");
    expect(screen.queryByText("Recent predictions")).not.toBeInTheDocument();
  });

  it("keeps the AI Advisor shortcuts available on the first screen", async () => {
    mockApi();

    setup();

    expect(await screen.findByText("AI Advisor shortcuts")).toBeInTheDocument();
    expect(screen.getByText("Crop Advice")).toBeInTheDocument();
    expect(screen.getByText("Watering Advice")).toBeInTheDocument();
    expect(screen.getByText("Fertilizer Advice")).toBeInTheDocument();
    expect(screen.getByText("Market Prices")).toBeInTheDocument();
  });
});
