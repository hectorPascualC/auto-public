# Auditoria SRE — prova fictícia del cron cada 30 minuts

## Disseny previ i risc

Objectiu: separar una execució automàtica **real** de GitHub Actions (`event=schedule`) d'una prova activada per `push` o `workflow_dispatch`. Un workflow `SUCCESS` no és prova que el cron hagi disparat. Tampoc s'infereix l'hora nominal de l'arrencada del runner, perquè GitHub pot retardar o ometre schedules.

- Workflow aïllat: `.github/workflows/cron-smoke-30m.yml`.
- Cron UTC exacte: `7,37 * 25,26 10 *` (proves del 25 i 26 d'octubre de 2026, cada 30 minuts, lluny del minut 0).
- L'interval de 30 minuts és de programació **sol·licitada**, no un SLA d'execució.
- Permisos únics: `contents: read`. Sense secrets, Cloudflare, GITHUB_TOKEN en variables, crides de xarxa, dispatch, monitor, Playwright ni escriptura al repositori.
- Concurrència exclusiva i `timeout-minutes: 3`.
- Dades que escriu: **només** un JSON innocu a `RUNNER_TEMP`, pujat com a artifact efímer de 2 dies.
- `push` en canviar exclusivament el fitxer del workflow: verifica que el codi arrenca però etiqueta inequívocament `SMOKE_ONLY_NOT_SCHEDULE_EVIDENCE`.
- `schedule`: només aquest esdeveniment pot generar `SCHEDULE_DELIVERED`; l'hora és observada, mai inventada.
- Mesura: comprovar runs d'event `schedule`, els seus logs, l'artifact amb `source_event=schedule` i el mateix run_id, almenys en 2 activacions consecutives diferents.
- Caducitat: cron acotat a 25–26 d'octubre, no és permanent. Cal retirar el workflow amb PR+CI després d'obtenir les evidències; no crear altres automatitzacions.

## Criteris de validació posterior

1. CI PR: Python `unittest`, YAML i regressió del monitor, NODE i bundle Cloudflare PASS.
2. CI push després de merge: PASS i workflow fictici amb `event=push` i report `SMOKE_ONLY_NOT_SCHEDULE_EVIDENCE`.
3. Cron real: mínim dos runs diferents amb `event=schedule` i artifacts `SCHEDULE_DELIVERED`; no incloure `push` en el recompte.
4. No hi ha cap modificació de `health.json`, `consumer.json`, `audit.json` o `slot-ledger.json` per part d'aquest workflow. Cal comprovar les diferències per SHA/commit i les tasques executades.
5. Si el cron no es dispara: estat `PENDENT/BLOQUEJAT`, no PASS; revisar que el workflow es trobi a main, estat d'activació, permisos i retards GitHub, sense inventar execucions.
6. No s'alteren les quatre passades laborables del monitor: 08:00, 11:00, 13:00, 17:00 Europe/Madrid.

## Evidències

Les URL, run IDs i hores de GitHub s'han d'afegir a l'informe SRE un cop siguin observades. **Aquest document descriu els criteris de prova, no afirma cap cron real verificat.**
