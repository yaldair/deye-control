# EMHASS → Deye via Remote Control (zonder YamBMS)

> **Let op: niet door mij live getest.** De flows in deze repository zijn afgeleid van de flow die ik zelf gebruik, maar deze versies heb ik **niet** zelf op mijn omvormer gedraaid. Daarvoor had ik mijn eigen sturing moeten uitzetten. Ze zijn alleen getest in Node-RED tegen gesimuleerde data.
>
> Je stuurt hiermee je omvormer en accu aan. Gebruik op eigen risico. Begin met `DRY_RUN = true`, gebruik de testflow en werk met kleine vermogens. Dit is gedeeld zoals het is: ik bied geen support en geen updates. Fork het en pas het aan naar je eigen situatie.

Een Node-RED-flow die het optimalisatieplan van [EMHASS](https://github.com/davidusb-geek/emhass) uitvoert op een Deye hybride omvormer. Hij gebruikt de **Remote Control-registers (1100+)**, die in RAM staan. De flow schrijft nooit naar de TOU-tabel of andere persistente instellingen, dus er is geen EEPROM-slijtage door de sturing.

## Het idee

- **Native is de basis.** De TOU-tabel stel je één keer handmatig in op gewoon zelfverbruik. Zo werkt de Deye ook als Node-RED, HA of je server uitvalt.
- **Remote is de uitzondering.** Alleen als EMHASS iets wil wat native niet kan (netladen, verkopen, de accu stilzetten), zet de flow remote control aan voor dat kwartier.
- **Watchdog als vangnet.** Remote staat aan met een watchdog van 5 minuten, die de flow elke minuut verlengt. Stopt de flow, dan valt de Deye vanzelf terug op native.

```
EMHASS publish-sensoren ──► 1 Plan inlezen ──► 2 Classificeren + segmenteren ──► 3 Gewenste stand ──► 4 Remote executor ──► HA ──► Deye 1100-1110
   (elke minuut)                               per kwartier: charge/discharge/      native of remote     1 write per tick (5 s),
                                               sell/hold + bron (PV/net)            + vermogen + doel     read-back, keepalive
```

## Wat er per kwartier gebeurt

| EMHASS wil | Uitvoering | Hoe |
|---|---|---|
| Ontladen naar de eigen load | native | TOU: zelfverbruik, zero-export |
| Laden uit PV (alles of max + rest export) | native | TOU: surplus naar de accu |
| Laden uit het net | remote | Vast vermogen tot doel-SOC (einde segment); de Deye stopt zelf op het doel |
| Verkopen aan het net | remote | Vast vermogen tot doel-SOC |
| Hold (accu stil) | remote | Accu 0 W; PV-surplus gaat naar het net, tekort komt uit het net |
| Laden uit PV, bewust minder dan beschikbaar | native, of remote met `RC_LIMITED_PV` | Zie beperkingen |
| Deels ontladen, rest bewust uit het net | native, of remote met `RC_PARTIAL_DISCHARGE` | Zie beperkingen |
| Geen plan voor dit kwartier / plan verouderd | native | Remote uit |

Het vermogen komt uit EMHASS (`p_batt` van het stuurkwartier). Het doel-SOC is de SOC aan het einde van het segment volgens EMHASS, begrensd tussen `SOC_MIN` en `SOC_MAX_CHARGE`. Is het doel al bereikt, dan zet de flow de accu stil in plaats van remote steeds aan en uit te schakelen.

## Beperkingen

- **Zero-export geldt niet in remote.** In remote-kwartieren gaat alles wat de accu niet opneemt of levert naar of uit het net. Bij hold is dat precies de bedoeling. Maar bij een negatieve terugleverprijs exporteer je dan PV. Curtailment zit **niet** in deze flow; dat moet je apart regelen (via de PV-omvormer of de exportlimiet). Test zelf of jouw Deye in remote de "max sell power" nog respecteert.
- **Een setpoint is geen plafond.** Remote zegt "accu levert X W", niet "accu levert hoogstens X W". Daarom staan `RC_LIMITED_PV` en `RC_PARTIAL_DISCHARGE` standaard **uit**:
  - `RC_LIMITED_PV`: trekt er een wolk over, dan laadt de accu het vaste vermogen uit het net bij.
  - `RC_PARTIAL_DISCHARGE`: zakt de load onder het setpoint, dan gaat het verschil uit de accu het net op.
- **Geen begrenzing van ontlaadstroom per apparaat.** Wie wil voorkomen dat de accu een warmtepomp of EV voedt, heeft een plafond op de ontlaadstroom nodig (bijvoorbeeld via een BMS die de DCL laat aansturen, zoals YamBMS). Dat kan remote niet netjes.
- **De BMS doet de bovenkant.** Laadcurve, balanceren en float regelt je BMS via CAN. De flow gaat via remote niet boven `SOC_MAX_CHARGE`.

## Vereisten

- **Deye hybride omvormer met firmware die Remote Control (1100+) ondersteunt.** Getest op een SUN-12K-SG05LP3 met firmware 1175. Voor andere modellen of firmware: eerst het testprotocol hieronder volgen.
- **Een closed-loop BMS via CAN** (Pylontech, Seplos, JK met CAN, etc.). Remote stopt op de SOC van de omvormer, en die moet kloppen.
- **Home Assistant** met de Deye uitgelezen en de RC-registers als `select`/`number`-entiteiten (zie stap 2).
- **EMHASS** die zijn plan naar HA publiceert (`publish-data`), met de standaardsensoren `sensor.soc_batt_forecast`, `sensor.p_batt_forecast`, `sensor.p_grid_forecast` en bij voorkeur `sensor.p_load_forecast` en `sensor.p_pv_forecast`. Een kwartiertijdstap (`optimization_time_step: 15`) is aangenomen.
- **Node-RED** met `node-red-contrib-home-assistant-websocket` (getest met 0.80.3), en bij de HA-serverconfig **"Enable global context store"** aan. De flow leest de states uit de global context.

## Installatie

### 1. TOU-tabel eenmalig instellen

Stel in de Deye (display of app) alle zes de tijdvakken gelijk in:

- Time of Use: aan
- Grid charge: uit, in alle vakken
- Capacity / SOC: je minimale SOC, gelijk aan `SOC_MIN` (bijvoorbeeld 15%)
- Solar sell: aan als je PV-surplus wilt terugleveren
- Werkmodus: zero-export (to CT / load limiter, afhankelijk van je meetopstelling)

Daarna blijft de tabel ongemoeid.

### 2. Remote Control-registers in Home Assistant

De flow verwacht zes entiteiten:

| Register | Functie | Ruwe waarden | Gebruik in de flow |
|---|---|---|---|
| 1100 | Remote control | 0 = uit, 1 = aan | `RC_OPT_ON` / `RC_OPT_OFF` |
| 1101 | Watchdog (s) | telt af zodra 1100 = 1; bij 0 zet de omvormer 1100 terug op 0 | 300, keepalive wisselt 300/301 |
| 1104 | Stuurzijde | 0 = AC, 1 = accu (DC), 2 = net | altijd accu (`RC_OPT_SIDE_BATT`) |
| 1105 | Accustrategie | 2 = vermogen (1109), 3 = SOC (1110), 5 = vermogen + SOC | 2 (`RC_OPT_POWER`) en 5 (`RC_OPT_POWER_SOC`) |
| 1109 | Accuvermogen | % × 10 van nominaal, signed: + = ontladen, − = laden | één decimaal, max `MAX_PCT` |
| 1110 | Doel-SOC | % × 10 | geheel getal |

Niet gebruikt: 1106 (fasemodus), 1111 (totaalvermogen, niet getest) en 1115 (max PV/MPPT). Voor 1115 geldt: 1000 of hoger geeft **0 W PV**. Definieer dat register niet als je het niet nodig hebt.

Het hele blok staat in RAM: 1101 telt elke seconde af, en dat kan niet in EEPROM. Vóór de eerste write las ik 1104 = AC en 1110 = 80%; dat lijken de standaardwaarden.

**Met de Sunsynk/Deye add-on (kellerza):** gebruik [`mysensors.py`](mysensors.py). De optieteksten daarin (`On`/`Off`/`Battery`/`Power`/`Power+SOC`) zijn ook de standaardwaarden in de flow. De entity-ID's worden `<prefix>_rc_mode` enzovoort; met prefix `deye` sluiten ze direct aan op de flow.

**Met ha-solarman:** die integratie werkt met YAML-definitiebestanden per omvormertype. Je kunt een eigen definitie maken met deze registers als schrijfbare `select`/`number`-items. Hoe dat precies moet, verschilt per versie; zie de documentatie van ha-solarman. Kopieer het standaardbestand onder een eigen naam, anders gaat je wijziging verloren bij een update. **Let op:** de registerbeschrijving in de ha-solarman-PR voor remote control wijkt vanaf 1106 af van de Deye-documentatie en van wat ik uitlees. Ga uit van de tabel hierboven en controleer met het testprotocol. Ook 1100 = 2/3 staat niet in de Deye-documentatie; de flow gebruikt alleen 0 en 1.

Hoe de entiteiten heten en welke optieteksten je select-entiteiten tonen, maakt niet uit. Dat stel je in stap 4 in.

### 3. Flow importeren

Importeer `emhass-deye-remote.json` (Menu → Import). Open daarna de node **Deye RC (HA action)** en kies je eigen Home Assistant-server. Die is bewust leeg gelaten.

### 4. Configureren

Dubbelklik op het tabblad → **Environment variables**. Alle instellingen staan daar; je hoeft geen code aan te passen.

| Variabele | Standaard | Betekenis |
|---|---|---|
| `DRY_RUN` | `true` | Alleen loggen wat er geschreven zou worden |
| `RC_ENABLED_AT_START` | `false` | Executor aan na een (re)start van Node-RED |
| `ENT_FC_SOC` … `ENT_FC_PV` | EMHASS-standaard | Entiteiten van de EMHASS-publish |
| `ENT_BATT_SOC` | `sensor.deye_battery_soc` | Gemeten accu-SOC (anders de forecast-state) |
| `RC_ENT_*` | `select.deye_rc_*` / `number.deye_rc_*` | Je RC-entiteiten (stap 2) |
| `RC_OPT_*` | `On` / `Off` / `Battery` / `Power` / `Power+SOC` | Exacte optieteksten van je select-entiteiten |
| `W_PER_PCT` | `120` | W per % setpoint: nominaal omvormervermogen / 100 (12 kW → 120) |
| `MAX_PCT` | `42` | Plafond van het setpoint (≈ 5 kW bij 12 kW) |
| `MAX_CHARGE_W` | `5000` | Maximaal laadvermogen; boven 90% hiervan telt laden als "max" |
| `SOC_MIN` | `15` | Ondergrens bij ontladen via remote |
| `SOC_MAX_CHARGE` | `95` | Bovengrens bij laden via remote |
| `HOLD_VIA_REMOTE` | `true` | Hold via remote (0 W). Uit = native, dan ontlaadt de accu gewoon |
| `RC_LIMITED_PV` | `false` | Begrensd PV-laden via remote (zie beperkingen) |
| `RC_PARTIAL_DISCHARGE` | `false` | Deel-ontladen via remote (zie beperkingen) |
| `RC_WATCHDOG_S` | `300` | Watchdog in seconden: zo lang blijft remote actief zonder Node-RED |
| `RC_KEEPALIVE_S` | `60` | Interval waarop de watchdog verlengd wordt |
| `RC_RESEND_S` | `15` | Zelfde write niet opnieuw binnen deze tijd (wachten op read-back) |
| `PLAN_STALE_MIN` | `10` | Plan ouder dan dit → remote uit |
| `CONTROL_LEAD_S` | `90` | Zoveel seconden vóór een kwartier geldt dat kwartier al |
| `DEADBAND_W` | `100` | Vermogens hieronder tellen als 0 |
| `PV_TOLERANCE_W` | `250` | Marge bij herkennen van begrensd PV-laden |
| `SELL_MARGIN_PCT` | `1` | Ontladen knijpt af vlak bij het doel; het doel ligt daarom iets lager |
| `MIN_PCT` | `1` | Kleinere setpoints worden 0 |
| `TZ_NAME` | `Europe/Amsterdam` | Alleen voor statusteksten |
| `STATE_PREFIX` | `rc` | Voorvoegsel van de globals `<prefix>_plan`, `<prefix>_state`, `<prefix>_inhibit` |

Na het wijzigen van env-variabelen: **Deploy**.

### 5. Droogdraaien

Laat `DRY_RUN` op `true` en klik **remote AAN**. De debug-node **DRY-RUN writes** toont nu welke writes de executor zou doen, in de echte volgorde. **gewenste stand** toont per minuut wat de flow wil en waarom. Met de inject **simuleer tijdstip** (pas `control_now` aan) zie je wat de flow op een ander moment zou doen, zonder dat de executor iets doet.

Laat dit een dag meelopen en vergelijk met het EMHASS-plan.

### 6. Testprotocol voor live

Voordat de executor live gaat, controleer je of jouw omvormer zich gedraagt zoals de flow aanneemt. Daarvoor is er een aparte testflow: [`rc-testflow.json`](rc-testflow.json). Die doet de metingen automatisch, met kleine vermogens, read-back na elke write en een veiligheidsstop.

**Voorbereiding**
1. Importeer `rc-testflow.json`. Hij komt op een eigen tabblad "RC test (Deye remote)".
2. Zet alles uit wat de Deye aanstuurt. De remote executor moet **UIT** staan; de testrunner weigert te starten als hij een live executor ziet. Zet ook andere automations uit die de Deye of de BMS-limieten aansturen.
3. Kies je HA-server in de node **HA call (RC)**.
4. Vul de tab-variabelen in (dubbelklik het tabblad). De `RC_ENT_*`, `RC_OPT_*` en `W_PER_PCT` zijn dezelfde als in de hoofdflow. Extra:

| Variabele | Standaard | Betekenis |
|---|---|---|
| `ENT_BATT_POWER` | `sensor.deye_battery_power` | Gemeten accuvermogen |
| `BATT_POWER_SIGN` | `1` | `1` als die sensor + = ontladen geeft, anders `-1` |
| `ENT_BATT_SOC` | `sensor.deye_battery_soc` | Gemeten SOC |
| `ENT_GRID_POWER` | leeg | Optioneel: netvermogen, alleen voor in de log |
| `ENT_SHUNT_POWER` / `SHUNT_POWER_SIGN` | leeg / `-1` | Optioneel: een shunt als tweede meting (Victron SmartShunt: − = ontladen) |
| `DCL_ENTITY` | leeg | Optioneel: `number`-entiteit voor de ontlaadstroomgrens van je BMS. Leeg = T6 vraagt je die handmatig in te stellen |
| `DCL_TEST_A` | `10` | Ontlaadstroomgrens tijdens T6 |
| `SAFETY_MAX_W` | `1500` | Test stopt direct boven dit accuvermogen |
| `READBACK_S` | `8` | Wachttijd voor read-back na een write (de add-on pollt elke ~5 s) |
| `KEEPALIVE_VIA` | `watchdog` | Keepalive in T5: `watchdog`, `power` of `mode` (zie T4) |

**De tests** (één tegelijk, steeds via de inject-knoppen):

| Test | Wat | Duur | Verwacht |
|---|---|---|---|
| T0 | Alleen lezen | direct | Alle entiteiten gevonden, waarden logisch. 1100 = uit |
| T1 | Remote aan met 0 W, watchdog 60 s, niets verlengen | ~2 min | Terugval na ~60 s |
| T2 | +5% en daarna −5% | ~1,5 min | Ontladen bij +, laden bij −, ~`W_PER_PCT` × 5 W |
| T3 | Idem met ±10% | ~1,5 min | Lineair: dubbel zoveel als T2 |
| T4a/b/c | Watchdog 60 s, op t+40 s één register herschrijven (1101, 1109 of 1100) | ~2 min | Welke variant de timer verlengt. Bij mij alleen 1101 (a) |
| T5a | Vermogen + SOC: ontladen met 5% tot SOC − 3 | tot ~30 min | Stopt zelf op het doel |
| T5b | Vermogen + SOC: laden met 5% tot SOC + 1 | tot ~30 min | Stopt zelf op het doel |
| T5c | Laden gevraagd, doel onder de huidige SOC | ~1 min | Accu doet niets |
| T6 | Ontlaadstroomgrens BMS op ~10 A, +10% gevraagd | ~1 min | Accuvermogen begrensd door de BMS |

Na elke test, ook bij een fout of STOP: 1100 uit en 1109 = 0, met controle. **STOP** is altijd veilig. **Log tonen** zet de resultaten en de volledige log in de debug-sidebar en in `rc-test.log` (in de werkmap van Node-RED). Verlengt bij T4 alleen een andere variant dan 1101 de watchdog, pas dan `KEEPALIVE_VIA` aan vóór T5. De hoofdflow ondersteunt nu alleen keepalive via 1101.

Op de SUN-12K-SG05LP3 met fw 1175 slaagden alle tests. De metingen:

- **Schaal en teken:** 1% = 120 W. +5% gaf 598 W ontladen, −5% gaf 600 W laden, ±10% gaf ±1199 W. Reactie binnen ongeveer 5–10 s.
- **Watchdog:** de timer start pas bij 1100 = 1 en telt zichtbaar af. Na afloop valt de omvormer zelf terug op normaal (zelfverbruik/zero-export).
- **Keepalive:** alleen 1101 opnieuw schrijven verlengt de timer. 1109 of 1100 opnieuw schrijven doet niets. Met watchdog 120 s en elke ~70 s een write naar 1101 bleef remote 30 minuten stabiel aan.
- **Strategie 5 (vermogen + doel-SOC):** laden stopt netjes zelf op het doel. Ontladen ook, maar binnen ongeveer 0,5–1% van het doel knijpt hij af (gemeten ~210 W in plaats van 600 W). Een doel 3% lager gaf de volle 600 W. Daarom legt de flow het ontlaaddoel `SELL_MARGIN_PCT` lager dan het EMHASS-doel.
- **Tegenstrijdige vraag** (laden, maar doel onder huidige SOC): de accu doet niets (~20 W) en het huis draait op het net. Dat is in feite een hold.
- **BMS-limieten blijven leidend:** met de ontlaadstroomgrens van de BMS op 10 A en +10% (1200 W) gevraagd, ontlaadde hij ~580 W. CCL/DCL via CAN begrenzen dus het remote-setpoint.
- **Zero-export geldt niet in remote accumodus:** 1200 W ontladen bij ~500 W huisverbruik gaf ~700 W teruglevering. Handig voor verkopen, maar alles wat het plan mist, gaat naar of van het net.

Gaat dat allemaal goed: in de hoofdflow `DRY_RUN` op `false`, **remote AAN**, en kijk de eerste netlaad- of verkoopperiode mee. Het testtabblad kun je daarna uitschakelen of verwijderen.

## Bediening

- **remote AAN / remote UIT**: hoofdschakelaar. Bij UIT zet de executor remote uit, en de Deye gaat terug naar native.
- **Status onder de nodes**: elke node laat zien wat hij doet. De executor toont `[DRY]`, `[UIT]`, `REMOTE` of `native` plus de reden.
- **Globals voor dashboards en eigen uitbreidingen** (prefix instelbaar met `STATE_PREFIX`, standaard `rc`):
  - `rc_plan`: het stuurkwartier, het segment en de gewenste stand, elke minuut bijgewerkt.
  - `rc_state`: wat de executor nu doet.
  - `rc_inhibit`: zelf te zetten. Een tekst of `true` houdt de Deye native (de tekst verschijnt als reden). Leegmaken (`undefined`/`false`) geeft de executor weer vrij. Bedoeld voor eigen logica, zoals balanceren via de BMS of een handmatige override.

Draai je deze flow naast een eigen executor (bijvoorbeeld in `DRY_RUN` ter vergelijking), geef hem dan een eigen `STATE_PREFIX`, zodat de globals niet botsen.

## Veiligheid

- De executor schrijft maximaal één register per 5 seconden en controleert de read-back vóór de volgende stap.
- Remote gaat pas aan als stuurkant, modus, doel en vermogen kloppen en de watchdog staat ingesteld.
- Ontbreekt een RC-entiteit in HA, dan schrijft de executor niets.
- Stopt Node-RED, HA of de verbinding, dan loopt de watchdog af binnen `RC_WATCHDOG_S`, en de Deye valt terug op de TOU-basis.
- Remote werkt niet off-grid; bij netuitval regelt de Deye zelf.

## Bekende vereenvoudigingen

- Kwartiergrenzen worden berekend op hele-uur-tijdzones (klopt voor NL/BE).
- Eén los hold-kwartier tussen twee gelijke laad- of ontlaadkwartieren wordt als solver-artefact gladgestreken. Het vermogen blijft dat van het kwartier zelf.
- Curtailment, EV en warmtepomp zitten niet in deze flow.

## Credits

Architectuur, ontwerpkeuzes en alle metingen aan de Deye zijn van mij (Yaldair). De code en documentatie heb ik samen met Claude (Anthropic) uitgewerkt.

Op mijn eigen installatie draait een uitgebreidere flow die ook YamBMS gebruikt. De flows in deze repository heeft Claude op basis daarvan gemaakt, om ze universeler en deelbaar te maken. De registermetingen in dit document komen van mijn eigen installatie.
