"""Probes read an app and return facts. They never return verdicts.

Each module exposes probe(app_dir: Path) -> list[dict] and self_test() -> None.
self_test must raise if the probe would report a wrong fact on a known input.
"""
