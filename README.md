# UniFi WAN Data Monitor

Läsande Home Assistant custom integration för UDM Pro. Välj **valfritt rapporterat WAN-interface** efter anslutning. Varje konfigurationspost har egna sensorer, egen sparad förbrukning och egen månadspott. Lägg till integrationen igen om flera WAN ska övervakas samtidigt.

Utgångspunkt: UniFi Network **10.6.109**, UDM Pro firmware **5.1.34**. Testfixturen visar WAN2 på `eth8` med syntetiska RX/TX-värden. Alla adresser, identifierare, tider och räknare i testdata är exempelvärden. Testdata använder påhittad MAC och innehåller inga cookies, lösenord eller API-nycklar från användaren.

**Status: utvecklingsversion, 0.1.2.** Enheten svarade HTTP 401 på det officiella sites-anropet utan autentisering 2026-11-02. Autentiserad åtkomst till portbytes är **inte verifierad mot den fysiska UDM:en**. Konfigurationsflödet kräver därför ett lyckat anrop och giltiga WAN-räknare innan det tillåter installation. Se `VALIDATION.md` för utförda tester och återstående driftsprov.

## 1. Verifiera autentisering och endpoint först

Använd en **ny lokal API-nyckel** från din konsol, eller ett separat **lokalt UniFi-konto** med läsrättigheter för Network. Kontots faktiska behörighet till den interna v2-endpointen kan behöva kontrolleras i din version. Molnkonto med MFA stöds inte av det lokala inloggningsflödet. Återanvänd inte en webbläsarsession.

| Metod | Vad integrationen verifierar |
|---|---|
| API-nyckel | `GET /proxy/network/integration/v1/sites` med `X-API-Key`, därefter den interna device-endpointen med samma nyckel |
| Lokalt konto | Ny egen session via `POST /api/auth/login`, därefter den interna device-endpointen |

Primär intern endpoint:

```text
GET /proxy/network/v2/api/site/default/device?separateUnmanaged=true&includeTrafficUsage=true
```

Från v0.1.2: om v2-endpointen saknas eller inte ger giltiga WAN-räknare provas också `GET /proxy/network/api/s/default/stat/device`, med samma autentisering. Enhetsobjekt kan ligga inuti nästlade JSON-listor eller objekt. Giltiga `port_table`-räknare, MAC och uttrycklig WAN-mappning krävs fortfarande. Ingen global gatewayräknare eller hastighetsuppskattning används som ersättning.

Vald endpoint sparas i konfigurationsposten och används därefter vid polling och återautentisering. Den byts inte automatiskt vid ett driftfel. Räknarnas källidentitet omfattar endpointen; äldre sparade baslinjer återställs försiktigt vid första provet efter v0.1.2, medan redan summerad förbrukning behålls. `counter_source` visas som attribut på period- och täckningssensorerna.

Det officiella sites-anropet är bara ett autentiseringstest. Det bevisar **inte** åtkomst till `port_table`. Ingen fallback uppskattar bytes från hastighet eller från hela gatewayens globala räknare. Om nyckeln fungerar för sites men nekas för device-anropet visas ett särskilt fel; välj då lokalt konto. Integrationens session skapas i minnet från den nya inloggningen, aldrig från inmatade cookies, CSRF-token eller browser-export.

Verifiera direkt i Home Assistants konfigurationsdialog, eller kör det medföljande verktyget på en dator med Python 3.12+ och nätverksåtkomst till UDM:

```shell
python -m pip install aiohttp
python tools/verify_connection.py --host https://192.0.2.1 --mode api_key
python tools/verify_connection.py --host https://192.0.2.1 --mode local
```

`192.0.2.1` är en dokumentationsadress. Ersätt den med din egen konsols adress, både här och i HA-dialogen.

