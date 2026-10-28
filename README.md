# AUTO-PUBLIC — seguiment de places docents 507 / 627 / F57 / F87

Repositori públic del monitor de fonts oficials (11 serveis territorials i EDUBCN).

## Arquitectura de producció (GitHub-only)

- **GitHub Actions** executa l'escaneig de fonts oficials i la persistència compacta.
- Quatre franges nominals laborables, hora **Europe/Madrid**: **08:00, 11:00, 13:00 i 17:00**.
- Cada franja té crons de primer intent, reserva i recuperació, amb deduplicació i registre de rebuts.
- L'única automatització de ChatGPT SRE existent pot efectuar un rescat condicional en finestra acotada; no es crea cap controlador ni cron addicional.
- Un workflow verd **no acredita** un escaneig: les etapes de lectura de fonts, verificació i persistència han d'haver-se executat realment.

La programació nativa de GitHub Actions és *best effort*: poden aparèixer retards o execucions omeses.
Les franges del 27 d'octubre de 2026 tenen rebuts reals de rescat; les execucions verdes
del 28 d'octubre consultades no acreditaven una nova exploració.

## Auditoria i autoreparació

- [Política del repair harness GitHub-only](docs/REPAIR_HARNESS_GITHUB_ONLY.md)
- [Workflow d'auditoria SRE](.github/workflows/sre-audit-v2.yml)
- [Motor d'incidències i reparacions permeses](auto-places-docents/repair_harness.py)
- [Proves de regressió del motor](auto-places-docents/tests/test_sre_repair_harness.py)
- [Auditoria de paritat GitHub-only del 25 d'octubre](auto-places-docents/GITHUB_ONLY_PARITY_AUDIT_2026-10-25.md)

La primera capa de reparació identifica incidències i pot regenerar **localment**
el `consumer.json` derivat **només** si els registres canònics estan auditats.
La correcció local NO es publica a producció automàticament; les modificacions
persistents requereixen PR i verificació. Les incidències desconegudes no
desencadenen modificacions de codi ni reintents cecs.

## Qualitat i privacitat

- [CI de regressions](.github/workflows/auto-places-docents-ci.yml)
- [Workflow del monitor](.github/workflows/auto-places-docents.yml)

Aquest repositori és públic. No s'hi han d'incorporar candidats privats,
correspondència ni credencials. Els historials antics requereixen revisió
separada: sanejar els fitxers nous no elimina automàticament els anteriors.

Les carpetes i documents de controladors antics són **històrics**, no la
infraestructura activa del monitor GitHub-only.
