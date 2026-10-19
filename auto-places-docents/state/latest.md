# Passada directa 2026-10-19T21:59:10+02:00

Font: HTTP directe a Generalitat + Playwright directe a EDUBCN. Sense Tavily/Firecrawl.

| Àmbit | Frescor | 507 hits (diag.) | F57 hits (diag.) | 627 hits (diag.) | F87 hits (diag.) | Àncora global |
|---|---|---:|---:|---:|---:|---|
| Alt Pirineu i Aran | **FRESC** | 0 | 0 | 8 | 0 | APA-2627-S061 |
| Baix Llobregat | **FRESC** | 2 | 0 | 5 | 0 | 19780786 |
| Barcelonès | **FRESC** | 3 | 0 | 2 | 0 | 19764412 |
| Catalunya Central | **FRESC** | 0 | 1 | 0 | 0 | — |
| Girona | **FRESC** | 3 | 0 | 1 | 0 | — |
| Lleida | **FRESC** | 4 | 0 | 0 | 0 | 2026/SEC/111 |
| Maresme-Vallès Oriental | **FRESC** | 0 | 0 | 0 | 0 | — |
| Penedès | **FRESC** | 1 | 0 | 1 | 1 | 19772254 |
| Tarragona | **FRESC** | 0 | 3 | 0 | 0 | — |
| Terres de l'Ebre | **FRESC** | 0 | 0 | 1 | 0 | — |
| Vallès Occidental | **FRESC** | 8 | 2 | 8 | 1 | — |
| EDUBCN | **FRESC** | 3 | 1 | 3 | 1 | GENSEC_2627_186 |

## Notes de frescor
- Cap incidència final de frescor.
## Ús
Aquest fitxer és una síntesi tècnica. Per redactar la llista general i la shortlist, cal llegir `latest.json`, aplicar RESULTAT/cobertura i la regla de caducitat per `Fins a`.

## EDUBCN probe v3 override
- Frescor: **FRESC**
- Àncora global: `GENSEC_2627_186`
- GENSEC visibles: 45
- Documents GENSEC recuperats: 55
- Places target validades en el mateix document: 7
- Estratègia: agrupació per GENSEC + validació d'especialitat dins del mateix PDF/fitxa
- `GENSEC_2627_064`: 627,F87 | Institut Mare de Déu de la Mercè | sencera de docent de PFI. | fi 31/08/2027 | resultat=False
- `GENSEC_2627_162`: 507 | Institut Mare de Déu de la Mercè | sencera dins la Família professional d’Informàtica i | fi Alta titular | resultat=False
- `GENSEC_2627_163`: 627 | Institut Mare de Déu de la Mercè | sencera dins la Família professional d’Informàtica i | fi Alta titular | resultat=False
- `GENSEC_2627_171`: 507 | Institut Tecnològic de Barcelona | Sencera | fi 31/08/2027 | resultat=True
- `GENSEC_2627_175`: 627 | Institut Tecnològic de Barcelona | 0’5 | fi 31/08/2027 | resultat=True
- `GENSEC_2627_180`: 507 | Institut TIC de Barcelona | SENCERA | fi Alta titular o 30/06/2027 | resultat=False
- `GENSEC_2627_182`: F57 | Institut TIC de Barcelona | SENCERA | fi 28/10/2026 | resultat=True

## EDUBCN probe v4 final
- Regla: especialitat target només si apareix al mateix document oficial de la plaça.
- Identitat: es conserva el codi complet, inclosos sufixos (`_SCO`, etc.); el número base només serveix per frescor.
- Places documentals target verificades: 7
- `GENSEC_2627_064`: 627,F87 | Institut Mare de Déu de la Mercè | sencera de docent de PFI. | fi 31/08/2027 | resultat=False
- `GENSEC_2627_162`: 507 | Institut Mare de Déu de la Mercè | sencera dins la Família professional d’Informàtica i | fi Alta titular | resultat=False
- `GENSEC_2627_163`: 627 | Institut Mare de Déu de la Mercè | sencera dins la Família professional d’Informàtica i | fi Alta titular | resultat=False
- `GENSEC_2627_171`: 507 | Institut Tecnològic de Barcelona | Sencera | fi 31/08/2027 | resultat=True
- `GENSEC_2627_175`: 627 | Institut Tecnològic de Barcelona | 0’5 | fi 31/08/2027 | resultat=True
- `GENSEC_2627_180`: 507 | Institut TIC de Barcelona | SENCERA | fi Alta titular o 30/06/2027 | resultat=False
- `GENSEC_2627_182`: F57 | Institut TIC de Barcelona | SENCERA | fi 28/10/2026 | resultat=True

