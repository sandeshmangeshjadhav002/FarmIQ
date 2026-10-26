import { useEffect, useState } from "react";
import Icon from "@/components/common/Icon";
import { SecondaryButton } from "@/components/common/Button";
import ScreenShell from "@/components/layout/ScreenShell";
import useApi from "@/hooks/useApi";

/** Single IoT sensor card. */
function SensorCard({ icon, label, value, detail, tone }) {
  return (
    <div className="rounded-[20px] border border-[#E3E9E4] bg-white p-4 shadow-[0_4px_16px_rgba(31,57,44,.04)]">
      <div className="mb-4 flex items-start justify-between">
        <span className={`grid h-9 w-9 place-items-center rounded-xl ${tone}`}>
          <Icon name={icon} size={19} />
        </span>
        <span className="flex items-center gap-1 text-[9px] font-bold text-[#4A9365]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#52AB71]" />
          LIVE
        </span>
      </div>
      <p className="text-[11px] font-semibold text-[#75877D]">{label}</p>
      <p className="mt-1 text-[24px] font-extrabold tracking-[-0.03em] text-[#193A2A]">{value}</p>
      <p className="mt-1 text-[10px] text-[#809087]">{detail}</p>
    </div>
  );
}

function SkeletonCard() {
  return <div className="h-28 animate-pulse rounded-[20px] bg-[#E8F0EB]" />;
}

/**
 * My Farm screen — shows the first farm from the API with live sensor readings.
 */
export default function FarmScreen({ navigate }) {
  const { data: farmsData, loading: farmsLoading } = useApi("/api/farms?limit=1");
  const { data: dashData,  loading: dashLoading  } = useApi("/api/dashboard/summary");
  const { data: sensorsData } = useApi("/api/sensor-readings?limit=5");

  const farm    = farmsData?.items?.[0] ?? null;
  const dash    = dashData ?? {};
  const reading = sensorsData?.items?.[0] ?? null;

  // Derive sensor values from the latest reading
  const moisture    = reading?.soil_moisture    != null ? `${reading.soil_moisture.toFixed(0)}%` : "—";
  const temperature = reading?.temperature       != null ? `${reading.temperature.toFixed(1)}°C`  : "—";
  const moistureDetail    = reading ? "Live sensor reading" : "No sensor data";
  const temperatureDetail = reading ? "Live sensor reading" : "No sensor data";

  const farmName  = farm?.name     ?? "My Farm";
  const farmLoc   = farm?.location ?? "—";
  const farmArea  = farm?.area_value ? `${farm.area_value} ${farm.area_unit} • ${farm.soil_type ?? "Soil type not set"}` : "Area not set";

  return (
    <ScreenShell active="farm" navigate={navigate}>
      <div className="px-5 pb-7 pt-5">
        {/* Header */}
        <header className="mb-6 flex items-center gap-3">
          <button
            onClick={() => navigate("home")}
            aria-label="Back"
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-[#DFE7E1] bg-white text-[#3F5A4B] active:scale-95"
          >
            <Icon name="arrow" size={18} className="rotate-180" />
          </button>
          <div className="flex-1">
            <p className="text-[11px] font-bold uppercase tracking-[.12em] text-[#668173]">My farm</p>
            <h1 className="mt-0.5 text-[22px] font-extrabold tracking-[-0.04em] text-[#17392A]">
              {farmsLoading ? "Loading…" : farmName}
            </h1>
          </div>
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#E5F1E8] text-[#216B45]">
            <Icon name="farm" size={23} />
          </span>
        </header>

        {/* Farm summary card */}
        <div className="mb-7 rounded-[22px] bg-[#216B45] p-5 text-white shadow-[0_10px_24px_rgba(33,107,69,.2)]">
          {farmsLoading ? (
            <div className="h-20 animate-pulse rounded-xl bg-white/20" />
          ) : farm ? (
            <>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[.12em] text-white/65">Farm details</p>
                  <p className="mt-2 text-[18px] font-bold">{farmLoc}</p>
                  <p className="mt-1 text-[12px] text-white/70">{farmArea}</p>
                </div>
                <span className="rounded-full bg-white/15 px-3 py-1.5 text-[10px] font-bold">ACTIVE</span>
              </div>
              <div className="mt-5 grid grid-cols-3 border-t border-white/15 pt-4 text-center">
                <div>
                  <b className="block text-[17px]">{dash.farms ?? "—"}</b>
                  <span className="text-[9px] text-white/65">Farms</span>
                </div>
                <div className="border-x border-white/15">
                  <b className="block text-[17px]">{dash.devices ?? "—"}</b>
                  <span className="text-[9px] text-white/65">Sensors</span>
                </div>
                <div>
                  <b className="block text-[17px]">{farm.current_crop ? "Active" : "Good"}</b>
                  <span className="text-[9px] text-white/65">Farm health</span>
                </div>
              </div>
            </>
          ) : (
            <div className="text-center">
              <p className="text-[13px] font-bold text-white/80">No farm added yet.</p>
              <p className="mt-1 text-[11px] text-white/60">Go to Farm Management to add your first farm.</p>
            </div>
          )}
        </div>

        {/* Current crop */}
        {farm?.current_crop && (
          <>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[17px] font-extrabold text-[#1D382A]">Current crop</h2>
            </div>
            <div className="mb-7 flex gap-3 overflow-x-auto pb-1">
              <div className="min-w-[116px] rounded-2xl border border-[#E4EAE5] bg-white p-3">
                <span className="mb-3 grid h-9 w-9 place-items-center rounded-xl bg-[#E9F4E9] text-[#2C7049]">
                  <Icon name="crop" size={18} />
                </span>
                <p className="text-[13px] font-bold text-[#243F31]">{farm.current_crop}</p>
                <p className="mt-1 text-[10px] text-[#7D8D84]">Active</p>
              </div>
            </div>
          </>
        )}

        <SecondaryButton onClick={() => navigate("more")}>
          <Icon name="plus" size={17} /> Manage farms
        </SecondaryButton>

        {/* Sensors */}
        <div className="mt-7 mb-3 flex items-center justify-between">
          <h2 className="text-[17px] font-extrabold text-[#1D382A]">Connected sensors</h2>
          <button className="text-[11px] font-bold text-[#216B45]">
            {dash.devices_online ?? 0} online
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {reading ? (
            <>
              <SensorCard detail={moistureDetail}    icon="droplet"     label="Soil Moisture" tone="bg-[#E7F4F7] text-[#287A8E]" value={moisture} />
              <SensorCard detail={temperatureDetail} icon="temperature" label="Temperature"   tone="bg-[#FFF0E1] text-[#B06E2B]" value={temperature} />
            </>
          ) : (
            <div className="col-span-2 rounded-[20px] border border-dashed border-[#AFC4B5] p-6 text-center text-[12px] text-[#7B8C82]">
              No sensor data yet. Pair a device to see live readings.
            </div>
          )}
        </div>
        <button
          onClick={() => navigate("more")}
          className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-[#AFC4B5] text-[12px] font-bold text-[#216B45]"
        >
          <Icon name="sensor" size={18} /> Connect Sensor
        </button>
      </div>
    </ScreenShell>
  );
}
