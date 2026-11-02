# Verifiering 2026-11-02

## Resultat

- Kodkontroll med Ruff: godkänd.
- Protokoll-, räkne- och paketeringstester: se `test-results.txt` i leveransen för slutligt antal.
- HA-adaptertester: samma fil redovisar tester av config flow, WAN-val, options flow, koordinator, sensorer, kvoter, felhantering och riktig HA Store-skrivning/återläsning.
- Verklig aiohttp-transport mot tillfällig lokal testserver verifierar att lokalt konto använder en egen nyskapad cookie-session och att API-nyckelmetoden aldrig skickar cookies.
- Alla testuppgifter är syntetiska. Ingen exponerad cookie, token eller nyckel från den refererade chatten har använts i koden eller nätverksanropen.

## Kontakt med den fysiska UDM:en

Följande anrop utfördes utan autentisering, utan cookies och utan nycklar:

| Anrop | Resultat |
|---|---|
| `GET /proxy/network/integration/v1/sites` | HTTP 401, JSON |
| `GET /proxy/network/v2/api/site/default/device?separateUnmanaged=true&includeTrafficUsage=true` | HTTP 401 |

Det bekräftar nåbarhet och krav på autentisering. Ett HTTP 401-svar bevisar inte att den interna endpointen fungerar efter inloggning: autentiseringslagret kan svara före routing. Ingen ny säker inloggningsuppgift fanns tillgänglig. Autentiserat schema, faktiska rättigheter och firmwarebeteende måste därför verifieras med HA:s konfigurationsdialog eller `tools/verify_connection.py`.

Konfigurationsflödet gör detta prov obligatoriskt och sparar ingen post om räknare saknas. API-nyckel för officiella sites godtas inte ensam som bevis för portåtkomst. Integrationens interna API-stöd bygger på användarens tillhandahållna JSON, inte på ett antagande om officiellt API-stöd.

## Testmiljö och begränsningar

Lokala protokolltester kördes med Python 3.12.14, aiohttp 3.14.5 och pytest 9.2.0. HA-adaptertester kördes med **riktiga Home Assistant 2025.3.4-klasser**, Python 3.13.18 och HA:s aiohttp 3.11.13. Två kompilerade beroenden använde Windows-kompatibla versioner: `ciso8601` 2.3.3 och `lru-dict` 1.4.1. Övriga direkta HA-beroenden följde HA:s versioner. En varning från HA:s egen HTTP-klass om aiohttp-arv förekom; inga integrationsfel kvarstår i testkörningen.

Detta är inte ett fullständigt driftsprov på HA OS. Medföljande GitHub Actions kör protokolltester och HA-adaptertester i separata Linuxjobb med HA 2025.3.4 och dess normala beroenden. Workflow-filen är skapad men har inte körts på GitHub här. HACS/hassfest-validering och GitHub-publicering är inte utförda; ersätt först manifestets `REPLACE_OWNER` med `prepare_repository.py`.

## Återstående driftsprov

1. Verifiera en ny API-nyckel mot både sites och device; vid nekad intern åtkomst, verifiera ett separat lokalt konto. Ange hemligheten direkt i HA eller i det lokala verktygets dolda prompt.
2. Installera på HA OS och välj önskat WAN. Kontrollera att nytt prov ger samma porträknare som konsolen.
3. Generera en känd mängd trafik på valt WAN. Kontrollera RX+TX-delta och kvotprocent; räkna med annan overhead än ISP:s mätare.
4. Starta om HA och kontrollera att månadsförbrukningen fortsätter. Koppla bort UDM kort och kontrollera otillgänglighet och återhämtning.
5. Vid ett planerat routerdriftsprov: kontrollera räknarnollning och faktisk failover. En rapporterad sekundär uplink visar aktivt sekundärt WAN, men inte om orsaken är failover, manuellt val eller lastbalansering.

Inga QoS- eller routerkonfigurationsändringar utfördes. Framtida styrning ingår inte i denna version.
