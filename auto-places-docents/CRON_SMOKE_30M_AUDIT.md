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

### Postflight — 25/10/2026 (Europe/Madrid)

**PASS: GitHub ha lliurat dos esdeveniments reals `schedule` del workflow temporal, amb execució de l'script i pujada d'artifacts.**

| Evidència | 1a activació | 2a activació |
| --- | --- | --- |
| URL | https://github.com/hectorPascualC/auto-public/actions/runs/40201436178 | https://github.com/hectorPascualC/auto-public/actions/runs/40218094773 |
| GitHub event | `schedule` | `schedule` |
| Run created UTC | 2026-10-25 14:16:09Z | 2026-10-25 17:46:41Z |
| Runner observed Madrid | 2026-10-25 15:16:16 CET | 2026-10-25 18:46:49 CET |
| Job | 121193250483 SUCCESS | 121243514250 SUCCESS |
| Artifact | 12601839685 | 12608405361 |
| `source_event` | `schedule` | `schedule` |
| `status` | `SCHEDULE_DELIVERED` | `SCHEDULE_DELIVERED` |
| `run_id` en JSON | 40201436178 | 40218094773 |
| `schedule_expression` | `7,37 * 25,26 10 *` | `7,37 * 25,26 10 *` |
| Fonts / dispatch / escriptures persistents reportats | 0 / 0 / 0 | 0 / 0 / 0 |

L'auditoria ha comprovat el resultat dels jobs, els registres JSON i l'existència dels artifacts amb el nom i l'ID concordants. **No s'han descarregat els bytes interns dels artifacts**; els JSON equivalents s'han comprovat directament als logs. La comprovació de zero efectes laterals es basa en el codi del workflow/script, el registre i l'absència de passos de monitor, no en telemetria externa de xarxa.

**Límit important: NO PASS per puntualitat de 30 minuts.** Les dues execucions observades estan separades per 3 h 30 min 32 s, malgrat que el cron demanava intervals de 30 minuts. El transport de GitHub funciona, però aquestes dues observacions no demostren regularitat ni SLA. L'hora exacta de la franja nominal no es pot inferir dels timestamps de creació. Tampoc s'ha demostrat encara la puntualitat de les quatre passades laborables reals.

**Decisió:** retirar el workflow temporal per PR+CI; conservar l'script i els tests com a evidència reproduïble, i verificar que `main` ja no conté el cron. Això evita que el calendari `25,26 10` es reactivi cada any. No es canvien els crons de producció, secrets, Cloudflare ni dades del monitor.

**Estat final de l'experiment:** `PASS` per dues entregues automàtiques reals, `NO ACREDITAT` per cadència regular de 30 minuts. La restauració Cloudflare de dilluns 26/10 és una verificació separada, encara pendent.
