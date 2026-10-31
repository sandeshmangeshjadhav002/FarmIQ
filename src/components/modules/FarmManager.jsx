import { useState } from "react";
import { DemoBadge, ModuleButton, Field, SelectField } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";
import { farmChecklist } from "@/data/modules";
import { apiPost, apiDelete, apiGet } from "@/lib/apiClient";
import { getCurrentPosition } from "@/lib/geolocation";
import { useLocation } from "@/lib/locationStore";
import useApi from "@/hooks/useApi";

/**
 * Farm Management module — fetches farms from GET /api/farms,
 * creates new ones via POST /api/farms, and deletes via DELETE /api/farms/{id}.
 *
 * The farm form can fill its own location from the device instead of asking the
 * farmer to type it: the button below requests a position, then resolves it to
 * a readable label via GET /api/weather/reverse (Photon/OpenStreetMap). The
 * coordinates are what get saved; the label is an editable convenience. If the
 * lookup fails the coordinates are still kept, and typing the location by hand
 * always works.
 */
export default function FarmManager() {
  const { setLocation: setSharedLocation } = useLocation();
  const { data, loading, error, refetch } = useApi("/api/farms");
  const farms = data?.items ?? [];

  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [coords, setCoords] = useState(null); // { latitude, longitude }
  const [locating, setLocating] = useState(false);
  const [locNote, setLocNote] = useState(null); // { tone, message }
  const [areaUnit, setAreaUnit] = useState("Acres");
  const [irrigation, setIrrigation] = useState("Drip");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const resetForm = () => {
    setName("");
    setLocation("");
    setCoords(null);
    setLocNote(null);
    setFormError("");
  };

  /**
   * Ask the device where it is, then try to label that point.
   *
   * Runs only on tap so the OS permission dialog appears with context. A
   * reverse-geocode failure is not a failure of the whole action — the
   * coordinate is still usable for weather.
   */
  const useMyLocation = async () => {
    if (locating) return; // re-entrancy guard: repeat taps would race the label
    setLocating(true);
    setLocNote(null);
    try {
      const pos = await getCurrentPosition();
      setCoords({ latitude: pos.latitude, longitude: pos.longitude });

      let label = null;
      try {
        const resolved = await apiGet(
          `/api/weather/reverse?lat=${pos.latitude}&lon=${pos.longitude}`,
        );
        label = resolved?.label ?? null;
      } catch {
        label = null; // coordinates are still saved; the label is optional
      }

      if (label && !location.trim()) {
        setLocation(label);
        setLocNote({
          tone: "ok",
          message: label ? `Location filled from the device: ${label}` : "",
        });
      } else if (label) {
        setLocNote({
          tone: "ok",
          message: `Coordinates saved. The detected name is "${label}" — your typed location was kept.`,
        });
      } else {
        setLocNote({
          tone: "warn",
          message:
            "Coordinates saved, but no place name could be looked up. Please type the location.",
        });
      }
    } catch (err) {
      setLocNote({
        tone: "warn",
        message: err.message || "Could not get your location.",
      });
    } finally {
      setLocating(false);
    }
  };

  const addFarm = async () => {
    if (saving) return; // re-entrancy guard (the button is also disabled)
    if (!name.trim() || !location.trim()) {
      setFormError("Farm name and location are required.");
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      await apiPost("/api/farms", {
        name: name.trim(),
        location: location.trim(),
        area_unit: areaUnit.toLowerCase(),
        irrigation_type: irrigation.toLowerCase(),
        ...(coords
          ? { latitude: coords.latitude, longitude: coords.longitude }
          : {}),
      });

      // Sync the shared location store with the farm's coordinates
      // so other features (weather, drought, organic farming) can reuse it.
      if (coords) {
        setSharedLocation({
          label: location.trim(),
          latitude: coords.latitude,
          longitude: coords.longitude,
          source: "farm",
        });
      }

      resetForm();
      setAdding(false);
      refetch();
    } catch (err) {
      setFormError(err.message || "Could not save farm. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingState />;
  if (error && !farms.length)
    return <ErrorState message={error.message} onRetry={refetch} />;

  return (
    <div className="space-y-4">
      {farms.length === 0 && !adding && (
        <div className="rounded-[22px] border border-[#E0E8E2] bg-white p-6 text-center">
          <p className="text-[13px] font-bold text-[#3C5C49]">No farms yet</p>
          <p className="mt-1 text-[11px] text-[#7B8C82]">
            Add your first farm to get started.
          </p>
        </div>
      )}

      {farms.map((farm, index) => (
        <div
          key={farm.id}
          className="w-full rounded-[20px] border border-[#E0E8E2] bg-white p-4 text-left"
        >
          <div className="flex justify-between">
            <div>
              <h2 className="text-[14px] font-extrabold text-[#213D2F]">
                {farm.name}
              </h2>
              <p className="mt-1 text-[10px] text-[#77887E]">{farm.location}</p>
              {farm.latitude != null && farm.longitude != null && (
                <p className="mt-0.5 text-[9px] font-semibold text-[#216B45]">
                  Location saved — weather uses this point
                </p>
              )}
            </div>
            <span className="text-[9px] font-bold text-[#216B45]">
              {index === 0 ? "SELECTED" : "SELECT"}
            </span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <span className="rounded-xl bg-[#F3F6F2] p-3 text-[10px] text-[#53685C]">
              {farm.area_value
                ? `${farm.area_value} ${farm.area_unit}`
                : "Area not set"}
            </span>
            <span className="rounded-xl bg-[#F3F6F2] p-3 text-[10px] text-[#53685C]">
              {farm.current_crop || "No crop added"}
            </span>
          </div>
        </div>
      ))}

      {!adding ? (
        <ModuleButton onClick={() => setAdding(true)}>
          <ModuleIcon name="plus" size={17} />
          Add Farm
        </ModuleButton>
      ) : (
        <section className="space-y-3 rounded-[22px] border border-[#DCE6DF] bg-white p-4">
          <div>
            <h2 className="text-[15px] font-extrabold text-[#213D2F]">
              Add a farm
            </h2>
            <p className="mt-1 text-[10px] text-[#7B8C82]">
              Step 1 of 3 • Skip anything you do not know.
            </p>
          </div>
          <Field
            label="Farm name *"
            value={name}
            onChange={setName}
            placeholder="Example: Sunrise Farm"
          />
          <Field
            label="Farm location *"
            value={location}
            onChange={setLocation}
            placeholder="Village, district, state"
          />

          {/* Device location. Asking here (rather than at login) means the
              permission dialog appears only when the farmer can see why. */}
          <div className="-mt-1 mb-4 space-y-2">
            <button
              type="button"
              onClick={useMyLocation}
              disabled={locating}
              className="flex h-10 w-full items-center justify-center gap-2 rounded-2xl border border-[#CFE0D5] bg-[#F0F7F2] text-[11px] font-extrabold text-[#216B45] disabled:opacity-60"
            >
              <ModuleIcon name={locating ? "signal" : "pin"} size={15} />
              {locating ? "Getting location…" : "Use my current location"}
            </button>
            <p className="text-[9px] leading-4 text-[#8A998F]">
              Fills the location from where you are now. The permission is only
              asked when you tap this, and you can always type the location
              instead.
            </p>
            {coords && (
              <div className="flex items-center justify-between gap-2 rounded-xl bg-[#F3F6F2] px-3 py-2">
                <span className="text-[9px] font-semibold text-[#53685C]">
                  Saved point: {coords.latitude.toFixed(5)},{" "}
                  {coords.longitude.toFixed(5)}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    setCoords(null);
                    setLocNote(null);
                  }}
                  className="text-[9px] font-extrabold text-[#9D4C3E] underline"
                >
                  Clear
                </button>
              </div>
            )}
            {locNote && (
              <p
                role="status"
                className={`rounded-xl p-2.5 text-[9px] font-semibold leading-4 ${
                  locNote.tone === "ok"
                    ? "bg-[#EAF6EF] text-[#216B45]"
                    : "bg-[#FFF5DE] text-[#8A6D2B]"
                }`}
              >
                {locNote.message}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <SelectField
              label="Area unit"
              value={areaUnit}
              onChange={setAreaUnit}
              options={["Acres", "Hectares", "Guntha"]}
            />
            <SelectField
              label="Irrigation"
              value={irrigation}
              onChange={setIrrigation}
              options={["Drip", "Sprinkler", "Flood", "Not known"]}
            />
          </div>
          {formError && (
            <p className="rounded-xl bg-[#FCE9E5] p-3 text-[10px] font-bold text-[#9D4C3E]">
              {formError}
            </p>
          )}
          <div className="flex gap-2">
            <ModuleButton
              secondary
              onClick={() => {
                resetForm();
                setAdding(false);
              }}
            >
              Cancel
            </ModuleButton>
            <ModuleButton onClick={addFarm} disabled={saving}>
              {saving ? "Saving…" : "Save farm"}
            </ModuleButton>
          </div>
        </section>
      )}

      <section className="rounded-[20px] border border-[#E0E8E2] bg-white p-4">
        <h2 className="text-[14px] font-extrabold text-[#213D2F]">
          Farm details checklist
        </h2>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {farmChecklist.map((item) => (
            <button
              key={item}
              className="rounded-xl bg-[#F3F6F2] p-3 text-left text-[10px] font-bold text-[#50665A]"
            >
              {item}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3">
      {[1, 2].map((n) => (
        <div
          key={n}
          className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]"
        />
      ))}
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rounded-[22px] bg-[#FCE9E5] p-4 text-center">
      <p className="text-[12px] font-bold text-[#9D4C3E]">
        {message || "Could not load farms."}
      </p>
      <button
        onClick={onRetry}
        className="mt-3 text-[11px] font-bold text-[#216B45] underline"
      >
        Try again
      </button>
    </div>
  );
}
