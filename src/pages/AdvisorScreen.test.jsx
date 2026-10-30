import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiGetMock } = vi.hoisted(() => ({ apiGetMock: vi.fn() }));

vi.mock("@/lib/apiClient", () => ({
  apiGet: apiGetMock,
}));

import AdvisorScreen from "./AdvisorScreen";

const FARM = {
  id: "f1",
  name: "Green Valley Farm",
  location: "Nashik, Maharashtra",
  current_crop: "Tomato",
};

const TASK_TITLES = [
  "Choose a suitable crop",
  "Understand soil conditions",
  "Get fertilizer guidance",
  "Assess irrigation needs",
  "Manage drought risks",
  "Compare farming methods",
  "Analyse a crop image",
];

describe("AdvisorScreen", () => {
  let navigate;
  let openModule;

  beforeEach(() => {
    apiGetMock.mockReset();
    navigate = vi.fn();
    openModule = vi.fn();
  });

  it("lists every advisory task as a shortcut on one screen", async () => {
    apiGetMock.mockResolvedValue({ items: [FARM] });

    render(<AdvisorScreen navigate={navigate} openModule={openModule} />);

    for (const title of TASK_TITLES) {
      expect(await screen.findByText(title)).toBeInTheDocument();
    }
  });

  it("opens the existing tool for the chosen task", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue({ items: [FARM] });

    render(<AdvisorScreen navigate={navigate} openModule={openModule} />);

    await user.click(await screen.findByText("Understand soil conditions"));
    expect(openModule).toHaveBeenCalledWith("soil");

    await user.click(screen.getByText("Analyse a crop image"));
    expect(openModule).toHaveBeenCalledWith("image-analysis");
  });

  it("states which farm the guidance is framed around", async () => {
    apiGetMock.mockResolvedValue({ items: [FARM] });

    render(<AdvisorScreen navigate={navigate} openModule={openModule} />);

    expect(await screen.findByText("Advising on")).toBeInTheDocument();
    expect(screen.getByText("Green Valley Farm")).toBeInTheDocument();
    expect(screen.getByText("Nashik, Maharashtra · Tomato")).toBeInTheDocument();
  });

  it("offers farm setup when the account has no farm yet", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue({ items: [] });

    render(<AdvisorScreen navigate={navigate} openModule={openModule} />);

    expect(await screen.findByText("No farm added yet")).toBeInTheDocument();
    expect(screen.queryByText("Advising on")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Add a farm/ }));
    expect(openModule).toHaveBeenCalledWith("farm-management");
  });

  it("keeps the free-form assistant as one option, not the only one", async () => {
    const user = userEvent.setup();
    apiGetMock.mockResolvedValue({ items: [FARM] });

    render(<AdvisorScreen navigate={navigate} openModule={openModule} />);

    await user.click(
      await screen.findByText("Ask FarmIQ in your own words"),
    );
    expect(navigate).toHaveBeenCalledWith("chat");

    await user.click(screen.getByText("Browse the Knowledge Centre"));
    expect(openModule).toHaveBeenCalledWith("knowledge");
  });
});
