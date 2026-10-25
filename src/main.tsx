import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import DesignSystem from "./DesignSystem";
import "@fontsource-variable/dm-sans";
import "@fontsource-variable/dm-sans/wght-italic.css";
import "@fontsource/dm-mono/latin-300.css";
import "@fontsource/dm-mono/latin-400.css";
import "@fontsource/dm-mono/latin-500.css";
import "@fontsource/dm-mono/latin-300-italic.css";
import "@fontsource/dm-mono/latin-400-italic.css";
import "@fontsource/dm-mono/latin-500-italic.css";
import "./styles.css";
import "./tokens.css";
import "./review.css";
import "./incident-threads.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname.replace(/\/$/, "") === "/design-system" ? (
      <DesignSystem />
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
