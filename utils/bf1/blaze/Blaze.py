import contextlib
import struct

from utils.bf1.blaze.Method import Components, Commands, Methods, Components2Int

# QType = {
#     "0": "Command",
#     "32": "Command",
#     "64": "Message",
#     "128": "KeepAlive",
#     "160": "KeepAlive",
#     "Command": 32,
#     "Message": 64
# }
QType = {
    "0": "Command",
    "32": "Result",
    "64": "Message",
    "96": "Error",
    "128": "Ping",
    "160": "Pong",
    "Command": 0,
    "Result": 32,
    "Message": 64,
    "Error": 96,
    "Ping": 128,
    "Pong": 160
}
# TYPE = {
#     "0": "Integer",
#     "1": "String",
#     "2": "Blob",
#     "3": "Struct",
#     "4": "List",
#     "5": "Map",
#     "6": "Union",
#     "7": "IntList",
#     "8": "Double",
#     "9": "Tripple",
#     "10": "Float"
# }
TYPE = {
    "0": "Integer",
    "1": "String",
    "2": "Blob",
    "3": "Struct",
    "4": "List",
    "5": "Map",
    "6": "Union",
    "7": "IntList",
    "8": "ObjectType",
    "9": "ObjectId",
    "10": "Float",
}
TYPE2INT = {v: int(k) for k, v in TYPE.items()}
Tags = {}
keepalive = bytearray(16)
keepalive[13] = 128


