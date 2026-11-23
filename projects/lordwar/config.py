"""游戏数值配置。想调平衡，改这里就行。"""

MAP_W = 48
MAP_H = 48
TICK_SECONDS = 0.5          # 服务器每 0.5 秒结算一次
MAX_BUILDING_LEVEL = 5

# 地形
PLAINS, FOREST, HILLS, GOLD, MOUNTAIN, WATER = "plains", "forest", "hills", "gold", "mountain", "water"
IMPASSABLE = {MOUNTAIN, WATER}
TERRAIN_NAMES = {
    PLAINS: "平原", FOREST: "森林", HILLS: "丘陵",
    GOLD: "金矿脉", MOUNTAIN: "高山", WATER: "湖泊",
}
# 丘陵防守加成
TERRAIN_DEFENSE = {HILLS: 1.25, FOREST: 1.1}

START_RES = {"gold": 300, "wood": 200}
BASE_INCOME = {"gold": 1.0, "wood": 1.0}   # 每 tick，主城 1 级
HQ_INCOME_PER_LEVEL = 0.5

# 拓展领地：费用 = base + per_tile * 当前领地数
EXPAND_BASE_GOLD = 20
EXPAND_PER_TILE_GOLD = 2

# 建筑：cost 为 1 级价格，升级价格 = cost * 下一级等级
BUILDINGS = {
    "hq": {
        "name": "主城", "icon": "🏰", "cost": {"gold": 200, "wood": 200},
        "terrain": None, "buildable": False,
        "desc": "核心建筑。被攻破即出局。升级提高收入和防御。",
    },
    "mine": {
        "name": "金矿场", "icon": "⛏️", "cost": {"gold": 60, "wood": 40},
        "terrain": [GOLD], "buildable": True,
        "desc": "只能建在金矿脉上。每级 +1.5 金币/tick。",
    },
    "lumber": {
        "name": "伐木场", "icon": "🪓", "cost": {"gold": 40, "wood": 20},
        "terrain": [FOREST], "buildable": True,
        "desc": "只能建在森林上。每级 +1.5 木材/tick。",
    },
    "farm": {
        "name": "集市", "icon": "🏪", "cost": {"gold": 50, "wood": 50},
        "terrain": [PLAINS], "buildable": True,
        "desc": "建在平原上。每级 +0.6 金币/tick。",
    },
    "barracks": {
        "name": "兵营", "icon": "⚔️", "cost": {"gold": 100, "wood": 80},
        "terrain": [PLAINS, HILLS], "buildable": True,
        "desc": "训练部队。Lv1 步兵，Lv2 弓箭手，Lv3 骑兵，Lv4 投石车。等级越高训练越快。",
    },
    "smithy": {
        "name": "铁匠铺", "icon": "🔨", "cost": {"gold": 120, "wood": 100},
        "terrain": [PLAINS, HILLS], "buildable": True,
        "desc": "研究武器和护甲。研究等级上限 = 铁匠铺等级。",
    },
    "tower": {
        "name": "箭塔", "icon": "🗼", "cost": {"gold": 80, "wood": 120},
        "terrain": [PLAINS, HILLS, FOREST, GOLD], "buildable": True,
        "desc": "防御建筑。守卫所在地块，视野 +3。",
    },
}

BUILDING_INCOME = {
    "mine": {"gold": 1.5},
    "lumber": {"wood": 1.5},
    "farm": {"gold": 0.6},
}
HQ_DEFENSE_PER_LEVEL = 100     # 主城自带防御力
TOWER_DEFENSE_PER_LEVEL = 80  # 箭塔自带防御力

# 兵种：单兵战力 = atk * hp / 50；speed 为每移动一格需要的 tick 数（越小越快）；time 为训练秒数
UNITS = {
    "infantry": {"name": "步兵", "icon": "🗡️", "cost": {"gold": 20, "wood": 5},
                 "atk": 10, "hp": 50, "speed": 2, "barracks": 1, "time": 2},
    "archer":   {"name": "弓箭手", "icon": "🏹", "cost": {"gold": 25, "wood": 15},
                 "atk": 16, "hp": 35, "speed": 2, "barracks": 2, "time": 3},
    "cavalry":  {"name": "骑兵", "icon": "🐎", "cost": {"gold": 50, "wood": 15},
                 "atk": 18, "hp": 80, "speed": 1, "barracks": 3, "time": 5},
    "catapult": {"name": "投石车", "icon": "🪨", "cost": {"gold": 80, "wood": 80},
                 "atk": 45, "hp": 40, "speed": 4, "barracks": 4, "time": 8,
                 "siege": 3.0},  # 攻打建筑时攻击力 x3
}

# 研究
RESEARCH = {
    "weapon": {"name": "武器锻造", "desc": "全军攻击 +15%/级", "cost": {"gold": 150, "wood": 100}},
    "armor":  {"name": "护甲锻造", "desc": "全军生命 +15%/级", "cost": {"gold": 120, "wood": 150}},
}
RESEARCH_BONUS = 0.15

# 野外 NPC
NPC_TYPES = {
    "wolves":  {"name": "狼群", "icon": "🐺", "power": 80,
                "reward": {"gold": 80, "wood": 40}, "weight": 5},
    "bandits": {"name": "土匪营地", "icon": "🏴", "power": 260,
                "reward": {"gold": 220, "wood": 120}, "weight": 3},
    "orcs":    {"name": "兽人部落", "icon": "👹", "power": 750,
                "reward": {"gold": 600, "wood": 400}, "weight": 2},
    "dragon":  {"name": "远古巨龙", "icon": "🐉", "power": 3200,
                "reward": {"gold": 2500, "wood": 1500}, "weight": 0},  # 地图中央唯一
}
NPC_TARGET_COUNT = 28
NPC_RESPAWN_TICKS = 60     # 每 30 秒尝试补充一个野怪
DRAGON_RESPAWN_TICKS = 600

# 视野
VISION_TERRITORY = 1
VISION_HQ = 4
VISION_TOWER = 3
VISION_ARMY = 2

PLAYER_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9a6324", "#800000", "#aaffc3", "#000075",
]
