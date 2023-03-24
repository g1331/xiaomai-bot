from rapidfuzz import fuzz
from zhconv import zhconv


# 传入武器dict源数据，返回武器根据条件排序后的列表,封装成类，方便后续调用

class WeaponData:
    # 传入武器dict源数据初始化
    def __init__(self, weapon_data: dict):
        self.weapon_data: list = weapon_data.get("result")
        self.weapon_item_list: list = []
        """例:
        self.weapon_item_list = [
            {weapon_item},...
        ]
        默认分类:戰場裝備、輕機槍、步槍、配備、半自動步槍、手榴彈、制式步槍、霰彈槍、坦克/駕駛員、衝鋒槍、佩槍、近戰武器
        将制式步槍也归类到步槍中
        """
        for category in self.weapon_data:
            for weapon in category["weapons"]:
                if weapon.get("category") == "制式步槍":
                    weapon["category"] = "步槍"
                self.weapon_item_list.append(weapon)

    # 按照规则来排序
    def filter(self, rule: str = None, sort_type: str = "击杀") -> list:
        """对武器进行分类排序"""
        weapon_list = []
        # 按照武器类别、兵种、击杀数来过滤
        for weapon in self.weapon_item_list:
            if rule in ["精英兵"]:
                if weapon.get("category") == "戰場裝備" or weapon.get("guid") in [
                    "8A849EDD-AE9F-4F9D-B872-7728067E4E9F"
                ]:
                    weapon_list.append(weapon)
            elif rule in ["机枪", "轻机枪"]:
                if weapon.get("category") == "輕機槍":
                    weapon_list.append(weapon)
            elif rule in ["步枪", "狙击枪"]:
                if weapon.get("category") == "步槍":
                    weapon_list.append(weapon)
            elif rule in ["装备", "配备"]:
                if weapon.get("category") == "配備":
                    weapon_list.append(weapon)
            elif rule in ["半自动步枪", "半自动"]:
                if weapon.get("category") == "半自動步槍":
                    weapon_list.append(weapon)
            elif rule in ["手榴弹", "手雷", "投掷物"]:
                if weapon.get("category") == "手榴彈":
                    weapon_list.append(weapon)
            elif rule in ["霰弹枪", "散弹枪"]:
                if weapon.get("category") == "霰彈槍":
                    weapon_list.append(weapon)
            elif rule in ["驾驶员", "坦克驾驶员"]:
                if weapon.get("category") == "坦克/駕駛員":
                    weapon_list.append(weapon)
            elif rule in ["冲锋枪"]:
                if weapon.get("category") == "衝鋒槍":
                    weapon_list.append(weapon)
            elif rule in ["副武器", "佩枪", "手枪"]:
                if weapon.get("category") == "佩槍":
                    weapon_list.append(weapon)
            elif rule in ["近战"]:
                if weapon.get("category") == "近戰武器":
                    weapon_list.append(weapon)
            elif rule in ["突击兵", "土鸡兵", "土鸡", "突击"]:
                if weapon.get("category") in ["衝鋒槍", "霰彈槍"] or weapon.get("guid") in [
                    "245A23B1-53BA-4AB2-A416-224794F15FCB",  # M1911
                    "D8AEB334-58E2-4A52-83BA-F3C2107196F0",
                    "7085A5B9-6A77-4766-83CD-3666DA3EDF28",
                    "079D8793-073C-4332-A959-19C74A9D2A46",
                    "72CCBF3E-C0FE-4657-A1A7-EACDB2D11985",
                    "6DFD1536-BBBB-4528-917A-7E2821FB4B6B",
                    "BE041F1A-460B-4FD5-9E4B-F1C803C0F42F",
                    "AE96B513-1F05-4E63-A273-E98FA91EE4D0",
                ]:
                    weapon_list.append(weapon)
            elif rule in ["侦察兵", "侦察", "斟茶兵", "斟茶"]:
                if weapon.get("category") in ["步枪"] or weapon.get("guid") in [
                    "2543311A-B9BC-4F72-8E71-C9D32DCA9CFC",
                    "ADAD5F72-BD74-46EF-AB42-99F95D88DF8E",
                    "2D64B139-27C8-4EDB-AB14-734993A96008",
                    "EF1C7B9B-8912-4298-8FCB-29CC75DD0E7F",
                    "9CF9EA1C-39A1-4365-85A1-3645B9621901",
                    "033299D1-A8E6-4A5A-8932-6F2091745A9D",
                ]:
                    weapon_list.append(weapon)
            elif rule in ["医疗兵", "医疗"]:
                if weapon.get("category") in ["半自動步槍"] or weapon.get("guid") in [
                    "F34B3039-7B3A-0272-14E7-628980A60F06",
                    "03FDF635-8E98-4F74-A176-DB4960304DF5",
                    "165ED044-C2C5-43A1-BE04-8618FA5072D4",
                    "EBA4454E-EEB6-4AF1-9286-BD841E297ED4",
                    "670F817E-89A6-4048-B8B2-D9997DD97982",
                    "9BCDB1F5-5E1C-4C3E-824C-8C05CC0CE21A",
                    "245A23B1-53BA-4AB2-A416-224794F15FCB",
                    "4E317627-F7F8-4014-BB22-B0ABEB7E9141",
                ]:
                    weapon_list.append(weapon)
            elif rule in ["支援兵", "支援"]:
                if weapon.get("category") in ["輕機槍"] or weapon.get("guid") in [
                    "0CC870E0-7AAE-44FE-B9D8-5D90706AF38B",
                    "6CB23E70-F191-4043-951A-B43D6D2CF4A2",
                    "3DC12572-2D2F-4439-95CA-8DFB80BA17F5",
                    "2B421852-CFF9-41FF-B385-34580D5A9BF0",
                    "EBE043CB-8D37-4807-9260-E2DD7EFC4BD2",
                    "2B0EC5C1-81A5-424A-A181-29B1E9920DDA",
                    "19CB192F-1197-4EEB-A499-A2DA449BE811",
                    "52B19C38-72C0-4E0F-B051-EF11103F6220",
                    "C71A02C3-608E-42AA-9179-A4324A4D4539",
                    "8BD0FABD-DCCE-4031-8156-B77866FCE1A0",
                    "F59AA727-6618-4C1D-A5E2-007044CA3B89",
                    "95A5E9D8-E949-46C2-B5CA-36B3CA4C2E9D",
                    "60D24A79-BFD6-4C8F-B54F-D1AA6D2620DE",
                    "02D4481F-FBC3-4C57-AAAC-1B37DC92751E"
                ]:
                    weapon_list.append(weapon)
            else:
                weapon_list.append(weapon)
        # 按照击杀/爆头率/命中率/时长排序
        sort_type_dict = {
            "击杀": "kills",
            "爆头率": "headshots",
            "命中率": "accuracy",
            "时长": "seconds"
        }
        weapon_list.sort(
            key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type, "kills"), 0),
            reverse=True
        )
        return weapon_list

    # 根据武器名搜索武器信息
    def search_weapon(self, target_weapon_name):
        """根据武器名搜索武器信息"""
        weapon_list = []
        for weapon in self.weapon_item_list:
            # 先将武器名转换为简体中文，再进行模糊匹配
            weapon_name = zhconv.convert(weapon.get("name"), 'zh-hans')
            # 非完全匹配，基于最佳的子串（substrings）进行匹配
            if fuzz.partial_ratio(target_weapon_name, weapon_name) > 70:
                weapon_list.append(weapon)
        return weapon_list


