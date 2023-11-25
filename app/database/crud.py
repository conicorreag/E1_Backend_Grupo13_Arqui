from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from sqlalchemy.sql import cast
from sqlalchemy.types import DateTime
from . import models
from datetime import datetime, timedelta
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

def create_user_transaction(db: Session, user_sub: str, datetime: str, symbol: str, quantity: int, location):
    selected_stock = get_selected_stock(db, symbol)
    total_price = get_transaction_total_price(quantity, selected_stock)
    
    user_wallet = get_user_wallet(db, user_sub)

    transaction_status = "waiting"
    if user_wallet.balance - total_price < 0:
        transaction_status = "rejected"

    transaction = models.Transaction(
            user_sub=user_sub,
            datetime=datetime,
            symbol=symbol,
            quantity=quantity,
            status=transaction_status,
            location=location,
            request_id=uuid6.uuid7(),
            total_price=total_price,
            token=""
        )
    add_transaction_to_database(db, transaction)
    return transaction

def add_token_to_transaction(db: Session, transaction: object, token):
    transaction.token = token
    db.commit()
    db.refresh(transaction)
    return transaction


def create_general_transaction(db: Session, datetime: str, symbol: str, quantity: int, request_id: str ):
    selected_stock = get_selected_stock(db, symbol)
    if not selected_stock:
        return None
    total_price = get_transaction_total_price(quantity, selected_stock)
    transaction_status = "waiting"
    transaction = models.GeneralTransactions(
            datetime=datetime,
            symbol=symbol,
            quantity=quantity,
            status=transaction_status,
            request_id=request_id,
            total_price=total_price
        )
    add_transaction_to_database(db, transaction)
    return transaction


def get_transaction_total_price(quantity: int, selected_stock):
    price = selected_stock.price
    return float(price) * int(quantity)

def get_selected_stock(db: Session, symbol : str):
    recent_stocks = get_recent_stocks(db)
    return next((stock for stock in recent_stocks if stock.symbol == symbol), None)

def add_transaction_to_database(db: Session, transaction):
    db.add(transaction)
    db.commit()
    db.refresh(transaction)


def validate_general_transaction(db: Session, request_id: int, validation: bool):
    transaction = db.query(models.GeneralTransactions).filter(models.GeneralTransactions.request_id == request_id).first()
    if not transaction:
        return None
    status = "rejected"
    if validation:
        status = "approved"
    set_transaction_validation(db, transaction, status)
    return transaction


def validate_user_transaction(db: Session, token: str, status: str):
    transaction = db.query(models.Transaction).filter(models.Transaction.token == token).first()
    set_transaction_validation(db, transaction, status)
    return transaction


def set_transaction_validation(db: Session, transaction, status):
    transaction.status = status
    db.commit()
    db.refresh(transaction)


def make_user_pay_transaction(db: Session, transaction):
    update_user_wallet(db, transaction.user_sub, -transaction.total_price)


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
        response = models.Wallet(user_sub=user_sub, balance=0)
        db.add(response)
        db.commit()
        db.refresh(response)
    return response


def get_historical_prices(db: Session, symbol: str, initial_date: str):
    query = db.query(models.Stock).filter(models.Stock.symbol == symbol, cast(models.Stock.datetime, DateTime) >= initial_date).all()
    return query


def get_N(db: Session, symbol: str):
    # Calcula la fecha de hace 7 días desde hoy
    seven_days_ago = datetime.now() - timedelta(days=7)

    # Realiza la consulta para contar las transacciones aprobadas
    approved_count = db.query(models.GeneralTransactions) \
        .filter(models.GeneralTransactions.symbol == symbol) \
        .filter(models.GeneralTransactions.status == 'approved') \
        .filter(cast(models.GeneralTransactions.datetime, DateTime) >= seven_days_ago) \
        .count()

    return approved_count


