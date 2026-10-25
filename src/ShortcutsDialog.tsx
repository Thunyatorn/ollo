import { useEffect, useRef } from "react";
export default function ShortcutsDialog() {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const open = () => { document.querySelectorAll<HTMLDetailsElement>(".account-menu[open]").forEach(menu => menu.open = false); if (!dialog.current?.open) dialog.current?.showModal(); };
    window.addEventListener("ollo:shortcuts", open);
    return () => window.removeEventListener("ollo:shortcuts", open);
  }, []);
  return <dialog ref={dialog} className="shortcuts-dialog" aria-labelledby="shortcuts-title" onClose={() => document.querySelector<HTMLElement>(".account-menu > summary")?.focus()}>
    <h2 id="shortcuts-title">Keyboard shortcuts</h2>
    <div className="shortcuts-list">{[
      ["Play / pause", "Space"], ["Seek 5 seconds", "← / →"], ["Seek 10 seconds", "Shift + ← / →"], ["Start / end", "Home / End"],
      ["Reverse / pause / forward", "J / K / L"], ["Step one second", ", / ."], ["Previous / next incident", "[ / ]"],
      ["Mute / unmute", "U"], ["Fullscreen", "F"], ["Single / grid / focus", "1 / 2 / 3"], ["Show shortcuts", "?"],
    ].map(([label, keys]) => <div key={label}><span>{label}</span><kbd>{keys}</kbd></div>)}</div>
    <button className="button" onClick={() => dialog.current?.close()}>Close</button>
  </dialog>;
}
