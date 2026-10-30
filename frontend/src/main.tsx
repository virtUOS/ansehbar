// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import "@fontsource-variable/plus-jakarta-sans";
import "./index.css";
import "./i18n";
import { ThemeProvider } from "@basicbar/ui";
import App from "./App";
import { Overview } from "./pages/Overview";
import { InvitationsAdmin, RecordersAdmin, RoomView, SettingsAdmin } from "./pages/Placeholders";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Overview /> },
      { path: "raum/:id", element: <RoomView /> },
      { path: "verwaltung/rekorder", element: <RecordersAdmin /> },
      { path: "verwaltung/einladungen", element: <InvitationsAdmin /> },
      { path: "verwaltung/einstellungen", element: <SettingsAdmin /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  </React.StrictMode>,
);
