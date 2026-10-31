/**
 * Reusable location selector — the single UI for setting the farmer's shared
 * location. Shows the current location and offers GPS + manual search.
 *
 * Used in the home screen header area so the farmer sees and can change their
 * location from one place, instead of being asked repeatedly by each feature.
 *
 * Design follows the existing FarmIQ glassmorphism style:
 *   bg-white/40 backdrop-blur-md, rounded-[22px], border border-white/30.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";

import Icon from "@/components/common/Icon";
import { useLocation } from "@/lib/locationStore";

export default function LocationSelector({ compact = false }) {
  const { t } = useTranslation();
  const {
    location,
    locating,
    locationError,
    detectLocation,
    setManualLocation,
    hasLocation,
    hasCoordinates,
  } = useLocation();

  const [showSearch, setShowSearch] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [localError, setLocalError] = useState(null);

  const handleGps = async () => {
    setLocalError(null);
    try {
      await detectLocation();
    } catch {
      // error is already in locationError from the store
    }
  };

  const handleSearch = async () => {
    const name = searchText.trim();
    if (name.length < 2) {
      setLocalError(t("locationSelector.typeAtLeast"));
      return;
    }
    setLocalError(null);
    try {
      await setManualLocation(name);
      setShowSearch(false);
      setSearchText("");
    } catch {
      // non-fatal — setManualLocation handles failure gracefully
      setShowSearch(false);
      setSearchText("");
    }
  };

  const displayError = localError || locationError;

  return (
    <div className="rounded-[18px] border border-white/30 bg-white/40 backdrop-blur-md p-3">
      {/* Current location display */}
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-xl bg-[#E5F3F7] text-[#28778A]">
          <Icon name="pin" size={15} />
        </span>
        <div className="min-w-0 flex-1">
          {hasLocation ? (
            <>
              <p className="truncate text-[12px] font-extrabold text-[#17392A]">
                {location.label}
              </p>
              <p className="text-[9px] text-[#7B8C82]">
                {hasCoordinates
                  ? `${location.latitude?.toFixed(3)}, ${location.longitude?.toFixed(3)}`
                  : t("locationSelector.noCoordinates")}
              </p>
            </>
          ) : (
            <p className="text-[11px] font-semibold text-[#7B8C82]">
              {compact
                ? t("locationSelector.setLocation")
                : t("locationSelector.noLocationSet")}
            </p>
          )}
        </div>
        {/* Change button */}
        <button
          onClick={() => setShowSearch((v) => !v)}
          className="shrink-0 rounded-full border border-[#D9E4DC] bg-white px-3 py-1.5 text-[9px] font-extrabold text-[#216B45] transition active:scale-95"
        >
          {hasLocation
            ? t("locationSelector.change")
            : t("locationSelector.set")}
        </button>
      </div>

      {/* Location source badge */}
      {hasLocation && location.source && (
        <div className="mt-1.5 flex items-center gap-1">
          <span className="rounded-full bg-[#EAF6EF] px-2 py-0.5 text-[8px] font-extrabold uppercase tracking-[.06em] text-[#216B45]">
            {location.source === "gps"
              ? t("locationSelector.gps")
              : location.source === "farm"
              ? t("locationSelector.savedFarm")
              : t("locationSelector.manual")}
          </span>
        </div>
      )}

      {/* Expandable search + GPS panel */}
      {showSearch && (
        <div className="mt-3 space-y-2 border-t border-white/20 pt-3">
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleGps}
              disabled={locating}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-[#CFE0D5] bg-[#F0F7F2] px-3 py-2 text-[10px] font-extrabold text-[#216B45] disabled:opacity-50"
            >
              <Icon name={locating ? "signal" : "pin"} size={14} />
              {locating
                ? t("locationSelector.detecting")
                : t("locationSelector.useGps")}
            </button>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder={t("locationSelector.placeholder")}
              className="h-10 min-w-0 flex-1 rounded-xl border border-[#DDE6DF] bg-white px-3 text-[11px] text-[#203B2D] outline-none focus:border-[#76A58A]"
            />
            <button
              onClick={handleSearch}
              disabled={locating}
              className="flex h-10 shrink-0 items-center justify-center rounded-xl bg-[#216B45] px-4 text-[10px] font-extrabold text-white disabled:opacity-50"
            >
              {locating ? "…" : t("locationSelector.search")}
            </button>
          </div>

          <p className="text-[9px] leading-4 text-[#84938B]">
            {t("locationSelector.hint")}
          </p>
        </div>
      )}

      {/* Error display */}
      {displayError && (
        <p className="mt-2 rounded-xl bg-[#FCE9E5] p-2 text-[9px] font-semibold leading-4 text-[#9D4C3E]">
          {displayError}
        </p>
      )}
    </div>
  );
}
