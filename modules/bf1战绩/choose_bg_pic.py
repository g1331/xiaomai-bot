import json
import os
import random
import time


class bg_pic(object):

    # 注册背景+修改->绑定的qq文件
    @staticmethod
    def register_bg(qq: int, player_pid: int, bg_num: int, date) -> str:
        data = {
            "qq": qq,
            "pid": player_pid,
            "num": bg_num,
            "date": date
        }
        try:
            player_path = f"./data/battlefield/players/{player_pid}"
            if not os.path.exists(player_path):
                os.mkdir(player_path)
            with open(f"./data/battlefield/players/{player_pid}/bg.json", 'w+', encoding="utf-8") as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            bg_path = f'./data/battlefield/players/{player_pid}/bg'
            if not os.path.exists(bg_path):
                os.mkdir(f'./data/battlefield/players/{player_pid}/bg')
            if date == 0:
                date = "永久"
            else:
                date = time.strftime('%Y年%m月%d日', time.localtime(date))
            return f"成功为qq:{qq}创建pid:{player_pid}的{bg_num}张背景\n到期时间:{date}"
        except Exception as e:
            return f"出错了!{e}"

    # 注销背景
    @staticmethod
    def cancellation_bg(player_pid: int):
        try:
            player_path = f"./data/battlefield/players/{player_pid}"
            if not os.path.exists(player_path):
                return "玩家档案不存在,请先查询一次战绩!"
            bg_file_path = f"./data/battlefield/players/{player_pid}/bg.json"
            if os.path.exists(bg_file_path):
                try:
                    os.remove(bg_file_path)
                    return f"成功注销{player_pid}的背景！"
                except Exception as e:
                    return f"注销{player_pid}背景失败{e}"
            else:
                return f"{player_pid}背景未注册!"
        except Exception as e:
            return f"出错了!{e}"

    # 删除
    @staticmethod
    def del_bg(player_pid: int) -> str:
        bg_path = f'./data/battlefield/players/{player_pid}/bg'
        if not os.path.exists(bg_path):
            return f"{player_pid}的背景不存在"
        try:
            os.remove(bg_path)
            return f"成功删除{player_pid}的背景"
        except Exception as e:
            return f"出错了!{e}"

    # 是否到期
    @staticmethod
    def check_date(player_pid) -> bool:
        """
        过期返回false
        :param player_pid: 玩家pid
        :return: 没过期返回true
        """
        json_path = f"./data/battlefield/players/{player_pid}/bg.json"
        if os.path.exists(json_path):
            with open(f"./data/battlefield/players/{player_pid}/bg.json", 'r', encoding="utf-8") as file:
                data = json.load(file)
                if data["date"] != 0:
                    if data["date"] < time.time():
                        return False
                return True
        else:
            return False

    # 选择背景
    @staticmethod
    def choose_bg(player_pid: int, bg_type: str) -> str:
        if bg_pic.check_date(player_pid):
            bg_path = f'./data/battlefield/players/{player_pid}/bg'
            if os.path.exists(bg_path):
                bg_list = os.listdir(bg_path)
                if len(bg_list) != 0:
                    bg = random.choice(bg_list)
                    return f"./data/battlefield/players/{player_pid}/bg/{bg}"
        # path = './data/battlefield/pic/bg/'
        # file_name_list = os.listdir(path)
        # bg = random.choice(bg_list)
        if bg_type == "stat":
            return f"./data/battlefield/pic/bg2/" + str(random.randint(1, 10)) + ".png"
        return "./data/battlefield/pic/bg/" + str(random.randint(1, 10)) + ".png"

    # 检查序号
    @staticmethod
    def check_bg_rank(player_pid, bg_rank):
        with open(f"./data/battlefield/players/{player_pid}/bg.json", 'r', encoding="utf-8") as file:
            data = json.load(file)
            if bg_rank > data["num"]:
                return f"无法超过上限哦~你的背景数:{data['num']}"

    # 检查pid和qq对应
    @staticmethod
    def check_qq_pid(player_pid, qq: int) -> bool:
        with open(f"./data/battlefield/players/{player_pid}/bg.json", 'r', encoding="utf-8") as file:
            data = json.load(file)
            if data['qq'] != qq:
                return False
            return True
