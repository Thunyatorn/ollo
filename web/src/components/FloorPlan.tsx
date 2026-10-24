import type { Zone, TrackPosition } from '../module_bindings/types';

type Point = { x: number; y: number };

interface Props {
  room: { widthM: number; heightM: number };
  zones?: Zone[];
  positions?: TrackPosition[];
  blindSpots?: Point[][];
  alertTracks?: Set<string>;
  /** polygon being drawn (meters) */
  draft?: Point[];
  onPoint?: (p: Point) => void;
  onTrackClick?: (trackId: string) => void;
  /** show predicted path for tracks in alert */
  showPath?: boolean;
}

const RED = '#b00000', ORANGE = '#a65a00', BLUE = '#1f3f8f', GREY = '#555';
const zoneColor = (s: string) => (s === 'high' ? RED : s === 'medium' ? ORANGE : BLUE);

// A floor plan drawn like a technical figure: meter grid with ticks, hatched zones,
// circles for children, squares for adults. Coordinates are meters, so positions need no conversion.
export default function FloorPlan({ room, zones = [], positions = [], blindSpots = [], alertTracks, draft, onPoint, onTrackClick, showPath }: Props) {
  const { widthM: w, heightM: h } = room;
  const unit = Math.max(w, h);
  const dotR = unit * 0.035;
  const pad = unit * 0.07; // margin for axis labels, and so rings at the walls stay inside the picture
  const tick = unit * 0.03;

  function click(e: React.MouseEvent<SVGSVGElement>) {
    if (!onPoint) return;
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const m = svg.getScreenCTM();
    if (!m) return;
    const p = pt.matrixTransform(m.inverse());
    const clamp = (v: number, max: number) => Math.round(Math.min(max, Math.max(0, v)) * 100) / 100;
    onPoint({ x: clamp(p.x, w), y: clamp(p.y, h) });
  }

  const poly = (pts: Point[]) => pts.map(p => `${p.x},${p.y}`).join(' ');
  const hatch = (id: string, color: string, gap: number, angle: number) => (
    <pattern id={id} width={gap} height={gap} patternUnits="userSpaceOnUse" patternTransform={`rotate(${angle})`}>
      <line x1={0} y1={0} x2={0} y2={gap} stroke={color} strokeWidth={gap * 0.14} />
    </pattern>
  );

  return (
    <svg
      className="plan"
      viewBox={`${-pad} ${-pad} ${w + 2 * pad} ${h + 2 * pad}`}
      onClick={click}
      role="img"
      aria-label="Floor plan of the room, in meters"
      style={{ cursor: onPoint ? 'crosshair' : 'default', aspectRatio: `${w + 2 * pad} / ${h + 2 * pad}` }}
    >
      <defs>
        {hatch('hatch-high', RED, unit * 0.04, 45)}
        {hatch('hatch-medium', ORANGE, unit * 0.05, 45)}
        {hatch('hatch-low', BLUE, unit * 0.06, 45)}
        {hatch('hatch-blind', GREY, unit * 0.05, -45)}
      </defs>

      {/* 1 m grid with axis labels */}
      {Array.from({ length: Math.floor(w) + 1 }, (_, i) => (
        <g key={`x${i}`}>
          {i > 0 && i < w && <line x1={i} y1={0} x2={i} y2={h} stroke="#c9c9c9" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
          <line x1={i} y1={h} x2={i} y2={h + tick} stroke="#000" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={i} y={h + tick + unit * 0.035} textAnchor="middle" fontSize={unit * 0.032} fill="#000">{i}</text>
        </g>
      ))}
      {Array.from({ length: Math.floor(h) + 1 }, (_, i) => (
        <g key={`y${i}`}>
          {i > 0 && i < h && <line x1={0} y1={i} x2={w} y2={i} stroke="#c9c9c9" strokeWidth={1} vectorEffect="non-scaling-stroke" />}
          <line x1={-tick} y1={i} x2={0} y2={i} stroke="#000" strokeWidth={1} vectorEffect="non-scaling-stroke" />
          <text x={-tick - unit * 0.01} y={i + unit * 0.011} textAnchor="end" fontSize={unit * 0.032} fill="#000">{i}</text>
        </g>
      ))}
      <rect x={0} y={0} width={w} height={h} fill="none" stroke="#000" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      <text x={w} y={h + tick + unit * 0.075} textAnchor="end" fontSize={unit * 0.03} fontStyle="italic" fill="#000">meters</text>

      {blindSpots.map((b, i) => (
        <polygon key={`b${i}`} points={poly(b)} fill="url(#hatch-blind)" stroke={GREY} strokeDasharray="5 3" strokeWidth={1} vectorEffect="non-scaling-stroke" />
      ))}

      {zones.filter(z => z.status !== 'off').map(z => (
        <g key={z.id}>
          <polygon
            points={poly(z.polygon)}
            fill={z.status === 'draft' ? 'none' : `url(#hatch-${z.severity})`}
            stroke={zoneColor(z.severity)}
            strokeWidth={2}
            strokeDasharray={z.status === 'draft' ? '6 4' : undefined}
            vectorEffect="non-scaling-stroke"
          />
          {z.polygon[0] && (
            <text x={z.polygon[0].x + unit * 0.012} y={z.polygon[0].y + unit * 0.05} fontSize={unit * 0.04} fontWeight={700} fill={zoneColor(z.severity)}
              stroke="#fff" strokeWidth={unit * 0.012} paintOrder="stroke">
              {z.name}{z.status === 'draft' ? ' (draft)' : ''}
            </text>
          )}
        </g>
      ))}

      {draft && draft.length > 0 && (
        <g>
          <polyline points={poly(draft)} fill="none" stroke="#000" strokeWidth={2} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
          {draft.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={dotR * 0.45} fill="#000" />)}
        </g>
      )}

      {positions.filter(p => p.visible).map(p => {
        const isAlert = alertTracks?.has(p.trackId);
        const isChild = p.kind === 'child';
        return (
          <g key={p.trackId} onClick={onTrackClick ? e => { e.stopPropagation(); onTrackClick(p.trackId); } : undefined} style={{ cursor: onTrackClick ? 'pointer' : undefined }}>
            {showPath && isAlert && (
              <line x1={p.x} y1={p.y} x2={p.x + p.vx * 3} y2={p.y + p.vy * 3} stroke={RED} strokeWidth={2} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
            )}
            {isAlert && <circle className="ring" cx={p.x} cy={p.y} r={dotR * 1.8} fill="none" stroke={RED} strokeWidth={3} vectorEffect="non-scaling-stroke" />}
            {isChild ? (
              <circle className="dot" cx={p.x} cy={p.y} r={dotR} fill={isAlert ? RED : '#fff'} stroke="#000" strokeWidth={2} vectorEffect="non-scaling-stroke" />
            ) : (
              <rect className="dot" x={p.x - dotR} y={p.y - dotR} width={dotR * 2} height={dotR * 2} fill="#000" />
            )}
            <text className="lbl" x={p.x} y={p.y + dotR * 0.4} textAnchor="middle" fontSize={dotR * 1.15} fontWeight={700}
              fill={isChild && !isAlert ? '#000' : '#fff'} pointerEvents="none">{p.label}</text>
            {isAlert && (
              <g pointerEvents="none">
                <rect x={p.x + dotR * 0.7} y={p.y - dotR * 1.9} width={dotR * 1.1} height={dotR * 1.1} fill="#000" />
                <text x={p.x + dotR * 1.25} y={p.y - dotR * 1.02} textAnchor="middle" fontSize={dotR * 1.0} fontWeight={700} fill="#fff">!</text>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
