"""FarmIQ-RAG: Retrieval-Augmented Generation module for agricultural Q&A."""

__version__ = "0.1.0"


def _install_fast_packages_distributions() -> None:
    """Make ``importlib.metadata.packages_distributions()`` cheap on slow filesystems.

    ``transformers`` calls that function at import time. The stdlib builds the
    import-name -> distribution-name map by stat()'ing every file of every
    installed distribution that ships no ``top_level.txt``. On machines whose
    packages live on a synchronised/scanned volume (OneDrive, antivirus
    real-time protection) each stat can cost ~1 ms, turning a single
    ``import transformers`` into a multi-minute stall.

    The mapping is only ever used as a hint (see
    ``transformers.utils.import_utils._candidate_distribution_names``, which
    always falls back to the import name itself), so we replace it with a
    ``top_level.txt``-only implementation that reads one small file per
    distribution instead of stat()'ing its whole file list.
    """
    try:
        import importlib.metadata as _metadata
    except Exception:  # pragma: no cover - stdlib always present
        return
    if getattr(_metadata, "_farmiq_fast_packages", False):
        return

    def _fast_packages_distributions() -> dict:
        mapping: dict = {}
        for dist in _metadata.distributions():
            try:
                declared = dist.read_text("top_level.txt")
            except Exception:
                declared = None
            if not declared:
                continue
            name = dist.metadata.get("Name") if dist.metadata else None
            if not name:
                continue
            for line in declared.splitlines():
                pkg = line.strip()
                if pkg:
                    mapping.setdefault(pkg, []).append(name)
        return mapping

    _metadata.packages_distributions = _fast_packages_distributions
    _metadata._farmiq_fast_packages = True


_install_fast_packages_distributions()
