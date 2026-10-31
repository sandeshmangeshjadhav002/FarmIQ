import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Both the API client and the geolocation module are mocked so nothing touches
// the network or the device. The real useApi hook still runs, so the
// loading -> data transition is exercised as well.
const { apiGetMock, apiPostMock, apiDeleteMock, getPositionMock } = vi.hoisted(
  () => ({
    apiGetMock: vi.fn(),
    apiPostMock: vi.fn(),
    apiDeleteMock: vi.fn(),
    getPositionMock: vi.fn(),
  }),
);

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
  apiPost: apiPostMock,
  apiDelete: apiDeleteMock,
}));

vi.mock("@/lib/geolocation", () => ({
  getCurrentPosition: getPositionMock,
}));

import { LocationProvider } from "@/lib/locationStore";

import FarmManager from "./FarmManager";

const LABEL = "Gangapur, Nashik, Maharashtra, India";

/** Answer /api/farms (via useApi) and the reverse-geocode lookup. */
function primeApi({ farms = [], reverse = { label: LABEL } } = {}) {
  apiGetMock.mockImplementation((path) => {
    if (path.startsWith("/api/farms")) {
      return Promise.resolve({ items: farms, total: farms.length });
    }
    if (path.startsWith("/api/weather/reverse")) {
      return reverse instanceof Error
        ? Promise.reject(reverse)
        : Promise.resolve(reverse);
    }
    return Promise.resolve({});
  });
}

async function openForm(user) {
  render(
    <LocationProvider>
      <FarmManager />
    </LocationProvider>,
  );
  await user.click(await screen.findByRole("button", { name: /Add Farm/ }));
}

describe("FarmManager location capture", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiPostMock.mockReset();
    apiDeleteMock.mockReset();
    getPositionMock.mockReset();
  });

  it("fills the location from the device and saves the point with the farm", async () => {
    const user = userEvent.setup();
    primeApi();
    getPositionMock.mockResolvedValue({
      latitude: 19.9975,
      longitude: 73.7898,
      accuracy_m: 8,
    });
    apiPostMock.mockResolvedValue({});

    await openForm(user);

    // The permission dialog is only triggered by this explicit tap.
    await user.click(
      screen.getByRole("button", { name: /Use my current location/ }),
    );

    const location = screen.getByLabelText(/Farm location/);
    await waitFor(() => expect(location).toHaveValue(LABEL));

    expect(apiGetMock).toHaveBeenCalledWith(
      "/api/weather/reverse?lat=19.9975&lon=73.7898",
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      /Location filled from the device/,
    );
    expect(
      screen.getByText(/Saved point: 19\.99750, 73\.78980/),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/Farm name/), "Sunrise Farm");
    await user.click(screen.getByRole("button", { name: /Save farm/ }));

    expect(apiPostMock).toHaveBeenCalledWith(
      "/api/farms",
      expect.objectContaining({
        name: "Sunrise Farm",
        location: LABEL,
        latitude: 19.9975,
        longitude: 73.7898,
      }),
    );
  });

  it("keeps a typed location and still saves the detected point", async () => {
    const user = userEvent.setup();
    primeApi();
    getPositionMock.mockResolvedValue({
      latitude: 19.9975,
      longitude: 73.7898,
    });
    apiPostMock.mockResolvedValue({});

    await openForm(user);
    await user.type(
      screen.getByLabelText(/Farm location/),
      "My field near the canal",
    );
    await user.click(
      screen.getByRole("button", { name: /Use my current location/ }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      /your typed location was kept/,
    );
    expect(screen.getByLabelText(/Farm location/)).toHaveValue(
      "My field near the canal",
    );

    await user.type(screen.getByLabelText(/Farm name/), "Canal Farm");
    await user.click(screen.getByRole("button", { name: /Save farm/ }));

    expect(apiPostMock).toHaveBeenCalledWith(
      "/api/farms",
      expect.objectContaining({
        location: "My field near the canal",
        latitude: 19.9975,
        longitude: 73.7898,
      }),
    );
  });

  it("still keeps the point when no place name can be looked up", async () => {
    const user = userEvent.setup();
    primeApi({
      reverse: Object.assign(new Error("service down"), { status: 503 }),
    });
    getPositionMock.mockResolvedValue({ latitude: 19.5, longitude: 73.5 });
    apiPostMock.mockResolvedValue({});

    await openForm(user);
    await user.click(
      screen.getByRole("button", { name: /Use my current location/ }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      /no place name could be looked up/i,
    );
    expect(
      screen.getByText(/Saved point: 19\.50000, 73\.50000/),
    ).toBeInTheDocument();
    // Coordinates remain authoritative even without a human-readable label.
    expect(screen.getByLabelText(/Farm location/)).toHaveValue("");
  });

  it("shows a permission message and leaves the form usable when denied", async () => {
    const user = userEvent.setup();
    primeApi();
    getPositionMock.mockRejectedValue(
      Object.assign(
        new Error(
          "Location permission was denied. You can type the location instead.",
        ),
        { name: "GeolocationError", code: "denied" },
      ),
    );
    apiPostMock.mockResolvedValue({});

    await openForm(user);
    await user.click(
      screen.getByRole("button", { name: /Use my current location/ }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      /permission was denied/i,
    );
    expect(screen.queryByText(/Saved point/)).not.toBeInTheDocument();

    // Manual entry must still work, and no coordinate may be invented.
    await user.type(screen.getByLabelText(/Farm name/), "Typed Farm");
    await user.type(screen.getByLabelText(/Farm location/), "Nashik");
    await user.click(screen.getByRole("button", { name: /Save farm/ }));

    expect(apiPostMock).toHaveBeenCalledWith(
      "/api/farms",
      expect.objectContaining({ name: "Typed Farm", location: "Nashik" }),
    );
    expect(apiPostMock.mock.calls[0][1]).not.toHaveProperty("latitude");
    expect(apiPostMock.mock.calls[0][1]).not.toHaveProperty("longitude");
  });

  it("discards the captured point when the farmer clears it", async () => {
    const user = userEvent.setup();
    primeApi();
    getPositionMock.mockResolvedValue({
      latitude: 19.9975,
      longitude: 73.7898,
    });
    apiPostMock.mockResolvedValue({});

    await openForm(user);
    await user.click(
      screen.getByRole("button", { name: /Use my current location/ }),
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        /Location filled from the device/,
      ),
    );

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(/Saved point/)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/Farm name/), "Cleared Farm");
    await user.type(screen.getByLabelText(/Farm location/), "Nashik");
    await user.click(screen.getByRole("button", { name: /Save farm/ }));

    expect(apiPostMock.mock.calls[0][1]).not.toHaveProperty("latitude");
  });

  it("shows the saved-point hint on a farm that has coordinates", async () => {
    primeApi({
      farms: [
        {
          id: "f1",
          name: "Sunrise Farm",
          location: "Nashik",
          latitude: 19.9975,
          longitude: 73.7898,
          area_unit: "acres",
        },
      ],
    });

    render(
      <LocationProvider>
        <FarmManager />
      </LocationProvider>,
    );

    expect(await screen.findByText("Sunrise Farm")).toBeInTheDocument();
    expect(
      screen.getByText(/Location saved — weather uses this point/),
    ).toBeInTheDocument();
  });
});
