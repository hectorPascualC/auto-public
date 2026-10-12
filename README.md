# AUTO-PUBLIC — places docents 507 / 627 / F57 / F87

Monitor de places docents de difícil cobertura de Catalunya. Consulta fonts oficials dels serveis territorials i del Consorci d’Educació de Barcelona.

## Execució

GitHub Actions executa el workflow **AUTO places docents 507-627** a la branca `main`, de dilluns a divendres, amb el cron UTC:

```cron
0 6,7,9,10,12,13,14,15 * * 1-5
```

És un horari fix en UTC; l’hora local varia amb l’horari d’estiu/hivern. La plataforma pot endarrerir les execucions programades.

A **Actions → AUTO places docents 507-627 → Run workflow**:

- `run_monitor`: `true` per defecte.
- `force_run`: `false` per defecte; permet ometre la comprovació de frescor si correspon.

Utilitza el runner estàndard `ubuntu-latest` i el `GITHUB_TOKEN` automàtic del repositori amb `contents: write`. No necessita un PAT ni CircleCI.

## Resultats

La primera passada genera `auto-places-docents/state/`:

- `consumer.json`: estat resumit per a consumidors.
- `latest.json`: estat tècnic del monitor.
- `latest.md`: informe llegible.
- `health.json` i `audit.json`: controls de qualitat.
- `history/`: instantànies generades en aquest repositori.

Els resultats són públics i provenen de fonts oficials accessibles sense autenticació. Els fitxers crus de descàrrega es mantenen només al runner i no es publiquen com a artifacts.

## Origen i continuïtat

Còpia independent dels scripts d’AUTO-PUBLIC, amb historial Git nou. No incorpora dades, branques ni historial del repositori d’origen. La primera passada parteix sense estat anterior; les següents poden comparar la frescor i les retirades amb les dades generades aquí.

Els consumidors que llegien el repositori anterior han de canviar la font a aquest repositori. Cal verificar una primera execució correcta abans de retirar els triggers de l’antic sistema.
