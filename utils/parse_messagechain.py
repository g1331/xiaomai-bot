from graia.amnesia.message import MessageChain
from graia.ariadne.message.element import At, Plain


def get_targets(message: MessageChain) -> list[int]:
    ats = message.get(At)
    plains = message.get(Plain)
    return [at.target for at in ats] + \
           [int(qid) for qid in "".join([plain.text for plain in plains]).strip().split(" ") if qid.isdigit()]
