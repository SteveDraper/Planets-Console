"""Game-level entity dataclasses (GameSettings, Game, GameInfo, TurnInfo)."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.models.comms import Message, Note, Vcr
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.enums import GameStatus
from api.models.planet import Planet
from api.models.player import Advantage, Badge, Player, Race, Relation, Score
from api.models.ship import Ship
from api.models.space import (
    Artifact,
    Blackhole,
    Cutscene,
    IonStorm,
    Minefield,
    Nebula,
    Star,
    Wormhole,
)
from api.models.starbase import Starbase, StockItem


@dataclass
class GameSettings:
    id: int
    name: str
    turn: int
    buildqueueplanetid: int
    victorycountdown: int
    maxallies: int
    maxshareintel: int
    maxsafepassage: int
    alliessharefullinfo: bool
    mapwidth: int
    mapheight: int
    numplanets: int
    shiplimit: int
    hoststart: str
    hostcompleted: str
    nexthost: str
    lastinvite: str
    teamsize: int
    planetscanrange: int
    shipscanrange: int
    allvisible: bool
    minefieldsvisible: bool
    allplanetsvisible: bool
    planetownershipvisible: bool
    starbasesvisible: bool
    shipsatplanetsvisible: bool
    noreducedpodscanrange: bool
    allnormalscannedshipsvisible: bool
    oneseesshipallseeship: bool
    spectatormode: bool
    allshareintel: bool
    nebulas: int
    stars: int
    neutrinostars: int
    blackholes: int
    maxwormholes: int
    wormholemix: int
    wormholescanrange: int
    discussionid: str
    nuionstorms: bool
    maxions: int
    maxioncloudsperstorm: int
    debrisdiskpercent: int
    debrisdiskversion: int
    cloakfail: int
    structuredecayrate: int
    mapshape: int
    verycloseplanets: int
    closeplanets: int
    nextplanets: int
    otherplanetsminhomeworlddist: int
    ncircles: int
    hwdistribution: int
    ndebrisdiscs: int
    balanceadjustment: int
    closeplanetrangeinc: int
    levelid: int
    nextlevelid: int
    storyid: int
    killrace: bool
    runningstart: int
    deadradius: int
    playerselectrace: bool
    militaryscorepercent: int
    hideraceselection: bool
    hideplayerselection: bool
    fixedstartpositions: bool
    shuffleteampositions: bool
    interestsignup: bool
    interestsignupracecount: int
    minnativeclans: int
    maxnativeclans: int
    nohomeworld: bool
    homeworldhasstarbase: bool
    homeworldclans: int
    homeworldresources: int
    hwlosthappinesslosscolonists: int
    hwlosthappinesslossnatives: int
    gamepassword: str
    extraplanets: int
    extraships: int
    centerextraplanets: int
    centerextraships: int
    extraplanetsrandomloc: bool
    extrashipsrandomloc: bool
    wanderingtribescount: int
    wanderingtribesdist: int
    neutroniumlevel: float
    duraniumlevel: float
    tritaniumlevel: float
    molybdenumlevel: float
    averagedensitypercent: int
    developmentfactor: int
    nativeprobability: int
    nativegovernmentlevel: int
    neusurfacemax: int
    dursurfacemax: int
    trisurfacemax: int
    molsurfacemax: int
    neugroundmax: int
    durgroundmax: int
    trigroundmax: int
    molgroundmax: int
    planetlevelmax: int
    computerbuildships: bool
    computerbuilddelay: int
    computerreplacedrops: bool
    bringhomesectorships: bool
    homesectorshipvaluemin: int
    homesectorshipvaluemax: int
    entryportalplayers: str
    reinforcementsallowed: bool
    fightorfail: int
    fofactiveturn: int
    fofincrement: int
    fofaccelrate: int
    fofaccelstartturn: int
    fofaccelstartdate: str
    fofbyteam: bool
    meteorshowerchance: int
    computerplayerrangelimitation: int
    stealthmode: bool
    sphere: bool
    showallexplosions: bool
    highidfixchunnelusepodhullid: bool
    highidfixfightertransferoffset: int
    nochunnelhives: bool
    mining200adjustment: int
    freestarbasefighters5adjustment: int
    cyborgmaxnativetaxrateadjustment: int
    assimilationrateadjustment: int
    maxhissersperplanet: int
    chunnelstabilizationeverywhere: bool
    groundattackadjustments: str
    colonisttaxrateadjustments: str
    nativetaxrateadjustments: str
    campaignmode: bool
    maxadvantage: int
    fascistdoublebeams: bool
    starbasefightertransfer: bool
    superspyadvanced: bool
    cloakandintercept: bool
    quantumtorpedos: bool
    galacticpower: bool
    hardenedmines: bool
    racehullsonlyfascistdoublebeams: bool
    racehullsonlycloakandintercept: bool
    racehullsonlyhiss: bool
    repairshipreplacessagefrigate: bool
    migtransportreplacesmigscout: bool
    saurianlightfrigatereplacessaurian: bool
    scorpiuscarrierreplacesscorpiuslight: bool
    sscruiseriireplacessscruiser: bool
    sscarrierplusreplacessscarrier: bool
    skyfireplusreplacesskyfire: bool
    d7creplacesd7a: bool
    quietusplusreplacesquietus: bool
    cybernautlightreplacescybernaut: bool
    birdshaveenlighten: bool
    sscruiserinterceptinterference: bool
    moscowinterceptinterference: bool
    sapphirenowebimmunity: bool
    destroyplanetcausesfear: bool
    quantumtorpedomissrateforgravitonics: int
    torpedomissrateforsinglegunboats: int
    elusivefighterdefense: int
    fedfrigatefighterdefense: int
    scoutsplanetimmunity: bool
    hrossfightertransfer: bool
    empirehasaggregator: bool
    fighterfactoryshipset: int
    ironslavescoutreplacesironslave: bool
    diplomaticspiesnoambassador: bool
    simplestealtharmordist: int
    simplestealtharmorsensorswwepdist: int
    torpedoset: int
    shiplimittype: int
    plsminships: int
    plsextraships: int
    plsshipsperplanet: int
    productionqueue: bool
    productionbasecost: int
    productionstarbaseoutput: int
    productionstarbasereward: int
    productionsmallshipset: int
    planetaryproductionqueue: bool
    fcodesrbx: bool
    ppqminbuilds: int
    endturn: int
    alwaysuseendturn: bool
    maxplayersperrace: int
    nowebfriendlycodes: bool
    nowebsinotherids: bool
    webdiplomacylevel: int
    webdraindiplomacylevel: int
    crystalwebimmunity: int
    fcodesmustmatchgsx: bool
    fcodesextraalchemy: bool
    fcodesbdx: bool
    fcodesnogsx: bool
    fcodesnomix: bool
    cloningenabled: bool
    supertransportfuelmod: int
    unlimitedfuel: bool
    unlimitedammo: bool
    nominefields: bool
    nosupplies: bool
    nowarpwells: bool
    directtransfermc: bool
    directtransferammo: bool
    transferoverloadprioritizeammo: bool
    topadvancecount: int
    snapgridsize: int
    dumppartsdumpstorps: bool
    burrowsimprovemining: bool
    horwaspfighterlossclankill: int
    hivesdetectlife: bool
    sensorsweepcombatpodscanrange: int
    sensorsweepnoncombatpodscanrange: int
    horwaspscanrobotmodifier: float
    isacademy: bool
    acceleratedturns: int
    disallowedraces: str
    emorkslegacy: bool
    combatrng: int
    chainedintercept: bool
    randomplayerslots: bool
    presethulls: bool
    presethullsbyrace: str
    presetadvantages: bool
    orderedgroupjoindays: int
    joininggroupindex: int
    aicanchangediplomacy: bool
    defensepostsblocksensorsweep: bool
    victoryscorepointsneededsolo: int
    victoryscorepointsneededally: int
    victoryscorepointsperplanet: int
    victoryscorepointsperstarbase: int
    victoryscorepointsperhighpop: int
    victoryscoreclansforhighpop: int
    victoryscorepointsperbonus: int
    victoryscorebonusdetails: bool


@dataclass
class Game:
    id: int
    name: str
    description: str
    shortdescription: str
    status: GameStatus
    datecreated: str
    dateended: str
    maptype: int
    gametype: int
    wincondition: int
    difficulty: float
    tutorialid: int
    requiredlevelid: int
    maxlevelid: int
    masterplanetid: int
    quadrant: int
    mintenacity: int
    faststart: int
    turnsperweek: int
    yearstarted: int
    isprivate: bool
    scenarioid: int
    createdby: str
    turn: int
    slots: int
    turnstatus: str
    hostdays: str
    slowhostdays: str
    hosttime: str
    lastbackuppath: str
    nexthost: str
    allturnsin: bool
    lastnotified: bool
    ishosting: bool
    lastloadeddate: str
    deletedate: str
    lasthostdate: str
    password: str
    groups: str
    leagueseason: int
    leaguetier: int
    leaguegametype: int
    haspassword: bool
    statusname: str
    justended: bool
    iscustom: bool
    timetohostshort: str
    timetohost: str


@dataclass
class GameInfo:
    game: Game
    players: list[Player]
    relations: list[Relation]
    settings: GameSettings
    schedule: str
    timetohost: str
    wincondition: str
    yearfrom: int
    yearto: int


@dataclass
class TurnInfo:
    settings: GameSettings
    game: Game
    player: Player
    players: list[Player]
    scores: list[Score]
    maps: list[str]
    planets: list[Planet]
    ships: list[Ship]
    ionstorms: list[IonStorm]
    nebulas: list[Nebula]
    stars: list[Star]
    starbases: list[Starbase]
    stock: list[StockItem]
    minefields: list[Minefield]
    relations: list[Relation]
    messages: list[Message]
    mymessages: list[Message]
    notes: list[Note]
    vcrs: list[Vcr]
    races: list[Race]
    hulls: list[Hull]
    racehulls: list[int]
    beams: list[Beam]
    engines: list[Engine]
    torpedos: list[Torpedo]
    advantages: list[Advantage]
    activebadges: list[Badge]
    badgechange: bool
    blackholes: list[Blackhole] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    wormholes: list[Wormhole] = field(default_factory=list)
    cutscenes: list[Cutscene] = field(default_factory=list)
