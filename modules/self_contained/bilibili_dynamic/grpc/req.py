import grpc.aio

from loguru import logger
from grpc import RpcError
from grpc_status import rpc_status
from google.protobuf.json_format import MessageToDict

from .bilibili.app.dynamic.v2.dynamic_pb2 import DynSpaceReq
from .bilibili.app.dynamic.v2.dynamic_pb2_grpc import DynamicStub

server = "grpc.biliapi.net"


async def grpc_dyn_get(uid: int):

    async with grpc.aio.secure_channel(server, grpc.ssl_channel_credentials()) as channel:
        stub = DynamicStub(channel)
        req = DynSpaceReq(host_uid=int(uid))
        meta = (("x-bili-device-bin", b""),)
        try:
            resp = await stub.DynSpace(req, metadata=meta)
        except RpcError as e:
            status = rpc_status.from_call(e)
            logger.error({MessageToDict(status, preserving_proto_field_name=True)})
        return MessageToDict(resp, preserving_proto_field_name=True)
