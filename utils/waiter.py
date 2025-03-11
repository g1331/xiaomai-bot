from graia.ariadne.message.element import Image
from graia.broadcast.interrupt.waiter import Waiter
from graia.ariadne.message.chain import MessageChain
from graia.ariadne.event.message import (
    Group,
    Member,
    GroupMessage,
    FriendMessage,
    Friend,
)


class ConfirmWaiter(Waiter.create([GroupMessage])):
    def __init__(
        self, group: Group, member: Member, confirm_words: list[str] or None = None
    ):
        self.confirm_words = confirm_words or ["是", "y", "yes", "确认"]
        self.group_id = group.id
        self.member_id = member.id

    async def detected_event(self, group: Group, member: Member, message: MessageChain):
        if group.id == self.group_id and member.id == self.member_id:
            return message.display.strip() in self.confirm_words


class FriendConfirmWaiter(Waiter.create([FriendMessage])):
    def __init__(self, friend: Friend or int, confirm_words: list[str] or None = None):
        self.confirm_words = confirm_words or ["是", "y", "yes", "确认"]
        self.friend_id = friend.id if isinstance(friend, Friend) else friend

    async def detected_event(self, friend: Friend, message: MessageChain):
        if friend.id == self.friend_id:
            return message.display.strip() in self.confirm_words


# eg:
# await asyncio.wait_for(InterruptControl(create(Broadcast)).wait(FriendConfirmWaiter(friend)), 30)


class ImageWaiter(Waiter.create([GroupMessage])):
    def __init__(self, group: Group, member: Member):
        self.group_id = group.id
        self.member_id = member.id

    async def detected_event(self, group: Group, member: Member, message: MessageChain):
        if group.id == self.group_id and member.id == self.member_id:
            return message[Image][0] if message.has(Image) else None


class QuoteWaiter(Waiter.create([GroupMessage])):
    def __init__(self, group: Group, sender: Member):
        self.group_id = group.id
        self.sender_id = sender.id

    async def get_quote_msgChain(
        self, group: Group, sender: Member, message: MessageChain, event: GroupMessage
    ) -> MessageChain:
        if event.quote and group.id == self.group_id and sender.id == self.sender_id:
            return message
