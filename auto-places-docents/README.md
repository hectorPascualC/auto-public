# Motor AUTO-PUBLIC

Consulta el [README principal](../README.md) per a horari, execució i resultats.

Ordre de processament:

1. `monitor_v2.py` (utilitza `monitor.py`).
2. `edubcn_probe.py`.
3. `edubcn_finalize.py`.
4. `active_snapshot_v2.py` (utilitza `active_snapshot.py`).
5. `normalize_report.py`.

Les dependències són a `requirements.txt`. El workflow instal·la Chromium per a Playwright.