Verktyget frågar efter hemligheten dolt. Lägg aldrig nyckel/lösenord i kommandoraden, en fråga här i chatten eller en Git-fil. För självsignerat certifikat kan du uttryckligen använda `--insecure`, eller avmarkera **Verifiera TLS-certifikat** i integrationen. Rekommenderat är ett certifikat som HA litar på. HTTPS krävs alltid; omdirigeringar följs inte.

## 2. Installera i Home Assistant OS

Home Assistant Core **2025.3+** är målet. Installera i Core-konfigurationsmappen, inte i Supervisor eller ett separat tillägg.

### Manuell installation från detta paket

1. Öppna HA:s `/config` med exempelvis Studio Code Server eller Samba.
2. Kopiera mappen `custom_components/unifi_wan_data_monitor` till `/config/custom_components/unifi_wan_data_monitor`.
3. Starta om Home Assistant.
4. Välj **Inställningar → Enheter och tjänster → Lägg till integration → UniFi WAN Data Monitor**.
5. Välj autentiseringsmetod, ange UDM:ens HTTPS-adress, site `default` och nya inloggningsuppgifter.
6. Välj WAN-interface i listan, exempelvis **WAN2 / eth8** eller **WAN / eth9**. Bara WAN-portar med giltiga `rx_bytes` och `tx_bytes` erbjuds. Port med värdet 0 är giltig; saknad räknare är ett fel.
7. Ange kvot, brytdag, uppdateringsintervall och eventuell känd förbrukning hittills.

### HACS: anpassat repository

Repository: **https://github.com/binbin2000/unifi-wan-data-monitor**

1. Öppna **HACS → ⋮ → Anpassade repositories**.
2. Ange `https://github.com/binbin2000/unifi-wan-data-monitor`.
3. Välj typen **Integration** och klicka **Lägg till**.
4. Sök efter **UniFi WAN Data Monitor**, öppna den och välj **Ladda ned**.
5. Starta om Home Assistant och lägg till integrationen under **Inställningar → Enheter och tjänster**.

Detta är ett anpassat repository, inte en integration som granskats för HACS standardkatalog. Autentiserad åtkomst till din UDM verifieras när integrationen konfigureras.

Om du i stället skapar en egen fork kan du uppdatera metadata med:

```shell
python tools/prepare_repository.py DITT_GITHUB_KONTO/unifi-wan-data-monitor
```

Det fyller manifestets dokumentationslänk, issue-länk och ansvarig med din forks repo-uppgifter.

## Konfiguration och inställningar

| Inställning | Standard | Betydelse |
|---|---|---|
| WAN-interface | eth8 om tillgängligt | Väljs ur enhetens `ethernet_overrides` och `port_table`; ingen hårdkodad portnumrering |
| Månadspott | 100 GB | Decimal GB: 100 GB = 100 000 000 000 byte |
| Brytdag | 1 | 1–31, lokal midnatt i HA:s tidszon; dag 31 blir sista dagen i korta månader |
| Uppdateringsintervall | 60 sekunder | 30–3 600 sekunder |
| Känd förbrukning vid start | 0 GB | Valfritt RX+TX-belopp för innevarande period, används endast vid den allra första baslinjen |

Efter installation finns pott, brytdag och intervall under **Konfigurera**. Ändring laddar om integrationen. Ändrad pott behåller förbrukningen. Ändrad brytdag börjar en ny lokal period med noll månadsförbrukning; tidigare period kan inte räknas om utan historik. Startförbrukningen kan inte användas för efterhandskorrigering: ändringar efter första provet ignoreras. För adress eller nya uppgifter: välj **Konfigurera om** i integrationspostens meny. För annat WAN: lägg till en ny post, så blandas inte två portar i samma räknare.

Ange **Europe/Stockholm** i HA om abonnemanget följer svensk tid. Sommar- och vintertid följer HA:s lokala kalender.

## Sensorer

Namnen innehåller valt WAN och interface, exempelvis `WAN2 eth8 cycle usage`. HA bestämmer slutliga entity-ID:n. Använd entitetsväljaren när du bygger dashboard eller automation.

