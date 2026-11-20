# Passada directa 2026-11-20T16:44:11+01:00

Font: HTTP directe a Generalitat + Playwright directe a EDUBCN. Sense Tavily/Firecrawl.

| Àmbit | Frescor | 507 hits (diag.) | F57 hits (diag.) | 627 hits (diag.) | F87 hits (diag.) | Àncora global |
|---|---|---:|---:|---:|---:|---|
| Alt Pirineu i Aran | **FRESC** | 3 | 0 | 6 | 0 | APA-2627-S069 |
| Baix Llobregat | **FRESC** | 4 | 0 | 0 | 0 | 19874761 |
| Barcelonès | **FRESC** | 0 | 0 | 0 | 0 | 19874256 |
| Catalunya Central | **FRESC** | 0 | 1 | 0 | 0 | — |
| Girona | **FRESC** | 4 | 0 | 2 | 0 | — |
| Lleida | **FRESC** | 4 | 0 | 0 | 0 | 2026/SEC/135 |
| Maresme-Vallès Oriental | **FRESC** | 0 | 0 | 1 | 0 | — |
| Penedès | **FRESC** | 0 | 0 | 3 | 1 | 19865272 |
| Tarragona | **FRESC** | 0 | 3 | 0 | 0 | — |
| Terres de l'Ebre | **FRESC** | 0 | 0 | 1 | 0 | — |
| Vallès Occidental | **FRESC** | 9 | 2 | 14 | 1 | — |
| EDUBCN | **FRESC** | 0 | 0 | 0 | 0 | GENSEC_2627_204 |

## Notes de frescor
- Cap incidència final de frescor.
## Ús
Aquest fitxer és una síntesi tècnica. Per redactar la llista general i la shortlist, cal llegir `latest.json`, aplicar RESULTAT/cobertura i la regla de caducitat per `Fins a`.

## EDUBCN probe v3 override
- Frescor: **FRESC**
- Àncora global: `GENSEC_2627_204`
- GENSEC visibles: 17
- Documents GENSEC recuperats: 22
- Places target validades en el mateix document: 0
- Estratègia: agrupació per GENSEC + validació d'especialitat dins del mateix PDF/fitxa

## EDUBCN probe v4 final
- Regla: especialitat target només si apareix al mateix document oficial de la plaça.
- Identitat: es conserva el codi complet, inclosos sufixos (`_SCO`, etc.); el número base només serveix per frescor.
- Places documentals target verificades: 0

## Presència activa v1 — autoritativa
- Regla: una plaça continua activa mentre apareix al PDF/llistat oficial ACTUAL, encara que el termini de sol·licitud hagi vençut.
- Si desapareix d'una font **FRESCA** i la presència és autoritativa, surt de la llista activa.
- Si la font és PARCIAL/CACHE OBSOLETA o l'extracció no és segura, **no es poda** per desaparició.
- Els `hits` bruts són només diagnòstic; el recompte següent és de **places úniques actuals**.

| Àmbit | Frescor | Autoritativa | 507 | F57 | 627 | F87 | Mode |
|---|---|---|---:|---:|---:|---:|---|
| Alt Pirineu i Aran | FRESC | sí | 1 | 0 | 0 | 0 | offer-documents |
| Baix Llobregat | FRESC | sí | 2 | 0 | 0 | 0 | offer-documents |
| Barcelonès | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Catalunya Central | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Girona | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Lleida | FRESC | sí | 1 | 0 | 0 | 0 | offer-documents |
| Maresme-Vallès Oriental | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Penedès | FRESC | sí | 0 | 0 | 1 | 0 | offer-documents |
| Tarragona | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Terres de l'Ebre | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Vallès Occidental | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| EDUBCN | FRESC | sí | 0 | 0 | 0 | 0 | edubcn-document-verified |

### Places actuals detectades
- **Alt Pirineu i Aran**: `APA-2627-S064` (507)
- **Baix Llobregat**: `19831268` (507), `19874761` (507)
- **Barcelonès**: cap
- **Catalunya Central**: cap
- **Girona**: cap
- **Lleida**: `2026/SEC/089` (507)
- **Maresme-Vallès Oriental**: cap
- **Penedès**: `19862262` (627)
- **Tarragona**: cap
- **Terres de l'Ebre**: cap
- **Vallès Occidental**: cap
- **EDUBCN**: cap
  - Desaparegudes des de la passada anterior: `GENSEC_2627_064`, `GENSEC_2627_162`, `GENSEC_2627_163`, `GENSEC_2627_180`, `GENSEC_2627_187`

## Auditoria SSTT v2
- Estat: **PASS**
- SSTT auditats: **11/11**
- Àmbits totals auditats (inclòs EDUBCN): **12/12**
- Errors d'identificació: **0**

| Àmbit | FRESC | Autoritativa | Hits actuals | Hits identificats | Sense ID | Places actives |
|---|---|---|---:|---:|---:|---:|
| Alt Pirineu i Aran | sí | sí | 1 | 1 | 0 | 1 |
| Baix Llobregat | sí | sí | 2 | 2 | 0 | 2 |
| Barcelonès | sí | sí | 0 | 0 | 0 | 0 |
| Catalunya Central | sí | sí | 0 | 0 | 0 | 0 |
| Girona | sí | sí | 0 | 0 | 0 | 0 |
| Lleida | sí | sí | 1 | 1 | 0 | 1 |
| Maresme-Vallès Oriental | sí | sí | 0 | 0 | 0 | 0 |
| Penedès | sí | sí | 1 | 1 | 0 | 1 |
| Tarragona | sí | sí | 0 | 0 | 0 | 0 |
| Terres de l'Ebre | sí | sí | 0 | 0 | 0 | 0 |
| Vallès Occidental | sí | sí | 0 | 0 | 0 | 0 |
