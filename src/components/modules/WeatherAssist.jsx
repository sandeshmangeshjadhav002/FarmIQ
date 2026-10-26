import { useCallback, useState } from "react";

import { apiGet } from "@/lib/apiClient";
import ModuleIcon from "./ModuleIcon";
import { ModuleButton } from "./ModuleShared";

/**
 * Weather auto-fill panel for the ML prediction forms.
 *
 * Calls GET /api/weather/current with either the browser's geolocation or a
 * manually typed place name, then maps the response's `autofill` block onto
 * form fields via `fieldMap` ({ formFieldKey: autofillKey }).
 *
 * Every number comes from the live Open-Meteo response — nothing is invented.
 * The three rainfall quantities are shown separately (current observation,
 * forecast, historical accumulation) so they can never be confused. When the
 * weather service is down the panel shows an error and the form stays usable:
 * auto-fill is optional and every value remains editable.
 *
 * @param {object}   props.fieldMap   - { formFieldKey: "temperature"|"humidity"|"rainfall" }
 * @param {Function} props.onAutofill - Called with (values, report) to fill the form.
 */
export default function WeatherAssist({ fieldMap = {}, onAutofill }) {
  const [location, setLocation] = useState("");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastQuery, setLastQuery] = useState(null);

  const applyAutofill = useCallback(
    (rep) => {
      const applied = {};
      for (const [formKey, autoKey] of Object.entries(fieldMap)) {
        const entry = rep?.autofill?.[autoKey];
        if (entry && typeof entry.value === "number") applied[formKey] = entry.value;
      }
      if (Object.keys(applied).length) onAutofill?.(applied, rep);
      return applied;
    },
    [fieldMap, onAutofill]
  );

  const load = useCallback(
    async (query) => {
      setLoading(true);
      setError(null);
      try {
        const qs =
          query.lat != null
            ? `?lat=${query.lat}&lon=${query.lon}`
            : `?location=${encodeURIComponent(query.location)}`;
        const rep = await apiGet(`/api/weather/current${qs}`);
        setReport(rep);
        setLastQuery(query);
        applyAutofill(rep);
      } catch (err) {
        setReport(null);
        if (err.status === 503) {
          setError(
            "The weather service is unavailable right now. Auto-fill is off — " +
              "type the values manually and the prediction still works."
          );
        } else {
          setError(err.message || "Could not fetch weather for that location.");
        }
      } finally {
        setLoading(false);
      }
    },
    [applyAutofill]
  );

  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setError("This device does not support location lookup. Enter a place name instead.");
      return;
    }
    setLoading(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => load({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => {
        setLoading(false);
        setError("Location permission denied. Enter a place name instead.");
      },
      { timeout: 10000, maximumAge: 600000 }
    );
  };

  const lookUp = () => {
    const name = location.trim();
    if (name.length < 2) {
      setError("Type at least 2 characters of a place name.");
      return;
    }
    load({ location: name });
  };

  const applied = report ? Object.entries(fieldMap).filter(([, a]) => report.autofill?.[a]) : [];

  return (
    <section className="space-y-3 rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E5F3F7] text-[#28778A]">
            <ModuleIcon name="drop" size={16} />
          </span>
          <h2 className="text-[13px] font-extrabold text-[#213D2F]">Auto-fill from weather</h2>
        </div>
        {lastQuery && (
          <button
            onClick={() => load(lastQuery)}
            disabled={loading}
            className="rounded-full border border-[#D9E4DC] bg-white px-3 py-1.5 text-[10px] font-extrabold text-[#216B45] disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[140px] flex-1">
          <span className="mb-1.5 block text-[10px] font-bold text-[#52675B]">Location</span>
          <input
            type="text"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && lookUp()}
            placeholder="e.g. Nashik"
            className="h-10 w-full rounded-xl border border-[#DDE6DF] bg-white px-3 text-[12px] text-[#203B2D] outline-none focus:border-[#76A58A]"
          />
        </label>
        <ModuleButton onClick={useMyLocation} disabled={loading}>
          <ModuleIcon name="signal" size={15} />
          {loading ? "Loading…" : "Use my location"}
        </ModuleButton>
        <button
          onClick={lookUp}
          disabled={loading}
          className="h-11 rounded-xl border border-[#D9E4DC] bg-white px-4 text-[12px] font-extrabold text-[#216B45] disabled:opacity-50"
        >
          Look up
        </button>
      </div>

      {error && (
        <p className="rounded-xl bg-[#FCE9E5] p-3 text-[10px] font-semibold leading-5 text-[#9D4C3E]">
          {error}
        </p>
      )}

      {report && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-[9px] text-[#75867C]">
            <span className="rounded-full bg-white px-2.5 py-1 font-extrabold text-[#216B45]">
              Source: {report.source}
            </span>
            {report.location?.name && <span>{report.location.name}</span>}
            <span>
              {report.location?.latitude}, {report.location?.longitude}
            </span>
          </div>

          {/* Current observation — the only source used for temperature/humidity */}
          <div className="rounded-2xl border border-[#E0E8E2] bg-white p-3">
            <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
              {report.current?.label ?? "Current observation"}
            </p>
            <div className="mt-2 grid grid-cols-4 gap-2 text-[11px]">
              <Readout label="Temp" value={fmt(report.current?.temperature_c, "°C")} />
              <Readout label="Humidity" value={fmt(report.current?.humidity_pct, "%")} />
              <Readout label="Rain now" value={fmt(report.current?.precipitation_mm, "mm")} />
              <Readout
                label="Observed"
                value={report.current?.observed_at ? report.current.observed_at.slice(11, 16) : "—"}
              />
            </div>
          </div>

          {/* Two distinct rainfall quantities, never merged */}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-2xl border border-[#E5EEF7] bg-white p-3">
              <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
                {report.historical_rainfall?.label}
              </p>
              <p className="mt-2 text-[17px] font-extrabold text-[#1D3A2B]">
                {fmt(report.historical_rainfall?.total_mm, "mm")}
              </p>
              <p className="mt-1 text-[9px] text-[#84938B]">
                {report.historical_rainfall?.days} days · last 7 days{" "}
                {fmt(report.historical_rainfall?.past_7_days_mm, "mm")}
              </p>
            </div>
            <div className="rounded-2xl border border-[#E5EEF7] bg-white p-3">
              <p className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
                {report.forecast_rainfall?.label}
              </p>
              <p className="mt-2 text-[17px] font-extrabold text-[#1D3A2B]">
                {fmt(report.forecast_rainfall?.total_mm, "mm")}
              </p>
              <p className="mt-1 text-[9px] text-[#84938B]">
                Next {report.forecast_rainfall?.days} days
              </p>
            </div>
          </div>

          {applied.length > 0 ? (
            <div className="rounded-2xl bg-[#EAF6EF] p-3">
              <p className="text-[10px] font-extrabold text-[#1D4A33]">
                Filled {applied.length} field{applied.length > 1 ? "s" : ""} — you can edit these
              </p>
              <ul className="mt-2 space-y-1.5">
                {applied.map(([formKey, autoKey]) => {
                  const entry = report.autofill[autoKey];
                  return (
                    <li key={formKey} className="text-[10px] leading-5 text-[#3C5C49]">
                      <b>{entry.label}</b>: <b>{entry.value}</b> {entry.unit} ·{" "}
                      <span className="text-[#75867C]">{entry.origin}</span>
                      {entry.note && (
                        <span className="mt-0.5 block text-[9px] italic text-[#8A6D2B]">
                          {entry.note}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <p className="text-[10px] text-[#75867C]">
              No matching form fields were auto-filled from this reading.
            </p>
          )}

          {report.notes?.length > 0 && (
            <ul className="space-y-1">
              {report.notes.map((n) => (
                <li key={n} className="text-[9px] leading-4 text-[#84938B]">
                  • {n}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function Readout({ label, value }) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-[.06em] text-[#8A998F]">{label}</p>
      <p className="mt-1 text-[13px] font-extrabold text-[#213D2F]">{value}</p>
    </div>
  );
}

function fmt(value, unit) {
  return typeof value === "number" ? `${value} ${unit}` : "—";
}
