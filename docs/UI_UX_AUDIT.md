# Ollo UI/UX audit

Reviewed October 24, 2026. Scope: the current `ollo/src` application running at localhost:5173, desktop at 1440×1000 and 1440×900, and mobile at 390×844. Inspected Overview, Grid, a resolved incident thread, Settings, and History; reviewed the associated React and CSS. This is an expert heuristic review, not a user study. Active emergencies, real camera feeds, real calls, and successful caregiver response links were not exercised. No application behavior was changed.

## Design judgment

Ollo already has a coherent visual foundation: restrained dark surfaces, a recognizable geometric mark, disciplined teal accents, and footage linked to timestamped incident conversations. Keep those strengths.

The main weakness is the allocation of attention. The interface gives footage and editor controls the strongest presence, while monitoring health, source authenticity, response ownership, and important event descriptions are quieter or absent. It currently feels closer to a specialist video-review tool than a reassuring operational workspace for caregivers. The design should help someone answer: **Is monitoring working? What needs attention? Where? Who is responding?**

## Prioritized findings

### 1. Make monitoring state and source authenticity unmistakable — P1

**Observed:** The default Overview displays an AI-generated still with tracking boxes and playback controls, without a persistent visible illustration label. The Entrance tile simultaneously says “Offline,” “LIVE,” and “Not connected.” Backend connection/demo status lives in the account menu. These are different states, but the interface makes users reconcile them.

**Change:** Give each feed an explicit source label: “Demo illustration,” “Recorded footage,” “Live · updated 1s ago,” or “Disconnected · last received …”. Only show live freshness when it is supported by frame data. Keep camera connectivity, analysis health, and notification readiness distinct in a compact persistent system-status area. A connected API alone does not mean a room is being monitored.

**Why:** Before users interpret an observation, they need to know whether the evidence is current and whether the system can act. This is the highest-priority trust improvement.

### 2. Give immediate response a stronger hierarchy — P1

**Observed in code:** The desktop incident thread exposes resolution outcomes but does not render an “I am responding” control; that action exists in the separate caregiver route. There is no persistent responder summary in the thread header. The tested default fixtures are already resolved, so the urgent end-to-end experience remains unverified.

**Change:** For an open event, show a concise action header: observation, room, elapsed time, assigned caregiver, and actual response status. Make “I am responding” the main action, with “Request backup” secondary. After acknowledgment, replace the action with “Maya is responding · acknowledged 14s ago”; offer resolution once the person has checked the room. Keep actual call attempts separate from recording an “Escalated” outcome.

**Why:** Reading a thread should not be a prerequisite for discovering the next operational action. Ownership prevents multiple staff assuming someone else is handling the situation.

### 3. Redesign the mobile incident layout — P1

**Observed:** At 390px, the incident panel puts its date in a left column and the list in a narrow right column. Full titles collapse to fragments such as “Someone n…” and “Someone lo…”. The video and editor consume most of the initial viewport. There is no horizontal page overflow, but the content is still difficult to scan.

**Change:** Use a full-width date/filter toolbar above full-width incident rows. Allow titles to wrap to two lines; put time and owner on separate short lines. For mobile monitoring, lead with open incidents and a compact camera preview. For historical review, expand footage on demand and use a simplified seek bar with previous/next event controls.

**Why:** Responsive design needs to reprioritize tasks, not merely fit the desktop composition into a smaller width.

### 4. Repair History and align its scope with Overview — P1

**Observed:** “Needs review” renders `function open() { [native code] }` instead of a count. Overview shows two resolved demo incidents while History shows zero total incidents and a fresh-start empty state. Code confirms that Overview adds local fixtures while History reads only session incidents.

**Change:** Compute the intended open-incident count explicitly. Expose consistent scope labels and filters: real/session data versus demo examples, selected camera, and date range. If demo examples stay excluded from History, say so and provide an explicit demo-history view. Ensure counts and list items describe the same scope.

**Why:** Contradictory records weaken confidence in the entire incident trail, even when the underlying cause is fixture handling.

### 5. Put the event above the conversation metadata — P2

**Observed:** At desktop size, long titles truncate despite a large amount of unused vertical space below the two rows. “3 replies” and repeated room names receive prominent placement; urgency and the nature of the observation are less legible. Both rows reuse the same full-room illustration as a thumbnail.

**Change:** Use two-line titles with specific, non-diagnostic wording such as “Rapid lowering near play area.” Lead metadata with response state and owner, then time. Reduce repeated room labels in a camera-scoped list. Use a real event-time still when available; otherwise label a room preview as context rather than implying it captures the incident.

**Why:** The list should support deciding what to open. Reply count is usually less useful than what happened and whether someone is responding.

### 6. Separate monitoring from detailed footage review — P2

**Observed:** Overview presents an overview strip, clock ruler, waveform, event ranges, elapsed time, duration, speed, and playback controls at once. The default waveform is synthetic; its illustrative status is available through a tooltip/accessibility label rather than visible copy.

**Change:** Offer clear “Monitor” and “Review footage” task modes. Keep live health and actionable incidents prominent in Monitor. Use the richer timeline in Review, with labeled event ranges and a small legend. Display a waveform only for actual audio, or visibly label it as a demo illustration. Distinguish clock time from clip position with text or context.

**Why:** Precision controls are valuable, but they impose unnecessary interpretation when the immediate task is checking room safety.

### 7. Make essential navigation discoverable — P2

**Observed:** History and Settings are inside the account ellipsis menu, mixed with shortcuts and sign-out. Overview and Grid are the prominent top-level tabs, even though they are layout choices within the same task.

**Change:** Give Monitor, Incidents, and Settings persistent navigation. Keep single/grid as local view controls. Keep identity and account actions in the account menu. Show the current page and a clear route back to monitoring on secondary pages.

