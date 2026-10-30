import { useState } from "react";
import { moduleConfigs } from "@/data/modules";
import { DemoBadge, ModuleButton, SelectField, Metric } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";
import useApi from "@/hooks/useApi";

/**
 * Generic module screen — used for all modules that don't have a custom UI.
 * Farm/crop selectors are populated from the API; sensor readings and dashboard
 * data replace the hardcoded values for the 'sensors' and 'mlops' keys.
 * All other modules continue to show their static demo content.
 */
export default function GenericModule({ moduleKey, onAsk }) {
  const config = moduleConfigs[moduleKey] ?? moduleConfigs.reports;
  const [saved, setSaved] = useState(false);

  // Real farms for the farm selector.
  const { data: farmsData } = useApi("/api/farms");
  const farmNames = (farmsData?.items ?? []).map((f) => f.name);
  const farmOptions = farmNames.length > 0 ? farmNames : ["No farms yet"];

  // For sensors module: real latest readings.
  const { data: sensorsData } = useApi(
    moduleKey === "sensors" ? "/api/sensor-readings?limit=4" : null,
  );
  const readings = sensorsData?.items ?? [];

  // For sensors module: real device counts from dashboard.
  const { data: dashData } = useApi(
    moduleKey === "sensors" || moduleKey === "mlops"
      ? "/api/dashboard/summary"
      : null,
  );

  // For mlops module: real model health.
  const { data: mlData } = useApi(
    moduleKey === "mlops" ? "/api/health/ml" : null,
  );

  const [farm, setFarm] = useState(farmOptions[0] ?? "");
  const [crop, setCrop] = useState("Tomato");

  // Build dynamic config for sensor and mlops modules.
  let displayConfig = config;

  if (moduleKey === "sensors" && (readings.length > 0 || dashData)) {
    const online = dashData?.devices_online ?? "—";
    const offline =
      dashData?.devices != null
        ? dashData.devices - dashData.devices_online
        : "—";
    const latest = readings[0];
    const rows = readings
      .slice(0, 4)
      .map((r) => [
        r.device_id ?? "Sensor",
        r.soil_moisture != null
          ? `${r.soil_moisture.toFixed(0)}%`
          : r.temperature != null
          ? `${r.temperature.toFixed(1)}°C`
          : "—",
        new Date(r.created_at).toLocaleTimeString("en-IN", {
          hour: "2-digit",
          minute: "2-digit",
        }),
      ]);
    displayConfig = {
      ...config,
      metrics: [
        ["Online", String(online), "Devices connected"],
        ["Offline", String(offline), "Need attention"],
        ["Data points", String(readings.length), "Recent readings"],
      ],
      title: "Sensor readings",
      detail: latest
        ? `Last reading: ${new Date(latest.created_at).toLocaleTimeString()}`
        : config.detail,
      rows: rows.length > 0 ? rows : config.rows,
    };
  }

  if (moduleKey === "mlops" && mlData) {
    const models = mlData.models ?? {};
    const modelRows = Object.entries(models).map(([domain, info]) => [
      domain,
      info.model ? "Model loaded" : "No model",
      info.preprocessing ? "Preprocessing ✓" : "Missing artefacts",
    ]);
    displayConfig = {
      ...config,
      metrics: [
        ["Models", String(Object.keys(models).length), "Registered"],
        [
          "Loaded",
          String(Object.values(models).filter((m) => m.model).length),
          "With trained model",
        ],
        ["Baseline", "Irrigation", "Rule-based fallback"],
      ],
      rows: modelRows.length > 0 ? modelRows : config.rows,
    };
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <SelectField
          label="Farm"
          value={farm}
          onChange={setFarm}
          options={farmOptions}
        />
        <SelectField
          label="Crop"
          value={crop}
          onChange={setCrop}
          options={["Tomato", "Onion", "Wheat", "Chickpea", "Rice", "Cotton"]}
        />
      </div>

      <div className="flex items-center justify-between">
        {moduleKey === "sensors" && readings.length > 0 ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[#E5F3F7] px-2.5 py-1 text-[9px] font-extrabold uppercase tracking-[.06em] text-[#287A8E]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#287A8E]" /> Live data
          </span>
        ) : (
          <DemoBadge />
        )}
        <span className="text-[9px] font-semibold text-[#829188]">
          Updated{" "}
          {new Date().toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {displayConfig.metrics.map(([label, value, note]) => (
          <Metric key={label} label={label} value={value} note={note} />
        ))}
      </div>

      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h2 className="text-[14px] font-extrabold text-[#203C2E]">
          {displayConfig.title}
        </h2>
        <p className="mt-1 text-[11px] leading-5 text-[#75867C]">
          {displayConfig.detail}
        </p>
      </section>

      <section className="overflow-hidden rounded-[22px] border border-[#E0E8E2] bg-white">
        {displayConfig.rows.map(([name, value, note], index) => (
          <div
            key={`${name}-${index}`}
            className={`flex items-center gap-3 p-4 ${
              index ? "border-t border-[#EDF1EE]" : ""
            }`}
          >
            <span className="min-w-0 flex-1">
              <b className="block text-[12px] text-[#294234]">{name}</b>
              <span className="mt-1 block text-[9px] text-[#84938B]">
                {note}
              </span>
            </span>
            <span className="text-right text-[11px] font-extrabold text-[#426653]">
              {value}
            </span>
          </div>
        ))}
      </section>

      <div className="grid grid-cols-2 gap-3">
        <ModuleButton secondary onClick={() => setSaved(!saved)}>
          <ModuleIcon name={saved ? "check" : "plus"} size={16} />
          {saved ? "Saved" : "Save"}
        </ModuleButton>
        <ModuleButton onClick={onAsk}>Ask FarmIQ</ModuleButton>
      </div>
    </div>
  );
}
