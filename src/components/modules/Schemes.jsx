import { useState } from "react";

import useApi from "@/hooks/useApi";
import ModuleIcon from "./ModuleIcon";
import { ModuleButton } from "./ModuleShared";

/**
 * Government Agricultural Schemes.
 *
 * Reads verified reference data from GET /api/schemes (served from a structured
 * data file, not an LLM/RAG). Each field is badged as either "confirmed" on the
 * official portal or "needs verification", and every scheme carries a
 * last-verified date and (where available) the official link.
 */
export default function Schemes() {
  const { data, loading, error, refetch } = useApi("/api/schemes");
  const [openId, setOpenId] = useState(null);

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((n) => (
          <div key={n} className="h-24 animate-pulse rounded-[20px] bg-[#E8F0EB]" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <p className="rounded-2xl bg-[#FCE9E5] p-4 text-[11px] font-semibold text-[#9D4C3E]">
          Could not load scheme information{error.status ? ` (${error.status})` : ""}.
        </p>
        <ModuleButton secondary onClick={refetch}>
          Try again
        </ModuleButton>
      </div>
    );
  }

  const schemes = data?.schemes ?? [];

  return (
    <div className="space-y-4">
      <section className="rounded-[22px] border border-[#DCE6DF] bg-[#F7FAF8] p-4">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-[#E9F1EA] text-[#3C6A4D]">
            <ModuleIcon name="shield" size={16} />
          </span>
          <h2 className="text-[13px] font-extrabold text-[#213D2F]">{data?.metadata?.title}</h2>
        </div>
        <p className="mt-2 text-[10px] leading-5 text-[#75867C]">{data?.metadata?.disclaimer}</p>
        <p className="mt-2 text-[10px] leading-5 text-[#75867C]">
          {data?.metadata?.verification_note}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Legend tone="ok" text="Confirmed" />
          <Legend tone="warn" text="Needs verification" />
          <span className="rounded-full bg-white px-2.5 py-1 text-[9px] font-extrabold text-[#52675B]">
            Last verified: {data?.metadata?.last_verified}
          </span>
        </div>
      </section>

      {schemes.map((scheme) => (
        <SchemeCard
          key={scheme.id}
          scheme={scheme}
          open={openId === scheme.id}
          onToggle={() => setOpenId(openId === scheme.id ? null : scheme.id)}
        />
      ))}

      {data?.additional_support?.length > 0 && (
        <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
          <h2 className="text-[13px] font-extrabold text-[#203C2E]">Other useful support</h2>
          <ul className="mt-3 space-y-2">
            {data.additional_support.map((item) => (
              <li key={item.name} className="flex items-start gap-2">
                <StatusDot status={item.status} />
                <span className="text-[10px] leading-5 text-[#52675B]">
                  <b>{item.name}</b> — {item.summary}
                </span>
              </li>
            ))}
          </ul>
          {data?.cautions?.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-[#EDF1EE] pt-3">
              {data.cautions.map((c, i) => (
                <li key={i} className="text-[9px] leading-4 text-[#84938B]">
                  • {c}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function SchemeCard({ scheme, open, onToggle }) {
  return (
    <section className="overflow-hidden rounded-[22px] border border-[#E0E8E2] bg-white">
      <button onClick={onToggle} className="flex w-full items-start gap-3 p-4 text-left">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#E9F1EA] text-[#3C6A4D]">
          <ModuleIcon name="shield" size={18} />
        </span>
        <span className="min-w-0 flex-1">
          <b className="block text-[12px] text-[#294234]">{scheme.name}</b>
          <span className="mt-1 block text-[9px] text-[#84938B]">{scheme.category}</span>
          <span className="mt-1 block text-[10px] leading-5 text-[#75867C]">{scheme.summary}</span>
        </span>
        <span className="text-[#829188]">
          <ModuleIcon name={open ? "back" : "arrow"} size={16} />
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-[#EDF1EE] p-4">
          <Field label="Purpose" item={scheme.purpose} />
          <Field label="Eligibility" item={scheme.eligibility} />

          <div>
            <FieldLabel label="Benefits" />
            <ul className="mt-1.5 space-y-1.5">
              {scheme.benefits.map((b, i) => (
                <li key={i} className="flex items-start gap-2">
                  <StatusDot status={b.status} />
                  <span className="text-[10px] leading-5 text-[#52675B]">{b.text}</span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <FieldLabel label="How to apply" />
            <ol className="mt-1.5 space-y-1.5">
              {scheme.application_process.map((step, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-[3px] grid h-4 w-4 shrink-0 place-items-center rounded-full bg-[#E9F1EA] text-[8px] font-extrabold text-[#3C6A4D]">
                    {i + 1}
                  </span>
                  <span className="text-[10px] leading-5 text-[#52675B]">
                    {step.step}
                    {step.status === "needs_verification" && <VerifyBadge />}
                  </span>
                </li>
              ))}
            </ol>
          </div>

          {scheme.official_links?.length > 0 && (
            <div>
              <FieldLabel label="Official link" />
              <div className="mt-1.5 flex flex-col gap-1.5">
                {scheme.official_links.map((link) => (
                  <a
                    key={link.url}
                    href={link.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="text-[10px] font-extrabold text-[#216B45] underline"
                  >
                    {link.label} ↗
                  </a>
                ))}
              </div>
            </div>
          )}

          {scheme.verification_note && (
            <p className="rounded-xl bg-[#FFF5DE] p-3 text-[9px] leading-4 text-[#8A6D2B]">
              {scheme.verification_note}
            </p>
          )}

          <p className="text-[9px] text-[#9AA79F]">Last verified: {scheme.last_verified}</p>
        </div>
      )}
    </section>
  );
}

function Field({ label, item }) {
  if (!item) return null;
  return (
    <div>
      <FieldLabel label={label} checked={item.status === "confirmed"} />
      <p className="mt-1 text-[10px] leading-5 text-[#52675B]">
        {item.text}
        {item.status === "needs_verification" && <VerifyBadge />}
      </p>
      {item.note && <p className="mt-1 text-[9px] italic leading-4 text-[#8A6D2B]">{item.note}</p>}
    </div>
  );
}

function FieldLabel({ label, checked }) {
  return (
    <span className="flex items-center gap-2">
      <span className="text-[9px] font-extrabold uppercase tracking-[.08em] text-[#7A8B82]">
        {label}
      </span>
      {checked && (
        <span className="rounded-full bg-[#EAF6EF] px-1.5 py-0.5 text-[8px] font-extrabold text-[#216B45]">
          confirmed
        </span>
      )}
    </span>
  );
}

function VerifyBadge() {
  return (
    <span className="ml-1.5 whitespace-nowrap rounded-full bg-[#FFF5DE] px-1.5 py-0.5 text-[8px] font-extrabold text-[#916112]">
      verify
    </span>
  );
}

function StatusDot({ status }) {
  return (
    <span
      className={`mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full ${
        status === "confirmed" ? "bg-[#2F7D52]" : "bg-[#D99A2B]"
      }`}
    />
  );
}

function Legend({ tone, text }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-[9px] font-extrabold text-[#52675B]">
      <span className={`h-1.5 w-1.5 rounded-full ${tone === "ok" ? "bg-[#2F7D52]" : "bg-[#D99A2B]"}`} />
      {text}
    </span>
  );
}