# 传入载具dict源数据，根据条件返回排序后的载具列表
class VehicleData:
    # 初始化
    def __init__(self, vehicle_data: dict):
        self.vehicle_data: list = vehicle_data.get("result")
        self.vehicle_item_list: list = []
        """
        载具的分类:
            重型坦克、巡航坦克、輕型坦克、火砲裝甲車、攻擊坦克、突擊裝甲車、
            攻擊機、轟炸機、戰鬥機、重型轟炸機、
            飛船、
            地面載具、
            船隻、驅逐艦、
            定點武器、
            機械巨獸(火车、飞艇、char 2c、无畏舰)、
            馬匹
        """
        for category in self.vehicle_data:
            for vehicle in category["vehicles"]:
                vehicle["category"] = category["name"]
                self.vehicle_item_list.append(vehicle)

    # 排序
    def filter(self, rule: str = None, sort_type: str = "击杀") -> list:
        vehicle_list = []
        # 按照载具类别、击杀数来过滤
        for vehicle in self.vehicle_item_list:
            if rule in ["坦克"]:
                if vehicle.get("category") in ["重型坦克", "巡航坦克", "輕型坦克", "攻擊坦克", "突擊裝甲車"]:
                    vehicle_list.append(vehicle)
            elif rule in ["地面"]:
                if vehicle.get("category") in [
                    "重型坦克", "巡航坦克", "輕型坦克", "火砲裝甲車", "攻擊坦克", "突擊裝甲車", "地面載具", "馬匹", "定點武器"
                ] or vehicle.get("guid") in [
                    "A3ED808E-1525-412B-8E77-9EB6902A55D2",  # 装甲列车
                    "BBFC5A91-B2FC-48D2-8913-658C08072E6E"  # Char 2C
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["飞机"]:
                if vehicle.get("category") in ["攻擊機", "轟炸機", "戰鬥機", "重型轟炸機"]:
                    vehicle_list.append(vehicle)
            elif rule in ["飞船", "飞艇"]:
                if vehicle.get("category") in ["飛船"] or vehicle.get("guid") in [
                    "1A7DEECF-4F0E-E343-9644-D6D91DCAEC12",  # 飞艇
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["空中"]:
                if vehicle.get("category") in ["攻擊機", "轟炸機", "戰鬥機", "重型轟炸機", "飛船"] or vehicle.get("guid") in [
                    "1A7DEECF-4F0E-E343-9644-D6D91DCAEC12",  # 飞艇
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["海上"]:
                if vehicle.get("category") in ["船隻", "驅逐艦"] or vehicle.get("guid") in [
                    "003FCC0A-2758-8508-4774-78E66FA1B5E3",  # 无畏舰
                ]:
                    vehicle_list.append(vehicle)
            elif rule in ["定点"]:
                if vehicle.get("category") in ["定點武器"]:
                    vehicle_list.append(vehicle)
            else:
                vehicle_list.append(vehicle)

        # 按照击杀/时长/摧毁数
        sort_type_dict = {
            "击杀": "kills",
            "时长": "seconds",
            "摧毁": "destroyed"
        }
        vehicle_list.sort(
            key=lambda x: x.get("stats").get("values").get(sort_type_dict.get(sort_type, "kills"), 0),
            reverse=True
        )
        return vehicle_list

    # 搜索载具
    def search_vehicle(self, target_vehicle_name):
        """根据载具名搜索载具信息"""
        vehicle_list = []
        for vehicle in self.vehicle_item_list:
            # 先将载具名转换为简体中文，再进行模糊匹配
            vehicle_name = zhconv.convert(vehicle.get("name"), 'zh-hans')
            # 非完全匹配，基于最佳的子串（substrings）进行匹配
            if fuzz.partial_ratio(target_vehicle_name, vehicle_name) > 70:
                vehicle_list.append(vehicle)
        return vehicle_list