**Why:** Product tasks deserve more prominence than presentation preferences. Hidden history makes the product feel smaller and harder to learn.

### 8. Make Grid useful when cameras are absent — P2

**Observed:** Two tiles reuse the same illustration; one tile is disconnected; the fourth is an unexplained blank rectangle. Grid mode does not explain these demo conditions prominently.

**Change:** Label each demonstration feed and give an unused slot a “Connect camera” action. Give disconnected feeds last-seen information and a reconnect/setup action. Surface camera-specific open-incident counts. Preserve camera positions during an incident; draw attention without unexpectedly rearranging the grid.

**Why:** Empty states should explain operational coverage and lead to recovery. Stable spatial positions support fast recognition.

### 9. Increase readability and touch comfort — P2

**Observed:** Most incident metadata is 12px. On mobile, measured playback control height is 24px, overlay/fullscreen 26px, and account/notification controls 28px. These are compact for hurried touch interaction. Some secondary system messages are visually very subdued.

**Change:** Use 14–16px for essential incident content, retain smaller type for supporting precision data, and aim for approximately 44px touch areas on mobile. Expand hit areas without requiring oversized icons. Verify text contrast, keyboard focus, 200% zoom, and reduced-motion behavior with actual rendered states.

**Why:** The interface should remain usable at a glance and with imprecise input. The measurements identify comfort concerns; this review does not claim a complete WCAG conformance assessment.

### 10. Make the brand and onboarding feel intentional — P2

**Observed:** Settings says “MAKE NESTWATCH YOURS” under Ollo branding and describes a hackathon environment. Source setup is reached through Settings or less prominent camera actions rather than a clear initial readiness sequence.

**Change:** Standardize visible naming to Ollo. Add a focused readiness flow: connect a source, confirm its room/location, configure responders, and verify a test alert. Show completed and incomplete requirements with truthful capability labels. Keep demonstration tools in a clearly marked demo section.

**Why:** A consistent voice and a clear path to readiness make the product feel considered and help users understand what is operational.

## A more novel artistic direction: calm vigilance

The visual character can be warmer and more distinctive while retaining Ollo’s dark surfaces, existing teal accent, and geometric mark. The opportunity is a designed relationship between rooms, observations, and people responding.

### A. Living room atlas — strongest direction

Create a compact architectural drawing of the facility: simplified rooms, fine geometric lines, meaningful landmarks, and camera coverage. Use a top-down view by default for legibility; explore a shallow isometric treatment where it improves spatial recognition. Derive clipped corners and line details from Ollo’s mark rather than introducing an unrelated illustration style.

Selecting a room opens its feed and incidents. An event marks its verified room or zone; selecting it reveals the observation and responder. Avoid drawing exact person positions or paths without calibrated data. Offline rooms use a clear disconnected symbol and label, not reassuring animation. This extends the prototype’s existing calibrated floor-plan concept into a recognizable product element.

**Artistic value:** Ollo feels like a thoughtfully drawn place people care for. **Practical value:** staff orient themselves across rooms without scanning every video. **Placement:** an optional “Space” overview, with a small locator in incident details. **Risk:** setup effort and inaccurate geometry; start with a manually configured room diagram and validate recognition before adding perspective.

### B. Response ribbon — useful second experiment

Replace an undifferentiated stream of system messages with a compact typographic sequence: “Observed → Maya notified → Maya responding → Resolved.” Each stage has an actual timestamp and can reveal its supporting log. Distinguish attempted, failed, and confirmed delivery; the ribbon must never imply completion from a scheduled action.

**Artistic value:** a distinctive rhythm of line, spacing, and typography. **Practical value:** it makes the product’s observe-to-response loop visible. Keep one shared accent and semantic status colors, with text and icons doing the explanatory work.

### C. Quiet geometric illustration — supporting brand layer

Develop a small family of architectural line drawings based on the Ollo mark for first-run setup, disconnected cameras, and reports. Onboarding can show a line connecting camera, room, and responder as each step is verified. Use motion briefly for meaningful transitions, honor reduced motion, and avoid continuous ambient movement beside footage.

**Artistic value:** a coherent authored identity beyond the logo. **Practical value:** illustrations explain setup and recovery. Keep them out of the urgent action area.

## Suggested sequence and validation

1. **Trust and response:** explicit feed states, correct History, coherent data scope, visible ownership and acknowledgment.
2. **Information hierarchy:** mobile incident rows, readable titles, task navigation, simpler monitoring controls and larger touch areas.
3. **Signature design:** prototype the room atlas and response ribbon, then test against the current interface with caregivers or representative operators.

Suggested usability tasks: identify a disconnected room, distinguish demo from live, locate an open event, claim response, find a past event, and explain whether a call was attempted or acknowledged. Measure first-click accuracy, task completion, time to identify the responsible person, and mistakes interpreting system state. Establish a baseline before claiming improvement; no user-performance results are asserted here.

## Source pointers

- `src/App.tsx`: initial illustration mode, mobile acknowledgment, Overview fixtures, History count and data scope, Settings naming.
- `src/Navbar.tsx`: account-menu navigation and connection state.
- `src/EventTrace.tsx`: list hierarchy and desktop thread actions.
- `src/LiveCameraPlaceholder.tsx`: unconditional LIVE badge in disconnected placeholder.
- `src/EditorTimeline.tsx` and `src/AudioWaveform.tsx`: generated demo waveform and precision review controls.
- `src/tokens.css`: current type scale and semantic design tokens.

Visual evidence: `docs/ui-ux-audit/` contains the inspected desktop Overview, thread, Grid, History, and mobile screens. These are prototype/demo screens, not live monitoring footage.
