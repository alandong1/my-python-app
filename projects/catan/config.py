"""卡坦岛的规则数值。想调规则或画面颜色，改这里就行。

规则依据：卡坦岛（Catan）基础版的规则，3–4 人，先到 10 分获胜。
"""

RESOURCES = ("brick", "lumber", "wool", "grain", "ore")
RESOURCE_NAMES = {"brick": "砖块", "lumber": "木材", "wool": "羊毛", "grain": "粮食", "ore": "矿石"}
BANK_START = 19                       # 银行每种资源的初始数量

# 地形 → 产出的资源（沙漠不产出）
TERRAIN_RESOURCE = {"hills": "brick", "forest": "lumber", "pasture": "wool",
                    "fields": "grain", "mountains": "ore"}
TERRAIN_NAMES = {"hills": "丘陵", "forest": "森林", "pasture": "牧场",
                 "fields": "农田", "mountains": "山脉", "desert": "沙漠"}
TERRAIN_DECK = (["forest"] * 4 + ["pasture"] * 4 + ["fields"] * 4
                + ["hills"] * 3 + ["mountains"] * 3 + ["desert"])
# 数字圆片（沙漠没有数字）。6 和 8 是「红数字」，生成棋盘时尽量不相邻
NUMBER_TOKENS = (2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12)
# 港口：4 个「任意 3:1」，5 个「某种资源 2:1」
HARBOR_TYPES = ("any", "any", "any", "any", "brick", "lumber", "wool", "grain", "ore")

# 建造费用
COST = {
    "road": {"brick": 1, "lumber": 1},
    "settlement": {"brick": 1, "lumber": 1, "wool": 1, "grain": 1},
    "city": {"grain": 2, "ore": 3},
    "dev": {"ore": 1, "wool": 1, "grain": 1},
}
PIECE_LIMIT = {"road": 15, "settlement": 5, "city": 4}   # 每人可以放的数量

# 发展卡牌库（共 25 张）
DEV_DECK = {"knight": 14, "vp": 5, "road_building": 2, "year_of_plenty": 2, "monopoly": 2}
DEV_NAMES = {"knight": "骑士", "vp": "胜利点", "road_building": "道路建设",
             "year_of_plenty": "丰收之年", "monopoly": "垄断"}

VP_TO_WIN = 10
LONGEST_ROAD_MIN = 5          # 最长道路至少 5 段才能拿到，奖励 2 分
LARGEST_ARMY_MIN = 3          # 最大骑士团至少打出 3 张骑士，奖励 2 分

MIN_PLAYERS = 3
MAX_PLAYERS = 4
PLAYER_COLORS = ["#d9423a", "#2f6fd1", "#f4f4f4", "#f08a24"]   # 红、蓝、白、橙（和卡坦岛一致）
PLAYER_COLOR_NAMES = ["红", "蓝", "白", "橙"]
