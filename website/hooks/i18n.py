# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""MkDocs hook: German/English twin sites without an i18n plugin.

mkdocs.yml builds the German site at the root, mkdocs.en.yml (INHERIT)
the English one into en/. This hook

- points the language selector at the counterpart of the current page
  (``PAGES``; pages without one fall back to the other language's start
  page, as configured in ``extra.alternate``), rendered by
  overrides/partials/alternate.html;
- serves the shared theme assets (website/assets/) in the English build,
  whose docs_dir is website/en/.

Keep ``PAGES`` in sync when a page is added or renamed.
"""

from __future__ import annotations

import os
import posixpath

from mkdocs.structure.files import File

# German source path -> English source path (relative to each docs_dir).
PAGES = {
    "index.md": "index.md",
    "anleitung/index.md": "guide/index.md",
    "anleitung/anmelden.md": "guide/sign-in.md",
    "anleitung/uebersicht.md": "guide/overview.md",
    "anleitung/raumansicht.md": "guide/room-view.md",
    "anleitung/kalender.md": "guide/calendar.md",
    "anleitung/alarme.md": "guide/alarms.md",
    "anleitung/rekorder.md": "guide/recorders.md",
    "anleitung/zugang.md": "guide/access.md",
    "anleitung/einstellungen.md": "guide/settings.md",
    "installation.md": "installation.md",
}
EN_PAGES = {en: de for de, en in PAGES.items()}

# Where each language lives, relative to the German site root.
ROOT = {"de": "", "en": "en/"}
WEBSITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _url(src: str) -> str:
    """Directory URL of a source file (use_directory_urls)."""
    stem = src[: -len(".md")]
    if stem == "index" or stem.endswith("/index"):
        stem = stem[: -len("index")]
    else:
        stem += "/"
    return stem


def _lang(config) -> str:
    return config.theme["language"]


def on_files(files, config, **kwargs):
    if _lang(config) == "de":
        return files
    assets = os.path.join(WEBSITE, "assets")
    for name in sorted(os.listdir(assets)):
        uri = f"assets/{name}"
        if files.get_file_from_path(uri) is None:
            files.append(
                File(uri, WEBSITE, config.site_dir, config.use_directory_urls)
            )
    return files


def on_page_context(context, page, config, nav, **kwargs):
    lang = _lang(config)
    src = page.file.src_uri
    counterpart = {
        "de": {"de": src, "en": PAGES.get(src)},
        "en": {"de": EN_PAGES.get(src), "en": src},
    }[lang]
    # Path from this page up to the German site root.
    up = "../" * page.url.count("/") + ("../" if lang == "en" else "")
    links = {}
    for target_lang, target_src in counterpart.items():
        if target_src is None:
            continue
        target = ROOT[target_lang] + _url(target_src)
        links[target_lang] = posixpath.normpath(up + target) + "/" if (up + target) else "./"
    context["alternate_links"] = links
    return context
