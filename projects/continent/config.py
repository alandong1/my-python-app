"""大陆争霸的数值配置：地图大小、单位、建筑、研究。

所有游戏数值都放在这里，改平衡只改这一个文件（和领主战争的 config.py 一样）。
时间单位是「回合」：1 回合 = 1 秒，见 game.TICK。
"""
from __future__ import annotations

W = 48          # 地图宽（格）
H = 32          # 地图高（格）
TICK = 1.0      # 一个回合对应的真实秒数
START_GOLD = 1000
RESPAWN_GOLD = 500
HQ_INCOME = 2          # 主基地每回合（秒）的金币
MINE_INCOME = 4        # 每座矿场每回合的金币
HQ_HP = 1000
HQ_SIGHT = 5
QUEUE_MAX = 5          # 每座建筑最多排队几个单位
BUILD_RANGE = 5        # 建筑必须离自己的基地/建筑在这么多格以内
RELOCATE_TIME = 30     # 搬迁要多少回合
RELOCATE_COOLDOWN = 120
RELOCATE_BASE = 300
RELOCATE_PER_TILE = 20
MAX_TICKS_PER_CALL = 600   # 一次请求最多推进多少回合，防止服务器长时间卡住

# 地形代码：w 海、p 平原、f 森林、m 山地
SEA, PLAIN, FOREST, MOUNTAIN = "w", "p", "f", "m"
BUILDABLE = (PLAIN, FOREST)

# 研究：四类装备，每类三级。费用按等级递增。
RESEARCH_CLASSES = {
    "infantry": "步兵类",
    "vehicle": "车辆类",
    "air": "空军类",
    "navy": "海军类",
}
RESEARCH_COSTS = (300, 700, 1400)   # 升到第 1、2、3 级的费用
RESEARCH_MAX = 3
ATTACK_PER_LEVEL = 0.20             # 每级攻击 +20%
HP_PER_LEVEL = 0.10                 # 每级生命上限 +10%

# 单位：domain 是活动领域（land 陆地 / sea 海上 / air 空中）；
# targets 是它能攻击的领域；cool 是两次攻击之间的回合数（0 表示不攻击）。
UNITS = {
    "infantry": dict(name="步兵", icon="🪖", cls="infantry", domain="land", cost=60, time=5,
                     hp=60, atk=10, rng=2, cool=1, sight=3, speed=0.5,
                     targets=("land",), mountain=True, producer="barracks"),
    "mg": dict(name="机枪兵", icon="🔫", cls="infantry", domain="land", cost=100, time=8,
               hp=70, atk=8, rng=3, cool=1, sight=3, speed=0.5,
               targets=("land", "air"), mountain=True, producer="barracks"),
    "truck": dict(name="运兵车", icon="🚙", cls="vehicle", domain="land", cost=150, time=8,
                  hp=80, atk=0, rng=0, cool=0, sight=3, speed=1.0,
                  targets=(), mountain=False, producer="barracks"),
    "tank": dict(name="坦克", icon="🛡️", cls="vehicle", domain="land", cost=450, time=15,
                 hp=300, atk=30, rng=4, cool=2, sight=4, speed=0.7,
                 targets=("land", "sea"), mountain=False, producer="factory"),
    "artillery": dict(name="大炮", icon="💣", cls="vehicle", domain="land", cost=400, time=14,
                      hp=160, atk=40, rng=6, cool=3, sight=4, speed=0.4,
                      targets=("land", "sea"), mountain=False, producer="factory"),
    "missile": dict(name="导弹车", icon="🚀", cls="vehicle", domain="land", cost=700, time=20,
                    hp=200, atk=60, rng=8, cool=4, sight=5, speed=0.4,
                    targets=("land", "sea", "air"), mountain=False, producer="factory"),
    "scout": dict(name="侦察机", icon="🛩️", cls="air", domain="air", cost=200, time=10,
                  hp=80, atk=0, rng=0, cool=0, sight=9, speed=2.0,
                  targets=(), mountain=True, producer="airfield"),
    "fighter": dict(name="战斗机", icon="✈️", cls="air", domain="air", cost=500, time=15,
                    hp=150, atk=35, rng=4, cool=1, sight=6, speed=1.5,
                    targets=("air",), mountain=True, producer="airfield"),
    "carrier": dict(name="航母", icon="🚢", cls="navy", domain="sea", cost=1200, time=30,
                    hp=800, atk=50, rng=5, cool=2, sight=5, speed=0.5,
                    targets=("land", "sea", "air"), mountain=False, producer="port"),
}

# 建筑：requires 是前置建筑；ore 表示必须建在矿点上；shore 表示必须靠海；
# produces 是能生产的单位；atk/rng/cool 是建筑自己的炮（炮台）。
BUILDINGS = {
    "hq": dict(name="主基地", icon="🏰", cost=0, hp=HQ_HP, sight=HQ_SIGHT, requires=None,
               ore=False, shore=False, produces=(), atk=0, rng=0, cool=0),
    "barracks": dict(name="兵营", icon="⛺", cost=200, hp=400, sight=3, requires=None,
                     ore=False, shore=False, produces=("infantry", "mg", "truck"),
                     atk=0, rng=0, cool=0),
    "factory": dict(name="工厂", icon="🏭", cost=400, hp=600, sight=3, requires="barracks",
                    ore=False, shore=False, produces=("tank", "artillery", "missile"),
                    atk=0, rng=0, cool=0),
    "airfield": dict(name="机场", icon="🛫", cost=500, hp=500, sight=3, requires="factory",
                     ore=False, shore=False, produces=("scout", "fighter"),
                     atk=0, rng=0, cool=0),
    "port": dict(name="港口", icon="⚓", cost=400, hp=500, sight=3, requires="barracks",
                 ore=False, shore=True, produces=("carrier",), atk=0, rng=0, cool=0),
    "mine": dict(name="矿场", icon="⛏️", cost=150, hp=300, sight=2, requires=None,
                 ore=True, shore=False, produces=(), atk=0, rng=0, cool=0),
    "pillbox": dict(name="炮台", icon="🗼", cost=150, hp=400, sight=4, requires=None,
                    ore=False, shore=False, produces=(), atk=25, rng=4, cool=2,
                    targets=("land", "sea")),
}

PLAYER_COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f1c40f", "#9b59b6", "#e67e22",
                 "#1abc9c", "#ff6fb5", "#95a5a6", "#8e5a2b"]
