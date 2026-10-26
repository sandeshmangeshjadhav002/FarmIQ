import Icon from "@/components/common/Icon";
import { navItems } from "@/data/modules";

/**
 * Sticky bottom navigation bar.
 *
 * The extra padding-bottom via style uses the CSS env() safe-area-inset-bottom
 * so the nav sits above the Android gesture bar and iPhone home indicator.
 * Tailwind does not have a built-in safe-area utility in v4 without a plugin,
 * so we apply it via inline style.
 *
 * @param {object}   props
 * @param {string}   props.active    - Currently active screen key.
 * @param {Function} props.navigate  - Called with the new screen key.
 */
export default function BottomNavigation({ active, navigate }) {
  return (
    <nav
      className="sticky bottom-0 z-20 mt-auto grid grid-cols-4 border-t border-white/20 bg-white/40 px-2 pt-1 backdrop-blur-xl"
      style={{ paddingBottom: "calc(0.5rem + env(safe-area-inset-bottom, 0px))" }}
    >
      {navItems.map((item) => {
        const selected = active === item.key;
        return (
          <button
            key={item.key}
            aria-label={item.label}
            aria-current={selected ? "page" : undefined}
            className={`flex flex-col items-center justify-center gap-1 py-1 text-[10px] font-semibold transition active:scale-95 ${
              selected ? "text-[#216B45]" : "text-[#85948C]"
            }`}
            onClick={() => navigate(item.key)}
          >
            <span
              className={`grid h-8 w-12 place-items-center rounded-full transition ${
                selected ? "bg-[#E6F2E9]" : ""
              }`}
            >
              <Icon name={item.icon} size={20} />
            </span>
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}
