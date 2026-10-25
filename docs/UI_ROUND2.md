# Incident threads and layout

The right inspector now has a compact date row and counted All/Open/Resolved filters. Incident rows show the plain-language title, start time, camera, reply count and resolution owner. Opening a row replaces the list with a thread in the same panel; Back restores the list's scroll position and keyboard focus.

The player reserves a complete timeline row before allocating the remaining height to video. Video letterboxing remains centered and proportional to the actual source aspect ratio. Focus/overlay and fullscreen controls are in the player bar, so they cannot sit in a letterbox strip. A styled camera picker in the video header works in Overview and Grid, with arrow-key navigation, Escape dismissal and focus restoration. The redundant Cameras sidebar section and clip information trigger are removed. Incident titles truncate on one line without an unread dot, and elapsed time and duration share a lighter, joined pill.

The newest owner preferences take priority over conflicting screenshot advice: navigation stays compact and neutral using shared surface tokens, handles stay thin and teal, the ruler stays compact, and the date picker keeps its simplified current-day treatment. The handoff's explicit request to restore the elapsed-time editor and static duration is implemented. App-rendered video clocks are removed. Thread timestamps use wall-clock times with tabular numerals, no elapsed offsets or full dates. Detection labels show small in-box IDs and are hidden for non-staff roles.

## Threads

`adaptIncidentThread` derives the view from the existing incident and linked call attempts without changing backend incident data. It maps detections, system events, acknowledgment and resolution messages into a typed thread. Missing confidence is omitted. A real evidence still takes priority over the camera preview; a camera preview is not claimed to be the exact detection frame.

The thread has a detection message, quiet system-event rail, grouped runs of three or more system events, staff notes with initials, and status dividers. Notes can attach the current playhead time. An anchored note appears as a timeline pin; clicking it opens its thread, selects the incident and scrolls to the note. Jump to moment seeks and plays from the incident start. Live sources disable historical seeking and explain why.

The thread is now a read-only message feed with a camera thumbnail in its header, aligned author/time rows and quieter system activity. The note composer, attachment controls and empty-note prompt are removed. Loading, error and empty-list states remain supported. The header’s Resolve menu records False alarm, Handled or Escalated. These are outcome labels only; Escalated does not place a call. Back from an incident resolved under the Open filter switches to All so its originating row remains available for focus restoration.

## Persistence and audit boundaries

Notes, read state and resolution outcomes are held in App memory for the current session. Resolution remains a session-only overlay. They are not written to the backend and do not replace the server's authoritative incident status. The adapter applies this temporary overlay to the thread view. Reloading the app clears it.

`recordAudit` accepts a typed action, viewer, incident/camera IDs, timestamp and optional reason/range. Opening threads, adding notes, resolving and exporting all call it. Audit entries are also session-memory stubs, without durable storage or authenticated identity.

Exports live in the thread's actions menu. Details download as JSON with the current thread messages and outcome, viewer and required export reason. Export clip downloads an existing saved evidence clip; unavailable clips have a disabled action with an explanatory tooltip. Existing clip downloads do not apply a new export watermark. No new backend routes or dependencies were added in this round.

## Verification

- `npm run build`: TypeScript and production Vite build pass.
- `npm run test:threads`: nine adapter, note, resolution, audit and time-parser tests pass.
- `npm run test:threads:ui`: keyboard opening, header focus, list scroll/focus restoration, header thumbnails, removal of the composer, grouped events, jump/seek, required export reasons, exported thread JSON, saved clip bytes, session outcomes, read/audit hooks and reduced motion pass in Chromium.
- Timeline and message feed remain inside the viewport at 1323×820, 1920×1200 and 1024×768. Shared playback remains below the complete camera grid.
- Screenshots are in `ui-round2/before`, `phase-a`, `phase-b`, `phase-c`, `phase-d` and `final`. Each phase's preceding folder supplies its before view; `final` includes both list and thread states at all three sizes.
- No configured lint script or linter exists in this package. No lint dependency was introduced. Typechecking runs as part of the build.
- New component styles use existing semantic colors and shared spacing/type/radius tokens. No new literal colors, font sizes or radii are introduced in the thread stylesheet. Runtime geometry (video percentages and textarea measured height) remains computed from content.
- Existing uncommitted work is preserved; changes remain uncommitted instead of mixing previous UI edits into phase commits.

Text uses the shared primary/secondary colors. On the overlay surface, primary text is 13.26:1 and secondary text is 7.57:1. Status text has at least 8.45:1. White text on primary actions is 4.57:1. Primary focus/selection on the overlay surface is 3.39:1. Decorative separators are not text or controls.

## Open decisions

- Confirm the outcome vocabulary and what each outcome should do operationally.
- Decide who can write notes/resolve and whether parents see system messages. Current role checks are client-side presentation flags, not authorization.
- Wire note, read-state, outcome and audit persistence to authenticated backend APIs.
- Set audio, retention, redaction, export authorization and watermark policy. Existing UI scaffolding makes no new policy decision.
- Supply recording start/timezone metadata for real footage; otherwise the adapter infers a recording anchor from the incident's known timestamp and media offset.

The latest layout refinement follows Impeccable’s layout, Operate-mode and craft-floor guidance from https://github.com/pbakaus/impeccable. Its optional context engine could not run in this environment; existing source, design tokens and rendered views supplied the project context.