| Sensor | Enhet / innebörd |
|---|---|
| Port RX / port TX | Råa byte från aktuell fysisk WAN-port; diagnostik, avstängda som standard |
| Observed RX / TX | Ackumulerade säkert observerade deltan sedan installation, bevaras mellan HA-omstarter |
| Cycle usage | Periodens RX + TX + eventuell känd startförbrukning; byte, visas normalt i GB |
| Quota remaining | `max(0, kvot − förbrukning)` i decimal GB |
| Quota used | Andel av kvoten i procent; kan överstiga 100 % |
| Billing cycle start | Periodens startdatum |
| Accounting coverage | `partial` samt orsak, antal räknarnollningar och separata månadsbyte som attribut |
| Active WAN | Gatewayens rapporterade aktiva uplink-grupp, exempelvis WAN eller WAN2; okänd om den inte kan avgöras |
| Selected WAN active (binär) | Om rapporterad uplink matchar valt WAN |
| Secondary WAN active (binär) | Om uplink är ett annat WAN än primärt WAN; **inte** bevis för varför trafik flyttats |
| Link (binär) | Fysisk länk upp/ned, separat från aktiv uplink |
| Quota exceeded (binär) | Förbrukning minst lika stor som kvoten |

RX ses från gatewayen: normalt nedladdning från ISP. TX är normalt uppladdning. Pottberäkningen summerar båda; jämför med operatörens debiteringsmodell. Portens trafik kan även innehålla trafik som ISP räknar annorlunda.

## Räknarnollning, omstarter och mätluckor

- Första provet sätter baslinjen. Alla historiska portbyte debiteras **inte** som denna månads trafik.
- Varje lyckad uppdatering sparar baslinje och totalsummor atomiskt via HA Store innan nya värden visas. Om skrivningen misslyckas flyttas inte baslinjen. HA-omstart behåller summeringen.
- Lägre uptime tillsammans med nyare `last_seen` bekräftar omstart och sätter ny baslinje för båda riktningarna. Saknas nyare tidsstämpel behålls den gamla baslinjen och provet markeras `unconfirmed_restart`. Trafik före/under omstarten kan saknas; första värdet efter omstarten läggs inte på som gissad trafik.
- Lägre räknare utan bekräftad omstart kan vara nollning, wrap eller gammalt API-svar. Integrationen behåller tidigare högsta baslinje tills båda räknarna återhämtat sig. Det kan ge underräkning efter en fristående portnollning men förhindrar stora falska påslag. Ingen 32/64-bitars wrap gissas.
- Svar med äldre `last_seen` ignoreras. Bortfall, saknade fält eller ogiltiga räknare ersätts aldrig med noll; sensorerna blir otillgängliga vid API-fel och senaste giltiga baslinjen behålls.
- Trafik mellan två prov över en periodgräns kan inte fördelas exakt. Den läggs på observerad total, men utesluts från den nya periodens pott. Ingen linjär fördelning eller ISP-historik hittas på.
- En lång lucka räknas när positiva deltan fortfarande kan läsas, men perioden markeras som ofullständig. Flera routeromstarter mellan prov kan aldrig garanterat upptäckas av dessa räknare.
- `partial` är avsiktligt konservativt även under normal drift: installation mitt i en period, polling och interna räknare ger inget faktureringsbevis. Integrationens värde kan vara lägre än ISP:s. Använd operatörens saldo som facit nära kvotgränsen.

Intern v2-API är versionsberoende. Enbart länkstatus eller byteökning tolkas aldrig som failover. `uplink.name` mappas till WAN-grupp enligt ditt JSON-exempel. Lastbalansering, policy routing och flera samtidiga uplinks kan inte beskrivas fullständigt med detta enda fält. Primärt WAN antas heta `WAN`; sekundärt aktivt WAN kan även vara manuellt valt.

## Säkerhet och omfattning

