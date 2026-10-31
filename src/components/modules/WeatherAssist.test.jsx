import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiGetMock, getPositionMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  getPositionMock: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({ apiGet: apiGetMock }));
vi.mock("@/lib/geolocation", () => ({ getCurrentPosition: getPositionMock }));

import { LocationProvider } from "@/lib/locationStore";

import WeatherAssist from "./WeatherAssist";

/** WeatherAssist reads the shared location context, so every render needs it. */
const renderWeather = (props = {}) =>
  render(
    <LocationProvider>
      <WeatherAssist {...props} />
    </LocationProvider>,
  );

const FARM = { id: "f1", name: "Sunrise Farm", latitude: 19.9975, longitude: 73.7898 };

const REPORT = {
  source: "Open-Meteo",
  fetched_at: "2026-10-28T10:00:00+00:00",
  location: { name: null, latitude: 19.9975, longitude: 73.7898, timezone: "Asia/Kolkata" },
  current: {
    observed_at: "2026-10-28T10:00",
    temperature_c: 28.4,
    humidity_pct: 71,
    precipitation_mm: 0,
    rain_mm: 0,
    label: "Current observation",
  },
  forecast_rainfall: { days: 2, total_mm: 2, daily: [], label: "Forecast rainfall (not yet fallen)" },
  historical_rainfall: {
    days: 30,
    past_7_days_mm: 12,
    total_mm: 40,
    daily: [],
    label: "Historical rainfall (already fallen, cumulative)",
  },
  autofill: {
    temperature: {
      value: 28.4,
      unit: "°C",
      origin: "current observation",
      label: "Current air temperature",
      is_cumulative: false,
    },
    humidity: {
      value: 71,
      unit: "%",
      origin: "current observation",
      label: "Current relative humidity",
      is_cumulative: false,
    },
    rainfall: {
      value: 40,
      unit: "mm",
      origin: "historical accumulation",
      label: "Accumulated rainfall — past 30 days",
      is_cumulative: true,
      note: "Accumulated history, not today's rain.",
    },
  },
  notes: ["Rainfall values are historical."],
};

describe("WeatherAssist coordinate sources", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    getPositionMock.mockReset();
  });

  it("uses the saved farm point on request, without asking for a permission", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(REPORT);
    const onAutofill = vi.fn();

    renderWeather({
      fieldMap: { temperature: "temperature", rainfall: "rainfall" },
      onAutofill,
      farm: FARM,
    });

    await user.click(
      screen.getByRole("button", { name: /Use Sunrise Farm's saved location/ }),
    );

    // The stored point is queried directly — no reverse geocoding, no device.
    expect(apiGetMock).toHaveBeenCalledWith("/api/weather/current?lat=19.9975&lon=73.7898");
    expect(getPositionMock).not.toHaveBeenCalled();

    expect(
      await screen.findByText(/the farm's own location, not where this phone is/),
    ).toBeInTheDocument();

    // The auto-fill still maps the report onto the caller's form keys.
    expect(onAutofill).toHaveBeenCalledWith(
      { temperature: 28.4, rainfall: 40 },
      REPORT,
    );
  });

  it("warns that the phone's own position may not match the field", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(REPORT);
    getPositionMock.mockResolvedValue({ latitude: 18.5204, longitude: 73.8567 });

    renderWeather({ fieldMap: { temperature: "temperature" }, farm: FARM });

    await user.click(screen.getByRole("button", { name: /Use this phone's location/ }));

    expect(apiGetMock).toHaveBeenCalledWith("/api/weather/current?lat=18.5204&lon=73.8567");
    expect(
      await screen.findByText(/if you are not standing at the farm/i),
    ).toBeInTheDocument();
  });

  it("hides the farm shortcut when the farm has no stored coordinates", () => {
    apiGetMock.mockResolvedValue(REPORT);

    renderWeather({ farm: { id: "f1", name: "Sunrise Farm" } });

    expect(
      screen.queryByRole("button", { name: /saved location/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Use this phone's location/ }),
    ).toBeInTheDocument();
  });

  it("still looks up a hand-typed place name", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue(REPORT);

    renderWeather();

    await user.type(screen.getByLabelText("Location"), "Nashik");
    await user.click(screen.getByRole("button", { name: /Look up/ }));

    expect(apiGetMock).toHaveBeenCalledWith("/api/weather/current?location=Nashik");
    expect(getPositionMock).not.toHaveBeenCalled();
  });

  it("surfaces the weather service being down without blocking the form", async () => {
    const user = userEvent.setup();
    apiGetMock.mockRejectedValue(Object.assign(new Error("Service Unavailable"), { status: 503 }));

    renderWeather({ farm: FARM });

    await user.click(
      screen.getByRole("button", { name: /Use Sunrise Farm's saved location/ }),
    );

    expect(await screen.findByText(/Auto-fill is off/)).toBeInTheDocument();
  });
});
