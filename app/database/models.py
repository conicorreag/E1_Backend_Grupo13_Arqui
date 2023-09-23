from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    stocks_id = Column(String, index=True)
    datetime = Column(String, index=True)
    symbol = Column(String, index=True)
    shortName = Column(String, index=True)
    price = Column(Float)
    currency = Column(String)
    source = Column(String)



class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, index=True)
    user_sub = Column(String, index=True)
    datetime = Column(String, index=True)
    symbol = Column(String, index=True)
    quantity = Column(Integer)
    status = Column(String)  # Puede ser approved, rejected o waiting
    location = Column(String)


class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True, index=True)
    user_sub = Column(String, index=True)
    balance = Column(Float)
