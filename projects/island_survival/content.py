"""荒岛求生的内容表：物品、资源、配方、建筑、作物、食物。

这里只放「有什么」，不放「怎么运行」（那是 game.py 的事）。
想加一个新东西，通常只改这个文件，再在 game.py 里补它的效果。
"""
from __future__ import annotations

from typing import Dict, Tuple

# ------------------------------------------------------------ 物品（名字）

ITEMS: Dict[str, str] = {
    # 基础材料
    "wood": "木材", "stone": "石头", "iron_ore": "铁矿石", "iron_ingot": "铁锭",
    "fiber": "纤维", "rope": "绳子", "stick": "木棍", "shell": "贝壳",
    # 食材与种子
    "coconut": "椰子", "berry": "浆果", "herb": "草本植物", "mushroom": "蘑菇",
    "raw_fish": "生鱼", "raw_meat": "生肉", "carrot": "胡萝卜", "potato": "土豆", "corn": "玉米",
    "carrot_seed": "胡萝卜种子", "potato_seed": "土豆种子", "corn_seed": "玉米种子",
    # 做好的食物
    "cooked_fish": "熟鱼", "cooked_meat": "熟肉", "roasted_corn": "烤玉米", "jam": "果酱",
    "veg_soup": "蔬菜汤", "fish_stew": "鱼汤", "skewer": "烤肉串",
    # 药
    "medicine": "草药",
    # 工具
    "stone_axe": "石斧", "stone_pick": "石镐", "hoe": "锄头", "spear": "鱼叉",
    "iron_axe": "铁斧", "iron_pick": "铁镐",
    # 武器和防具
    "wood_sword": "木剑", "iron_sword": "铁剑", "grass_armor": "草甲", "iron_armor": "铁甲",
    # 家具
    "bed": "床", "table": "桌子", "chair": "椅子", "chest": "箱子", "rug": "地毯", "lamp": "油灯",
    "fireplace": "壁炉", "bookshelf": "书架",
}

TOOLS = ("stone_axe", "stone_pick", "hoe", "spear", "iron_axe", "iron_pick")
# 武器：物品 → 攻击力；防具：物品 → 防御力。每人一个武器位、一个防具位。
WEAPONS = {"wood_sword": {"name": "木剑", "attack": 4}, "iron_sword": {"name": "铁剑", "attack": 7}}
ARMORS = {"grass_armor": {"name": "草甲", "defense": 2}, "iron_armor": {"name": "铁甲", "defense": 5}}
FURNITURE = ("bed", "table", "chair", "chest", "rug", "lamp", "fireplace", "bookshelf")
SEEDS = ("carrot_seed", "potato_seed", "corn_seed")

# 吃东西的效果：物品 → (饱食, 精神, 健康, 生病几率)
FOOD: Dict[str, Tuple[float, float, float, float]] = {
    "coconut": (12, 2, 0, 0.0),
    "berry": (10, 0, 0, 0.0),
    "mushroom": (8, 0, 0, 0.05),
    "raw_fish": (15, 0, 0, 0.15),
    "raw_meat": (20, 0, 0, 0.15),
    "carrot": (10, 0, 0, 0.0),
    "potato": (8, 0, 0, 0.0),
    "corn": (8, 0, 0, 0.0),
    "cooked_fish": (35, 3, 0, 0.0),
    "cooked_meat": (40, 3, 0, 0.0),
    "roasted_corn": (18, 0, 0, 0.0),
    "jam": (25, 0, 0, 0.0),
    "veg_soup": (40, 5, 10, 0.0),
    "fish_stew": (40, 3, 0, 0.0),
    "skewer": (45, 5, 0, 0.0),
}

# ------------------------------------------------------------ 资源点

# 资源：kind → 名字、血量（采几下）、再生秒数
RESOURCES: Dict[str, Tuple[str, int, int]] = {
    "tree": ("树", 3, 90),
    "bush": ("灌木丛", 2, 60),
    "herb": ("草本植物", 2, 60),
    "reed": ("芦苇", 2, 60),
    "rock": ("石头", 3, 240),
    "shell": ("贝壳", 1, 120),
    "mushroom": ("蘑菇", 1, 120),
}
# 有几率挡路的资源（树和石头）
BLOCKING = ("tree", "rock")

