"""
Molty Royale AI Bot — Data Models
Dataclasses for all game objects, parsed from API JSON responses.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Item:
    """An item (weapon, recovery, utility, currency)."""
    id: str
    name: str
    category: str  # weapon, recovery, utility, currency
    atk_bonus: int = 0
    range_: int = 0
    hp_restore: int = 0
    ep_restore: int = 0
    type_id: str = ""
    effect: str = ""
    sub_type: str = ""  # passive, consumable

    @classmethod
    def from_dict(cls, d: dict) -> "Item":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            category=d.get("category", ""),
            atk_bonus=d.get("atkBonus", 0),
            range_=d.get("range", 0),
            hp_restore=d.get("hpRestore", 0),
            ep_restore=d.get("epRestore", 0),
            type_id=d.get("typeId", ""),
            effect=d.get("effect", ""),
            sub_type=d.get("subType", ""),
        )

    @property
    def is_weapon(self) -> bool:
        return self.category == "weapon"

    @property
    def is_recovery(self) -> bool:
        return self.category == "recovery"

    @property
    def is_currency(self) -> bool:
        return self.category == "currency"

    @property
    def is_utility(self) -> bool:
        return self.category == "utility"


@dataclass
class Weapon:
    """Equipped weapon info from API."""
    id: str
    name: str
    atk_bonus: int = 0
    range_: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Optional["Weapon"]:
        if not d:
            return None
        return cls(
            id=d.get("id", ""),
            name=d.get("name", "Fist"),
            atk_bonus=d.get("atkBonus", 0),
            range_=d.get("range", 0),
        )


@dataclass
class Interactable:
    """A facility in a region."""
    id: str
    type: str  # supply_cache, medical_facility, watchtower, broadcast_station, cave
    is_used: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Interactable":
        return cls(
            id=d.get("id", ""),
            type=d.get("type", ""),
            is_used=d.get("isUsed", False),
        )


@dataclass
class Region:
    """A map region (hex tile)."""
    id: str
    name: str = ""
    terrain: str = "plains"
    weather: str = "clear"
    vision_modifier: int = 0
    is_death_zone: bool = False
    connections: list = field(default_factory=list)
    interactables: list = field(default_factory=list)
    position: Optional[dict] = None

    @classmethod
    def from_dict(cls, d) -> Optional["Region"]:
        if isinstance(d, str):
            # Sometimes connectedRegions are just string IDs
            return cls(id=d)
        if not isinstance(d, dict):
            return None
        interactables = []
        for i in d.get("interactables", []):
            if isinstance(i, dict):
                interactables.append(Interactable.from_dict(i))
        # connections can be strings or dicts
        connections = []
        for c in d.get("connections", []):
            if isinstance(c, str):
                connections.append(c)
            elif isinstance(c, dict):
                connections.append(c.get("id", ""))
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            terrain=d.get("terrain", "plains"),
            weather=d.get("weather", "clear"),
            vision_modifier=d.get("visionModifier", 0),
            is_death_zone=d.get("isDeathZone", False),
            connections=connections,
            interactables=interactables,
            position=d.get("position"),
        )

    @property
    def has_unused_facility(self) -> bool:
        return any(not i.is_used for i in self.interactables)

    def get_unused_facilities(self):
        return [i for i in self.interactables if not i.is_used]


@dataclass
class AgentSelf:
    """Our agent's full stats."""
    id: str
    name: str
    hp: int
    max_hp: int
    ep: int
    max_ep: int
    atk: int
    def_: int
    vision: int
    region_id: str
    inventory: list  # List[Item]
    equipped_weapon: Optional[Weapon]
    is_alive: bool
    kills: int

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSelf":
        inv = [Item.from_dict(i) for i in d.get("inventory", [])]
        weapon = Weapon.from_dict(d.get("equippedWeapon"))
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            hp=d.get("hp", 100),
            max_hp=d.get("maxHp", 100),
            ep=d.get("ep", 10),
            max_ep=d.get("maxEp", 10),
            atk=d.get("atk", 10),
            def_=d.get("def", 5),
            vision=d.get("vision", 1),
            region_id=d.get("regionId", ""),
            inventory=inv,
            equipped_weapon=weapon,
            is_alive=d.get("isAlive", True),
            kills=d.get("kills", 0),
        )

    @property
    def weapon_atk_bonus(self) -> int:
        return self.equipped_weapon.atk_bonus if self.equipped_weapon else 0

    @property
    def weapon_range(self) -> int:
        return self.equipped_weapon.range_ if self.equipped_weapon else 0

    @property
    def weapon_name(self) -> str:
        return self.equipped_weapon.name if self.equipped_weapon else "Fist"

    @property
    def total_atk(self) -> int:
        return self.atk + self.weapon_atk_bonus

    @property
    def inventory_weapons(self):
        return [i for i in self.inventory if i.is_weapon]

    @property
    def inventory_recovery(self):
        return [i for i in self.inventory if i.is_recovery]

    @property
    def inventory_count(self) -> int:
        return len(self.inventory)

    @property
    def inventory_full(self) -> bool:
        return self.inventory_count >= 10

    @property
    def hp_percent(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0


@dataclass
class VisibleAgent:
    """Another agent visible on the map."""
    id: str
    name: str
    hp: int
    max_hp: int
    atk: int
    def_: int
    region_id: str
    equipped_weapon: Optional[Weapon]
    is_alive: bool
    inventory: list = field(default_factory=list)  # May be partially visible

    @classmethod
    def from_dict(cls, d: dict) -> "VisibleAgent":
        weapon = Weapon.from_dict(d.get("equippedWeapon"))
        inv = [Item.from_dict(i) for i in d.get("inventory", [])]
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            hp=d.get("hp", 100),
            max_hp=d.get("maxHp", 100),
            atk=d.get("atk", 10),
            def_=d.get("def", 5),
            region_id=d.get("regionId", ""),
            equipped_weapon=weapon,
            is_alive=d.get("isAlive", True),
            inventory=inv,
        )

    @property
    def weapon_atk_bonus(self) -> int:
        return self.equipped_weapon.atk_bonus if self.equipped_weapon else 0

    @property
    def total_atk(self) -> int:
        return self.atk + self.weapon_atk_bonus

    @property
    def weapon_name(self) -> str:
        return self.equipped_weapon.name if self.equipped_weapon else "Fist"

    def get_recovery_items(self):
        """Get recovery items visible in enemy inventory."""
        return [i for i in self.inventory if i.is_recovery]

    def estimate_healing_potential(self) -> int:
        """Estimate total HP the enemy can recover from visible recovery items."""
        total = 0
        for item in self.get_recovery_items():
            if item.hp_restore > 0:
                total += item.hp_restore
            elif item.name.lower() in ("emergency food",):
                total += 20
            elif item.name.lower() in ("bandage",):
                total += 30
            elif item.name.lower() in ("medkit",):
                total += 50
        return total


