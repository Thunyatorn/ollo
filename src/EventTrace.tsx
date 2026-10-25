import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, Check, ChevronDown, ScanLine } from "lucide-react";
import EventExport from "./EventExport";
import { adaptIncidentThread, threadClock } from "./incidentThreads";
import type { IncidentMessage, IncidentThread, LookoutState, ResolutionOutcome } from "./types";

type NoteDraft = { text: string; anchorSeconds?: number; anchorAt?: string };
type Props = {
  state: LookoutState; room: number; selected: string | null;
  userId?: string; cameraId?: string; cameraThumbnail?: string; recordingStartedAt?: string;
  threads?: IncidentThread[]; openedId?: string | null; selectedNoteId?: string | null; position?: number;
  canSeek?: boolean; canAnnotate?: boolean; loading?: boolean; error?: string;
  onHover?: (id: string | null) => void; onSelect?: (id: string) => void;
  onOpen?: (id: string) => void; onBack?: () => void;
  onAddNote?: (id: string, draft: NoteDraft) => void | Promise<void>;
  onResolve?: (id: string, outcome: ResolutionOutcome) => void | Promise<void>;
  onAction?: (id: string, action: string) => void;
  onSeek: (seconds: number) => void; onJump?: (seconds: number) => void; onReport?: (id: string) => void;
};
function groupMessages(messages: IncidentMessage[]) {
  const groups: IncidentMessage[][] = [];
  for (const message of messages) {
    if (message.kind === "system" && groups.at(-1)?.[0].kind === "system") groups.at(-1)!.push(message);
    else groups.push([message]);
  }
  return groups;
}
export default function EventTrace({ state, selected, userId = "Local operator", cameraId = "camera", cameraThumbnail, recordingStartedAt, threads: supplied, openedId, selectedNoteId, canSeek = true, canAnnotate = true, loading = false, error, onHover, onSelect, onOpen, onBack, onResolve, onSeek }: Props) {
  const threads = supplied ?? state.incidents.map(incident => adaptIncidentThread(incident, { cameraId, cameraName: incident.room, thumbnailUrl: cameraThumbnail, recordingStartedAt, attempts: state.attempts }));
  const [filter, setFilter] = useState("All");
  const [localOpened, setLocalOpened] = useState<string | null>(null);
  const activeId = openedId === undefined ? localOpened : openedId;
  const thread = threads.find(t => t.id === activeId);
  const [messageError, setMessageError] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const root = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const savedScroll = useRef(0);
  const origin = useRef<string | null>(null);
  const counts = { All: threads.length, Open: threads.filter(t => t.status !== "resolved").length, Resolved: threads.filter(t => t.status === "resolved").length };
  const visible = threads.filter(t => filter === "All" || (filter === "Open" ? t.status !== "resolved" : t.status === "resolved"));
  useLayoutEffect(() => {
    if (activeId) {
      origin.current = activeId; heading.current?.focus(); if (body.current) body.current.scrollTop = 0;
    } else {
      if (list.current) list.current.scrollTop = savedScroll.current;
      root.current?.querySelector<HTMLButtonElement>(`[data-thread-id="${CSS.escape(origin.current ?? "")}"]`)?.focus({ preventScroll: true });
    }
    setMessageError("");
  }, [activeId]);
  useEffect(() => {
    if (selectedNoteId) document.getElementById(`message-${selectedNoteId}`)?.scrollIntoView({ block: "center", behavior: "instant" });
  }, [selectedNoteId, activeId]);
  const open = (item: IncidentThread) => {
    savedScroll.current = list.current?.scrollTop ?? 0; origin.current = item.id;
    setLocalOpened(item.id); onOpen?.(item.id); onSelect?.(item.id);
    if (canSeek && item.startSeconds !== undefined) onSeek(item.startSeconds);
  };
  const back = () => { if (filter === "Open" && thread?.status === "resolved") setFilter("All"); setLocalOpened(null); onBack?.(); onHover?.(null); };
  const time = (message: IncidentMessage) => {
    const at = message.kind === "note" && message.anchorAt ? message.anchorAt : message.at;
    return canSeek && message.anchorSeconds !== undefined
      ? <button className="thread-time" title={`Jump to ${threadClock(at)}`} onClick={() => onSeek(message.anchorSeconds!)}>{threadClock(at)}</button>
      : <time className="thread-time" dateTime={at}>{threadClock(at)}</time>;
  };
  return <aside className={`event-trace incident-panel ${thread ? "is-thread" : "is-list"}`} ref={root} aria-label="Incidents" aria-busy={loading}>
    {loading ? <div className="thread-state" role="status">Loading incidents…</div> : error ? <div className="thread-state" role="alert">{error}</div> : !thread ? <>
      <div className="thread-filters" role="group" aria-label="Filter incidents">{(["All", "Open", "Resolved"] as const).map(value => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value}<span>{counts[value]}</span></button>)}</div>
      <div className="incident-list" ref={list} onScroll={event => { savedScroll.current = event.currentTarget.scrollTop; }} role="list" aria-label="Incident threads">
        {!visible.length ? <div className="thread-state"><Check size={18} /><p>Nothing flagged on this day</p><span>{filter === "All" ? "Anything that needs a look will appear here." : "No incidents match this filter."}</span></div> : visible.map(item => {
          const replies = Math.max(0, item.messages.length - 1);
          const owner = item.resolution?.by || item.source.assigned_responder;
          const status = item.status === "resolved" ? owner ? `Resolved by ${owner.split(" ")[0]}` : "Resolved" : item.status === "in_review" ? "In review" : "Open";
          return <div role="listitem" key={item.id} className={`incident-thread-row status-${item.status} ${selected === item.id ? "is-selected" : ""}`}>
            <button className="incident-row-button" data-thread-id={item.id} title={item.title} onClick={() => open(item)} onMouseEnter={() => onHover?.(item.id)} onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(item.id)} onBlur={() => onHover?.(null)} onKeyDown={event => {
              if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
              event.preventDefault(); const rows = Array.from(root.current?.querySelectorAll<HTMLButtonElement>(".incident-row-button") || []); rows[(rows.indexOf(event.currentTarget) + (event.key === "ArrowDown" ? 1 : -1) + rows.length) % rows.length]?.focus();
            }}>
              {item.thumbnailUrl ? <img className="thread-thumbnail" src={item.thumbnailUrl} alt={`${item.cameraName} camera screenshot`} /> : <span className="thread-thumbnail" aria-label="Camera screenshot unavailable"><ScanLine size={16} /></span>}
              <span className="thread-row-copy"><span className="thread-row-heading"><strong>{item.title}</strong><time dateTime={item.startedAt}>{new Date(item.startedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</time></span><span className="thread-row-meta">{item.cameraName} · {replies} {replies === 1 ? "reply" : "replies"} · {status}</span></span>
            </button>
          </div>;
        })}
      </div>
    </> : <>
      <header className="incident-thread-header">
        <div className="thread-navigation"><button className="thread-back" onClick={back} aria-label="Back to incidents"><ArrowLeft size={14} />Incidents</button><EventExport incident={thread.source} cameraId={cameraId} userId={userId} thread={thread} /></div>
        <div className="thread-header-summary">
          {thread.thumbnailUrl ? <img className="thread-header-thumbnail" src={thread.thumbnailUrl} alt={`${thread.cameraName} camera screenshot`} /> : <span className="thread-header-thumbnail" aria-label="Camera screenshot unavailable"><ScanLine size={20} /></span>}
          <div className="thread-heading-copy"><h2 ref={heading} tabIndex={-1}>{thread.title}</h2><div className="thread-header-meta"><span>{thread.cameraName}</span></div></div>
        </div>
        <div className="thread-resolution">{thread.status !== "resolved" && <details className="thread-resolve"><summary className="thread-resolve-trigger" aria-label="Resolve incident" title={canAnnotate ? "Choose an outcome" : "Your role cannot resolve incidents"}>Resolve<ChevronDown size={12} /></summary><div>{([['false_alarm', 'False alarm'], ['handled', 'Handled'], ['escalated', 'Escalated']] as const).map(([outcome, label]) => <button type="button" key={outcome} disabled={!canAnnotate || !onResolve} title={!canAnnotate ? "Your role cannot resolve incidents" : !onResolve ? "Resolution is unavailable in this preview" : outcome === "escalated" ? "Record the outcome only; this does not place a call" : label} onClick={async event => { const menu = event.currentTarget.closest("details"); try { await onResolve?.(thread.id, outcome); if (menu) menu.open = false; } catch (e) { setMessageError(e instanceof Error ? e.message : "Could not resolve this incident."); } }}>{label}</button>)}</div></details>}</div>
        {messageError && <p role="alert">{messageError}</p>}
      </header>
      <div className="incident-thread-body" ref={body} role="log" aria-label="Incident messages" aria-live="polite">
        {groupMessages(thread.messages).map(group => {
          const first = group[0];
          if (first.kind === "system") return <section className="thread-system-events" key={first.id}>
            {group.length >= 3 && <button className="system-events-toggle" aria-expanded={!!expandedGroups[first.id]} onClick={() => setExpandedGroups(current => ({ ...current, [first.id]: !current[first.id] }))}>{group.length} system events<ChevronDown size={12} /></button>}
            {(group.length < 3 || expandedGroups[first.id]) && group.map(message => <div className="thread-system-event" id={`message-${message.id}`} key={message.id}>{time(message)}<p>{message.text}</p></div>)}
          </section>;
          const message = first;
          if (message.kind === "status") return <div className="thread-status-message" key={message.id} id={`message-${message.id}`}><Check size={13} /><span>{message.text}</span>{time(message)}</div>;
          return <article className={`thread-message kind-${message.kind} ${selectedNoteId === message.id ? "is-target" : ""}`} key={message.id} id={`message-${message.id}`}>
            {message.kind === "detection" ? <span className="thread-message-avatar system-avatar" aria-label="ollo"><img src="/ollo-mark.svg" alt="" draggable={false} /></span> : <span className="thread-message-avatar" aria-hidden="true">{message.authorName.charAt(0).toUpperCase()}</span>}
            <div><div className="thread-message-meta"><strong>{message.kind === "detection" ? "ollo" : message.authorName}</strong>{time(message)}</div><p>{message.text}</p>{message.kind === "detection" && message.confidence !== undefined && <p className="thread-confidence">Confidence: {Math.round(message.confidence <= 1 ? message.confidence * 100 : message.confidence)}%</p>}</div>
          </article>;
        })}
        {thread.source.limitations?.length ? <details className="thread-context"><summary>Detection context</summary>{thread.source.limitations.map(value => <p key={value}>{value}</p>)}</details> : null}
        {thread.source.second_opinion && <details className="thread-context"><summary>Second opinion</summary><p>{thread.source.second_opinion.assessment.replaceAll("_", " ")}</p>{thread.source.second_opinion.observations.map((o, i) => <p key={i}>{o.description}</p>)}</details>}
      </div>

    </>}
  </aside>;
}
