import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";
import App from "./App";
import "./styles.css";

// Community only, and deliberately. An Enterprise trial key taken out now
// expires before this is judged, and a demo that degrades on a date is not a
// demo. Everything the grid does here is in the free, MIT-licensed build.
ModuleRegistry.registerModules([AllCommunityModule]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
