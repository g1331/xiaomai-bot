import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage, Member
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Plain, Image, Source
from graia.ariadne.message.parser.twilight import (
    Twilight, FullMatch, SpacePolicy, WildcardMatch
)
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Saya, Channel
from sqlalchemy import select

from core.control import Permission, Function, FrequencyLimitation, Distribute
from core.models import saya_model
from core.orm import orm
from core.orm.tables import TarotRecord

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = "Tarot"
channel.meta["author"] = "SAGIRI-kawaii"
channel.meta["description"] = "高级塔罗牌占卜插件，支持多种牌阵和时间限制"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


# 原有的单张抽牌功能（保持向后兼容）
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("-塔罗牌").space(SpacePolicy.PRESERVE)]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def tarot_single(app: Ariadne, group: Group, member: Member, source: Source):
    await app.send_group_message(group, await Tarot.get_single_tarot(), quote=source)


# 每日运势 - 仅使用大阿卡那，每日限制一次
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("-每日运势").space(SpacePolicy.PRESERVE)]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def daily_fortune(app: Ariadne, group: Group, member: Member, source: Source):
    result = await Tarot.get_daily_fortune(member.id, group.id)
    await app.send_group_message(group, result, quote=source)


# 三张牌阵 - 使用全牌，每小时限制一次
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("-三张牌阵").space(SpacePolicy.PRESERVE)]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def three_card_spread(app: Ariadne, group: Group, member: Member, source: Source):
    result = await Tarot.get_three_card_spread(member.id, group.id)
    await app.send_group_message(group, result, quote=source)


# 凯尔特十字牌阵 - 使用全牌，每日限制一次
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("-凯尔特十字").space(SpacePolicy.PRESERVE)]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def celtic_cross(app: Ariadne, group: Group, member: Member, source: Source):
    result = await Tarot.get_celtic_cross(member.id, group.id)
    await app.send_group_message(group, result, quote=source)


