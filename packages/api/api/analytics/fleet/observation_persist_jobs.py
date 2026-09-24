"""Time fleet observation_leg + persist of a synthetic 683364-sized ledger."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from api.analytics.export_context import make_analytic_query_context
from api.analytics.fleet.compute_orchestration import FleetPersistencePolicy
from api.analytics.fleet.compute_plane.observation_leg import run_fleet_observation_leg
from api.analytics.fleet.compute_services import FleetComputeServices
from api.analytics.fleet.constants import ANALYTIC_ID
from api.analytics.fleet.persistence import FleetSnapshotPersistenceService
from api.analytics.fleet.scoreboard_slice import fleet_scoreboard_slice_to_json
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.options import TurnAnalyticsOptions
from api.compute.scope import ComputeScope
from api.serialization.turn import turn_info_from_json
from api.storage.base import JSONValue, StorageBackend
from api.storage.file_json_jobs import (
    PROBE_FLEET_KEY,
    PROBE_GAME_ID,
    PROBE_PERSPECTIVE,
    PROBE_TURN_KEY,
    PROBE_TURN_NUMBER,
    json_node_count,
    synthetic_large_fleet_document,
)

# Freeze-safe RST: compact turn_sample clone (player 1, turn 111). Not an operator dump.
_PROBE_TURN_JSON = r"""{"planets":[],"ships":[],"ionstorms":[],"nebulas":[],"stars":[],"blackholes":[],"artifacts":[],"wormholes":[],"starbases":[],"stock":[],"minefields":[],"relations":[],"messages":[],"mymessages":[],"cutscenes":[],"notes":[],"vcrs":[],"races":[],"hulls":[],"racehulls":[],"beams":[],"engines":[],"torpedos":[],"advantages":[],"activebadges":[],"settings":{"name":"Serada 9 Sector","turn":111,"buildqueueplanetid":0,"victorycountdown":6,"maxallies":1,"maxshareintel":2,"maxsafepassage":3,"alliessharefullinfo":false,"mapwidth":2150,"mapheight":2150,"numplanets":500,"shiplimit":500,"hoststart":"6/23/2025 2:51:28 PM","hostcompleted":"6/23/2025 2:53:27 PM","nexthost":"1/1/0001 12:00:00 AM","lastinvite":"1/1/0001 12:00:00 AM","teamsize":1,"planetscanrange":10000,"shipscanrange":300,"allvisible":false,"minefieldsvisible":false,"allplanetsvisible":false,"planetownershipvisible":false,"starbasesvisible":false,"shipsatplanetsvisible":false,"noreducedpodscanrange":false,"allnormalscannedshipsvisible":false,"oneseesshipallseeship":false,"spectatormode":false,"allshareintel":false,"nebulas":0,"stars":4,"neutrinostars":0,"blackholes":0,"maxwormholes":0,"wormholemix":80,"wormholescanrange":100,"discussionid":"","nuionstorms":true,"maxions":4,"maxioncloudsperstorm":10,"debrisdiskpercent":50,"debrisdiskversion":2,"cloakfail":0,"structuredecayrate":3,"mapshape":0,"verycloseplanets":3,"closeplanets":10,"nextplanets":0,"otherplanetsminhomeworlddist":155,"ncircles":5,"hwdistribution":2,"ndebrisdiscs":1,"balanceadjustment":0,"closeplanetrangeinc":0,"levelid":0,"nextlevelid":0,"storyid":0,"killrace":false,"runningstart":0,"deadradius":81,"playerselectrace":false,"militaryscorepercent":65,"hideraceselection":false,"hideplayerselection":false,"fixedstartpositions":false,"shuffleteampositions":false,"interestsignup":false,"interestsignupracecount":0,"minnativeclans":20,"maxnativeclans":90000,"nohomeworld":false,"homeworldhasstarbase":true,"homeworldclans":25000,"homeworldresources":3,"hwlosthappinesslosscolonists":70,"hwlosthappinesslossnatives":20,"gamepassword":"","extraplanets":0,"extraships":0,"centerextraplanets":0,"centerextraships":0,"extraplanetsrandomloc":false,"extrashipsrandomloc":false,"wanderingtribescount":0,"wanderingtribesdist":0,"neutroniumlevel":2.24,"duraniumlevel":1.29,"tritaniumlevel":1.59,"molybdenumlevel":1.16,"averagedensitypercent":55,"developmentfactor":1,"nativeprobability":50,"nativegovernmentlevel":2,"neusurfacemax":250,"dursurfacemax":40,"trisurfacemax":50,"molsurfacemax":25,"neugroundmax":700,"durgroundmax":500,"trigroundmax":500,"molgroundmax":200,"planetlevelmax":0,"computerbuildships":true,"computerbuilddelay":0,"computerreplacedrops":false,"bringhomesectorships":false,"homesectorshipvaluemin":0,"homesectorshipvaluemax":0,"entryportalplayers":"","reinforcementsallowed":false,"fightorfail":22,"fofactiveturn":0,"fofincrement":5,"fofaccelrate":0,"fofaccelstartturn":0,"fofaccelstartdate":"1/1/0001 12:00:00 AM","fofbyteam":false,"meteorshowerchance":1,"computerplayerrangelimitation":0,"stealthmode":false,"sphere":false,"showallexplosions":true,"highidfixchunnelusepodhullid":false,"highidfixfightertransferoffset":0,"nochunnelhives":true,"mining200adjustment":0,"freestarbasefighters5adjustment":0,"cyborgmaxnativetaxrateadjustment":0,"assimilationrateadjustment":0,"maxhissersperplanet":0,"chunnelstabilizationeverywhere":false,"groundattackadjustments":"","colonisttaxrateadjustments":"","nativetaxrateadjustments":"","campaignmode":false,"maxadvantage":500,"fascistdoublebeams":true,"starbasefightertransfer":true,"superspyadvanced":true,"cloakandintercept":true,"quantumtorpedos":true,"galacticpower":true,"hardenedmines":false,"racehullsonlyfascistdoublebeams":true,"racehullsonlycloakandintercept":true,"racehullsonlyhiss":true,"repairshipreplacessagefrigate":true,"migtransportreplacesmigscout":false,"saurianlightfrigatereplacessaurian":false,"scorpiuscarrierreplacesscorpiuslight":false,"sscruiseriireplacessscruiser":false,"sscarrierplusreplacessscarrier":false,"skyfireplusreplacesskyfire":false,"d7creplacesd7a":false,"quietusplusreplacesquietus":false,"cybernautlightreplacescybernaut":false,"birdshaveenlighten":true,"sscruiserinterceptinterference":true,"moscowinterceptinterference":false,"sapphirenowebimmunity":true,"destroyplanetcausesfear":true,"quantumtorpedomissrateforgravitonics":90,"torpedomissrateforsinglegunboats":0,"elusivefighterdefense":0,"fedfrigatefighterdefense":0,"scoutsplanetimmunity":false,"hrossfightertransfer":false,"empirehasaggregator":false,"fighterfactoryshipset":0,"ironslavescoutreplacesironslave":false,"diplomaticspiesnoambassador":false,"simplestealtharmordist":0,"simplestealtharmorsensorswwepdist":0,"torpedoset":0,"shiplimittype":0,"plsminships":0,"plsextraships":0,"plsshipsperplanet":1,"productionqueue":true,"productionbasecost":1,"productionstarbaseoutput":2,"productionstarbasereward":2,"productionsmallshipset":1,"planetaryproductionqueue":true,"fcodesrbx":true,"ppqminbuilds":10,"endturn":100,"alwaysuseendturn":false,"maxplayersperrace":10,"nowebfriendlycodes":true,"nowebsinotherids":true,"webdiplomacylevel":4,"webdraindiplomacylevel":0,"crystalwebimmunity":2,"fcodesmustmatchgsx":false,"fcodesextraalchemy":false,"fcodesbdx":false,"fcodesnogsx":false,"fcodesnomix":false,"cloningenabled":true,"supertransportfuelmod":70,"unlimitedfuel":false,"unlimitedammo":false,"nominefields":false,"nosupplies":false,"nowarpwells":false,"directtransfermc":true,"directtransferammo":true,"transferoverloadprioritizeammo":true,"topadvancecount":1,"snapgridsize":0,"dumppartsdumpstorps":false,"burrowsimprovemining":true,"horwaspfighterlossclankill":2,"hivesdetectlife":true,"sensorsweepcombatpodscanrange":60,"sensorsweepnoncombatpodscanrange":30,"horwaspscanrobotmodifier":0.5,"isacademy":false,"acceleratedturns":3,"disallowedraces":"","emorkslegacy":false,"combatrng":0,"chainedintercept":true,"randomplayerslots":false,"presethulls":false,"presethullsbyrace":"","presetadvantages":false,"orderedgroupjoindays":0,"joininggroupindex":0,"aicanchangediplomacy":false,"defensepostsblocksensorsweep":true,"victoryscorepointsneededsolo":0,"victoryscorepointsneededally":0,"victoryscorepointsperplanet":0,"victoryscorepointsperstarbase":0,"victoryscorepointsperhighpop":0,"victoryscoreclansforhighpop":0,"victoryscorepointsperbonus":0,"victoryscorebonusdetails":false,"id":0},"game":{"name":"Serada 9 Sector","description":"This is a battle for the Serada 9 Sector. The battle will be won when one commander captures 200 planets, or an alliance of two commanders capture 250 planets and hold them for 5 consecutive turns. This battle will run every day for 15 turns and then will drop to 3 turns per week.<br/><br/>Fight or Fail! You must control at least the number of planets shown to stay alive in this game. The Fight or Fail limit will increase every 5 Turns.<br/><br/>Accelerated Start! You can play your first 3 turns immediately, without having to wait for other players.<br/><br/>[2024 Standard Rules]","shortdescription":"Epic","status":3,"datecreated":"10/26/2024 9:02:31 AM","dateended":"6/23/2025 2:53:43 PM","maptype":2,"gametype":2,"wincondition":1,"difficulty":1.19047332832457,"tutorialid":0,"requiredlevelid":3,"maxlevelid":0,"masterplanetid":163,"quadrant":0,"mintenacity":80,"faststart":15,"turnsperweek":3,"yearstarted":166,"isprivate":false,"scenarioid":0,"createdby":"none","turn":111,"slots":11,"turnstatus":"x___xxx_xx_","hostdays":"__T_T_S","slowhostdays":"","hosttime":"22:21","lastbackuppath":"d:\\planetsdata\\backups\\game628580\\turn110-638862870869578167.zip","nexthost":"6/24/2025 10:21:00 PM","allturnsin":false,"lastnotified":true,"ishosting":false,"lastloadeddate":"3/16/2026 11:49:49 PM","deletedate":"","lasthostdate":"6/21/2025 3:33:31 PM","password":"","groups":"","leagueseason":0,"leaguetier":0,"leaguegametype":0,"haspassword":false,"statusname":"Finished","justended":false,"iscustom":false,"timetohostshort":"Finished","timetohost":"Finished","id":628580},"player":{"status":1,"statusturn":1,"accountid":22825,"username":"probe","email":"","raceid":8,"teamid":0,"prioritypoints":217,"joinrank":0,"finishrank":1,"turnjoined":1,"turnready":false,"turnreadydate":"6/21/2025 9:31:35 PM","turnstatus":1,"turnsmissed":0,"turnsmissedtotal":0,"turnsholiday":0,"turnsearly":25,"turn":3,"timcontinuum":0,"savekey":"","tutorialid":0,"tutorialtaskid":0,"megacredits":0,"duranium":0,"tritanium":0,"molybdenum":0,"leagueteamid":0,"id":1,"activehulls":"14,15,16,17,18,68,69,70,71,72,73,74,75,76,77,104,105","activeadvantages":"22,23,46,48,49,51,57,77","activeengines":"","activebeams":"","activetorps":""},"players":[{"status":1,"statusturn":1,"accountid":22825,"username":"probe","email":"","raceid":8,"teamid":0,"prioritypoints":217,"joinrank":0,"finishrank":1,"turnjoined":1,"turnready":false,"turnreadydate":"6/21/2025 9:31:35 PM","turnstatus":1,"turnsmissed":0,"turnsmissedtotal":0,"turnsholiday":0,"turnsearly":25,"turn":3,"timcontinuum":0,"savekey":"","tutorialid":0,"tutorialtaskid":0,"megacredits":0,"duranium":0,"tritanium":0,"molybdenum":0,"leagueteamid":0,"id":1,"activehulls":"14,15,16,17,18,68,69,70,71,72,73,74,75,76,77,104,105","activeadvantages":"22,23,46,48,49,51,57,77","activeengines":"","activebeams":"","activetorps":""}],"scores":[{"dateadded":"6/23/2025 2:52:44 PM","ownerid":1,"accountid":22825,"capitalships":130,"freighters":26,"planets":171,"starbases":121,"militaryscore":2509092,"inventoryscore":17556,"prioritypoints":217,"turn":111,"percent":45.92,"victoryscore":0,"victorybonuses":"","technologicalaccumulator":0,"widestreach":0,"greatestwarrior":0,"happybeings":0,"id":1218,"shipchange":1,"freighterchange":0,"planetchange":-4,"starbasechange":-2,"militarychange":-53869,"inventorychange":-270,"prioritypointchange":54,"percentchange":-0.0799999999999983,"victoryscorechange":0}],"maps":[],"badgechange":false}"""  # noqa: E501


@dataclass(frozen=True)
class ObservationPersistTiming:
    """Walls for one observation_leg plus FleetPersistencePolicy.persist."""

    encoded_bytes: int
    node_count: int
    player_count: int
    record_count: int
    observation_leg_seconds: float
    persist_seconds: float
    total_seconds: float

    def to_probe_json(self) -> dict[str, int | float]:
        """Wire object for ``--console-package-probe`` (uv vs frozen comparison)."""
        return {
            "encodedBytes": self.encoded_bytes,
            "nodeCount": self.node_count,
            "playerCount": self.player_count,
            "recordCount": self.record_count,
            "observationLegSeconds": self.observation_leg_seconds,
            "persistSeconds": self.persist_seconds,
            "totalSeconds": self.total_seconds,
        }


def time_observation_persist_jobs(
    storage: StorageBackend,
    *,
    document: dict[str, JSONValue] | None = None,
) -> ObservationPersistTiming:
    """Run observation_leg then persist against a synthetic fleet document.

    Seeds the tmp file store with ``document`` (default
    ``synthetic_large_fleet_document``), times ``run_fleet_observation_leg``
    for player 1, then ``FleetPersistencePolicy.persist`` (the pool persist
    hook). Does not use the OS console data directory.
    """
    payload = document if document is not None else synthetic_large_fleet_document()
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ledgers = payload.get("ledgers")
    if not isinstance(ledgers, dict) or not ledgers:
        raise ValueError("synthetic fleet document must contain ledgers")
    player_one = ledgers.get("1")
    if not isinstance(player_one, dict):
        raise ValueError("synthetic fleet document must include player 1")
    prior = persisted_fleet_ledger_from_json(player_one)
    record_count = len(prior.ledger.records)

    turn = turn_info_from_json(json.loads(_PROBE_TURN_JSON))
    if turn.settings.turn != PROBE_TURN_NUMBER:
        raise RuntimeError(f"probe turn must be {PROBE_TURN_NUMBER}, got {turn.settings.turn}")
    job_wire: dict[str, Any] = {
        "gameId": PROBE_GAME_ID,
        "perspective": PROBE_PERSPECTIVE,
        "playerId": 1,
        "materializeTurn": PROBE_TURN_NUMBER,
        "turnWire": fleet_scoreboard_slice_to_json(turn),
        "priorLedgerWire": player_one,
        "baselineLedgerWire": player_one["ledger"],
        "provenanceWire": {
            "turnEvidenceAtN": False,
            "priorLedgerAtNMinus1": True,
        },
    }

    storage.put(f"games/{PROBE_GAME_ID}/info", {"name": "probe"})
    storage.put(PROBE_TURN_KEY, {"turn": PROBE_TURN_NUMBER})
    storage.put(PROBE_FLEET_KEY, payload)

    persistence = FleetSnapshotPersistenceService(storage)

    def load_turn(turn_number: int):
        return turn if turn_number == PROBE_TURN_NUMBER else None

    ctx = make_analytic_query_context(
        turn,
        TurnAnalyticsOptions(),
        game_id=PROBE_GAME_ID,
        perspective=PROBE_PERSPECTIVE,
        load_turn=load_turn,
        export_services={
            ANALYTIC_ID: FleetComputeServices(
                persistence=persistence,
                game_id=PROBE_GAME_ID,
                perspective=PROBE_PERSPECTIVE,
                load_turn=load_turn,
            )
        },
    )
    scope = ComputeScope(
        analytic_id=ANALYTIC_ID,
        game_id=PROBE_GAME_ID,
        perspective=PROBE_PERSPECTIVE,
        turn=PROBE_TURN_NUMBER,
        player_id=1,
    )

    started = time.perf_counter()
    result = run_fleet_observation_leg(job_wire)
    observation_leg_seconds = time.perf_counter() - started
    if result.payload is None:
        raise RuntimeError("observation_leg produced no persist payload")

    persist_started = time.perf_counter()
    FleetPersistencePolicy().persist(ctx, scope, result.payload)
    persist_seconds = time.perf_counter() - persist_started

    return ObservationPersistTiming(
        encoded_bytes=len(encoded),
        node_count=json_node_count(payload),
        player_count=len(ledgers),
        record_count=record_count,
        observation_leg_seconds=observation_leg_seconds,
        persist_seconds=persist_seconds,
        total_seconds=observation_leg_seconds + persist_seconds,
    )
