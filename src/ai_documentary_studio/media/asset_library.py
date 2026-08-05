"""
Asset library — the catalog manager for every piece of media the
system touches.

This module is the implementation of the asset-library contract declared
in claude.md §7 (Repository Layout) and techstack.md §9 (Storage &
Filesystem). Every artifact that crosses a stage boundary lives under
``assets/library/`` in one of eight subdirectories:

    raw/  processed/  clips/  audio/
    narration/  music/  graphics/  renders/

Each individual asset is stored under ``raw/<asset_id>/`` (or the
matching subdir) with a ``manifest.json`` describing its provenance:
source, source URL, local path, license, SHA-256, and free-form
metadata. The manifest is the single record the Verifier consults when
deciding whether an asset may enter the next stage.

The library is intentionally filesystem-backed (no database): every
entry is a directory with a manifest, which means the catalog is
human-readable, git-diffable for manifests, and trivially backed up.
For larger deployments an SQLite index could be layered on top, but the
manifest-on-disk layout remains the source of truth.

Conforms to: AcquiredAsset (P7) schema. The ``catalog`` method accepts
the same fields as ``AcquiredAsset`` (plus a free-form metadata dict)
and writes them to ``raw/<asset_id>/manifest.json``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Storage taxonomy per techstack.md §9. Order matters only for the
# documentation string; lookups are by name.
STORAGE_SUBDIRS: tuple[str, ...] = (
    "raw",
    "processed",
    "clips",
    "audio",
    "narration",
    "music",
    "graphics",
    "renders",
)


class AssetLibrary:
    """Filesystem-backed catalog of media assets.

    Parameters
    ----------
    config
        Project config dict. Reads ``assets.library_root`` (default
        ``assets/library``) and ``assets.subdirs``.
    root
        Override the library root directory. Useful for tests and for
        per-project asset pools.
    """

    def __init__(self, config: dict, root: str = "assets/library"):
        self.config = config or {}
        cfg_root = self.config.get("assets", {}).get("library_root") or root
        self.root = Path(cfg_root)
        # Resolve subdir overrides from config, but always fall back to
        # the canonical taxonomy so the layout is stable.
        cfg_subdirs = self.config.get("assets", {}).get("subdirs", {}) or {}
        self.subdirs: dict[str, str] = {
            name: cfg_subdirs.get(name, name) for name in STORAGE_SUBDIRS
        }
        self._ensure_layout()

    # ─── Layout ──────────────────────────────────────────────────────────

    def _ensure_layout(self) -> None:
        """Create the eight taxonomy subdirectories if they don't exist."""
        self.root.mkdir(parents=True, exist_ok=True)
        for subdir in self.subdirs.values():
            (self.root / subdir).mkdir(parents=True, exist_ok=True)

    def subdir_path(self, name: str) -> Path:
        """Return the absolute path to a taxonomy subdir.

        Raises ``ValueError`` if ``name`` is not in the canonical
        taxonomy, to prevent typos from creating stray directories.
        """
        if name not in self.subdirs:
            raise ValueError(
                f"Unknown asset subdir {name!r}; expected one of {list(self.subdirs)}"
            )
        return self.root / self.subdirs[name]

    # ─── Public API ──────────────────────────────────────────────────────

    def catalog(
        self,
        asset_id: str,
        source: str,
        source_url: str,
        local_path: str,
        license: str,
        sha256: str,
        metadata: dict[str, Any] | None = None,
        subdir: str = "raw",
    ) -> dict[str, Any]:
        """Catalog a new asset or update an existing one.

        Writes ``<root>/<subdir>/<asset_id>/manifest.json`` with the
        given provenance fields plus a timestamp. The asset's actual
        media file is *not* copied — ``local_path`` is recorded as-is,
        so the cataloguer can point at any path (the YouTube cache, a
        stock-footage download dir, a generated graphic, etc.).

        Returns the manifest dict that was written.
        """
        if not asset_id:
            raise ValueError("asset_id must be non-empty")
        asset_dir = self.subdir_path(subdir) / asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)

        manifest: dict[str, Any] = {
            "asset_id": asset_id,
            "source": source,
            "source_url": source_url,
            "local_path": local_path,
            "license": license or "unknown",
            "sha256": sha256,
            "metadata": metadata or {},
            "cataloged_at": datetime.now(timezone.utc).isoformat(),
            "subdir": subdir,
        }
        manifest_path = asset_dir / "manifest.json"
        try:
            with manifest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        except OSError as e:
            log.error("asset_library.catalog: failed to write %s: %s", manifest_path, e)
            raise
        log.info(
            "asset_library.catalog: cataloged %s from %s (license=%s, sha256=%s...)",
            asset_id, source, license, (sha256 or "")[:12],
        )
        return manifest

    def get(self, asset_id: str) -> dict[str, Any] | None:
        """Return the manifest for ``asset_id`` or None if not cataloged.

        Searches every taxonomy subdir (raw, processed, clips, ...) so a
        caller doesn't need to know which subdir an asset lives in.
        """
        for subdir_name in self.subdirs.values():
            manifest_path = self.root / subdir_name / asset_id / "manifest.json"
            if manifest_path.exists():
                try:
                    with manifest_path.open("r", encoding="utf-8") as f:
                        return json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    log.warning(
                        "asset_library.get: corrupt manifest at %s: %s",
                        manifest_path, e,
                    )
                    return None
        return None

    def list_assets(self) -> list[dict[str, Any]]:
        """List every cataloged asset's manifest across all subdirs.

        Returns a flat list of manifest dicts, sorted by ``cataloged_at``
        ascending (oldest first). Corrupt manifests are skipped with a
        warning, never raised.
        """
        results: list[dict[str, Any]] = []
        for subdir_name in self.subdirs.values():
            subdir_path = self.root / subdir_name
            if not subdir_path.exists():
                continue
            for asset_dir in subdir_path.iterdir():
                if not asset_dir.is_dir():
                    continue
                manifest_path = asset_dir / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    with manifest_path.open("r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    results.append(manifest)
                except (OSError, json.JSONDecodeError) as e:
                    log.warning(
                        "asset_library.list_assets: skipping corrupt manifest %s: %s",
                        manifest_path, e,
                    )
        results.sort(key=lambda m: m.get("cataloged_at") or "")
        return results

    def exists(self, asset_id: str) -> bool:
        """Return True iff an asset with ``asset_id`` is cataloged."""
        return self.get(asset_id) is not None

    def move(
        self,
        asset_id: str,
        to_subdir: str,
    ) -> dict[str, Any] | None:
        """Move an asset's manifest from its current subdir to another.

        This is useful when a raw asset is promoted to ``processed`` (e.g.
        after transcoding) or when a clip is cut from ``processed`` to
        ``clips``. The manifest's ``subdir`` field is updated. The
        referenced ``local_path`` is NOT modified — the caller is
        responsible for moving the actual media file. Returns the
        updated manifest, or None if the asset was not found.
        """
        manifest = self.get(asset_id)
        if manifest is None:
            log.warning("asset_library.move: asset %s not found", asset_id)
            return None
        old_subdir = manifest.get("subdir", "raw")
        if old_subdir == to_subdir:
            return manifest
        old_dir = self.subdir_path(old_subdir) / asset_id
        new_dir = self.subdir_path(to_subdir) / asset_id
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        if old_dir.exists():
            # Move the whole asset directory, preserving any sibling files.
            old_dir.rename(new_dir)
        manifest["subdir"] = to_subdir
        manifest["moved_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path = new_dir / "manifest.json"
        try:
            with manifest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        except OSError as e:
            log.error("asset_library.move: failed to update manifest: %s", e)
        return manifest
