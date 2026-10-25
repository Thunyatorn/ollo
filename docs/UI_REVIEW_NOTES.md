> Latest incident-thread behavior and persistence limits: [UI_ROUND2.md](UI_ROUND2.md).

# Review screen implementation

The inspector keeps the date at the top, gives the event trace the flexible space, and puts Overview/Grid view tabs in the top navigation. Existing incident acknowledgment, resolution and report requests remain connected to the app's original handlers.

Playback and the timeline live below the entire camera layout inside the video column, including in Grid and Focus views. The right inspector spans the full workspace height. The single bar above the timeline contains play/pause, current clock time, speed and a right-aligned information icon. The information panel is a native top-layer popover with one concise two-column metadata grid with uniform text; it cannot be clipped by camera containers. The general Mark incident, In, Out, Save clip, Snapshot and Export toolbar is removed. Event trace and Cameras remain at the top when collapsed. The playhead has a symmetrical handle and a 1px stroke. The overview is a 12px-high bar with square side handles; range text, Fit and zoom buttons are removed. All incident ranges use primary teal, independent of event status. Camera status indicators use a cooler blue-green. Overview and Grid are compact, vertically centered controls with rounded corners, no texture or borders and Tailwind slate-700 for the active surface; view controls are removed from Cameras. Overview side handles are teal and 6px wide and ruler labels use a dimmer readable text token. Active camera indicators are brighter green; camera rows omit the Offline suffix and the header omits the role tag.

Event rows use a compact thread layout: camera screenshot, Incident heading, muted approximate start time and one-line description. Real evidence stills take priority over a camera preview. Filtering, keyboard navigation and timeline selection remain available. Expanded threads use compact teal seek chips with fully opaque teal text and a subtle background that strengthens on hover/focus, quiet borderless monospace tool badges and borderless export buttons with hover surfaces. The ruler is 28px high with 11px labels and omits AM/PM from clock labels. Expanded events provide Export details (a JSON download with viewer, timestamp and reason) and Export clip (the existing saved evidence clip). Events without a saved clip disable that action. Both exports require a reason. Details and clip downloads are implemented in the frontend; no new backend endpoints are introduced.

The ruler and event ranges show wall-clock times when recording start metadata is available. Only demo footage has a fixture start time (9 AM). Real footage falls back to elapsed time until `session.recording_started_at` is supplied. The fullscreen elapsed-time editor remains available and retains parser validation. Longer prerecorded videos default to a 30-minute visible window, bounded by their actual duration. The overview handles control the visible range; expanding both handles restores the entire video. Live feeds display the elapsed connected session time, using the backend recording start timestamp when supplied or the local connection time otherwise. This does not create a full-session DVR recording; live seeking remains disabled. Per-person DEMO badges and the video-bar illustrative-footage label are removed; camera rows and accessible waveform labels retain the demonstration context. No footage, activity density or routine schedule is fabricated.

Keyboard controls: Space toggles playback; J rewinds by seeking every 200 ms; K pauses; L plays forward; comma/period step one second; brackets jump between incident starts; U toggles permitted audio; F opens fullscreen; 1/2/3 choose a view; ? opens the guide. Shortcuts are also available from the top-right account/settings menu. Removed toolbar actions no longer have hidden keyboard shortcuts. Form fields and open popovers/dialogs retain their own keyboard handling.

## Integration boundaries

`recordAudit` is a typed, session-memory stub, not durable audit storage or authentication. Event exports record the requested range, identity and reason in that stub. Clip details show actions in the current session only. Downloaded JSON includes the export identity and reason, but video downloads use the existing saved clip without applying an export watermark; the export dialog states this explicitly. Existing incident acknowledgment, resolution and report requests stay connected to their original handlers.

Audio defaults off. Playback and real recorded waveform visibility require `session.audio_permitted === true`. The demo has a seeded synthetic waveform rendered with WaveSurfer.js and explicitly labeled Illustrative audio. The waveform renderer does not load an audio URL or play generated sound. Clip details show missing retention metadata honestly, or `session.kept_until` when supplied. The redaction toggle stores a preview request; it explicitly says blurring is not applied. No new role authorization or multi-facility model is imposed.

Existing styles now reference a centralized legacy palette, with semantic tokens for the review screen and a readable type scale. Existing layout geometry remains in the original stylesheet; new review spacing uses the 4px scale. SVG floor-plan labels use world-coordinate dimensions so they scale with the drawing. WaveSurfer.js is the added waveform-rendering dependency, bundled locally through npm. Existing uncommitted changes were preserved and the implementation is left uncommitted for review.

## Verification

- `npm run build`: TypeScript and production Vite build passed.
- `node --test scripts/timecode.test.mjs`: parser and formatter tests passed (valid forms, malformed fields, bounds and hour display).
- `node scripts/review-smoke.mjs`: browser checks for shared playback beneath Single/Grid/Focus camera layouts, top-layer info panel, full-height sidebar, collapsed-section alignment, filters, list/timeline selection, arrow navigation, shortcuts menu/dialog, required export reasons, JSON contents and saved-clip download bytes. A timeline harness checks 30-minute defaults for a one-hour recording, overview handles restoring full duration and growing live-session ranges preserving zoom. Clip transport uses an explicitly labeled synthetic test fixture.
- Before/after screenshots: `ui-baseline/` and `ui-after/`, at 1323×820, 1920×1200 and 1024×768. Both initial event rows fit without scrolling at each size.
- The repository has no lint script or configured linter; typechecking is included in the build.

## Decisions still needed

- Human and legal review of audio consent, including California all-party consent considerations, before granting audio permissions.
- Authenticated role permissions, parent access, export authorization and durable audit storage.
- Retention policy and the server-supplied expiry date; the UI does not choose either.
- Vision-pipeline redaction, backend export authorization and video watermark implementation. Existing saved clip download is implemented.
- Recording start timestamp and timezone metadata for uploaded footage; accepting clock-time input remains a separate decision.
- Facility selection and optional routine bands require a real facility/schedule model.

## Contrast measurements

WCAG relative-luminance ratios against the raised review surface (the lightest surface used by these labels). Body labels exceed 4.5:1; meaningful controls exceed 3:1. Decorative surface separators are excluded.

- Primary text: #ededed on #222222, 13.59:1.
- Secondary text / duration / ruler / camera IDs: #b5b5b5 on #222222, 7.76:1.
- Open status: #f0bd74 on #222222, 9.27:1.
- In review status: #d8c5f0 on #222222, 9.97:1.
- Resolved status: #a3c8ae on #222222, 8.66:1.
- Primary / focus / playhead: #20818E on #222222, 3.48:1.
- Primary action text: white on #20818E, 4.57:1.
- Structural interactive border: #858585 on #222222, 4.31:1.

Calendar styling: no visual footage underline, incident dots or legend. Today is teal unless selected, when it is white. Selecting a different day preserves today’s teal text. The Today footer action is a filled button. Footage/incident information remains in accessible date labels.
