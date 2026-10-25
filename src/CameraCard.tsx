import type { ReactNode } from "react";
import CameraPicker from "./CameraPicker";

type Props = {
  rooms: { id: string; name: string }[];
  camera: number;
  onSelect: (index: number) => void;
  status?: string;
  order?: number;
  children: ReactNode;
};

/** Shared frame and camera controls for both the selected feed and grid previews. */
export default function CameraCard({ rooms, camera, onSelect, status, order, children }: Props) {
  return <section className="camera-card" style={{ order }} aria-label={`${rooms[camera].name} camera`}>
    <div className="review-camera-header">
      <CameraPicker rooms={rooms} selected={camera} onSelect={onSelect} />
      {status && <span>{status}</span>}
    </div>
    {children}
  </section>;
}
