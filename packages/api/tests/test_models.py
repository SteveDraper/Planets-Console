"""Tests for entity dataclass models and enum types."""
import pytest

from api.models.enums import GameStatus, MessageType, NativeType
from api.models.comms import Message, Note, Vcr, VcrSide
from api.models.components import Beam, Engine, Hull, Torpedo
from api.models.game import Game, GameInfo, GameSettings, TurnInfo
from api.models.planet import Planet
from api.models.player import Advantage, Badge, Player, Race, Relation, Score
from api.models.ship import Ship, ShipHistory
from api.models.space import Blackhole, Cutscene, IonStorm, Minefield, Nebula, Star, Wormhole, Artifact
from api.models.starbase import Starbase, StockItem


class TestEnums:
    def test_message_type_members(self):
        assert MessageType.SHIP == 1
        assert MessageType.DISTRESS == 21
        assert MessageType.UNKNOWN == -1

    def test_native_type_members(self):
        assert NativeType.NONE == 0
        assert NativeType.BOVINOID == 2
        assert NativeType.HORWASP == 11
        assert NativeType.UNKNOWN == -1

    def test_game_status_members(self):
        assert GameStatus.JOINING == 0
        assert GameStatus.RUNNING == 1
        assert GameStatus.FINISHED == 3
        assert GameStatus.UNKNOWN == -1

    def test_enum_from_value(self):
        assert MessageType(8) is MessageType.COMBAT
        assert NativeType(5) is NativeType.AMORPHOUS
        assert GameStatus(2) is GameStatus.PAUSED

    def test_unknown_enum_value_raises(self):
        """Direct IntEnum construction still raises for unknown values."""
        with pytest.raises(ValueError):
            MessageType(99)


class TestPlayerModels:
    def test_player_instantiation(self):
        p = Player(
            id=1, status=1, statusturn=1, accountid=100, username="test",
            email="", raceid=3, teamid=0, prioritypoints=10, joinrank=0,
            finishrank=0, turnjoined=1, turnready=False, turnreadydate="",
            turnstatus=0, turnsmissed=0, turnsmissedtotal=0, turnsholiday=0,
            turnsearly=0, turn=1, timcontinuum=0, savekey="", tutorialid=0,
            tutorialtaskid=0, megacredits=0, duranium=0, tritanium=0,
            molybdenum=0, leagueteamid=0, activehulls="1,2,3",
            activeadvantages="", activeengines="", activebeams="", activetorps="",
        )
        assert p.username == "test"
        assert p.raceid == 3

    def test_score_instantiation(self):
        s = Score(
            id=1, dateadded="1/1/2025", ownerid=1, accountid=1,
            capitalships=10, freighters=5, planets=20, starbases=3,
            militaryscore=1000, inventoryscore=500, prioritypoints=50,
            turn=10, percent=25.0, victoryscore=0, victorybonuses="",
            technologicalaccumulator=0, widestreach=0, greatestwarrior=0,
            happybeings=0, shipchange=0, freighterchange=0, planetchange=0,
            starbasechange=0, militarychange=0, inventorychange=0,
            prioritypointchange=0, percentchange=0.0, victoryscorechange=0,
        )
        assert s.planets == 20
        assert s.percent == 25.0

    def test_relation_instantiation(self):
        r = Relation(id=1, playerid=1, playertoid=2, relationto=1, relationfrom=0, conflictlevel=0, color="")
        assert r.playerid == 1

    def test_badge_instantiation(self):
        b = Badge(
            id=1, raceid=1, badgelevel=1, badgetype=1, forrank=3, endturn=20,
            achievement=5, dur=5, tri=5, mol=5, mc=10, planets=10, ships=10,
            starbases=1, military=0, battleswon=0, name="Explorer",
            description="desc", completed=True,
        )
        assert b.completed is True

    def test_race_instantiation(self):
        r = Race(id=1, name="Federation", shortname="Fed", adjective="Federal",
                 baseadvantages="", advantages="", basehulls="", hulls="")
        assert r.shortname == "Fed"


class TestSpaceModels:
    def test_ion_storm(self):
        s = IonStorm(id=1, x=100, y=200, radius=50, voltage=120, warp=5, heading=180, isgrowing=True, parentid=0)
        assert s.voltage == 120

    def test_minefield(self):
        m = Minefield(id=1, ownerid=2, isweb=False, ishidden=False, units=100,
                      infoturn=10, friendlycode="???", x=100, y=200, radius=30)
        assert m.isweb is False

    def test_nebula(self):
        n = Nebula(id=1, x=50, y=60)
        assert n.x == 50

    def test_star(self):
        s = Star(id=1, name="Sol", x=100, y=200, temp=5000, radius=10, mass=1000, planets=3)
        assert s.planets == 3

    def test_stub_entities(self):
        assert Blackhole(id=1, x=0, y=0).id == 1
        assert Wormhole(id=1, x=0, y=0).id == 1
        assert Artifact(id=1).id == 1
        assert Cutscene(id=1).id == 1


