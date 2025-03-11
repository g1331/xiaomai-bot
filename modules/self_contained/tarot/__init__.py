import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

from graia.ariadne.app import Ariadne
from graia.ariadne.event.message import Group, GroupMessage, Member
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.message.element import Plain, Image, Source
from graia.ariadne.message.parser.twilight import Twilight, FullMatch, SpacePolicy
from graia.ariadne.util.saya import listen, decorate, dispatch
from graia.saya import Saya, Channel

from core.control import Permission, Function, FrequencyLimitation, Distribute
from core.models import saya_model

module_controller = saya_model.get_module_controller()
saya = Saya.current()
channel = Channel.current()
channel.meta["name"] = "Tarot"
channel.meta["author"] = "SAGIRI-kawaii"
channel.meta["description"] = "可以抽塔罗牌的插件，在群中发送 `-塔罗牌` 即可"
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))


@listen(GroupMessage)
@dispatch(Twilight([FullMatch("-塔罗牌").space(SpacePolicy.PRESERVE)]))
@decorate(
    Distribute.require(),
    Function.require(channel.module),
    FrequencyLimitation.require(channel.module),
    Permission.group_require(channel.metadata.level),
    Permission.user_require(Permission.User),
)
async def tarot(app: Ariadne, group: Group, sender: Member, source: Source):
    await app.send_group_message(group, await Tarot.get_tarot(sender.id), quote=source)


class Tarot(object):
    # Store user daily results: {user_id: (date, card_info, filename)}
    _user_draws: Dict[int, Tuple[str, dict, str]] = {}

    @staticmethod
    async def get_tarot(user_id: int) -> MessageChain:
        today = datetime.now().strftime("%Y-%m-%d")

        # Check if user already drew today
        if user_id in Tarot._user_draws:
            last_date, card, filename = Tarot._user_draws[user_id]
            if last_date == today:
                card_dir = (
                    "normal"
                    if card["meaning"]["normal"] in card["meaning"].get("current", "")
                    else "reverse"
                )
                card_type = "正位" if card_dir == "normal" else "逆位"
                content = f"[重复] {card['name']} ({card['name-en']}) {card_type}\n牌意：{card['meaning'][card_dir]}"
                elements = []
                img_path = f"{os.getcwd()}/statics/tarot/{card_dir}/{filename}.jpg"
                if filename and os.path.exists(img_path):
                    elements.append(Image(path=img_path))
                elements.append(Plain(text=content))
                return MessageChain(elements)

        # Draw new card
        card, filename = Tarot.get_random_tarot()
        card_dir = random.choice(["normal", "reverse"])
        card["meaning"]["current"] = card["meaning"][card_dir]  # Store current meaning
        Tarot._user_draws[user_id] = (today, card, filename)

        card_type = "正位" if card_dir == "normal" else "逆位"
        content = f"{card['name']} ({card['name-en']}) {card_type}\n牌意：{card['meaning'][card_dir]}"
        elements = []
        img_path = f"{os.getcwd()}/statics/tarot/{card_dir}/{filename}.jpg"
        if filename and os.path.exists(img_path):
            elements.append(Image(path=img_path))
        elements.append(Plain(text=content))
        return MessageChain(elements)

    @staticmethod
    def get_random_tarot():
        path = Path(os.getcwd()) / "statics" / "tarot" / "tarot.json"
        with open(path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
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
