from pathlib import Path

from graia.saya import Channel

from core.models import saya_model

module_controller = saya_model.get_module_controller()
channel = Channel.current()
channel.name("BF1入群审核")
channel.description("处理群加群审核")
channel.author("13")
channel.metadata = module_controller.get_metadata_from_path(Path(__file__))