class Blaze:
    packet = None
    readable = False

    def __init__(self, data):
        self.packet = data

    def decode(self, readable: bool = False) -> dict:
        byte_data = self.packet
        Blaze.readable = readable
        offset = 16
        length = int.from_bytes(byte_data[:4], byteorder='big') + int.from_bytes(
            byte_data[4:6], byteorder='big'
        )
        q_type = byte_data[13]
        type_ = QType.get(str(q_type), q_type)
        component = int.from_bytes(byte_data[6:8], byteorder='big')
        command = int.from_bytes(byte_data[8:10], byteorder='big')
        id_ = int.from_bytes(byte_data[11:13], byteorder='big')
        method = (
            type_
            if type_ in ["KeepAlive", "Pong"]
            else f"{Components.get(component, str(component))}."
                 + Commands[Components.get(component)][
                     QType.get(q_type, "Command")
                 ].get(str(command), str(command))
        )

        # if QType.get(str(type_)):
        #     logger.debug(
        #         f"\n头部:\n"
        #         f"    长度: {length}\n"
        #         f"    类型: {QType.get(str(type_))} {type_}\n"
        #         f"    组件: {component} {Components.get(component)}\n"
        #         f"    命令: {command} {Commands[Components.get(component)
        # ][QType.get(q_type, 'Command')].get(str(command), str(command))}\n"
        #         f"    ID: {id_}\n"
        #         f"    方法: {method}"
        #     )
        # else:
        #     component_value = Components.get(component, component)
        #     qtype_value = QType.get(q_type, 'Command')
        #     command_value = Commands.get(component_value, {}).get(qtype_value, {}).get(command, command)
        #     result = f"{component_value}.{command_value}"
        #     logger.debug(
        #         f"\n头部:\n"
        #         f"    长度: {length}\n"
        #         f"    类型: {type_}\n"
        #         f"    命令: {result}\n "
        #         f"    ID: {id_}\n"
        #         f"    方法: {method}"
        #     )

        if offset < len(byte_data):
            data = self.parse_struct(byte_data, offset, Blaze.readable)
        else:
            data = {'struct': {}}
        return {'method': method, 'type': type_, 'id': id_, 'length': length, 'data': data['struct']}

    @staticmethod
    def decode_tag(hex_str):
        tag_buffer = bytearray(4)
        tag_int = int(hex_str, 16)
        tag_buffer[0] = ((tag_int >> 18) & 63) + 32
        tag_buffer[1] = ((tag_int >> 12) & 63) + 32
        tag_buffer[2] = ((tag_int >> 6) & 63) + 32
        tag_buffer[3] = (tag_int & 63) + 32
        return tag_buffer.decode('ascii')

    @staticmethod
    def parse_integer(byte_data, offset):
        """Integer 不定长整数
        每个字节的第一位表示是否继续读取，将所有字节的后7位连起来，组成一个有符号整数（Little Endian）。
        """
        i, n = 1, byte_data[offset]
        negative = n & 0x40
        if n > 0x7f:
            n &= 0x7f
            while byte_data[offset] > 0x7f:
                offset += 1
                n += (byte_data[offset] & 0x7f) * (128 ** i * 0.5)
                i += 1
        offset += 1
        n = int(n)
        n = -n if negative else n
        return n, offset

    @staticmethod
    def parse_string(byte_data, offset):
        """String 字符串
        字符串数据由两部分组成：第一部分是一个整数（Integer，0x00），第二部分是一个长度等于该整数值的字符串。"""
        length, offset = Blaze.parse_integer(byte_data, offset)
        start = offset
        offset += length
        end = offset - 1
        try:
            return byte_data[start:end].decode('utf-8'), offset
        except UnicodeDecodeError:
            # logger.error(f"开始: {start}, 结束: {end}, 长度: {length}, offset: {offset}")
            data = None
            for i in range(length):
                with contextlib.suppress(UnicodeDecodeError):
                    data = byte_data[start:start + i].decode()
            return ("", offset) if data is None else (data, offset)

    @staticmethod
    def parse_blob(byte_data, offset):
        """Blob 二进制
        Blob数据与String相似，也由两部分组成：第一部分是一个整数（Integer，0x00），第二部分是一个长度等于该整数值的二进制数据。"""
        length, offset = Blaze.parse_integer(byte_data, offset)
        value = byte_data[offset:offset + length - 1].hex()
        offset += length
        return value, offset

    @staticmethod
    def parse_list(byte_data, header, offset):
        """List 列表
        List 数据包含多个相同类型的数据项。
        List 数据的第一个字节是 Type，表示存储的数据类型。之后是一个 Integer 类型的值，表示列表中包含的数据项的个数。最后是列表中的数据项。"""
        type_ = byte_data[offset]
        header["type"] += str(type_)
        offset += 1
        size, offset = Blaze.parse_integer(byte_data, offset)
        data = []
        if type_ == 3 and byte_data[offset] == 2:
            offset += 1
            header["type"] += "2"
        for _ in range(size):
            item_value, offset = Blaze.parse_block(byte_data, {"type": str(type_)}, offset, Blaze.readable)
            data.append(item_value)
        return data, offset

    @staticmethod
    def parse_map(byte_data, header, offset):
        """Map 键值对
        Map 数据包含多个键值对，每个键值对包含一个键和一个值。Map 数据的前两个字节分别表示键和值的类型。
        之后是一个 Integer 类型的值，表示 Map 中包含的键值对的个数。接下来是按照键-值键-值的结构排列的数据项。
        """
        key_type = str(byte_data[offset])
        val_type = str(byte_data[offset + 1])
        header["type"] += key_type + val_type
        offset += 2
        size, offset = Blaze.parse_integer(byte_data, offset)
        data = {}
        for _ in range(size):
            key_value, offset = Blaze.parse_block(byte_data, {"type": key_type}, offset, Blaze.readable)
            val_value, offset = Blaze.parse_block(byte_data, {"type": val_type}, offset, Blaze.readable)
            data[key_value] = val_value
        return data, offset

    @staticmethod
    def parse_union(byte_data, header, offset):
        """Union 联合体
        """
        data = {}
        union_type = byte_data[offset]
        header["type"] += str(union_type)
        offset += 1
        if union_type == 127:
            return data, offset
        u_header = {
            'tag': Blaze.decode_tag(byte_data[offset:offset + 3].hex()),
            'type': str(byte_data[offset + 3])
        }
        offset += 4
        result, offset = Blaze.parse_block(byte_data, u_header, offset, Blaze.readable)
        data[f"{u_header['tag'].ljust(4)} {u_header['type']}"] = result
        return data, offset

    @staticmethod
    def parse_double(buffer, offset):
        """Double 双精度浮点数
        8字节，IEEE 754 标准的双精度浮点数
        """
        double_value = struct.unpack('>d', buffer[offset:offset + 8])[0]
        offset += 8
        return double_value, offset

    @staticmethod
    def parse_object_type(buffer, offset):
        """ObjectType 类型定义
        包含两个Integer，第一个是ComponentId，第二个是TypeId
        """
        component_id, offset = Blaze.parse_integer(buffer, offset)
        component = Components.get(component_id)
        type_id, offset = Blaze.parse_integer(buffer, offset)
        type_ = TYPE[str(type_id)]
        return (component, type_), offset

    @staticmethod
    def parse_object_id(buffer, offset):
        """ObjectId 类型实体
        包含三个Integer，第一个是ComponentId，第二个是TypeId，第三个是EntityId
        """
        component_id, offset = Blaze.parse_integer(buffer, offset)
        component = Components.get(component_id)
        type_id, offset = Blaze.parse_integer(buffer, offset)
        type_ = TYPE[str(type_id)]
        entity_id, offset = Blaze.parse_integer(buffer, offset)
        return (component, type_, entity_id), offset

    @staticmethod
    def parse_tripple(byte_data, offset):
        data = []
        for _ in range(3):
            value, offset = Blaze.parse_integer(byte_data, offset)
            data.append(value)
        return data, offset

    @staticmethod
    def parse_int_list(byte_data, offset):
        """IntList 整数列表
        开头是一个Integer，后面是和开头的Int值相等数量的Int"""
        size, offset = Blaze.parse_integer(byte_data, offset)
        data = []
        for _ in range(int(size)):
            item_value, offset = Blaze.parse_integer(byte_data, offset)
            data.append(item_value)
        return data, offset

    @staticmethod
    def parse_float(buffer, offset):
        float_value = struct.unpack_from('>f', buffer, offset)[0]
        offset += 4
        return float_value, offset

    @staticmethod
    def parse_block(byte_data, header, offset, readable: bool):
        type_ = TYPE.get(header["type"], "Unknown")
        if type_ == "Integer":
            value, offset = Blaze.parse_integer(byte_data, offset)
        elif type_ == "String":
            value, offset = Blaze.parse_string(byte_data, offset)
        elif type_ == "Struct":
            data: dict = Blaze.parse_struct(byte_data, offset, readable)
            value, offset = data["struct"], data["offset"]
        elif type_ == "Blob":
            value, offset = Blaze.parse_blob(byte_data, offset)
        elif type_ == "List":
            value, offset = Blaze.parse_list(byte_data, header, offset)
        elif type_ == "Map":
            value, offset = Blaze.parse_map(byte_data, header, offset)
        elif type_ == "Union":
            value, offset = Blaze.parse_union(byte_data, header, offset)
        elif type_ == "Double":
            value, offset = Blaze.parse_double(byte_data, offset)
        elif type_ == "Tripple":
            value, offset = Blaze.parse_tripple(byte_data, offset)
        elif type_ == "IntList":
            value, offset = Blaze.parse_int_list(byte_data, offset)
        elif type_ == "Float":
            value, offset = Blaze.parse_float(byte_data, offset)
        elif type_ == "ObjectType":
            value, offset = Blaze.parse_object_type(byte_data, offset)
        elif type_ == "ObjectId":
            value, offset = Blaze.parse_object_id(byte_data, offset)
        else:
            raise TypeError("未知类型")

        return value, offset

    @staticmethod
    def parse_struct(byte_data, offset, readable: bool = False) -> dict:
        data = {}
        while byte_data[offset]:
            tag = Blaze.decode_tag(byte_data[offset:offset + 3].hex())
            type_ = str(byte_data[offset + 3])
            header = {'tag': tag, 'type': type_}
            offset += 4
            result, offset = Blaze.parse_block(byte_data, header, offset, readable)
            if readable:
                data[f"{header['tag']}".strip()] = result
            else:
                data[f"{header['tag'].ljust(4, ' ')} {str(header['type'])}"] = result
            if offset >= len(byte_data):
                break
        offset += 1
        return {'struct': data, 'offset': offset}

    def encode(self) -> bytes:
        hex_str = self.write_struct(self.packet.get('data'), end=False)

        header = ""
        length = len(hex_str) // 2

        if length > 0xFFFFFFFF:
            header += "FFFFFFFF"
            header += (length - 0xFFFFFFFF).to_bytes(2, byteorder="big").hex()
        else:
            header += length.to_bytes(4, byteorder="big").hex()
            header += "0000"

        if Methods.get(self.packet.get('method')):
            header += Methods[self.packet.get('method')][0].to_bytes(2, byteorder="big").hex()
            header += Methods[self.packet.get('method')][1].to_bytes(2, byteorder="big").hex()
        else:
            method_split = self.packet.get('method').split(".")
            header += int(method_split[0]).to_bytes(2, byteorder="big").hex()
            header += int(method_split[1]).to_bytes(2, byteorder="big").hex()

        header += self.packet.get("id", 0).to_bytes(3, byteorder="big").hex()
        header += "000000"

        return bytes.fromhex(header + hex_str)

    @staticmethod
    def write_struct(object_, end=True) -> hex:
        hex_str = ""
        for key, value in object_.items():
            tag = Blaze.encode_tag(key[:4])
            hex_str += f"{tag}0{key[5]}"
            hex_str += Blaze.write_block(key[5], value, key)
        if end:
            hex_str += "00"
        return hex_str

    @staticmethod
    def encode_tag(tag: str) -> str:
        hex_str = ""
        if tag in Tags:
            return Tags[tag]
        buffer = sum(
            ((int.from_bytes(c.encode(), byteorder='big') - 32) << (18 - 6 * i))
            for i, c in enumerate(tag)
        )
        hex_str += hex(buffer)[2:]
        Tags[tag] = hex_str
        return hex_str

    @staticmethod
    def write_block(type_str=None, value=None, key=None) -> hex:
        if TYPE[type_str] == "Integer":
            value = Blaze.write_integer(value)
        elif TYPE[type_str] == "String":
            value = Blaze.write_string(value)
        elif TYPE[type_str] == "Struct":
            value = Blaze.write_struct(value)
        elif TYPE[type_str] == "Blob":
            value = Blaze.write_blob(value)
        elif TYPE[type_str] == "List":
            value = Blaze.write_list(value, key)
        elif TYPE[type_str] == "Map":
            value = Blaze.write_map(value, key)
        elif TYPE[type_str] == "Union":
            value = Blaze.write_union(value, key)
        elif TYPE[type_str] == "Double":
            value = Blaze.write_double(value)
        elif TYPE[type_str] == "Tripple":
            value = Blaze.write_tripple(value)
        elif TYPE[type_str] == "IntList":
            value = Blaze.write_int_list(value)
        elif TYPE[type_str] == "Float":
            value = Blaze.write_float(value)
        elif TYPE[type_str] == "ObjectType":
            value = Blaze.write_object_type(value)
        elif TYPE[type_str] == "ObjectId":
            value = Blaze.write_object_id(value)
        else:
            raise TypeError(f"Unknown Type {type_str}")

        return value

    @staticmethod
    def write_integer(n):
        negative = False
        n = int(n)
        if n < 0:
            negative = True
            n = -n
        temp = [n % 64 + 128]
        n = n // 64
        while n > 0:
            temp.append(n % 128 + 128)
            n = n // 128
        if negative:
            temp[0] += 64
        temp[-1] -= 128
        return bytes(temp).hex()

    @staticmethod
    def write_string(text):
        if not text:
            return "00"
        text_hex = f"{text.encode().hex()}00"
        length = len(text_hex) // 2
        length_hex = Blaze.write_integer(length)
        return length_hex + text_hex

    @staticmethod
    def write_blob(blob_hex):
        blob_bytes = bytes.fromhex(blob_hex)
        length_hex = Blaze.write_integer(len(blob_bytes))
        return length_hex + blob_bytes.hex()

    @staticmethod
    def write_list(lst, key):
        hex_str = ""
        hex_str += f"0{key[6]}"
        hex_str += Blaze.write_integer(len(lst))  # size
        for item in lst:
            hex_str += Blaze.write_block(key[6], item, key)
        return hex_str

    @staticmethod
    def write_map(map_data, key):
        map_data = list(map_data.items())
        result = f"0{key[6]}0{key[7]}"
        result += Blaze.write_integer(len(map_data))
        for k, v in map_data:
            result += Blaze.write_block(key[6], k)
            result += Blaze.write_block(key[7], v)
        return result

    @staticmethod
    def write_union(data, key):
        if key[6]:
            hex_str = f"0{key[6]}"
            hex_str += Blaze.write_struct(data, False)
        else:
            hex_str = "7f"
        return hex_str

    @staticmethod
    def write_double(values):
        hex_str = ""
        hex_str += Blaze.write_integer(values[0])
        hex_str += Blaze.write_integer(values[1])
        return hex_str

    @staticmethod
    def write_object_type(values):
        hex_str = ""
        hex_str += Blaze.write_integer(Components2Int[values[0]])
        hex_str += Blaze.write_integer(TYPE2INT[values[1]])
        return hex_str

    @staticmethod
    def write_object_id(values):
        hex_str = ""
        hex_str += Blaze.write_integer(Components2Int[values[0]])
        hex_str += Blaze.write_integer(TYPE2INT[values[1]])
        hex_str += Blaze.write_integer(values[2])
        return hex_str

    @staticmethod
    def write_tripple(values):
        hex_str = ""
        hex_str += Blaze.write_integer(values[0])
        hex_str += Blaze.write_integer(values[1])
        hex_str += Blaze.write_integer(values[2])
        return hex_str

    @staticmethod
    def write_int_list(values):
        hex_str = ""
        hex_str += Blaze.write_integer(len(values))
        for value in values:
            hex_str += Blaze.write_integer(value)
        return hex_str

    @staticmethod
    def write_float(value):
        return struct.pack(">f", value).hex()
