import { useEffect, useRef } from "react";
import type { Incident } from "./types";
import { Bell, History, LogOut, MoreHorizontal, Settings2 } from "lucide-react";
import Brand from "./Brand";
import "./navbar.css";

type NavbarProps = {
  accountName?: string;
  connected?: boolean;
  notifications?: Incident[];
  onNavigate?: (page: string) => void;
  onSignOut?: () => void;
};

export default function Navbar({
  accountName = "Local operator",
  connected = false,
  notifications = [],
  onNavigate = page => { window.location.href = `/?page=${page}`; },
  onSignOut = () => { sessionStorage.setItem("nestwatch-workspace-closed", "true"); window.location.href = "/"; },
}: NavbarProps) {
  const notificationPopup = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (!notificationPopup.current?.contains(event.target as Node)) notificationPopup.current?.removeAttribute("open");
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, []);
  const recent = [...notifications].sort((a, b) => new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime()).slice(0, 20);
  return (
        <header className="topbar app-navbar">
          <button
            className="brand compact-brand"
            onClick={() => onNavigate("monitor")}
            aria-label="ollo monitor"
          >
            <Brand />
          </button>
          <div className="account-area">
            <div className="header-account-identity"><span className="account-avatar" aria-hidden="true">A</span><span>{accountName}</span></div>
            <details name="navbar-popover" className="account-menu" onKeyDown={e => { if (e.key === "Escape") { e.currentTarget.removeAttribute("open"); e.currentTarget.querySelector("summary")?.focus(); } }} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget)) e.currentTarget.removeAttribute("open"); }}>
              <summary aria-label="Account menu" title="Account menu"><MoreHorizontal size={16} /></summary>
              <div className="account-dropdown">
                <div className="account-identity"><span className="account-avatar" aria-hidden="true">A</span><div><strong>{accountName}</strong><span>Local workspace</span></div></div>
                <div className="account-connection"><span className={`status-dot ${connected ? "" : "red"}`} />{connected ? "System connected" : "Local demo"}</div>
                <button onClick={e => { onNavigate("settings"); e.currentTarget.closest("details")?.removeAttribute("open"); }}><Settings2 size={15} />Settings</button>
                <button onClick={e => { onNavigate("history"); e.currentTarget.closest("details")?.removeAttribute("open"); }}><History size={15} />Incident history</button>
                <button className="account-signout" onClick={onSignOut}><LogOut size={15} />Sign out</button>
              </div>
            </details>
            <details ref={notificationPopup} name="navbar-popover" className="notifications-menu" onKeyDown={event => {
              if (event.key === "Escape") {
                event.currentTarget.removeAttribute("open");
                event.currentTarget.querySelector("summary")?.focus();
              }
            }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.removeAttribute("open"); }}>
              <summary className="header-notifications" aria-label="Notifications" title="Notifications"><Bell size={16} strokeWidth={1.7} /></summary>
              <section className="notifications-popover" aria-label="Recent notifications">
                <div className="notifications-heading"><h2>Notifications</h2><span>{notifications.length}</span></div>
                {recent.length ? <ul className="notifications-list">{recent.map(notification => {
                  const date = new Date(notification.opened_at);
                  return <li key={notification.id}>
                    <span className={`notification-indicator ${notification.status === "resolved" || notification.status === "closed" ? "is-resolved" : ""}`} />
                    <div><strong>{notification.title}</strong><p>{notification.room} · {notification.status.replaceAll("_", " ")}</p>
                    {!Number.isNaN(date.getTime()) && <time dateTime={date.toISOString()}>{date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</time>}</div>
                  </li>;
                })}</ul> : <div className="notifications-empty"><Bell size={22} strokeWidth={1.5} /><strong>You're all caught up</strong><p>New incident notifications will appear here.</p></div>}
              </section>
            </details>
          </div>
        </header>
  );
}
