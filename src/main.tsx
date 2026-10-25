import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import DesignSystem from "./DesignSystem";
import "./styles.css";
import "./tokens.css";
import "./review.css";
import "./incident-threads.css";
const Agentation = import.meta.env.DEV
  ? lazy(() => import("agentation").then(module => ({ default: module.Agentation })))
  : null;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname.replace(/\/$/, "") === "/design-system" ? (
      <DesignSystem />
    ) : (
      <App />
    )}
    {Agentation && <Suspense fallback={null}><Agentation /></Suspense>}
  </React.StrictMode>,
);