def create_prediction(db: Session, user_sub: str, job_id: int, symbol: str, initial_date: str, final_date: str, future_dates: list, quantity: int, final_price: float, future_prices: list):
    prediction = models.Prediction(
        user_sub=user_sub,
        job_id=job_id,
        symbol=symbol,
        initial_date=initial_date,
        final_date=final_date,
        future_dates=future_dates,
        quantity=quantity,
        final_price=final_price,
        future_prices=future_prices,
        status="waiting"
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction


def update_prediction(db: Session, job_id: int, future_prices: list):
    prediction = db.query(models.Prediction).filter(models.Prediction.job_id == job_id).first()
    prediction.final_price = future_prices[-1] * prediction.quantity
    prediction.future_prices = future_prices
    prediction.status = "ready"
    db.commit()
    db.refresh(prediction)
    return prediction

def get_user_predictions(db: Session, user_sub: str):
    return db.query(models.Prediction).filter(models.Prediction.user_sub == user_sub).order_by(models.Prediction.initial_date).all()

def get_prediction(db: Session, prediction_id: int):
    return db.query(models.Prediction).filter(models.Prediction.id == prediction_id).first()
### Manejo de auctions
def create_auction(db: Session, symbol: str, quantity: int):
    selected_stock =db.query(models.StocksAvailable).filter(models.StocksAvailable.symbol == symbol)
    auction = models.Auction(
        auction_id = uuid6.uuid7(),
        proposal_id = "",
        quantity = quantity,
        stock_id = symbol,
        group_id = 13,
        status= "open"
    )

    db.add(auction)
    db.commit()
    db.refresh(auction)
    return auction

def save_proposal(db:Session, auction_id:str, proposal_id:str, symbol:str, quantity:int, group_id:int):
    Auction = db.query(models.Auction).filter(models.Auction.auction_id == auction_id)
    if not Auction or Auction.status == "closed":
        return
    proposal = models.Proposal(
        proposal_id = proposal_id,
        auction_id = auction_id,
        quantity = quantity,
        stock_id = symbol,
        group_id = group_id,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal

def get_received_proposal(db:Session, proposal_id:str):
    proposal_to_be_answered = db.query(models.Proposal).filter(models.Proposal.proposal_id == proposal_id)
    return proposal_to_be_answered

def complete_proposal_transaction(db:Session, proposal_id:str):
    auction_id = stock_exchange(db, proposal_id)
    rejected_proposals = db.query(models.Proposal).filter(models.Proposal.auction_id == auction_id)
    return rejected_proposals

def stock_exchange(db:Session, proposal_id:str):
    accepted_proposal = db.query(models.Proposal).filter(models.Proposal.proposal_id == proposal_id)
    accepted_auction = db.query(models.Auction).filter(models.Auction.auction_id == accepted_proposal.auction_id)
    
    received_stock = db.query(models.StocksAvailable).filter(models.StocksAvailable.symbol == accepted_proposal.stock_id)
    received_stock.quantity += accepted_proposal.quantity
    db.commit()
    db.refresh(received_stock)
    
    given_stock = db.query(models.StocksAvailable).filter(models.StocksAvailable.symbol == accepted_auction.stock_id)
    given_stock.quantity -= accepted_auction.quantity
    db.commit()
    db.refresh(given_stock)
    
    accepted_auction.status = "closed"
    accepted_proposal.delete()
    db.commit()
    return accepted_auction.auction_id

def delete_proposal(db: Session, proposal_to_be_deleted):
    proposal_to_be_deleted.delete()
    db.commit()
    
def save_auction(db: Session, auction_id : str, symbol : str, quantity : int, group_id : int):
    auction = models.Auction(
        auction_id = auction_id,
        proposal_id = "",
        quantity = quantity,
        stock_id = symbol,
        group_id = group_id,
        status= "open"
    )
    db.add(auction)
    db.commit()
    db.refresh(auction)
    return auction

def create_proposal(db:Session, auction_id:str, symbol:str, quantity:int):
    Auction = db.query(models.Auction).filter(models.Auction.auction_id == auction_id)
    if not Auction or Auction.status == "closed":
        return
    proposal = models.Proposal(
        proposal_id = uuid6.uuid7(),
        auction_id = auction_id,
        quantity = quantity,
        stock_id = symbol,
        group_id = 13,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal

def complete_auction_transaction(db:Session, proposal_id:str):
    stock_exchange(db, proposal_id)