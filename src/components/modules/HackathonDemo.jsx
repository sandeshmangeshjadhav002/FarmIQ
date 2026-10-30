/**
 * HackathonDemo — Interactive demonstration mode for judges.
 *
 * Allows judges to:
 * 1. Select a demo farm (Nashik grapes, Solapur soybean, Punjab wheat)
 * 2. View farm profile and default sensor readings
 * 3. Adjust sensor values (soil moisture, temperature, humidity)
 * 4. Observe how recommendations change in real time
 * 5. Compare different farm scenarios
 *
 * All data is clearly labelled DEMO. Real ML models run on the backend.
 * No real user data is touched.
 */
import { useState } from "react";
import { apiPost } from "@/lib/apiClient";
import useApi from "@/hooks/useApi";
import ModuleIcon from "./ModuleIcon";
import { ModuleButton, Field } from "./ModuleShared";

const PRIORITY_CONFIG = {
  critical: {
    bg: "bg-[#FCE9E5]",
    text: "text-[#9D3E2E]",
    badge: "bg-[#E8493B] text-white",
    label: "Critical",
  },
  high: {
    bg: "bg-[#FFF5DE]",
    text: "text-[#8A6D2B]",
    badge: "bg-[#D99A2B] text-white",
    label: "High",
  },
  moderate: {
    bg: "bg-[#E8EEF8]",
    text: "text-[#3F5A90]",
    badge: "bg-[#4F6590] text-white",
    label: "Moderate",
  },
  low: {
    bg: "bg-white",
    text: "text-[#52665B]",
    badge: "bg-[#9ABBA6] text-white",
    label: "Low",
  },
};

