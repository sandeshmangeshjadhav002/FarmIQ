import { useState } from "react";
import { DemoBadge, ModuleButton, Field, SelectField } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";
import { farmChecklist } from "@/data/modules";
import { apiPost, apiDelete } from "@/lib/apiClient";
import useApi from "@/hooks/useApi";

/**
 * Farm Management module — fetches farms from GET /api/farms,
 * creates new ones via POST /api/farms, and deletes via DELETE /api/farms/{id}.
 */
export default function FarmManager() {
  const { data, loading, error, refetch } = useApi("/api/farms");
  const farms = data?.items ?? [];

  const [adding,   setAdding]   = useState(false);
  const [name,     setName]     = useState("");
  const [location, setLocation] = useState("");
  const [areaUnit, setAreaUnit] = useState("Acres");
  const [irrigation, setIrrigation] = useState("Drip");
  const [saving,   setSaving]   = useState(false);
  const [formError, setFormError] = useState("");

  const addFarm = async () => {
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
      });
      setName(""); setLocation(""); setAdding(false);
      refetch();
    } catch (err) {
      setFormError(err.message || "Could not save farm. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingState />;
  if (error && !farms.length) return <ErrorState message={error.message} onRetry={refetch} />;

  return (
    <div className="space-y-4">
      {farms.length === 0 && !adding && (
        <div className="rounded-[22px] border border-[#E0E8E2] bg-white p-6 text-center">
          <p className="text-[13px] font-bold text-[#3C5C49]">No farms yet</p>
          <p className="mt-1 text-[11px] text-[#7B8C82]">Add your first farm to get started.</p>
        </div>
      )}

      {farms.map((farm, index) => (
        <div
          key={farm.id}
          className="w-full rounded-[20px] border border-[#E0E8E2] bg-white p-4 text-left"
        >
          <div className="flex justify-between">
            <div>
              <h2 className="text-[14px] font-extrabold text-[#213D2F]">{farm.name}</h2>
              <p className="mt-1 text-[10px] text-[#77887E]">{farm.location}</p>
            </div>
            <span className="text-[9px] font-bold text-[#216B45]">
              {index === 0 ? "SELECTED" : "SELECT"}
            </span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <span className="rounded-xl bg-[#F3F6F2] p-3 text-[10px] text-[#53685C]">
              {farm.area_value ? `${farm.area_value} ${farm.area_unit}` : "Area not set"}
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
            <h2 className="text-[15px] font-extrabold text-[#213D2F]">Add a farm</h2>
            <p className="mt-1 text-[10px] text-[#7B8C82]">Step 1 of 3 • Skip anything you do not know.</p>
          </div>
          <Field label="Farm name *" value={name} onChange={setName} placeholder="Example: Sunrise Farm" />
          <Field label="Farm location *" value={location} onChange={setLocation} placeholder="Village, district, state" />
          <div className="grid grid-cols-2 gap-3">
            <SelectField label="Area unit" value={areaUnit} onChange={setAreaUnit} options={["Acres", "Hectares", "Guntha"]} />
            <SelectField label="Irrigation" value={irrigation} onChange={setIrrigation} options={["Drip", "Sprinkler", "Flood", "Not known"]} />
          </div>
          {formError && (
            <p className="rounded-xl bg-[#FCE9E5] p-3 text-[10px] font-bold text-[#9D4C3E]">{formError}</p>
          )}
          <div className="flex gap-2">
            <ModuleButton secondary onClick={() => { setAdding(false); setFormError(""); }}>
              Cancel
            </ModuleButton>
            <ModuleButton onClick={addFarm} disabled={saving}>
              {saving ? "Saving…" : "Save farm"}
            </ModuleButton>
          </div>
        </section>
      )}

      <section className="rounded-[20px] border border-[#E0E8E2] bg-white p-4">
        <h2 className="text-[14px] font-extrabold text-[#213D2F]">Farm details checklist</h2>
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
        <div key={n} className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]" />
      ))}
    </div>
  );
}

function ErrorState({ message, onRetry }) {
  return (
    <div className="rounded-[22px] bg-[#FCE9E5] p-4 text-center">
      <p className="text-[12px] font-bold text-[#9D4C3E]">{message || "Could not load farms."}</p>
      <button onClick={onRetry} className="mt-3 text-[11px] font-bold text-[#216B45] underline">
        Try again
      </button>
    </div>
  );
}
