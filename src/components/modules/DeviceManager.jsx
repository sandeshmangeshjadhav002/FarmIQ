import { useState } from "react";
import { Metric, ModuleButton, SelectField } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";
import { apiPost } from "@/lib/apiClient";
import useApi from "@/hooks/useApi";

/**
 * Device Management — fetches real devices from GET /api/devices,
 * pairs new ones via POST /api/devices/pair.
 */
export default function DeviceManager() {
  const { data, loading, error, refetch } = useApi("/api/devices");
  const devices = data?.items ?? [];

  const [pairing, setPairing] = useState(false);
  const [farmAssign, setFarmAssign] = useState("Assign later");
  const [config, setConfig] = useState("Soil sensor");
  const [saving, setSaving] = useState(false);
  const [pairError, setPairError] = useState(null);

  const farmsData = useApi("/api/farms");
  const farmNames = (farmsData.data?.items ?? []).map((f) => f.name);
  const farmOptions = [...farmNames, "Assign later"];

  const onlineCount = devices.filter((d) => d.is_online).length;
  const offlineCount = devices.filter((d) => !d.is_online).length;

  const simulatePair = async () => {
    if (saving) return; // re-entrancy guard (the button is also disabled)
    setSaving(true);
    setPairError(null);
    try {
      const farmItem = (farmsData.data?.items ?? []).find(
        (f) => f.name === farmAssign,
      );
      await apiPost("/api/devices/pair", {
        name: `ESP32 Node ${devices.length + 1}`,
        farm_id: farmItem?.id ?? null,
        config: config.toLowerCase().replace(/ /g, "_"),
      });
      setPairing(false);
      refetch();
    } catch (err) {
      // Was silent before: a failed pairing left the panel looking unchanged,
      // so the user could not tell the device had not been added.
      setPairError(
        err.message || "Could not pair the device. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <LoadingState />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <Metric
          label="Connected"
          value={String(onlineCount)}
          note="Online now"
        />
        <Metric
          label="Offline"
          value={String(offlineCount)}
          note="Needs attention"
        />
        <Metric
          label="Total"
          value={String(devices.length)}
          note="Paired devices"
        />
      </div>

      <section className="overflow-hidden rounded-[22px] border border-[#E0E8E2] bg-white">
        {error && (
          <div className="p-6 text-center">
            <p
              role="alert"
              className="text-[12px] font-semibold text-[#9D4C3E]"
            >
              {error.message || "Could not load your devices."}
            </p>
            <button
              onClick={refetch}
              className="mt-2 text-[11px] font-extrabold text-[#216B45] underline underline-offset-2"
            >
              Try again
            </button>
          </div>
        )}
        {!error && devices.length === 0 && (
          <p className="p-6 text-center text-[12px] text-[#7B8C82]">
            No devices paired yet.
          </p>
        )}
        {!error &&
          devices.map((item, index) => (
            <button
              key={item.id}
              className={`flex w-full items-center gap-3 p-4 text-left ${
                index ? "border-t border-[#EDF1EE]" : ""
              }`}
            >
              <span
                className={`grid h-10 w-10 place-items-center rounded-xl ${
                  item.is_online
                    ? "bg-[#E5F3F7] text-[#28778A]"
                    : "bg-[#FCE9E5] text-[#A55243]"
                }`}
              >
                <ModuleIcon name="device" size={18} />
              </span>
              <span className="min-w-0 flex-1">
                <b className="block text-[11px] text-[#294234]">{item.name}</b>
                <span className="text-[9px] text-[#829188]">
                  {item.is_online ? "Online" : "Offline"}
                  {item.last_seen_at
                    ? ` · Last seen ${new Date(
                        item.last_seen_at,
                      ).toLocaleTimeString()}`
                    : ""}
                </span>
              </span>
              <b className="text-[10px] text-[#557064]">{item.config}</b>
            </button>
          ))}
      </section>

      {!pairing ? (
        <ModuleButton onClick={() => setPairing(true)}>
          <ModuleIcon name="plus" size={16} />
          Add device
        </ModuleButton>
      ) : (
        <section className="rounded-[22px] border border-[#CFE0D4] bg-white p-4 text-center">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-full bg-[#E8F3EA] text-[#216B45]">
            <ModuleIcon name="signal" />
          </span>
          <h2 className="mt-3 text-[14px] font-extrabold text-[#213D2F]">
            Pairing mode
          </h2>
          <p className="mt-1 text-[10px] leading-5 text-[#73867A]">
            Power on your ESP32/ESP8266 device and hold its PAIR button for 5
            seconds.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <SelectField
              label="Assign to farm"
              value={farmAssign}
              onChange={setFarmAssign}
              options={farmOptions}
            />
            <SelectField
              label="Configuration"
              value={config}
              onChange={setConfig}
              options={["Soil sensor", "Weather node", "Tank level"]}
            />
          </div>
          <div className="mt-3 flex gap-2">
            <ModuleButton secondary onClick={() => setPairing(false)}>
              Cancel
            </ModuleButton>
            <ModuleButton onClick={simulatePair} disabled={saving}>
              {saving ? "Pairing…" : "Simulate device found"}
            </ModuleButton>
          </div>
          {pairError && (
            <p
              role="alert"
              className="mt-3 rounded-xl bg-[#FCE9E5] p-3 text-[10px] font-semibold leading-5 text-[#9D4C3E]"
            >
              {pairError}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((n) => (
        <div
          key={n}
          className="h-16 animate-pulse rounded-[20px] bg-[#E8F0EB]"
        />
      ))}
    </div>
  );
}
