import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiPostMock } = vi.hoisted(() => ({ apiPostMock: vi.fn() }));

vi.mock("@/lib/apiClient", () => ({
  apiPost: apiPostMock,
}));

import PredictionExplanation from "./PredictionExplanation";

// A real-shaped ML response: the model's own output, which the explanation must
// reproduce rather than replace.
const RESULT = { label: "Chickpea", source: "model", confidence: 0.92 };
const INPUT = { N: 90, P: 42, K: 43, ph: 6.7 };

const GOOD_ANSWER = [
  "**Explanation:** Chickpea is the strongest match for this soil.",
  "Key factors: nitrogen 90 and pH 6.7 sit in the preferred range.",
  "Next step: sow within the next 10 days while the moisture is adequate.",
  "Limitations: this does not account for local pest history.",
].join("\n");

describe("PredictionExplanation", () => {
  beforeEach(() => {
    apiPostMock.mockReset();
  });

  it("renders nothing until there is a prediction to explain", () => {
    const { container } = render(
      <PredictionExplanation moduleKey="crop-recommendation" />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(apiPostMock).not.toHaveBeenCalled();
  });

  it("sends the model's own output to the assistant, once", async () => {
    apiPostMock.mockResolvedValue({ answer: GOOD_ANSWER });

    render(
      <PredictionExplanation
        farmName="Green Valley Farm"
        input={INPUT}
        moduleKey="crop-recommendation"
        result={RESULT}
      />,
    );

    await screen.findByText("Explanation");
    expect(apiPostMock).toHaveBeenCalledTimes(1);
    expect(apiPostMock).toHaveBeenCalledWith(
      "/api/chat",
      expect.objectContaining({
        top_k: 4,
        ml_results: expect.objectContaining({
          source: "farmiq_ml_model",
          domain: "crop-recommendation",
          prediction: "Chickpea",
          model_source: "model",
          inputs: INPUT,
          farm: "Green Valley Farm",
        }),
      }),
    );
  });

  it("shows the four labelled parts of the explanation", async () => {
    apiPostMock.mockResolvedValue({ answer: GOOD_ANSWER });

    render(
      <PredictionExplanation
        input={INPUT}
        moduleKey="crop-recommendation"
        result={RESULT}
      />,
    );

    expect(await screen.findByText("Explanation")).toBeInTheDocument();
    expect(screen.getByText("Key Factors")).toBeInTheDocument();
    expect(screen.getByText("Next Step")).toBeInTheDocument();
    expect(screen.getByText("Limitations")).toBeInTheDocument();
    // The assistant's own wording is shown, not rewritten.
    expect(
      screen.getByText(/nitrogen 90 and pH 6.7 sit in the preferred range/),
    ).toBeInTheDocument();
  });

  it("re-orders the parts even when the assistant replies out of sequence", async () => {
    apiPostMock.mockResolvedValue({
      answer: [
        "Next step: irrigate lightly tomorrow.",
        "Limitations: does not cover pest history.",
        "Explanation: the soil is suited to chickpea.",
        "Key factors: pH 6.7.",
      ].join("\n"),
    });

    render(
      <PredictionExplanation
        input={INPUT}
        moduleKey="crop-recommendation"
        result={RESULT}
      />,
    );

    await screen.findByText("Explanation");
    const labels = screen.getAllByRole("term").map((node) => node.textContent);
    expect(labels).toEqual([
      "Explanation",
      "Key Factors",
      "Next Step",
      "Limitations",
    ]);
  });

  it("keeps the prediction visible and explains the gap when the assistant is down", async () => {
    apiPostMock.mockRejectedValue(
      Object.assign(new Error("RAG unavailable"), { status: 503 }),
    );

    render(
      <PredictionExplanation
        input={INPUT}
        moduleKey="crop-recommendation"
        result={RESULT}
      />,
    );

    expect(
      await screen.findByText(/AI assistant is not available right now/),
    ).toBeInTheDocument();
    // The prediction itself is never touched by the AI failure.
    expect(
      screen.getByText(
        /prediction above is unchanged — it comes from the model/,
      ),
    ).toBeInTheDocument();
  });

  it("asks the farmer to sign in on a 401 instead of showing a raw error", async () => {
    apiPostMock.mockRejectedValue(
      Object.assign(new Error("Unauthorized"), { status: 401 }),
    );

    render(
      <PredictionExplanation input={INPUT} moduleKey="yield" result={RESULT} />,
    );

    expect(
      await screen.findByText(/Sign in again to see the explanation/),
    ).toBeInTheDocument();
  });

  it("retries the explanation without re-running the prediction", async () => {
    const user = userEvent.setup();
    apiPostMock
      .mockRejectedValueOnce(Object.assign(new Error("boom"), { status: 503 }))
      .mockResolvedValueOnce({ answer: GOOD_ANSWER });

    render(
      <PredictionExplanation
        input={INPUT}
        moduleKey="crop-recommendation"
        result={RESULT}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: /Try the explanation again/ }),
    );

    expect(await screen.findByText("Explanation")).toBeInTheDocument();
    expect(apiPostMock).toHaveBeenCalledTimes(2);
    // The same prediction was explained both times — the model was not re-run.
    expect(apiPostMock.mock.calls[1][1].ml_results.prediction).toBe("Chickpea");
  });
});
