from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, CheckConstraint

from core.orm import orm


class MemberPerm(orm.Base):
    """
    -1为全局黑 对应群号为0
    0为单群黑
    16为群员
    32为管理
    64为群主
    128为Admin
    256为Master
    """
    __tablename__ = 'MemberPerm'

    group_id = Column(Integer, primary_key=True)
    qq = Column(Integer, primary_key=True)
    perm = Column(Integer, nullable=False, info={'check': [-1, 0, 16, 32, 64, 128, 256]}, default=16)


class GroupPerm(orm.Base):
    """
    0为非活动群组
    1为正常活动群组
    2为vip群组
    3为测试群组
    """
    __tablename__ = 'GroupPerm'

    group_id = Column(Integer, primary_key=True)
    group_name = Column(String(length=60), nullable=False)
    perm = Column(Integer, nullable=False, info={'check': [0, 1, 2, 3]}, default=1)
    active = Column(Boolean, default=True)


class PermissionGroup(orm.Base):
    __tablename__ = 'PermissionGroup'

    id = Column(Integer, primary_key=True)
    group_name = Column(String(length=60), nullable=False, primary_key=True)
    type = Column(String, CheckConstraint('type in ("default", "admin")'))
    default_perm = Column(Integer, info={'check': [16, 32]})


# ForeignKey:外键约束,指定这一列的值必须是另一个表中的某列的值。
# 这可以避免出现指向不存在的权限组的情况，同时也方便数据库维护和更新。
# 例如，如果你想要删除一个权限组，数据库会自动删除该权限组下的所有成员，因为它们的外键都指向了该权限组的主键。
# 这意味着，如果你在PermissionGroup表中删除了一个具有特定id的行，则PermissionGroupPerm表中所有group_id列等于这个特定的id的行都会被删除。
# 这被称为级联删除。

class PermissionGroupPerm(orm.Base):
    """
    所属权限组的权限
    """
    __tablename__ = 'PermissionGroupPerm'

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey('PermissionGroup.id'))
    qq = Column(String)
    perm = Column(Integer, nullable=False, info={'check': [0, 16, 32, 64]})