# ------------------------------------------------------------ 动物

# 动物：kind → (名字, 血量, 能待的地形编号, 速度, 会不会逃, 数量目标)
ANIMALS = {
    "rabbit": ("兔子", 2, (3, 4), 0.6, True, 70),
    "crab": ("螃蟹", 1, (2,), 0.3, False, 25),
    # 狼只在夜里出现（见 WOLF_NIGHT_COUNT），所以白天的目标数量是 0
    "wolf": ("狼", 12, (3, 4), 0.8, False, 0),
}

# 狼：夜里的威胁
WOLF_NIGHT_COUNT = 5      # 每个夜晚出现几只
WOLF_AGGRO = 8.0          # 狼看到 8 格内、在室外的玩家就追
WOLF_REACH = 1.6          # 离多近才能咬到
WOLF_SPEED = 1.8          # 追人时的速度（格/秒）
WOLF_DAMAGE = 4           # 一口咬掉多少血（防御会减少）
WOLF_BITE_INTERVAL = 2.0  # 每隔几秒咬一口

# ------------------------------------------------------------ 配方

# 配方：id → 名字、需要的材料、做出来的东西、设施（None / workbench / fire / furnace）、设施等级、只给某个角色
RECIPES: Dict[str, dict] = {
    # 随手就能做
    "stick": {"name": "木棍", "in": {"wood": 1}, "out": {"stick": 2}, "station": None, "level": 0},
    "rope": {"name": "绳子", "in": {"fiber": 3}, "out": {"rope": 1}, "station": None, "level": 0},
    "medicine": {"name": "草药", "in": {"herb": 3}, "in_other": {"herb": 6}, "out": {"medicine": 1},
                 "station": None, "level": 0, "role": "doctor"},
    # 工作台 1 级
    "stone_axe": {"name": "石斧", "in": {"stick": 2, "stone": 3, "rope": 1}, "out": {"stone_axe": 1},
                  "station": "workbench", "level": 1},
    "stone_pick": {"name": "石镐", "in": {"stick": 2, "stone": 3, "rope": 1}, "out": {"stone_pick": 1},
                   "station": "workbench", "level": 1},
    "hoe": {"name": "锄头", "in": {"stick": 2, "stone": 2, "rope": 1}, "out": {"hoe": 1},
            "station": "workbench", "level": 1},
    "spear": {"name": "鱼叉", "in": {"stick": 3, "stone": 1, "rope": 1}, "out": {"spear": 1},
              "station": "workbench", "level": 1},
    "rug": {"name": "地毯", "in": {"fiber": 6}, "out": {"rug": 1}, "station": "workbench", "level": 1},
    # 武器和防具
    "wood_sword": {"name": "木剑", "in": {"stick": 2, "wood": 3}, "out": {"wood_sword": 1},
                   "station": "workbench", "level": 1},
    "grass_armor": {"name": "草甲", "in": {"fiber": 8, "rope": 2}, "out": {"grass_armor": 1},
                    "station": "workbench", "level": 1},
    "iron_sword": {"name": "铁剑", "in": {"stick": 1, "iron_ingot": 2, "rope": 1}, "out": {"iron_sword": 1},
                   "station": "workbench", "level": 2},
    "iron_armor": {"name": "铁甲", "in": {"iron_ingot": 4, "rope": 2}, "out": {"iron_armor": 1},
                   "station": "workbench", "level": 2},
    # 工作台 2 级
    "iron_axe": {"name": "铁斧", "in": {"stick": 2, "iron_ingot": 2, "rope": 1}, "out": {"iron_axe": 1},
                 "station": "workbench", "level": 2},
    "iron_pick": {"name": "铁镐", "in": {"stick": 2, "iron_ingot": 2, "rope": 1}, "out": {"iron_pick": 1},
                  "station": "workbench", "level": 2},
    "bed": {"name": "床", "in": {"wood": 6, "fiber": 4}, "out": {"bed": 1}, "station": "workbench", "level": 2},
    "table": {"name": "桌子", "in": {"wood": 4}, "out": {"table": 1}, "station": "workbench", "level": 2},
    "chair": {"name": "椅子", "in": {"wood": 2}, "out": {"chair": 1}, "station": "workbench", "level": 2},
    "chest": {"name": "箱子", "in": {"wood": 5}, "out": {"chest": 1}, "station": "workbench", "level": 2},
    "fireplace": {"name": "壁炉", "in": {"stone": 6}, "out": {"fireplace": 1}, "station": "workbench", "level": 2},
    "bookshelf": {"name": "书架", "in": {"wood": 5}, "out": {"bookshelf": 1}, "station": "workbench", "level": 1},
    "lamp": {"name": "油灯", "in": {"stick": 2, "fiber": 2}, "out": {"lamp": 1}, "station": "workbench",
             "level": 2},
    # 石炉
    "iron_ingot": {"name": "铁锭", "in": {"iron_ore": 2}, "out": {"iron_ingot": 1}, "station": "furnace",
                   "level": 1},
    # 火堆（做饭）
    "cook_fish": {"name": "熟鱼", "in": {"raw_fish": 1}, "out": {"cooked_fish": 1}, "station": "fire", "level": 1},
    "cook_meat": {"name": "熟肉", "in": {"raw_meat": 1}, "out": {"cooked_meat": 1}, "station": "fire", "level": 1},
    "roast_corn": {"name": "烤玉米", "in": {"corn": 1}, "out": {"roasted_corn": 1}, "station": "fire", "level": 1},
    "jam": {"name": "果酱", "in": {"berry": 3}, "out": {"jam": 1}, "station": "fire", "level": 1},
    "veg_soup": {"name": "蔬菜汤", "in": {"carrot": 1, "potato": 1, "mushroom": 1}, "out": {"veg_soup": 1},
                 "station": "fire", "level": 2},
    "fish_stew": {"name": "鱼汤", "in": {"raw_fish": 1, "carrot": 1}, "out": {"fish_stew": 1},
                  "station": "fire", "level": 2},
    "skewer": {"name": "烤肉串", "in": {"cooked_meat": 1, "herb": 1}, "out": {"skewer": 1},
               "station": "fire", "level": 2},
}

