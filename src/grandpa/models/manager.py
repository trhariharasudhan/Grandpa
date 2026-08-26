"""Model acquisition, local lifecycle management, and discovery for native GGUF models."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from grandpa.core import config as core_config
from grandpa.core.config import GrandpaConfig, load_config
from grandpa.core.registry import ModelRegistry
from grandpa.core.types import ModelSpec
from grandpa.models.security import validate_safe_destination_path
from grandpa.models.source import HuggingFaceModelSource, ModelSource

logger = logging.getLogger(__name__)


class NativeModelManager:
    """Manages installation, discovery, validation, and removal of local GGUF models."""

    def __init__(
        self,
        models_dir: Optional[Path | str] = None,
        source: Optional[ModelSource] = None,
    ) -> None:
        self.models_dir = (
            Path(models_dir).expanduser()
            if models_dir
            else core_config.DEFAULT_CONFIG_DIR / "models"
        )
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.source = source or HuggingFaceModelSource()
        self.manifest_path = self.models_dir / "registry.json"

    # ------------------------------------------------------------------
    # Installation / Acquisition
    # ------------------------------------------------------------------

    def install(
        self,
        model_id: str,
        source_ref: str,
        *,
        filename: Optional[str] = None,
        revision: str = "main",
        display_name: Optional[str] = None,
        family: str = "custom",
        capabilities: Sequence[str] = ("chat",),
        sha256: Optional[str] = None,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> ModelSpec:
        """Download a GGUF model artifact, verify it, and register it with ModelRegistry."""
        clean_model_id = model_id.strip()
        if not clean_model_id:
            raise ValueError("model_id cannot be empty.")

        # 1. Resolve remote artifact via provider-neutral source
        artifact = self.source.resolve(
            source_ref,
            filename=filename,
            revision=revision,
        )

        # 2. Download and verify artifact safely
        dest_path = self.source.download(
            artifact,
            self.models_dir,
            progress_callback=progress_callback,
            expected_sha256=sha256,
        )

        size_bytes = dest_path.stat().st_size if dest_path.exists() else 0

        # 3. Create ModelSpec and register in ModelRegistry
        spec = ModelSpec(
            model_id=clean_model_id,
            name=display_name or clean_model_id,
            version=revision,
            family=family,
            capabilities=capabilities,
            local_path=str(dest_path),
            size_bytes=size_bytes,
            backend="native",
            status="ready",
        )

        ModelRegistry.register_or_replace(clean_model_id, spec)

        # 4. Persist to local registry manifest
        self._save_manifest_entry(spec)
        return spec

    # ------------------------------------------------------------------
    # Removal / Lifecycle
    # ------------------------------------------------------------------

    def remove(self, model_id_or_filename: str) -> bool:
        """Safely remove a GGUF model file and unregister it from ModelRegistry."""
        target_name = model_id_or_filename.strip()
        if not target_name:
            return False

        # Check if registered with an explicit local_path
        target_path: Optional[Path] = None
        if ModelRegistry.contains(target_name):
            spec = ModelRegistry.get(target_name)
            if spec.local_path:
                target_path = Path(spec.local_path)

        if target_path is None:
            # Check models_dir for matching file
            candidate_names = [
                target_name,
                f"{target_name}.gguf",
            ]
            for cand_name in candidate_names:
                p = self.models_dir / cand_name
                if p.is_file():
                    target_path = p
                    break

        if target_path is None or not target_path.exists():
            return False

        # Security check: ensure target is strictly inside models_dir
        validate_safe_destination_path(target_path, self.models_dir)

        try:
            target_path.unlink()
        except OSError as exc:
            logger.warning("Failed to unlink model file %s: %s", target_path, exc)
            return False

        # Remove from manifest and ModelRegistry if present
        self._remove_manifest_entry(target_name)
        return True

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_local_models(self) -> List[ModelSpec]:
        """Scan ~/.grandpa/models/ for .gguf files and register valid specs."""
        if not self.models_dir.is_dir():
            return []

        manifest = self._load_manifest()
        discovered: List[ModelSpec] = []

        for f in self.models_dir.glob("*.gguf"):
            # Skip hidden and temporary files
            if f.name.startswith("."):
                continue

            model_id = f.stem
            size_bytes = f.stat().st_size
            meta = manifest.get(model_id, {})

            spec = ModelSpec(
                model_id=meta.get("model_id", model_id),
                name=meta.get("name", meta.get("display_name", model_id)),
                version=meta.get("version", "latest"),
                family=meta.get("family", "custom"),
                capabilities=tuple(meta.get("capabilities", ("chat",))),
                local_path=str(f.resolve()),
                size_bytes=size_bytes,
                backend="native",
                status="ready",
            )
            ModelRegistry.register_or_replace(spec.model_id, spec)
            discovered.append(spec)

        return discovered

    # ------------------------------------------------------------------
    # Manifest Helpers
    # ------------------------------------------------------------------

    def _load_manifest(self) -> Dict[str, Dict[str, Any]]:
        if not self.manifest_path.is_file():
            return {}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_manifest_entry(self, spec: ModelSpec) -> None:
        manifest = self._load_manifest()
        manifest[spec.model_id] = {
            "model_id": spec.model_id,
            "name": spec.name,
            "version": spec.version,
            "family": spec.family,
            "capabilities": list(spec.capabilities),
            "local_path": spec.local_path,
            "size_bytes": spec.size_bytes,
            "backend": spec.backend,
            "status": spec.status,
        }
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception as exc:
            logger.debug("Failed saving model manifest: %s", exc)

    def _remove_manifest_entry(self, model_id: str) -> None:
        manifest = self._load_manifest()
        if model_id in manifest:
            manifest.pop(model_id, None)
            try:
                with open(self.manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)
            except Exception:
                pass


def get_model_manager(config: Optional[GrandpaConfig] = None) -> NativeModelManager:
    """Return a configured NativeModelManager instance."""
    cfg = config or load_config()
    models_dir = getattr(getattr(cfg.engine, "native", None), "models_dir", None)
    return NativeModelManager(models_dir=models_dir)


def discover_native_models(models_dir: Optional[Path | str] = None) -> List[ModelSpec]:
    """Convenience discovery function."""
    mgr = NativeModelManager(models_dir=models_dir)
    return mgr.discover_local_models()


__all__ = [
    "NativeModelManager",
    "discover_native_models",
    "get_model_manager",
]
