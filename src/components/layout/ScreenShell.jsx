import BottomNavigation from "./BottomNavigation";

/**
 * Mobile screen wrapper — fills the full device screen on Android/iOS.
 *
 * On a real phone:
 *   - Full-width, full-height (no artificial max-w cap).
 *   - Bottom nav sits above the system gesture bar via pb-safe.
 *
 * On desktop (lg+) the layout centres a card at most 430px wide so the
 * desktop preview still looks good.
 *
 * @param {object}   props
 * @param {React.ReactNode} props.children
 * @param {string}   props.active    - Active nav key passed to BottomNavigation.
 * @param {Function} props.navigate  - Navigation callback.
 */
export default function ScreenShell({ children, active, navigate }) {
  return (
    <main className="
      mx-auto flex flex-col bg-white/60 backdrop-blur-2xl border-x border-white/20
      w-full h-full min-h-dvh
      lg:max-w-[430px] lg:shadow-[0_0_60px_rgba(26,57,40,.12)] lg:rounded-[30px] lg:min-h-[844px] lg:border-t lg:border-white/30
    ">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {children}
      </div>
      <BottomNavigation active={active} navigate={navigate} />
    </main>
  );
}
