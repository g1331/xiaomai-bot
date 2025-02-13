from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

DATA_PATH = "data/random_wife"


class Wife(Base):
    __tablename__ = 'wives'

    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    file_path = Column(String(500))
    owner_qq = Column(String(20), nullable=True)
    owner_name = Column(String(100), nullable=True)
    is_favorite = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DrawRecord(Base):
    __tablename__ = 'draw_records'

    id = Column(Integer, primary_key=True)
    user_qq = Column(String(20))
    wife_id = Column(Integer)
    draw_time = Column(DateTime, default=datetime.now)


# 初始化数据库连接
engine = create_engine(f"sqlite:///{DATA_PATH}/wives.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
