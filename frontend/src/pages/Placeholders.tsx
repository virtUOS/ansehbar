// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Temporary placeholders; replaced by the real pages in Tasks 8-10. */
import { useTranslation } from "react-i18next";

function Placeholder({ title }: { title: string }) {
  const { t } = useTranslation();
  return <h1 className="text-2xl font-bold">{t(title)}</h1>;
}

export const RoomView = () => <Placeholder title="Room" />;
export const RecordersAdmin = () => <Placeholder title="Recorders" />;
export const InvitationsAdmin = () => <Placeholder title="Invitations" />;
export const SettingsAdmin = () => <Placeholder title="Settings" />;
