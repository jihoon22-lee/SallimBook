import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Dashboard } from "./features/dashboard/Dashboard";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("Application root is missing");

createRoot(root).render(
  <StrictMode>
    <Dashboard />
  </StrictMode>,
);
