from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from sqlalchemy.sql import cast
from sqlalchemy.types import DateTime
from . import models
import uuid6


def create_stock(db: Session, stocks_id: int, datetime: str, symbol: str, shortName: str, price: float, currency: str, source: str):
    stock = models.Stock(
        stocks_id=stocks_id,
        datetime=datetime,
        symbol=symbol,
        shortName=shortName,
        price=price,
        currency=currency,
        source=source
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


def get_stock(db: Session, symbol: str):
    return db.query(models.Stock).filter(models.Stock.symbol == symbol).first()


def get_recent_stocks(db: Session):
    subquery = (
        db.query(models.Stock.symbol, func.max(cast(models.Stock.datetime, DateTime)).label("max_datetime"))
        .group_by(models.Stock.symbol)
        .subquery()
    )
    stocks_data = (
        db.query(models.Stock)
        .join(subquery, and_(models.Stock.symbol == subquery.c.symbol, cast(models.Stock.datetime, DateTime) == subquery.c.max_datetime))
        .all()
    )
    return stocks_data


def create_transaction(db: Session, user_sub: str, datetime: str, symbol: str, quantity: int, location):
    recent_stocks = get_recent_stocks(db)
    selected_stock = next((stock for stock in recent_stocks if stock.symbol == symbol), None)
    user_wallet = get_user_wallet(db, user_sub)
    price = selected_stock.price
    total_price = float(price) * int(quantity)
    transaction_status = "waiting"

    if user_wallet.balance - total_price < 0:
        transaction_status = "rejected"
    else:
        update_user_wallet(db, user_sub, -total_price)

    transaction = models.Transaction(
        user_sub=user_sub,
        datetime=datetime,
        symbol=symbol,
        quantity=quantity,
        status=transaction_status,
        location=location,
        request_id=uuid6.uuid7()
    )
    
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def validate_transaction(db: Session, request_id: int, validation: bool):
    transaction = db.query(models.Transaction).filter(models.Transaction.request_id == request_id).first()
    if validation:
        transaction.status = "approved"
    else:
        transaction.status = "rejected"
    db.commit()
    db.refresh(transaction)
    return transaction


def get_user_transactions(db: Session, user_sub: str):
    return db.query(models.Transaction).filter(models.Transaction.user_sub == user_sub).order_by(models.Transaction.datetime).all()


def update_user_wallet(db: Session, user_sub: str, amount: float):
    wallet = db.query(models.Wallet).filter(models.Wallet.user_sub == user_sub).first()
    if not wallet:
        wallet = models.Wallet(user_sub=user_sub, balance=amount)
        db.add(wallet)
    else:
        wallet.balance += amount
    db.commit()
    db.refresh(wallet)
    return wallet


def get_user_wallet(db: Session, user_sub: str):
    response =  db.query(models.Wallet).filter(models.Wallet.user_sub == user_sub).first()
    if not response:
        wallet = models.Wallet(user_sub=user_sub, balance=0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    print("----------aquiiii---------")
    print(user_sub)
    print(wallet)
    return wallet