# 设施的中文名（给菜单显示用）
STATION_NAMES = {None: "", "workbench": "工作台", "fire": "火堆", "furnace": "石炉"}

# ------------------------------------------------------------ 建筑

# 建筑：kind → 名字、建造材料、占几格（边长）、最高等级
BUILDS: Dict[str, dict] = {
    "workbench": {"name": "工作台", "cost": {"wood": 6, "stone": 2}, "size": 1, "max_level": 3},
    "campfire": {"name": "火堆", "cost": {"wood": 3, "stone": 1}, "size": 1, "max_level": 3},
    "furnace": {"name": "石炉", "cost": {"stone": 8}, "size": 1, "max_level": 2},
    "house": {"name": "房子", "cost": {"wood": 20, "stone": 6, "rope": 2}, "size": 4, "max_level": 3},
}

# 升级：kind → {新等级: 材料}
UPGRADES: Dict[str, Dict[int, dict]] = {
    "workbench": {2: {"wood": 10, "stone": 6}, 3: {"wood": 20, "iron_ingot": 4}},
    "campfire": {2: {"stone": 4, "wood": 4}, 3: {"iron_ingot": 2, "stone": 4}},
    "furnace": {2: {"stone": 12, "iron_ingot": 2}},
    "house": {2: {"wood": 20, "stone": 10, "rope": 4}, 3: {"wood": 30, "iron_ingot": 6, "rope": 6}},
}

# 房子的房间大小（格）：等级 → 边长
ROOM_SIZE = {1: 10, 2: 12, 3: 14}      # 进屋后房间的大小（房子在外面是 4×4）