@dataclass
class Monster:
    """A monster on the map."""
    id: str
    name: str
    hp: int
    atk: int
    def_: int
    region_id: str

    @classmethod
    def from_dict(cls, d: dict) -> "Monster":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            hp=d.get("hp", 5),
            atk=d.get("atk", 15),
            def_=d.get("def", 1),
            region_id=d.get("regionId", ""),
        )


@dataclass
class VisibleItem:
    """A ground item in a visible region."""
    region_id: str
    item: Item

    @classmethod
    def from_dict(cls, d: dict) -> "VisibleItem":
        return cls(
            region_id=d.get("regionId", ""),
            item=Item.from_dict(d.get("item", {})),
        )


@dataclass
class Message:
    """A chat message."""
    id: str
    sender_id: str
    sender_name: str
    type: str  # regional, private, broadcast
    content: str
    region_id: str = ""
    timestamp: str = ""
    turn: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            id=d.get("id", ""),
            sender_id=d.get("senderId", ""),
            sender_name=d.get("senderName", ""),
            type=d.get("type", "regional"),
            content=d.get("content", ""),
            region_id=d.get("regionId", ""),
            timestamp=d.get("timestamp", ""),
            turn=d.get("turn", 0),
        )


@dataclass
class PendingDeathzone:
    """A region that will become a death zone in the next expansion."""
    id: str
    name: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "PendingDeathzone":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
        )