export default function HackathonDemo() {
  const { data: farmsData, loading: farmsLoading } = useApi("/api/demo/farms");
  const [selectedFarm, setSelectedFarm] = useState(null);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Sensor sliders
  const [soilMoisture, setSoilMoisture] = useState(null);
  const [temperature, setTemperature] = useState(null);
  const [humidity, setHumidity] = useState(null);

  const farms = farmsData?.farms ?? [];

  const runPlan = async (farmId, overrides = false) => {
    setBusy(true);
    setError(null);
    try {
      let result;
      if (
        overrides &&
        (soilMoisture !== null || temperature !== null || humidity !== null)
      ) {
        result = await apiPost("/api/demo/sensor", {
          farm_id: farmId,
          soil_moisture:
            soilMoisture !== null ? Number(soilMoisture) : undefined,
          temperature: temperature !== null ? Number(temperature) : undefined,
          humidity: humidity !== null ? Number(humidity) : undefined,
          include_weather: true,
        });
      } else {
        result = await apiPost("/api/demo/plan", {
          farm_id: farmId,
          include_weather: true,
        });
      }
      setPlan(result);
    } catch (err) {
      setError(err.message || "Failed to run demo plan.");
    } finally {
      setBusy(false);
    }
  };

  const selectFarm = (farm) => {
    setSelectedFarm(farm);
    setSoilMoisture(null);
    setTemperature(null);
    setHumidity(null);
    setPlan(null);
    runPlan(farm.id);
  };

  return (
    <div className="space-y-4">
      {/* Demo banner */}
      <div className="rounded-[22px] border border-[#F0D090] bg-[#FFF8EA] p-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="rounded-full bg-[#D99A2B] px-2.5 py-0.5 text-[9px] font-extrabold uppercase text-white">
            Hackathon Demo Mode
          </span>
        </div>
        <p className="text-[11px] font-bold text-[#7A6428]">
          Synthetic data for demonstration only — no real user data is used.
        </p>
      </div>

      {/* Farm selector */}
      {farmsLoading ? (
        <div className="grid grid-cols-1 gap-2">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="h-16 animate-pulse rounded-[20px] bg-[#E8F0EB]"
            />
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#5D7B6B]">
            1. Select a demonstration farm
          </p>
          {farms.map((farm) => (
            <button
              key={farm.id}
              onClick={() => selectFarm(farm)}
              className={`w-full rounded-[20px] border p-4 text-left transition active:scale-[.98] ${
                selectedFarm?.id === farm.id
                  ? "border-[#216B45] bg-[#E6F3E8] shadow"
                  : "border-[#DDE6DF] bg-white hover:border-[#9CC9AD]"
              }`}
            >
              <div className="flex items-center justify-between">
                <p className="text-[12px] font-extrabold text-[#1D382A]">
                  {farm.name}
                </p>
                <span className="text-[9px] rounded-full bg-[#E5F1E8] px-2 py-0.5 text-[#216B45] font-bold">
                  {farm.crop}
                </span>
              </div>
              <p className="mt-0.5 text-[10px] text-[#7B8C82]">
                {farm.location} · {farm.area_value} {farm.area_unit} ·{" "}
                {farm.soil_type}
              </p>
              <p className="mt-1 text-[9px] text-[#9AA79F] leading-4">
                {farm.description}
              </p>
            </button>
          ))}
        </div>
      )}

      {/* Sensor controls */}
      {selectedFarm && (
        <div className="rounded-[22px] border border-[#DDE6DF] bg-white p-4 space-y-3">
          <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#5D7B6B]">
            2. Adjust simulated sensor values
          </p>
          <p className="text-[9px] text-[#84938B]">
            Leave blank to use defaults.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Field
                label="Soil moisture (%)"
                type="number"
                value={soilMoisture ?? ""}
                onChange={setSoilMoisture}
                placeholder="e.g. 25"
              />
              <p className="text-[8px] text-[#9AA79F] mt-0.5">
                Try: 15 (dry) · 50 (ok) · 80 (wet)
              </p>
            </div>
            <div>
              <Field
                label="Temperature (°C)"
                type="number"
                value={temperature ?? ""}
                onChange={setTemperature}
                placeholder="e.g. 32"
              />
              <p className="text-[8px] text-[#9AA79F] mt-0.5">
                Try: 25 (cool) · 38 (hot) · 42 (extreme)
              </p>
            </div>
            <div>
              <Field
                label="Humidity (%)"
                type="number"
                value={humidity ?? ""}
                onChange={setHumidity}
                placeholder="e.g. 45"
              />
            </div>
          </div>
          <ModuleButton
            disabled={busy}
            onClick={() => runPlan(selectedFarm.id, true)}
          >
            {busy ? "Running…" : "3. Generate Action Plan"}
          </ModuleButton>
        </div>
      )}

      {error && (
        <div className="rounded-[20px] bg-[#FCE9E5] p-4">
          <p className="text-[11px] font-bold text-[#9D3E2E]">{error}</p>
        </div>
      )}

      {/* Plan output */}
      {plan && (
        <div className="space-y-3">
          <p className="text-[10px] font-bold uppercase tracking-[.08em] text-[#5D7B6B]">
            4. Farm action plan results
          </p>

          {/* Summary */}
          <div className="rounded-[22px] border border-[#CDEBDA] bg-[#EAF6EF] p-4">
            <p className="text-[13px] font-extrabold text-[#1D4A33]">
              {plan.summary}
            </p>
            <div className="mt-2 flex gap-3">
              {plan.critical_count > 0 && (
                <span className="rounded-full bg-[#E8493B] px-2.5 py-1 text-[9px] font-extrabold text-white">
                  {plan.critical_count} Critical
                </span>
              )}
              {plan.high_count > 0 && (
                <span className="rounded-full bg-[#D99A2B] px-2.5 py-1 text-[9px] font-extrabold text-white">
                  {plan.high_count} High
                </span>
              )}
            </div>
            {plan.sensor_values_used && (
              <div className="mt-2 rounded-xl bg-white/60 p-2.5 text-[9px] text-[#4C6355]">
                Sensor values used: moisture{" "}
                {plan.sensor_values_used.soil_moisture}% · temp{" "}
                {plan.sensor_values_used.temperature}°C · humidity{" "}
                {plan.sensor_values_used.humidity}%
              </div>
            )}
          </div>

          {/* Action cards */}
          {(plan.actions ?? []).map((action, i) => {
            const cfg = PRIORITY_CONFIG[action.priority] ?? PRIORITY_CONFIG.low;
            return (
              <div
                key={i}
                className={`rounded-[20px] border p-4 ${cfg.bg} border-white/60`}
              >
                <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-[8px] font-extrabold uppercase ${cfg.badge}`}
                  >
                    {cfg.label}
                  </span>
                  <span className="text-[9px] uppercase tracking-[.08em] text-[#7A8C82] font-semibold">
                    {action.category?.replace("_", " ")}
                  </span>
                </div>
                <p
                  className={`text-[12px] font-extrabold leading-5 ${cfg.text}`}
                >
                  {action.action}
                </p>
                <p className="mt-0.5 text-[10px] leading-5 text-[#5A6F63]">
                  {action.reason}
                </p>
                {action.warnings?.map((w, wi) => (
                  <p key={wi} className="mt-1 text-[9px] text-[#8A6D2B]">
                    ⚠ {w}
                  </p>
                ))}
              </div>
            );
          })}

          {/* Weather / conditions */}
          {plan.weather_summary && (
            <div className="rounded-[22px] border border-[#C5DCE4] bg-[#EBF6FA] p-4">
              <p className="text-[10px] font-bold text-[#1A4A5A] mb-2">
                Weather conditions
              </p>
              <div className="grid grid-cols-2 gap-2 text-[10px]">
                {plan.weather_summary.temperature_c != null && (
                  <span>
                    🌡 {plan.weather_summary.temperature_c.toFixed(1)}°C
                  </span>
                )}
                {plan.weather_summary.humidity_pct != null && (
                  <span>
                    💧 {plan.weather_summary.humidity_pct.toFixed(0)}% humidity
                  </span>
                )}
                {plan.weather_summary.forecast_rain_7d_mm != null && (
                  <span className="text-[#D99A2B]">
                    🌧 {plan.weather_summary.forecast_rain_7d_mm.toFixed(1)} mm
                    forecast (7 days, unconfirmed)
                  </span>
                )}
              </div>
              {!plan.weather_summary.temperature_c && (
                <p className="text-[9px] text-[#5A8090]">
                  Weather data unavailable — using sensor data only.
                </p>
              )}
            </div>
          )}

          <p className="text-[9px] text-[#9AA79F] text-right">
            Generated:{" "}
            {plan.generated_at
              ? new Date(plan.generated_at).toLocaleTimeString("en-IN")
              : "—"}
          </p>
        </div>
      )}
    </div>
  );
}
