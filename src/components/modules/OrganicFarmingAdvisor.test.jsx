import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// The API client is mocked globally so no real network calls are made. The real
// useApi hook still runs, so the loading -> data transition is exercised too.
const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock: vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
  apiPost: apiPostMock,
}));

import OrganicFarmingAdvisor, { mapServerErrors } from "./OrganicFarmingAdvisor";

const OPTIONS = {
  crops: ["Tomato", "Paddy (Rice)"],
  soil_types: ["Loam", "Sandy"],
  preferences: [
    { id: "organic", title: "Organic farming", short: "No synthetic inputs.", note: "Slow transition." },
    { id: "modern", title: "Modern farming", short: "Recommended doses.", note: "Higher input cost." },
    { id: "integrated", title: "Integrated farming", short: "A middle path.", note: "Builds soil health." },
  ],
  legend: { guidance: "Curated guidance.", unavailable: "Not estimated by FarmIQ." },
  metadata: { last_updated: "2026-10-28" },
};

const METHOD = {
  id: "organic",
  title: "Organic farming",
  short: "No synthetic inputs.",
  summary: "Builds soil organic matter.",
  fit_note: "Requires on-farm organic material.",
  recommended_practices: { status: "guidance", items: ["Compost application"] },
  fertilizer_and_nutrition: { status: "guidance", text: "Use farmyard manure." },
  pest_and_disease_management: { status: "guidance", text: "Scouting-based IPM." },
  estimated_cost_per_acre: { status: "unavailable", value: null, unit: "INR / acre", note: "Use local rates." },
  labour_requirement: { status: "unavailable", text: "Not estimated." },
  water_requirement: { status: "guidance", text: "Mulching reduces evaporation." },
  benefits: { status: "guidance", items: ["Better soil structure"] },
  limitations: { status: "guidance", items: ["Nutrient supply is slower"] },
  soil_health: { status: "guidance", text: "Improves organic carbon." },
  yield_impact: { status: "unavailable", text: "Not guaranteed to stay the same." },
  environmental_impact: { status: "guidance", text: "Lower chemical load." },
  transition_difficulty: { status: "guidance", level: "Medium", text: "Two to three seasons." },
  sources: ["ICAR"],
};

const COMPARISON = {
  crop: "Tomato",
  soil_type: "Loam",
  area_acres: 2.5,
  preference: "integrated",
  preference_title: "Integrated farming",
  methods: [METHOD, { ...METHOD, id: "conventional", title: "Conventional farming" }],
  warnings: ["Reduce fertiliser gradually."],
  resource_assessment: [{ resource: "Compost", available: true, usable_for: ["Compost"] }],
  organic_alternatives: [],
  cautions: ["Do not stop pesticide use abruptly."],
  recommendation: { summary: "Side-by-side comparison for Tomato.", nutrient_note: "Do not replace kg-for-kg.", next_step: "Generate a transition plan." },
  sources: { note: "ICAR / SAU guidance.", integrity_note: "Labelled.", content_source: "reference_file", last_updated: "2026-10-28" },
  disclaimer: "Reference information only.",
};

async function renderAdvisor() {
  apiGetMock.mockResolvedValue(OPTIONS);
  render(<OrganicFarmingAdvisor />);
  await screen.findByText("Tell us about your farm");
}

async function fillRequired(user) {
  await user.selectOptions(screen.getByLabelText("Crop"), "Tomato");
  await user.selectOptions(screen.getByLabelText("Soil type"), "Loam");
  await user.type(screen.getByLabelText("Farm size (acres)"), "2.5");
}

describe("mapServerErrors", () => {
  it("maps semantic (field) and schema (loc) errors to form keys", () => {
    expect(
      mapServerErrors([
        { field: "crop", message: "Select a crop." },
        { loc: ["body", "area_acres"], msg: "Input should be greater than 0" },
      ]),
    ).toEqual({
      crop: "Select a crop.",
      area_acres: "Input should be greater than 0",
    });
  });

  it("keeps the first error per field and ignores unusable entries", () => {
    expect(
      mapServerErrors([
        { field: "crop", message: "First." },
        { field: "crop", message: "Second." },
        { message: "no key" },
      ]),
    ).toEqual({ crop: "First." });
  });
});

describe("OrganicFarmingAdvisor", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiPostMock.mockReset();
  });

  it("shows a loading skeleton before the reference content arrives", () => {
    apiGetMock.mockReturnValue(new Promise(() => {}));
    const { container } = render(<OrganicFarmingAdvisor />);
    expect(container.querySelectorAll(".animate-pulse").length).toBe(3);
  });

  it("renders the form once the options load", async () => {
    await renderAdvisor();
    expect(screen.getByLabelText("Crop")).toBeInTheDocument();
    expect(screen.getByLabelText("Soil type")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare Farming Methods" })).toBeInTheDocument();
  });

  it("renders an error state with retry when the options fail to load", async () => {
    apiGetMock.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    render(<OrganicFarmingAdvisor />);
    expect(await screen.findByText(/Could not load the farming methods \(500\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("renders an empty state when the reference catalogue is empty", async () => {
    apiGetMock.mockResolvedValue({ ...OPTIONS, crops: [], soil_types: [] });
    render(<OrganicFarmingAdvisor />);
    expect(await screen.findByText(/No farming-method reference data is available/)).toBeInTheDocument();
  });

  it("blocks submission and shows validation errors for an incomplete form", async () => {
    const user = userEvent.setup();
    await renderAdvisor();

    await user.click(screen.getByRole("button", { name: "Compare Farming Methods" }));

    expect(screen.getByText("Select a crop.")).toBeInTheDocument();
    expect(screen.getByText("Select a soil type.")).toBeInTheDocument();
    expect(screen.getByText("Enter a farm size greater than zero.")).toBeInTheDocument();
    expect(apiPostMock).not.toHaveBeenCalled();
  });

  it("posts the built payload and renders the comparison", async () => {
    const user = userEvent.setup();
    await renderAdvisor();
    apiPostMock.mockResolvedValue(COMPARISON);

    await fillRequired(user);
    await user.click(screen.getByText("Cow dung / farmyard manure"));
    await user.click(screen.getByRole("button", { name: "Compare Farming Methods" }));

    expect(await screen.findByText("Comparison for Tomato")).toBeInTheDocument();
    expect(apiPostMock).toHaveBeenCalledWith(
      "/api/farming-methods/compare",
      expect.objectContaining({
        crop: "Tomato",
        soil_type: "Loam",
        area_acres: 2.5,
        preference: "integrated",
        resources: expect.objectContaining({ cow_dung: true, other: [] }),
      }),
    );
    // Cost must be shown as explicitly not estimated, never as a fabricated figure.
    expect(screen.getAllByText("Not estimated by FarmIQ").length).toBeGreaterThan(0);
  });

  it("maps a 422 response onto the form fields", async () => {
    const user = userEvent.setup();
    await renderAdvisor();
    apiPostMock.mockRejectedValue(
      Object.assign(new Error("Input validation failed."), {
        status: 422,
        data: { errors: [{ field: "crop", message: "'Maize' is not in the supported crop list." }] },
      }),
    );

    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Compare Farming Methods" }));

    expect(await screen.findByText("'Maize' is not in the supported crop list.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Input validation failed.");
  });
});
