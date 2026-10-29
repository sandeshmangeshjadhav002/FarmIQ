import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiGetMock, apiPostMock, apiPatchMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
  apiPatchMock: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
  apiPost: apiPostMock,
  apiPatch: apiPatchMock,
}));

import AlertsPanel from "./AlertsPanel";

// One simulated (demo) alert and one real, already-read alert.
const ALERTS = [
  {
    id: "a1",
    kind: "irrigation",
    priority: "critical",
    title: "Irrigate Soybean now.",
    body: "Soil moisture 22% is below the 42% threshold.",
    reason: "Soil moisture 22% is below the 42% threshold (ICAR guideline).",
    subject_id: "demo-solapur-soybean",
    is_read: false,
    is_demo: true,
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  },
  {
    id: "a2",
    kind: "sensor",
    priority: "high",
    title: "Sensor offline",
    body: null,
    reason: "No reading for 9 h.",
    subject_id: "dev-1",
    is_read: true,
    is_demo: false,
    created_at: new Date(Date.now() - 3 * 3_600_000).toISOString(),
  },
];

const envelope = (items) => ({
  total: items.length,
  unread: items.filter((a) => !a.is_read).length,
  items,
});

describe("AlertsPanel", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiPostMock.mockReset();
    apiPatchMock.mockReset();
    apiPostMock.mockResolvedValue({});
    apiPatchMock.mockResolvedValue({});
  });

  it("shows an honest empty state and never invents alert rows", async () => {
    apiGetMock.mockResolvedValue(envelope([]));

    render(<AlertsPanel />);

    expect(await screen.findByText("No alerts yet")).toBeInTheDocument();
    expect(
      screen.getByText(/FarmIQ never invents an alert/),
    ).toBeInTheDocument();
    // Nothing to act on → "Mark all read" must be disabled.
    expect(
      screen.getByRole("button", { name: "Mark all read" }),
    ).toBeDisabled();
  });

  it("renders each alert's priority, kind, reasoning and unread count", async () => {
    apiGetMock.mockResolvedValue(envelope(ALERTS));

    render(<AlertsPanel />);

    expect(
      await screen.findByText("Irrigate Soybean now."),
    ).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Irrigation")).toBeInTheDocument();
    // Each alert states why it was raised.
    expect(
      screen.getByText(/below the 42% threshold \(ICAR guideline\)/),
    ).toBeInTheDocument();
    expect(screen.getByText(/No reading for 9 h\./)).toBeInTheDocument();
    expect(screen.getByText("Sensor offline")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();

    // Unread summary reflects exactly the unread alert.
    const summary = screen
      .getByText("Unread", { selector: "p" })
      .closest("section");
    expect(within(summary).getByText("1")).toBeInTheDocument();
    expect(within(summary).getByText("2 total alerts")).toBeInTheDocument();
  });

  it("badges alerts that came from simulated readings", async () => {
    apiGetMock.mockResolvedValue(envelope(ALERTS));

    render(<AlertsPanel />);

    await screen.findByText("Irrigate Soybean now.");
    // Exactly one demo badge — only the simulated alert carries it.
    expect(screen.getAllByText("Simulated data")).toHaveLength(1);
  });

  it("hides read alerts under the unread filter and says so", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(envelope([ALERTS[1]])); // only the read alert

    render(<AlertsPanel />);

    await screen.findByText("Sensor offline");
    await user.click(screen.getByRole("button", { name: "Unread" }));

    expect(screen.queryByText("Sensor offline")).not.toBeInTheDocument();
    expect(screen.getByText("No unread alerts")).toBeInTheDocument();
  });

  it("marks a single alert read via PATCH and refetches", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(envelope(ALERTS));

    render(<AlertsPanel />);

    await screen.findByText("Irrigate Soybean now.");
    await user.click(screen.getByRole("button", { name: "Mark read" }));

    expect(apiPatchMock).toHaveBeenCalledWith("/api/alerts/a1", {
      is_read: true,
    });
    expect(apiGetMock).toHaveBeenCalledTimes(2); // mount + refetch
  });

  it("marks every alert read when unread alerts exist", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(envelope(ALERTS));

    render(<AlertsPanel />);

    await screen.findByText("Irrigate Soybean now.");
    await user.click(screen.getByRole("button", { name: "Mark all read" }));

    expect(apiPostMock).toHaveBeenCalledWith("/api/alerts/read-all", {});
  });

  it("re-derives alerts from the server when the farmer checks now", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(envelope(ALERTS));

    render(<AlertsPanel />);

    await screen.findByText("Irrigate Soybean now.");
    await user.click(screen.getByRole("button", { name: /Check now/ }));

    expect(apiPostMock).toHaveBeenCalledWith("/api/alerts/refresh", {});
    expect(apiGetMock).toHaveBeenCalledTimes(2);
  });

  it("asks the farmer to sign in on a 401 instead of showing a raw error", async () => {
    apiGetMock.mockRejectedValue(
      Object.assign(new Error("Unauthorized"), { status: 401 }),
    );

    render(<AlertsPanel />);

    expect(
      await screen.findByText(/Sign in to view your alerts/),
    ).toBeInTheDocument();
  });

  it("surfaces a transport failure verbatim", async () => {
    apiGetMock.mockRejectedValue(
      Object.assign(new Error("Alerts service is down"), { status: 503 }),
    );

    render(<AlertsPanel />);

    expect(
      await screen.findByText("Alerts service is down"),
    ).toBeInTheDocument();
  });
});