@dataclass
class GameResult:
    """Game end result."""
    is_winner: bool = False
    rewards: int = 0
    final_rank: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Optional["GameResult"]:
        if not d:
            return None
        return cls(
            is_winner=d.get("isWinner", False),
            rewards=d.get("rewards", 0),
            final_rank=d.get("finalRank", 0),
        )


@dataclass
class GameState:
    """Complete parsed game state from GET /state API."""
    self_agent: AgentSelf
    current_region: Region
    connected_regions: list  # List[Region]
    visible_agents: list     # List[VisibleAgent]
    visible_monsters: list   # List[Monster]
    visible_items: list      # List[VisibleItem]
    visible_regions: list    # List[Region]
    pending_deathzones: list # List[PendingDeathzone]
    recent_messages: list    # List[Message]
    game_status: str         # waiting, running, finished
    result: Optional[GameResult] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "GameState":
        """Parse raw API response into GameState."""
        self_agent = AgentSelf.from_dict(data.get("self", {}))
        current_region = Region.from_dict(data.get("currentRegion", {}))

        connected = []
        for r in data.get("connectedRegions", []):
            parsed = Region.from_dict(r)
            if parsed:
                connected.append(parsed)

        visible_agents = [VisibleAgent.from_dict(a) for a in data.get("visibleAgents", [])]
        visible_monsters = [Monster.from_dict(m) for m in data.get("visibleMonsters", [])]
        visible_items = [VisibleItem.from_dict(i) for i in data.get("visibleItems", [])]

        visible_regions = []
        for r in data.get("visibleRegions", []):
            parsed = Region.from_dict(r)
            if parsed:
                visible_regions.append(parsed)

        pending_dz = [PendingDeathzone.from_dict(p) for p in data.get("pendingDeathzones", [])]
        messages = [Message.from_dict(m) for m in data.get("recentMessages", [])]
        result = GameResult.from_dict(data.get("result"))

        return cls(
            self_agent=self_agent,
            current_region=current_region,
            connected_regions=connected,
            visible_agents=visible_agents,
            visible_monsters=visible_monsters,
            visible_items=visible_items,
            visible_regions=visible_regions,
            pending_deathzones=pending_dz,
            recent_messages=messages,
            game_status=data.get("gameStatus", "waiting"),
            result=result,
        )

    # ── Convenience Queries ───────────────────────────────────────
    @property
    def is_running(self) -> bool:
        return self.game_status == "running"

    @property
    def is_finished(self) -> bool:
        return self.game_status == "finished"

    @property
    def is_alive(self) -> bool:
        return self.self_agent.is_alive

    @property
    def in_death_zone(self) -> bool:
        return self.current_region.is_death_zone

    @property
    def pending_deathzone_ids(self) -> set:
        return {p.id for p in self.pending_deathzones}

    @property
    def in_pending_death_zone(self) -> bool:
        return self.current_region.id in self.pending_deathzone_ids

    def agents_in_region(self, region_id: str = None):
        """Get visible agents in a specific region (default: current)."""
        rid = region_id or self.self_agent.region_id
        return [a for a in self.visible_agents if a.region_id == rid and a.is_alive]

    def monsters_in_region(self, region_id: str = None):
        """Get monsters in a specific region (default: current)."""
        rid = region_id or self.self_agent.region_id
        return [m for m in self.visible_monsters if m.region_id == rid]

    def items_in_region(self, region_id: str = None):
        """Get ground items in a specific region (default: current)."""
        rid = region_id or self.self_agent.region_id
        return [vi for vi in self.visible_items if vi.region_id == rid]

    def get_safe_connected_regions(self) -> list:
        """Get connected regions that are NOT death zone and NOT pending death zone."""
        unsafe_ids = self.pending_deathzone_ids
        safe = []
        for r in self.connected_regions:
            if not r.is_death_zone and r.id not in unsafe_ids:
                safe.append(r)
        return safe

    def is_region_safe(self, region_id: str) -> bool:
        """Check if a region is safe (not death zone and not pending)."""
        if region_id in self.pending_deathzone_ids:
            return False
        # Check visible/connected regions for death zone status
        for r in self.connected_regions + self.visible_regions + [self.current_region]:
            if r.id == region_id:
                return not r.is_death_zone
        return True  # If we can't see it, assume safe (but prefer known-safe)
