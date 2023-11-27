from fastapi import APIRouter, Depends, Request, Query, Path
from sqlalchemy.orm import Session
from database import crud
from database.models import Stock
from database import database
import json

from fastapi.responses import RedirectResponse 
from api.webpay import webpay_plus_create, webpay_plus_commit
from api.functions import create_list_from_stock_data, get_location, sumar_dias_a_fechas

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
import os
import requests
from datetime import datetime, timedelta
import httpx
load_dotenv()

HOST = os.getenv("HOST")
PORT = 9000
USER = os.getenv("USER")
PASSWORD = os.getenv("PASSWORD")
REQUESTS_TOPIC = "stocks/requests"
VALIDATION_TOPIC = "stocks/validation"
GROUP_ID = "13"
JOB_URL = "http://producer:8080/job"
client = mqtt.Client()
client.username_pw_set(USER, PASSWORD)


def on_connect(client, userdata, flags, rc):
    print("Conectado al broker con código:", rc)


def on_connect(client, userdata, flags, rc):
    print("Solicitud de compra enviada: ", rc)


router = APIRouter()


@router.post("/create_stocks/")
async def create_stock(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    print(data)
    list_data = create_list_from_stock_data(data)
    for stock in list_data:
        crud.create_stock(db, stock["stocks_id"], stock["datetime"], stock["symbol"], stock["shortName"], stock["price"], stock["currency"], stock["source"])


@router.get("/stocks")
def show_stocks(db: Session = Depends(database.get_db)):
    return crud.get_recent_stocks(db)


@router.get("/stocks/{symbol}")
def get_stocks_by_symbol_paginated(
    symbol: str = Path(..., title="Symbol"),
    page: int = Query(1, description="Page number", gt=0),
    size: int = Query(30, description="Number of events per page", gt=0),
    db: Session = Depends(database.get_db)
):
    stocks_query = (
        db.query(Stock)
        .filter(Stock.symbol == symbol)
        .order_by(Stock.datetime)
    )

    stocks_paginated = stocks_query.offset((page - 1) * size).limit(size).all()

    return stocks_paginated


@router.post("/transactions_webpay/")
async def set_validation(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    token_purchase = data["token"]
    is_tbk = data["tbk"]
    if(is_tbk == False):
        status,token =  await webpay_plus_commit(token_purchase)
    elif(is_tbk == True):
        status = "user canceled"
    transaction = crud.validate_user_transaction(db, token_purchase, status)
    send_validation(transaction)
    if transaction.status == "approved":
        crud.make_user_pay_transaction(db, transaction)
    return {"status": status}
    

@router.patch("/transactions/general/")
async def set_validation(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    purchase = data["request_id"]
    validation = data["valid"]
    return crud.validate_general_transaction(db, purchase, validation)


@router.post("/transactions/general/")
async def purchase_request(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    transaction = crud.create_general_transaction(db, datetime=data["datetime"], symbol=data["symbol"], quantity=data["quantity"], request_id=data["request_id"])
    return transaction


@router.post("/transactions/")
async def purchase_request(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    ip = request.client.host
    location = get_location(ip)
    transaction = crud.create_user_transaction(db, user_sub=data["user_sub"], datetime=data["datetime"], symbol=data["symbol"], quantity=data["quantity"], location=location,admin=False)
    response =  await webpay_plus_create(transaction.id, transaction.total_price)
    crud.add_token_to_transaction(db, transaction, response["token"])
    if (transaction.status != "rejected"):
        send_request(transaction,response["token"])
    return json.dumps({"url":response["url"],"request_id":transaction.request_id,"token":response["token"], "status":transaction.status})

@router.post("/transactions/admin/")
async def purchase_request(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    ip = request.client.host
    location = get_location(ip)
    transaction = crud.create_user_transaction(db, user_sub=data["user_sub"], datetime=data["datetime"], symbol=data["symbol"], quantity=data["quantity"], location=location,admin=True)
    response =  await webpay_plus_create(transaction.id, transaction.total_price)
    crud.add_token_to_transaction(db, transaction, response["token"])
    if (transaction.status != "rejected"):
        send_request(transaction,response["token"])
    return json.dumps({"url":response["url"],"request_id":transaction.request_id,"token":response["token"], "status":transaction.status})



def send_request(transaction,token):
    request_id = transaction.request_id
    broker_message = {
        "request_id": request_id,
        "group_id": GROUP_ID,
        "symbol": transaction.symbol,
        "datetime": transaction.datetime,
        "deposit_token": token,
        "quantity": transaction.quantity,
        "seller": GROUP_ID
    }
    client.connect(HOST, PORT)
    client.publish(REQUESTS_TOPIC, json.dumps(broker_message))


def send_validation(transaction):
    request_id = transaction.request_id
    is_valid = transaction.status == "approved"
    broker_message = {
        "request_id": request_id,
        "group_id": GROUP_ID,
        "seller": GROUP_ID,
        "valid": is_valid
    }
    client.connect(HOST, PORT)
    client.publish(VALIDATION_TOPIC, json.dumps(broker_message))


@router.get("/transactions/{user_sub}")
async def get_user_transactions(user_sub: str, db: Session = Depends(database.get_db)):
    return crud.get_user_transactions(db, user_sub)


@router.put("/wallet/")
async def update_user_wallet(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    return crud.update_user_wallet(db, data["user_sub"], data["amount"])


@router.get("/wallet/{user_sub}")
async def get_user_wallet(user_sub: str, db: Session = Depends(database.get_db)):
    return crud.get_user_wallet(db, user_sub)


@router.post("/create_prediction/")

# LE LLEGA {final_date: '2024-02-01', quantity: '8', symbol: 'AMZN', user_sub: 'google-oauth2|101188055086216254198'}

async def create_prediction(request: Request, db: Session = Depends(database.get_db)):
    request_data = await request.json()
    print("llegó a crear-----------------------")

    # sacar datos:  # {historial: [{fecha: 1/2/5, precio: 1}, {fecha: 132/5, precio: 12}], N: 3}
    today_date = datetime.today()
    future_date = datetime.strptime(request_data["final_date"], "%Y-%m-%d")
    days = (future_date - today_date).days
    initial_date = datetime.now() - timedelta(days=days)
   

    result = crud.get_historical_prices(db, request_data["symbol"], initial_date)

    # Formatear los resultados en la estructura deseada
    historical_prices = [{"fecha": entry.datetime, "precio": entry.price} for entry in result]
    historical_dates = [entry.datetime for entry in result]
    future_dates = sumar_dias_a_fechas(historical_dates, days)
    print("-------historical_dates-------")
    print(historical_dates)
    print("--------days--------")
    print(days)
    print("-------future_dates-------")
    print(future_dates)


    N = crud.get_N(db, request_data["symbol"])
    print("-------N-------")
    print(N)


    # Crear un diccionario final
    datos = {"historial": historical_prices, "N": N}
    
    # async with httpx.AsyncClient() as client:
    #     response = await client.post("http://producer:8080/job", json=datos)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post("http://producer:8080/job", json=datos)

    
    print("-------response-------")
    print(response.json())
    job_id = response.json().get("job_id")
    crud.create_prediction(db=db, user_sub=request_data["user_sub"], job_id=job_id, symbol=request_data["symbol"], initial_date=today_date, final_date=request_data["final_date"], future_dates=future_dates, quantity=request_data["quantity"], final_price=0, future_prices=[])
    return response.json()



@router.get("/user_predictions/{user_sub}")
async def get_user_predictions(user_sub: str, db: Session = Depends(database.get_db)):
    predictions = crud.get_user_predictions(db, user_sub)
    for prediction in predictions:
        if prediction.status == "waiting":
            async with httpx.AsyncClient() as client:
                job_id = prediction.job_id
                response = await client.get(f"http://producer:8080/job/{job_id}")
                lista_ys = response.json().get("result")
            if lista_ys:
                crud.update_prediction(db, prediction.job_id, lista_ys)
    return crud.get_user_predictions(db, user_sub)


@router.get("/prediction/{prediction_id}")
async def get_prediction(prediction_id: int, db: Session = Depends(database.get_db)):
    return crud.get_prediction(db, prediction_id)
    

@router.get("/job_heartbeat/")
async def heartbeat_job():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://producer:8080/heartbeat")
    return response.json()
### manejo auctions

def send_message_to_auction_channel(auction, message : str):
    proposal_id = ""
    if message != "offer":
        proposal_id = auction.proposal_id
    broker_message = {
        "auction_id": auction.auction_id,
        "proposal_id": proposal_id,
        "stock_id": auction.stock_id,
        "quantity": auction.quantity,
        "group_id": auction.group_id,
        "type": message
        }
    client.connect(HOST, PORT)
    client.publish("stocks/auctions", json.dumps(broker_message))

## Primer Flujo (GRUPO 13 ENVIA AUCTION)
@router.post("/auctions/send/") # send auction
async def create_auction(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    # if(crud.stock_check(db, data["symbol"], data["quantity"])):
    auction = crud.create_auction(db, data["symbol"], data["quantity"])
    send_message_to_auction_channel(auction, "offer")
    return {"status": "ok","auction_id":auction.auction_id}
    # else:
    #     return {"status": "stocks insuficientes"}

#################################################
@router.post("/proposals/receive/") # receive proposal
async def receive_proposal(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    auction_id = data["auction_id"]
    proposal_id = data["proposal_id"]
    symbol = data["stock_id"]
    quantity = data["quantity"]
    group_id = data["group_id"]
    type = data["type"]
    proposal = crud.save_proposal(db, auction_id, proposal_id, symbol, quantity, group_id,type)
    return {"status": "ok","proposal_id":proposal_id}

################################################
@router.post("/proposals/answer/") # send proposal answer
async def answer_proposal(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    proposal_id = data["proposal_id"] # Solo aceptar, si llega aca no se rechaza
    proposal_answer = "acceptance"
    proposal_to_be_answered = crud.get_received_proposal(db, proposal_id)
    if proposal_answer == "acceptance" :
        send_message_to_auction_channel(proposal_to_be_answered, proposal_answer)
        rejected_proposals = crud.complete_proposal_transaction(db, proposal_id)
        if(rejected_proposals):
            for rejected_proposal in rejected_proposals:
                send_message_to_auction_channel(rejected_proposal, "rejection")
                crud.delete_proposal(rejected_proposal)
        return {"status": "ok",proposal_answer: proposal_to_be_answered.proposal_id}

    else:
        return {"status": "stocks insuficientes"}




## Segundo Flujo (GRUPO 13 RECIBE AUCTION)
@router.post("/auctions/receive/") # receive auction
async def save_auction(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    auction_id = data["auction_id"]
    symbol = data["stock_id"]
    quantity = data["quantity"]
    group_id = data["group_id"]
    auction = crud.save_auction(db, auction_id, symbol, quantity, group_id)
    return {"status": "ok","auction_id":auction.auction_id}

########################################
@router.post("/proposals/send/") # send proposal
async def receive_proposal(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    auction_id = data["auction_id"]
    symbol = data["stock_id"]
    quantity = data["quantity"]
    
    proposal_to_be_sent = crud.create_proposal(db, auction_id, symbol, quantity)
    send_message_to_auction_channel(proposal_to_be_sent, "proposal")
    return {"status": "ok","proposal_id":proposal_to_be_sent.proposal_id}
   

################################################
@router.post("/auctions/answer/") # receive proposal answer
async def answer_auctions(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    proposal_id = data["proposal_id"]
    proposal_answer = data["type"]    
    if proposal_answer == "acceptance":
        crud.stock_exchange_buy(db, proposal_id)
        
    elif proposal_answer == "rejection":
        rejected_proposal = crud.get_received_proposal(db, proposal_id)
        crud.delete_proposal(db, rejected_proposal)

    return {"status": "ok"}

@router.get("/stocks_available/")
async def get_stocks_available(db: Session = Depends(database.get_db)):
    return crud.get_stocks_available(db)


@router.get("/auctions_available/")
async def get_auctions_available(db: Session = Depends(database.get_db)):
    return crud.get_auctions_available(db)

@router.get("/auctions/admin/")
async def get_auctions_admin(db: Session = Depends(database.get_db)):
    return crud.get_auctions_admin(db)

@router.post("/proposals_available/")
async def get_proposals_available(request: Request, db: Session = Depends(database.get_db)):
    data = await request.json()
    auction_id = data["auction_id"]
    return crud.get_proposals_available(db,auction_id)

