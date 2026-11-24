"""记账本：手动记账，或者截图后识别屏幕上的金额。需要登录，账目只有自己能看到。"""
from app.registry import Project

# models 必须在 init_db() 之前 import，表才会被创建（这里 import server 时已经连带加载了它）
from . import models, server  # noqa: F401

PROJECT = Project(
    slug="bookkeeping",
    name="记账本",
    description="手动记账，或者在页面上快速双击截图，自动识别屏幕上的金额。",
    name_en="Bookkeeping",
    description_en="Track income and expenses by hand, or double-tap to screenshot and read the amount off the screen.",
    icon="💰",
    category="工具",
    status="测试中",
    requires_login=True,
    router=server.router,
    static_dir=server.STATIC,
)