## Presència activa v1 — autoritativa
- Regla: una plaça continua activa mentre apareix al PDF/llistat oficial ACTUAL, encara que el termini de sol·licitud hagi vençut.
- Si desapareix d'una font **FRESCA** i la presència és autoritativa, surt de la llista activa.
- Si la font és PARCIAL/CACHE OBSOLETA o l'extracció no és segura, **no es poda** per desaparició.
- Els `hits` bruts són només diagnòstic; el recompte següent és de **places úniques actuals**.

| Àmbit | Frescor | Autoritativa | 507 | F57 | 627 | F87 | Mode |
|---|---|---|---:|---:|---:|---:|---|
| Alt Pirineu i Aran | FRESC | sí | 0 | 0 | 1 | 0 | offer-documents |
| Baix Llobregat | FRESC | sí | 1 | 0 | 0 | 0 | offer-documents |
| Barcelonès | FRESC | sí | 3 | 0 | 2 | 0 | offer-documents |
| Catalunya Central | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Girona | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Lleida | FRESC | sí | 1 | 0 | 0 | 0 | offer-documents |
| Maresme-Vallès Oriental | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Penedès | FRESC | sí | 1 | 0 | 1 | 0 | offer-documents |
| Tarragona | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Terres de l'Ebre | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| Vallès Occidental | FRESC | sí | 0 | 0 | 0 | 0 | offer-documents |
| EDUBCN | FRESC | sí | 2 | 0 | 2 | 1 | edubcn-document-verified |

### Places actuals detectades
- **Alt Pirineu i Aran**: `APA-2627-S056` (627)
- **Baix Llobregat**: `19711802` (507)
- **Barcelonès**: `19650726` (627), `19659466` (507), `19664257` (627), `19697257` (507), `19736796` (507)
- **Catalunya Central**: cap
- **Girona**: cap
- **Lleida**: `2026/SEC/089` (507)
- **Maresme-Vallès Oriental**: cap
- **Penedès**: `19742262` (507), `19764334` (627)
- **Tarragona**: cap
- **Terres de l'Ebre**: cap
- **Vallès Occidental**: cap
- **EDUBCN**: `GENSEC_2627_064` (627,F87), `GENSEC_2627_162` (507), `GENSEC_2627_163` (627), `GENSEC_2627_180` (507)

## Auditoria SSTT v2
- Estat: **PASS**
- SSTT auditats: **11/11**
- Àmbits totals auditats (inclòs EDUBCN): **12/12**
- Errors d'identificació: **0**

| Àmbit | FRESC | Autoritativa | Hits actuals | Hits identificats | Sense ID | Places actives |
|---|---|---|---:|---:|---:|---:|
| Alt Pirineu i Aran | sí | sí | 1 | 1 | 0 | 1 |
| Baix Llobregat | sí | sí | 1 | 1 | 0 | 1 |
| Barcelonès | sí | sí | 5 | 5 | 0 | 5 |
| Catalunya Central | sí | sí | 0 | 0 | 0 | 0 |
| Girona | sí | sí | 0 | 0 | 0 | 0 |
| Lleida | sí | sí | 1 | 1 | 0 | 1 |
| Maresme-Vallès Oriental | sí | sí | 0 | 0 | 0 | 0 |
| Penedès | sí | sí | 2 | 2 | 0 | 2 |
| Tarragona | sí | sí | 0 | 0 | 0 | 0 |
| Terres de l'Ebre | sí | sí | 0 | 0 | 0 | 0 |
| Vallès Occidental | sí | sí | 0 | 0 | 0 | 0 |
