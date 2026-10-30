import { useState } from "react";
import { ModuleButton } from "./ModuleShared";
import ModuleIcon from "./ModuleIcon";
import { defaultReminders } from "@/data/modules";

/**
 * Farming Calendar module — reminders for sowing, spraying and harvest dates.
 * Reminder data is seeded from `data/modules.js`.
 */
export default function CalendarManager() {
  const [reminders, setReminders] = useState(defaultReminders);
  const [newTitle, setNewTitle] = useState("");

  const today = new Date().toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const pending = reminders.filter((r) => !r.done).length;

  const addReminder = () => {
    if (!newTitle.trim()) return;
    setReminders((prev) => [
      {
        id: Date.now(),
        title: newTitle.trim(),
        date: "Tomorrow • 8:00 AM",
        done: false,
      },
      ...prev,
    ]);
    setNewTitle("");
  };

  const toggleDone = (id) => {
    setReminders((prev) =>
      prev.map((r) => (r.id === id ? { ...r, done: !r.done } : r)),
    );
  };

  const editReminder = (item) => {
    const updated = window.prompt("Edit reminder", item.title);
    if (updated?.trim()) {
      setReminders((prev) =>
        prev.map((r) =>
          r.id === item.id ? { ...r, title: updated.trim() } : r,
        ),
      );
    }
  };

  const deleteReminder = (id) => {
    setReminders((prev) => prev.filter((r) => r.id !== id));
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") addReminder();
  };

  return (
    <div className="space-y-4">
      {/* Today */}
      <section className="rounded-[22px] bg-[#216B45] p-4 text-white">
        <p className="text-[10px] font-bold uppercase tracking-[.1em] text-white/65">
          {today}
        </p>
        <p className="mt-1 text-[20px] font-extrabold tracking-[-.02em]">
          {pending} reminder{pending === 1 ? "" : "s"} pending
        </p>
      </section>

      {/* Add reminder */}
      <section className="rounded-[22px] border border-[#E0E8E2] bg-white p-4">
        <h2 className="text-[14px] font-extrabold text-[#213D2F]">
          Add reminder
        </h2>
        <div className="mt-3 flex gap-2">
          <input
            aria-label="New reminder title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Reminder title..."
            className="h-11 min-w-0 flex-1 rounded-xl border border-[#DDE6DF] px-3 text-[11px] outline-none"
          />
          <ModuleButton onClick={addReminder}>
            <ModuleIcon name="plus" size={16} />
            Add
          </ModuleButton>
        </div>
      </section>

      {/* Reminder list */}
      <div className="space-y-2">
        {reminders.length === 0 && (
          <p className="rounded-2xl border border-dashed border-[#D8E3DA] bg-white p-6 text-center text-[12px] leading-5 text-[#7B8C82]">
            No reminders yet. Add one above to keep track of sowing, spraying
            and harvest dates.
          </p>
        )}
        {reminders.map((item) => (
          <div
            key={item.id}
            className="flex items-center gap-3 rounded-2xl border border-[#E0E8E2] bg-white p-3"
          >
            <button
              aria-label={item.done ? "Mark as not done" : "Mark as done"}
              onClick={() => toggleDone(item.id)}
              className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border ${
                item.done
                  ? "border-[#216B45] bg-[#216B45] text-white"
                  : "border-[#BFCFC3] text-transparent"
              }`}
            >
              <ModuleIcon name="check" size={15} />
            </button>

            <span className="min-w-0 flex-1">
              <b
                className={`block text-[11px] ${
                  item.done ? "text-[#8C9991] line-through" : "text-[#294234]"
                }`}
              >
                {item.title}
              </b>
              <span className="text-[9px] text-[#829188]">{item.date}</span>
            </span>

            <button
              aria-label={`Edit reminder: ${item.title}`}
              onClick={() => editReminder(item)}
              className="grid h-8 w-8 place-items-center text-[#4F6B5C]"
            >
              <ModuleIcon name="edit" size={15} />
            </button>
            <button
              aria-label={`Delete reminder: ${item.title}`}
              onClick={() => deleteReminder(item.id)}
              className="grid h-8 w-8 place-items-center text-[#9D5A4B]"
            >
              <ModuleIcon name="trash" size={15} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