All trafikläsning sker med GET. Enda POST är lokal autentisering. Inga tjänster, switchar eller API-anrop för QoS, trafikregler eller WAN-styrning finns. Sådan styrning kräver en separat framtida fas.

Nyckel eller lösenord sparas i HA:s vanliga config entry, **inte i källkoden**. HA:s `.storage` och säkerhetskopior innehåller känsliga uppgifter; skydda åtkomsten. Sessionscookies lever bara i integrationens egen minnessession och stängs vid unload. Fel och loggar innehåller aldrig råa svarsbodyer, headers eller inloggningsuppgifter. API-nyckelmetoden använder en cookie-fri session.

## Testa och felsöka

Version 0.1.2 behåller adress, site, TLS-val och användarnamn i formuläret efter ett misslyckat försök. Lösenord och API-nyckel förifylls inte. Om båda device-endpointarna saknar giltiga WAN-räknare visas en separat, värderensad diagnostikrad för vardera endpointen. Det lokala verktyget `verify_connection.py` skriver också denna sammanfattning vid schemafel.

Version 0.1.1 gör WAN-upptäckten tåligare när andra enheter har tomma gränssnittstabeller. Om API-nyckeln fungerar för officiella sites men interna data inte ger WAN-räknare visas ett särskilt meddelande: prova då `local` med ett separat lokalt UniFi-konto. Det innebär inte att inloggning med lokalt konto garanterat ger ytterligare rättigheter.

Vid schemafel visas dessutom en säker diagnostikrad med endast datatyp och antal enheter, portar, giltiga RX/TX-par och WAN-mappningar. Den innehåller inga adresser, identifierare, räknarvärden, råa svar eller hemligheter. Kopiera den raden om felet kvarstår. Nollor i diagnostikens antal är **inte** nollställda trafiksensorer; konfigurationen stoppas fortfarande om giltiga räknare saknas.

```shell
python -m pip install -r requirements-test.txt
python -m pytest -q tests
python -m ruff check .
```

`ha_tests` kör dessutom de riktiga HA-klasserna för config flow, koordinator och entiteter. Se GitHub Actions-filen för Linuxmiljön. Tester täcker bland annat val av primärt/sekundärt WAN, räknarnollning, gamla svar, omstart/restore, periodbyte, kvot och utebliven åtkomst till portbytes.

Vid autentiseringsfel begär HA nya uppgifter. Vid timeout, schemafel eller frånkoppling visar sensorer `unavailable`. Kontrollera HTTPS, certifikat, site, Network-behörigheter och att vald fysisk port fortfarande är mappad till en WAN-grupp. Verktyget `verify_connection.py` ger en begränsad sammanfattning utan råa nätverksdumpningar.

Avinstallation: ta bort integrationsposten i HA. Då tas dess sparade räknarfil bort. Radera sedan integrationen via HACS eller ta bort komponentmappen och starta om HA. HA:s Recorder-historik hanteras separat av HA.

## Källor och API-underlag

- [Ubiquiti: officiella API:er och versionsspecifik lokal dokumentation](https://help.ui.com/hc/en-us/articles/30076656117655-Getting-Started-with-the-Official-UniFi-API). Kontrollera **Network → Integrations** på din UDM för dokumentationen för 10.6.109. Officiellt stöd för portbytes antas inte.
- [aiounifi: lokal UniFi OS-autentisering](https://github.com/Kane610/aiounifi/blob/master/aiounifi/interfaces/connectivity.py). Referens för `/api/auth/login`, inte ett löfte om rättigheter i din installation.
- [Home Assistant: Config flow](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/), [gemensam polling](https://developers.home-assistant.io/docs/integration_fetching_data/) och [sensorstatistik](https://developers.home-assistant.io/docs/core/entity/sensor/).
- [HACS: integrationsstruktur](https://www.hacs.xyz/docs/publish/integration/).

Inga beroenden till aiounifi behövs i drift; endast HA:s befintliga aiohttp/voluptuous och standardbibliotek används.
