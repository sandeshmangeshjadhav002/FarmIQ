import { describe, it, expect, vi, afterEach } from "vitest";

import { getCurrentPosition, GeolocationError } from "./geolocation";

/** Replace the platform geolocation API with a stub. */
function stubGeolocation(impl) {
  Object.defineProperty(navigator, "geolocation", {
    value: impl,
    configurable: true,
  });
}

afterEach(() => {
  Object.defineProperty(navigator, "geolocation", {
    value: undefined,
    configurable: true,
  });
  Object.defineProperty(window, "isSecureContext", {
    value: true,
    configurable: true,
  });
});

describe("getCurrentPosition", () => {
  it("resolves the device coordinates and the accuracy", async () => {
    stubGeolocation({
      getCurrentPosition: (success) =>
        success({
          coords: { latitude: 19.9975, longitude: 73.7898, accuracy: 12.5 },
        }),
    });

    await expect(getCurrentPosition()).resolves.toEqual({
      latitude: 19.9975,
      longitude: 73.7898,
      accuracy_m: 12.5,
    });
  });

  it("reports a null accuracy when the platform does not provide one", async () => {
    stubGeolocation({
      getCurrentPosition: (success) =>
        success({ coords: { latitude: 1, longitude: 2 } }),
    });

    await expect(getCurrentPosition()).resolves.toEqual({
      latitude: 1,
      longitude: 2,
      accuracy_m: null,
    });
  });

  it("passes conservative defaults to the platform", async () => {
    const spy = vi.fn((success) =>
      success({ coords: { latitude: 1, longitude: 2 } }),
    );
    stubGeolocation({ getCurrentPosition: spy });

    await getCurrentPosition();

    expect(spy).toHaveBeenCalledWith(
      expect.any(Function),
      expect.any(Function),
      {
        enableHighAccuracy: false,
        timeout: 10000,
        maximumAge: 600000,
      },
    );
  });

  it("forwards the caller's timeout and accuracy preference", async () => {
    const spy = vi.fn((success) =>
      success({ coords: { latitude: 1, longitude: 2 } }),
    );
    stubGeolocation({ getCurrentPosition: spy });

    await getCurrentPosition({
      timeout: 1234,
      highAccuracy: true,
      maximumAge: 0,
    });

    expect(spy.mock.calls[0][2]).toEqual({
      enableHighAccuracy: true,
      timeout: 1234,
      maximumAge: 0,
    });
  });

  it("rejects with 'unsupported' when the device has no geolocation API", async () => {
    Object.defineProperty(navigator, "geolocation", {
      value: undefined,
      configurable: true,
    });

    await expect(getCurrentPosition()).rejects.toMatchObject({
      name: "GeolocationError",
      code: "unsupported",
    });
  });

  it("rejects with 'insecure' outside a secure context, without prompting", async () => {
    const spy = vi.fn();
    stubGeolocation({ getCurrentPosition: spy });
    Object.defineProperty(window, "isSecureContext", {
      value: false,
      configurable: true,
    });

    await expect(getCurrentPosition()).rejects.toMatchObject({
      code: "insecure",
    });
    expect(spy).not.toHaveBeenCalled();
  });

  it.each([
    [1, "denied"],
    [2, "unavailable"],
    [3, "timeout"],
    [99, "unavailable"], // unknown platform code degrades safely
  ])(
    "maps platform error code %i to '%s'",
    async (platformCode, expectedCode) => {
      stubGeolocation({
        getCurrentPosition: (_success, failure) =>
          failure({ code: platformCode }),
      });

      const error = await getCurrentPosition().catch((e) => e);
      expect(error).toBeInstanceOf(GeolocationError);
      expect(error.code).toBe(expectedCode);
      // Every message must tell the farmer they can still type the location.
      expect(error.message).toMatch(/type the location/i);
    },
  );
});
