// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import React from "react";
import ReactDOM from "react-dom/client";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import "@fontsource-variable/plus-jakarta-sans";
import "./index.css";
import "./i18n";
import { ThemeProvider } from "@basicbar/ui";
import App from "./App";
import { Overview } from "./pages/Overview";
import { AdminLayout } from "./pages/admin/AdminLayout";
import { InvitationsAdmin } from "./pages/admin/InvitationsAdmin";
import { RecordersAdmin } from "./pages/admin/RecordersAdmin";
import { SettingsAdmin } from "./pages/admin/SettingsAdmin";
import { RoomView } from "./pages/RoomView";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Overview /> },
      { path: "raum/:id", element: <RoomView /> },
      {
        path: "verwaltung",
        element: <AdminLayout />,
        children: [
          { index: true, element: <Navigate to="/verwaltung/rekorder" replace /> },
          { path: "rekorder", element: <RecordersAdmin /> },
          { path: "einladungen", element: <InvitationsAdmin /> },
          { path: "einstellungen", element: <SettingsAdmin /> },
        ],
      },
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