class TestShipModels:
    def test_ship_history(self):
        h = ShipHistory(x=100, y=200)
        assert h.x == 100

    def test_ship_with_history(self):
        s = Ship(
            id=1, friendlycode="abc", name="Test", warp=9, x=100, y=200,
            beams=4, bays=0, torps=2, mission=1, mission1target=0,
            mission2target=0, enemy=0, damage=0, crew=100, clans=0,
            neutronium=50, tritanium=0, duranium=0, molybdenum=0, supplies=0,
            ammo=10, megacredits=0, transferclans=0, transferneutronium=0,
            transferduranium=0, transfertritanium=0, transfermolybdenum=0,
            transfersupplies=0, transferammo=0, transfermegacredits=0,
            transfertargetid=0, transfertargettype=0, targetx=100, targety=200,
            mass=300, heading=90, turn=5, turnkilled=0, beamid=5, engineid=7,
            hullid=10, ownerid=1, torpedoid=3, experience=0, infoturn=5,
            podhullid=0, podcargo=0, goal=0, goaltarget=0, goaltarget2=0,
            history=[ShipHistory(x=100, y=200), ShipHistory(x=110, y=210)],
        )
        assert len(s.history) == 2
        assert s.history[1].y == 210


class TestComponentModels:
    def test_hull(self):
        h = Hull(
            id=1, name="Scout", tritanium=40, duranium=20, molybdenum=5,
            fueltank=260, crew=180, engines=1, mass=75, techlevel=1, cargo=40,
            fighterbays=0, launchers=0, beams=1, cancloak=False, cost=50,
            special="", description="", advantage=0, isbase=True,
            dur=0, tri=0, mol=0, mc=0, parentid=0, academy=True,
        )
        assert h.name == "Scout"

    def test_beam(self):
        b = Beam(id=1, name="Laser", cost=1, tritanium=1, duranium=0,
                 molybdenum=0, mass=1, techlevel=1, crewkill=10, damage=3)
        assert b.damage == 3

    def test_engine(self):
        e = Engine(id=1, name="StarDrive 1", cost=1, tritanium=5, duranium=1,
                   molybdenum=0, techlevel=1, warp1=100, warp2=800, warp3=2700,
                   warp4=6400, warp5=12500, warp6=21600, warp7=34300, warp8=51200,
                   warp9=72900)
        assert e.warp9 == 72900

    def test_torpedo(self):
        t = Torpedo(id=1, fullid=1, name="Mark 1", torpedocost=1, launchercost=1,
                    tritanium=1, duranium=1, molybdenum=0, mass=2, techlevel=1,
                    crewkill=4, damage=5, combatrange=300)
        assert t.combatrange == 300


class TestCommsModels:
    def test_message(self):
        m = Message(id=1, ownerid=1, messagetype=MessageType.COMBAT,
                    headline="Battle", body="A battle occurred", target=0,
                    turn=5, x=100, y=200)
        assert m.messagetype == MessageType.COMBAT

    def test_note(self):
        n = Note(id=1, ownerid=1, body="hello", targetid=5, targettype=0, color="110")
        assert n.body == "hello"

    def test_vcr_side(self):
        vs = VcrSide(
            id=1, vcrid=1, objectid=10, name="Ship A", side=0,
            beamcount=4, launchercount=2, baycount=0, hullid=5, beamid=3,
            torpedoid=2, shield=100, damage=0, crew=200, mass=500, raceid=1,
            beamkillbonus=1, beamchargerate=1, torpchargerate=1,
            torpmisspercent=35, crewdefensepercent=0, torpedos=20, fighters=0,
            temperature=0, hasstarbase=False,
        )
        assert vs.objectid == 10

    def test_vcr(self):
        left = VcrSide(
            id=1, vcrid=1, objectid=10, name="L", side=0,
            beamcount=0, launchercount=0, baycount=0, hullid=1, beamid=0,
            torpedoid=0, shield=100, damage=0, crew=100, mass=100, raceid=1,
            beamkillbonus=0, beamchargerate=0, torpchargerate=0,
            torpmisspercent=0, crewdefensepercent=0, torpedos=0, fighters=0,
            temperature=0, hasstarbase=False,
        )
        right = VcrSide(
            id=2, vcrid=1, objectid=20, name="R", side=1,
            beamcount=0, launchercount=0, baycount=0, hullid=2, beamid=0,
            torpedoid=0, shield=100, damage=0, crew=100, mass=100, raceid=2,
            beamkillbonus=0, beamchargerate=0, torpchargerate=0,
            torpmisspercent=0, crewdefensepercent=0, torpedos=0, fighters=0,
            temperature=0, hasstarbase=False,
        )
        v = Vcr(id=1, seed=42, x=100, y=200, battletype=0,
                leftownerid=1, rightownerid=2, turn=5, left=left, right=right)
        assert v.left.name == "L"
        assert v.right.side == 1
