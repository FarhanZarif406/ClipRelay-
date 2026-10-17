import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import "./styles/additions.css";
import { initLanguage } from "./lib/i18n";

initLanguage();  // Roman Urdu from the first paint, when this browser last used it

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