# 单张塔罗牌解析
@listen(GroupMessage)
@dispatch(Twilight([
    FullMatch("/塔罗牌"),
    "card_name" @ WildcardMatch().space(SpacePolicy.PRESERVE)
]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def tarot_lookup(app: Ariadne, group: Group, source: Source, card_name: str):
    result = await Tarot.lookup_card(card_name.strip())
    await app.send_group_message(group, result, quote=source)


# 塔罗知识查询
@listen(GroupMessage)
@dispatch(Twilight([FullMatch("/塔罗知识").space(SpacePolicy.PRESERVE)]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def tarot_knowledge(app: Ariadne, group: Group, source: Source):
    result = Tarot.get_tarot_knowledge()
    await app.send_group_message(group, result, quote=source)


class Tarot:
    @staticmethod
    async def get_single_tarot() -> MessageChain:
        """获取单张塔罗牌（原有功能，保持兼容性）"""
        card, filename = Tarot.get_random_tarot()
        card_dir = random.choice(["normal", "reverse"])
        card_type = "正位" if card_dir == "normal" else "逆位"
        content = (
            f"{card['name']} ({card['name-en']}) {card_type}\n"
            f"牌意：{card['meaning'][card_dir]}"
        )
        elements = []
        img_path = f"{os.getcwd()}/statics/tarot/{card_dir}/{filename}.jpg"
        if filename and os.path.exists(img_path):
            elements.append(Image(path=img_path))
        elements.append(Plain(text=content))
        return MessageChain(elements)

    @staticmethod
    async def get_daily_fortune(user_id: int, group_id: int) -> MessageChain:
        """每日运势占卜 - 仅使用大阿卡那，每日限制一次"""
        # 检查是否今日已占卜
        if await Tarot._check_daily_limit(user_id, group_id, "daily_fortune"):
            return MessageChain([
                Plain("你今天已经进行过每日运势占卜了，请明天再来吧～")
            ])

        # 从大阿卡那中抽取一张牌
        card = await Tarot._draw_major_arcana()
        position = random.choice(["normal", "reverse"])
        position_text = "正位" if position == "normal" else "逆位"

        # 获取节日信息
        holiday_info = Tarot._get_holiday_info()
        holiday_text = f"\n\n🎉 {holiday_info}" if holiday_info else ""

        # 记录占卜
        await Tarot._record_divination(
            user_id, group_id, "daily_fortune", [card], [position]
        )

        content = (
            f"🌟 今日运势 🌟\n\n{card['name']} ({card['name-en']}) "
            f"{position_text}\n\n运势解读：{card['meaning'][position]}{holiday_text}"
        )

        return MessageChain([Plain(content)])

    @staticmethod
    async def get_three_card_spread(user_id: int, group_id: int) -> MessageChain:
        """三张牌阵占卜 - 使用全牌，每小时限制一次"""
        # 检查是否一小时内已占卜
        if await Tarot._check_hourly_limit(user_id, group_id, "three_card"):
            return MessageChain([
                Plain("你在一小时内已经进行过三张牌阵占卜了，请稍后再试～")
            ])

        # 抽取三张不重复的牌
        cards = await Tarot._draw_multiple_cards(3)
        positions = [random.choice(["normal", "reverse"]) for _ in range(3)]
        position_texts = ["正位" if p == "normal" else "逆位" for p in positions]

        # 获取节日信息
        holiday_info = Tarot._get_holiday_info()
        holiday_text = f"\n\n🎉 {holiday_info}" if holiday_info else ""

        # 记录占卜
        await Tarot._record_divination(user_id, group_id, "three_card", cards, positions)

        content = "🔮 三张牌阵 🔮\n\n"
        content += f"过去：{cards[0]['name']} {position_texts[0]}\n{cards[0]['meaning'][positions[0]]}\n\n"
        content += f"现在：{cards[1]['name']} {position_texts[1]}\n{cards[1]['meaning'][positions[1]]}\n\n"
        content += f"未来：{cards[2]['name']} {position_texts[2]}\n{cards[2]['meaning'][positions[2]]}{holiday_text}"

        return MessageChain([Plain(content)])

    @staticmethod
    async def get_celtic_cross(user_id: int, group_id: int) -> MessageChain:
        """凯尔特十字牌阵占卜 - 使用全牌，每日限制一次"""
        # 检查是否今日已占卜
        if await Tarot._check_daily_limit(user_id, group_id, "celtic_cross"):
            return MessageChain([
                Plain("你今天已经进行过凯尔特十字占卜了，请明天再来吧～")
            ])

        # 抽取十张不重复的牌
        cards = await Tarot._draw_multiple_cards(10)
        positions = [random.choice(["normal", "reverse"]) for _ in range(10)]

        # 凯尔特十字牌位含义
        position_meanings = [
            "现状", "挑战", "远程过去", "近期过去", "可能的未来",
            "近期未来", "你的方法", "外在影响", "内在感受", "最终结果"
        ]

        # 获取节日信息
        holiday_info = Tarot._get_holiday_info()
        holiday_text = f"\n\n🎉 {holiday_info}" if holiday_info else ""

        # 记录占卜
        await Tarot._record_divination(user_id, group_id, "celtic_cross", cards, positions)

        # 生成凯尔特十字文本布局
        content = "✨ 凯尔特十字牌阵 ✨\n\n"
        content += Tarot._generate_celtic_cross_layout(cards, positions, position_meanings)
        content += "\n💫 详细解读：\n"
        for i, (card, position, meaning) in enumerate(zip(cards, positions, position_meanings)):
            position_text = "正位" if position == "normal" else "逆位"
            content += f"{i+1}. {meaning}：{card['name']} {position_text}\n"

        content += f"{holiday_text}"

        return MessageChain([Plain(content)])

    @staticmethod
    async def lookup_card(card_name: str) -> MessageChain:
        """查询单张塔罗牌的详细信息"""
        card = await Tarot._find_card_by_name(card_name)
        if not card:
            return MessageChain([
                Plain(f"未找到名为 '{card_name}' 的塔罗牌。请检查拼写或使用中文牌名。")
            ])

        content = f"🃏 {card['name']} ({card['name-en']}) 🃏\n\n"
        content += f"正位含义：{card['meaning']['normal']}\n\n"
        content += f"逆位含义：{card['meaning']['reverse']}\n\n"
        if 'sign' in card:
            content += f"对应元素/星座：{card['sign']}"

        return MessageChain([Plain(content)])

    @staticmethod
    def get_tarot_knowledge() -> MessageChain:
        """获取塔罗牌知识"""
        knowledge = """🔮 塔罗牌小知识 🔮

📚 塔罗牌组成：
• 大阿卡那（Major Arcana）：22张，代表人生重大课题
• 小阿卡那（Minor Arcana）：56张，代表日常生活
  - 权杖（火元素）：创造力、事业、行动
  - 圣杯（水元素）：情感、关系、精神
  - 宝剑（风元素）：思想、沟通、冲突  
  - 星币（土元素）：物质、金钱、健康

🎯 牌阵类型：
• 每日运势：了解当天的整体运势
• 三张牌阵：过去-现在-未来的流动
• 凯尔特十字：最全面的生活指导

✨ 正位与逆位：
• 正位：牌的正面含义和能量
• 逆位：阻碍、内在课题或能量失衡

🌟 使用建议：
带着具体问题进行占卜，保持开放和诚实的心态。塔罗牌是自我反思的工具，而非绝对的预言。"""

        return MessageChain([Plain(knowledge)])

    @staticmethod
    async def _check_daily_limit(user_id: int, group_id: int, divination_type: str) -> bool:
        """检查用户是否已达到每日限制"""
        today = datetime.now().date()
        result = await orm.fetch_one(
            select(TarotRecord).where(
                TarotRecord.user_id == user_id,
                TarotRecord.group_id == group_id,
                TarotRecord.divination_type == divination_type,
                TarotRecord.divination_time >= today
            )
        )
        return result is not None

    @staticmethod
    async def _check_hourly_limit(user_id: int, group_id: int, divination_type: str) -> bool:
        """检查用户是否已达到每小时限制"""
        one_hour_ago = datetime.now() - timedelta(hours=1)
        result = await orm.fetch_one(
            select(TarotRecord).where(
                TarotRecord.user_id == user_id,
                TarotRecord.group_id == group_id,
                TarotRecord.divination_type == divination_type,
                TarotRecord.divination_time >= one_hour_ago
            )
        )
        return result is not None

    @staticmethod
    async def _record_divination(
        user_id: int,
        group_id: int,
        divination_type: str,
        cards: list[dict],
        positions: list[str]
    ):
        """记录占卜历史"""
        await orm.add(TarotRecord, {
            "user_id": user_id,
            "group_id": group_id,
            "divination_type": divination_type,
            "divination_time": datetime.now(),
            "cards_drawn": json.dumps([card['name'] for card in cards], ensure_ascii=False),
            "card_positions": json.dumps(positions, ensure_ascii=False)
        })

    @staticmethod
    async def _draw_major_arcana() -> dict:
        """从大阿卡那中抽取一张牌"""
        data = Tarot._load_tarot_data()
        return random.choice(data["major"])

    @staticmethod
    async def _draw_multiple_cards(count: int) -> list[dict]:
        """从全牌中抽取多张不重复的牌"""
        data = Tarot._load_tarot_data()
        all_cards = []
        for kind in ["major", "pentacles", "wands", "cups", "swords"]:
            all_cards.extend(data[kind])
        return random.sample(all_cards, count)

    @staticmethod
    async def _find_card_by_name(name: str) -> dict | None:
        """根据牌名查找塔罗牌"""
        data = Tarot._load_tarot_data()
        for kind in ["major", "pentacles", "wands", "cups", "swords"]:
            for card in data[kind]:
                if name in card["name"] or name in card["name-en"]:
                    return card
        return None

    @staticmethod
    def _generate_celtic_cross_layout(cards: list[dict], positions: list[str], meanings: list[str]) -> str:
        """生成凯尔特十字牌阵的文本布局"""
        # 简化牌名以适合布局
        def shorten_name(name: str, pos: str) -> str:
            short = name[:4] if len(name) > 4 else name
            return f"{short}{'↑' if pos == 'normal' else '↓'}"

        # 生成简化的牌名
        short_cards = [shorten_name(card['name'], pos) for card, pos in zip(cards, positions)]

        layout = f"""
           {short_cards[3]}
             ↑
       {short_cards[2]} ← {short_cards[0]} → {short_cards[5]}
             ↓
           {short_cards[1]}
           
                  {short_cards[9]}
                    ↑
                  {short_cards[8]}
                    ↑
                  {short_cards[7]}
                    ↑
                  {short_cards[6]}

位置说明：
• 中心({short_cards[0]})：当前状况
• 十字交叉({short_cards[1]})：面临挑战  
• 上方({short_cards[3]})：意识层面
• 左侧({short_cards[2]})：过去影响
• 右侧({short_cards[5]})：未来可能
• 右侧竖排：内在世界到最终结果
"""
        return layout

    @staticmethod
    def _load_tarot_data() -> dict:
        """加载塔罗牌数据"""
        path = Path(os.getcwd()) / "statics" / "tarot" / "tarot.json"
        with open(path, encoding="utf-8") as json_file:
            return json.load(json_file)

    @staticmethod
    def _get_holiday_info() -> str | None:
        """获取当前日期的节日信息"""
        now = datetime.now()
        month, day = now.month, now.day

        holidays = {
            (2, 14): "情人节：爱情能量格外强烈，感情相关的占卜会有特别的指导意义。",
            (10, 31): "万圣节：神秘力量增强，适合探索内在阴影和隐藏的真相。",
            (12, 25): "圣诞节：希望与新生的能量，适合许愿和展望未来。",
            (1, 1): "新年：新开始的能量，适合设定目标和计划未来。",
            (12, 31): "跨年夜：反思与展望的时刻，适合回顾过去和迎接新年。"
        }

        return holidays.get((month, day))

    @staticmethod
    def get_random_tarot():
        """原有的随机抽牌方法（保持兼容性）"""
        data = Tarot._load_tarot_data()
        kinds = ["major", "pentacles", "wands", "cups", "swords"]
        cards = []
        for kind in kinds:
            cards.extend(data[kind])
        card = random.choice(cards)
        filename = next(
            (
                "{}{:02d}".format(kind, card["num"])
                for kind in kinds
                if card in data[kind]
            ),
            "",
        )
        return card, filename
