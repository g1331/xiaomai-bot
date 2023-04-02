import json
import logging
import uuid
from typing import Optional

from flask import Flask, request
from loguru import logger
from pydantic import BaseModel

infos = {}
commands = {}
bots = {
    # "bot_name": {
    #     "onlineState": 1,
    #     "sessionId": "e183a98b-72b4-422b-bda5-57c57d22bdcd",
    #     "user": "bot_name",
    #     "gameId": None,
    #     "name": None,
    #     "state": "None",
    #     "path": "tunguska",
    #     "time": 1680345370863,
    # }
}


class NFBOT(BaseModel):
    onlineState: int
    sessionId: str
    user: str
    gameId: Optional[str]
    name: Optional[str]
    state: str
    path: str
    time: int


def generate_uuid():
    return str(uuid.uuid4())


flask = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


@flask.route('/', methods=['POST'])
async def index():
    global infos, commands, bots
    info = request.get_json(force=True, silent=True)
    # 传入NFBOT模型
    try:
        if info is None:
            return json.dumps({})
        nf_bot = NFBOT(**info)
    except Exception as e:
        logger.error(f"传入NFBOT模型失败, 错误信息: {e}")
        logger.error(f"传入的数据: {info}")
        return json.dumps({})
    if nf_bot.onlineState != 1:
        if nf_bot.state in [None, "None"]:
            nf_bot.state = "None"
        elif nf_bot.state == "Playing":
            nf_bot.state = "Playing"
        elif nf_bot.state == "Loading":
            #   如果超过5秒就是在游玩
            if (nf_bot.user in bots) and nf_bot.time - bots[nf_bot.user]["time"] > 5000:
                nf_bot.state = "Playing"
            else:
                nf_bot.state = "Loading"
    else:
        nf_bot.state = "Offline"
    if nf_bot.user not in bots:
        logger.info(f"{nf_bot.user} connected")
        bots[nf_bot.user] = info
    else:
        if infos[nf_bot.user].state != nf_bot.state:
            logger.info(f"{nf_bot.user}状态改变{bots[nf_bot.user]['state']}>>{nf_bot.state}")
        bots[nf_bot.user] = info
    infos[nf_bot.user] = nf_bot
    if nf_bot.user in commands:
        response_data = {'command': commands[nf_bot.user], 'id': generate_uuid()}
        logger.info(f"{nf_bot.user}执行{commands[nf_bot.user]}")
        del commands[nf_bot.user]
        return json.dumps(response_data)
    else:
        return json.dumps({})


def run_flask_app():
    logger.info("Flask app started")
    flask.run(host='0.0.0.0', port=80, debug=True, use_reloader=False)
