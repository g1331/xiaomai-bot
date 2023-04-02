import json
from pathlib import Path
from graia.ariadne.event.message import GroupMessage
from graia.broadcast import ExecutionStop
from graia.broadcast.builtin.decorators import Depend
from modules.self_contained.bf1_warm_server import infos, bots

perm_file_path = Path(__file__).parent / "perm.json"
group_file_path = Path(__file__).parent / "group.json"


def get_session():
    session = None
    for bot_name in bots:
        if bots[bot_name]["onlineState"] != 1:
            session = infos[bot_name].sessionId
            break
    if not session:
        return None
    else:
        return session


def get_bots():
    online_counter = 0
    rest_counter = 0
    busy_counter = 0
    for bot_name in bots:
        if infos[bot_name].onlineState == 3:
            online_counter += 1
        if infos[bot_name].state == "None":
            rest_counter += 1
        else:
            busy_counter += 1
    return {
        "online": online_counter,
        "rest": rest_counter,
        "busy": busy_counter,
        "total": len(bots)
    }


def get_perm_list() -> list:
    # 如果文件不存在则创建
    if not perm_file_path.exists():
        with open(perm_file_path, "w") as f:
            json.dump({"qqs": []}, f, indent=4, ensure_ascii=False)
    with open(perm_file_path, "r") as f:
        data = json.load(f)
        return data.get("qqs")


def add_perm(qq: int):
    perm_list = get_perm_list()
    perm_list.append(qq)
    with open(perm_file_path, "w") as f:
        json.dump({"qqs": perm_list}, f, indent=4, ensure_ascii=False)


def remove_perm(qq: int):
    perm_list = get_perm_list()
    perm_list.remove(qq)
    with open(perm_file_path, "w") as f:
        json.dump({"qqs": perm_list}, f, indent=4, ensure_ascii=False)


def get_group_list() -> list:
    # 如果文件不存在则创建
    if not group_file_path.exists():
        with open(group_file_path, "w") as f:
            json.dump({"groups": []}, f, indent=4, ensure_ascii=False)
    with open(group_file_path, "r") as f:
        data = json.load(f)
        return data.get("groups")


def add_group(group: int):
    group_list = get_group_list()
    group_list.append(group)
    with open(group_file_path, "w") as f:
        json.dump({"groups": group_list}, f, indent=4, ensure_ascii=False)


def remove_group(group: int):
    group_list = get_group_list()
    group_list.remove(group)
    with open(group_file_path, "w") as f:
        json.dump({"groups": group_list}, f, indent=4, ensure_ascii=False)


class Control(object):

    @classmethod
    def user_require(cls):
        async def wrapper(event: GroupMessage):
            perm_list = get_perm_list()
            if event.sender.id not in perm_list:
                print(event.sender.id)
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)

    @classmethod
    def group_require(cls):
        async def wrapper(event: GroupMessage):
            group_list = get_group_list()
            if event.sender.group.id not in group_list:
                raise ExecutionStop
            return Depend(wrapper)

        return Depend(wrapper)