# 家具效果：kind → (站在旁边时每秒精神, 每秒健康, 范围（格）)
FURNITURE_EFFECT = {
    "bed": (0.3, 0.1, 1.5),
    "lamp": (0.1, 0.0, 3.0),
    "fireplace": (0.2, 0.05, 3.0),     # 壁炉：暖和，让人安心
    "bookshelf": (0.1, 0.0, 2.5),      # 书架：看书让人平静
}
# 家具挡路的半径（格）；地毯和油灯不挡路
FURNITURE_BLOCK = {"bed": 0.45, "table": 0.45, "chair": 0.35, "chest": 0.4, "fireplace": 0.5, "bookshelf": 0.4}

# ------------------------------------------------------------ 作物

# 作物：kind → 种子、成熟秒数、收获（物品 → (最少, 最多)）、收获时掉种子的几率
CROPS: Dict[str, dict] = {
    "carrot": {"name": "胡萝卜", "seed": "carrot_seed", "grow": 120, "yield": {"carrot": (2, 3)}},
    "potato": {"name": "土豆", "seed": "potato_seed", "grow": 150, "yield": {"potato": (2, 3)}},
    "corn": {"name": "玉米", "seed": "corn_seed", "grow": 200, "yield": {"corn": (2, 2)}},
}
SEED_CHANCE = 0.7                  # 收获时掉一颗种子的几率
WILD_SEED_CHANCE = 0.2            # 采草本植物时掉种子的几率

# 工具等级：砍树时每下额外多得的木材
AXE_BONUS = {"stone_axe": 1, "iron_axe": 2}

# 采集的数量：资源 → (得到的物品, 中间值, 浮动)。每次采集在 [中间值-浮动, 中间值+浮动] 里随机。
# 进度条走完时一次性全部拿到（砍倒、采空、挖掉）。
YIELD = {
    "tree": ("wood", 7, 2),
    "rock": ("stone", 5, 1),
    "bush": ("berry", 4, 1),
    "herb": ("herb", 3, 1),
    "reed": ("fiber", 4, 1),
    "shell": ("shell", 2, 1),
    "mushroom": ("mushroom", 2, 1),
}
COCONUT_CHANCE = 0.6      # 砍倒一棵树时掉椰子的几率

# 篝火：每根柴烧多久（秒）、最多能攒多久、照亮多远（格）。越高级越久、越亮。
FUEL_SECONDS = {1: 180, 2: 360, 3: 600}
FUEL_MAX = 1200
LIGHT_RADIUS = {1: 3.5, 2: 5.5, 3: 8.0}

# 昼夜：现实 1 分钟 = 游戏 1 小时，所以 1 天 = 24 分钟。白天 18 分钟，夜晚 6 分钟，游戏从白天开始。
DAY_LEN = 18 * 60         # 白天的秒数（现实时间）
DAY_TOTAL = 24 * 60       # 一天的秒数（现实时间）

# 动作要花的时间（秒）：按下互动后，进度条走完才算成功
WORK_TIME = {"tree": 3.0, "rock": 2.0, "bush": 1.2, "herb": 1.2, "reed": 1.2,
             "shell": 0.8, "mushroom": 0.8, "animal": 0.8, "fish": 2.5}
# 进度条上显示的字
WORK_LABEL = {"tree": "砍树", "rock": "采石", "bush": "采集", "herb": "采集", "reed": "采集",
              "shell": "采集", "mushroom": "采集", "animal": "攻击", "fish": "钓鱼"}
# 工具让动作变快：倍率越小越快（只取最好的一个工具）
TREE_TOOL_SPEED = {"stone_axe": 0.7, "iron_axe": 0.5}
ROCK_TOOL_SPEED = {"stone_pick": 0.7, "iron_pick": 0.5}
SPEAR_SPEED = 0.6
# 一次互动最多同时采几个同类的资源（树、石头、灌木丛……）。时间按个数加长，但比逐个采快。
BATCH_MAX = 3
BATCH_TIME_STEP = 0.6     # 每多一个，时间多出 60% 的基础时间
