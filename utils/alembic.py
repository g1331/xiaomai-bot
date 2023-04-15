from sqlalchemy.exc import InternalError, ProgrammingError

from creart import create
from launart import Launchable, Launart

from core.bot import Umaru
from core.orm import orm


class AlembicService(Launchable):
    id = "umaru.core.alembic"

    @property
    def required(self):
        return set()

    @property
    def stages(self):
        return {"preparing"}

    async def launch(self, _mgr: Launart):
        async with self.stage("preparing"):
            try:
                _ = await orm.init_check()
                core = create(Umaru)
                _ = await core.alembic()
            except (AttributeError, InternalError, ProgrammingError):
                _ = await orm.create_all()
