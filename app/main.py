from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, engine
from sqlalchemy import String , select, ForeignKey, UniqueConstraint, and_
import os 
load_dotenv()
from sqlalchemy.orm import DeclarativeBase ,Mapped,mapped_column
from app.security import hash_password , verify_password
from app.auth import create_access_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth import create_access_token, SECRET_KEY, ALGORITHM
import jwt
from typing import Literal
import redis.asyncio as redis
import json
security = HTTPBearer()
app = FastAPI()

redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
)


class Taskstatusupdate(BaseModel):
    new_status: Literal["todo", "in_progress", "done"]

class Base (DeclarativeBase):
    pass

class User(Base):
    __tablename__ ="users"
    id:Mapped[int]=mapped_column(primary_key=True)
    username:Mapped[str]=mapped_column(String(50))
    email:Mapped[str]=mapped_column(String(255),unique=True)
    password_hash:Mapped[str]=mapped_column(String(255))
    role : Mapped[str]=mapped_column(String(20),default="employee")

class TaskCreate(BaseModel):
    title: str
    description : str
    board_id : int
    priority: str="medium"
    assigned_to: int |None=None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload["user_id"]

    except (jwt.InvalidTokenError, KeyError):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials"
        )

    statement = select(User).where(User.id == user_id)
    result = await db.execute(statement)

    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    return user

class UserCreate(BaseModel):
    username: str
    email:str
    password: str

class UserUpdate(BaseModel):
    username:str | None=None
    email:str | None=None

class UserResponse(BaseModel):
    id:int
    username:str    
    email:str

class BoardCreate(BaseModel):
    name: str
    description: str | None = None

class BoardUpdate(BaseModel):
    name:str | None=None
    description:str | None=None

class BoardMemberCreate(BaseModel):
    user_id:int 

class Task(Base):
    __tablename__="tasks"
    id:Mapped[int]=mapped_column(primary_key=True)
    title:Mapped[str]=mapped_column(String(500))
    description:Mapped[str|None]=mapped_column(String(500),nullable=True)
    status:Mapped[str]=mapped_column(String(50),default="todo")
    priority:Mapped[str]=mapped_column(String(20),default="medium")
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id"))
    assigned_to:Mapped[int|None]=mapped_column(ForeignKey("users.id"),nullable=True)
    created_by: Mapped[int]=mapped_column(ForeignKey("users.id"))


class UserLogin(BaseModel):
    email:str
    password:str



class ConnectionManager:

    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

manager = ConnectionManager()



@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    pubsub = redis_client.pubsub()
    await pubsub.subscribe("task_updates")

    async def receive_messages():
        try:
            while True:
                data = await websocket.receive_json()

                await redis_client.publish(
                    "task_updates",
                    json.dumps(data)
                )
        except WebSocketDisconnect:
            pass

    async def send_messages():
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await websocket.send_text(message["data"])
        except WebSocketDisconnect:
            pass

    import asyncio

    try:
        await asyncio.gather(
            receive_messages(),
            send_messages()
        )
    finally:
        await pubsub.unsubscribe("task_updates")
        await pubsub.close()



@app.get("/me",response_model=UserResponse)
async def get_me(
    current_user:User=Depends(get_current_user)
):
    return current_user
async def requires_manager(
        current_user:User = Depends(get_current_user)
):
    if current_user.role != "manager":
        raise HTTPException(status_code=403,detail = "Permission Required")
    return current_user

@app.get("/manager-test")
async def manager_test(
    current_user:User = Depends(requires_manager)
):
    return{
        "message":"Manager access granted",
        "username": current_user.username
    }

@app.get("/tasks")
async def get_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "manager":
        statement = select(Task)
    else:
        statement = select(Task).where(Task.assigned_to == current_user.id)

    result = await db.execute(statement)
    tasks = result.scalars().all()
    return tasks




@app.get("/tasks/{task_id}")
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    statement = select(Task).where(Task.id == task_id)
    result = await db.execute(statement)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404,detail="Task not found")

    if current_user.role != "manager":
        if task.assigned_to != current_user.id:
            raise HTTPException(status_code=403,detail="Permission denied")
    return task


@app.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    data: Taskstatusupdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    statement = select(Task).where(Task.id == task_id)
    result = await db.execute(statement)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role != "manager":
        if task.assigned_to != current_user.id:
            raise HTTPException(status_code=403, detail="Permission denied")

    if data.new_status == "done" and task.status != "in_progress":
        raise HTTPException(status_code=403,detail="Task can only be marked done from in_progress")

    task.status = data.new_status

    await db.commit()
    await db.refresh(task)

    await redis_client.publish(
        "task_updates",
        json.dumps({
            "task_id": task.id,
            "status": task.status,
            "board_id": task.board_id,
            "updated_by": current_user.id
        })
    )

    return task


@app.post("/task")
async def create_task(
    data: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(requires_manager)
):
    statement = select(Board).where(Board.id == data.board_id)
    result = await db.execute(statement)
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404,detail="Board not found")

    if data.assigned_to is not None:
        statement = select(User).where(User.id == data.assigned_to)
        result = await db.execute(statement)
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(status_code=404,detail="Assigned user not found")

    new_task = Task(
        title=data.title,
        description=data.description,
        board_id=data.board_id,
        priority=data.priority,
        assigned_to=data.assigned_to,
        created_by=current_user.id
    )

    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)
    return new_task


@app.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User =Depends(requires_manager)
):
    statement = select(Task).where(Task.id == task_id)
    result = await db.execute(statement)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404,detail="Task not found")

    await db.delete(task)
    await db.commit()
    return {"message": "Task deleted successfully"}



@app.post("/login")
async def login_user(
    data:UserLogin,
    db:AsyncSession=Depends(get_db)
):
    statement = select(User).where(User.email == data.email)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is None :
        raise HTTPException(status_code=401,detail="Invalid User or password ")
    if not verify_password(data.password,user.password_hash):
            raise HTTPException(status_code=401,detail="Invalid User or password")
    access_token = create_access_token(user.id)

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
    

@app.post("/register")
async def register_user(
    data:UserCreate,
    db:AsyncSession=Depends(get_db)
):
    statement = select(User).where(User.email == data.email)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is not None:
        raise HTTPException(status_code = 404,detail="Email already registered")
    password_hash = hash_password(data.password)
    new_user = User(
        username = data.username,
        email=data.email,
        password_hash=password_hash,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


@app.post("/boards/{board_id}/members")
async def add_board_member(
    board_id:int,
    data:BoardMemberCreate,
    db:AsyncSession=Depends(get_db)
):
    statement = select(Board).where(Board.id == board_id)
    result = await db.execute(statement)
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404,detail="Board is not found")
    statement = select(User).where(User.id == data.user_id)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    new_member= BoardMember(
        board_id=board_id,
        user_id=data.user_id
    )
    db.add(new_member)
    await db.commit()
    return{"message":"Member Created Sucessfully"}

@app.get("/boards/{board_id}/members")
async def get_board_memebers(
    board_id:int,
    db:AsyncSession=Depends(get_db)
):
    statement = select(Board).where(Board.id == board_id)
    result = await db.execute(statement)
    board = result.scalar_one_or_none()

    if board is None:
        raise HTTPException(status_code=404, detail="Board not found")
    statement = select(BoardMember).where(BoardMember.board_id == board_id)
    result = await db.execute(statement)
    members = result.scalars().all()
    return members

@app.delete("/boards/{board_id}/members/{user_id}")
async def remove_board_members(
    board_id:int,
    user_id:int,
    db:AsyncSession=Depends(get_db),
    current_user : User = Depends (requires_manager)
):
    statement=select(BoardMember).where(
    and_(
        BoardMember.board_id== board_id,
        BoardMember.user_id ==user_id
     )
    )
    result = await db.execute(statement)
    member = result.scalar_one_or_none()
    if member is None :
        raise HTTPException(status_code=404,detail="Member not found")
    await db.delete(member)
    await db.commit()
    return{"message":"Member removed Sucessfully"}

    

class Board(Base):
    __tablename__ = "boards"
    id: Mapped[int] = mapped_column(primary_key=True) 
    name:Mapped[str]=mapped_column(String(100))
    description:Mapped[str|None]=mapped_column(String(500),nullable=True)

class BoardMember(Base):
    __tablename__="board_members"
    id:Mapped[int]=mapped_column(primary_key=True)
    board_id:Mapped[int]=mapped_column(ForeignKey("boards.id"))
    user_id:Mapped[int]=mapped_column(ForeignKey("users.id"))

    __table_args__=(
        UniqueConstraint("board_id","user_id"),
    )


@app.post("/boards")
async def create_board(
    data: BoardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User=Depends(requires_manager)
):
    new_board = Board(
        name=data.name,
        description=data.description
    )

    db.add(new_board)
    await db.commit()
    return{
        "messaage":"Board Created Sucessfully",
        "board_id": new_board.id
    }

@app.get("/boards/{board_id}")
async def get_boards(
    board_id:int,
    db:AsyncSession=Depends(get_db)
    ):
    statement = select(Board).where(Board.id == board_id)
    result = await db.execute(statement)
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404,detail="Board not found")
    return board


@app.patch("/boards/{board_id}")
async def update_boards(
        board_id:int,
        data:BoardUpdate,
        db:AsyncSession=Depends(get_db),
        current_user : User = Depends(requires_manager)
):
    statement = select(Board).where(Board.id == board_id)
    result = await db.execute(statement)
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404,detail="Board not found")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(board, field, value)
    await db.commit()
    return board

@app.delete("/boards/{board_id}")
async def delete_boards(
    board_id:int,
    db:AsyncSession=Depends(get_db),
    current_user : User = Depends(requires_manager)
):
    statement = select(Board).where(Board.id == board_id)
    result = await db.execute(statement)
    board = result.scalar_one_or_none()
    if board is None:
        raise HTTPException(status_code=404,detail="Board not found")
    await db.delete(board)
    await db.commit()
    return {"message": "Board deleted successfully"}



@app.get("/users/{user_id}",response_model=UserResponse)
async def get_users(user_id:int ,db:AsyncSession=Depends(get_db)):
    statement = select(User).where(User.id==user_id)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404 , detail="User not found")
    
    return user

@app.post("/user")
async def create_user(data:UserCreate,db:AsyncSession=Depends(get_db)):
    new_user = User(
            username = data.username,
            password_hash = data.password,
            email = data.email,
        )
    db.add(new_user)
    await db.commit()
    return{"message":"User Created","User_id":new_user.id}

@app.patch("/users/{user_id}" ,response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession=Depends(get_db),
    current_user : User = Depends (requires_manager)
):
    statement = select(User).where(User.id==user_id)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is None :
        raise HTTPException(status_code=404, detail="User not found")
    update_data= data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    await db.commit()
    return user

@app.delete("/users/{user_id}")
async def delete_user(
    user_id:int,
    db:AsyncSession=Depends(get_db)
):
    statement = select(User).where(User.id==user_id)
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404,detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"message":"User deleted Sucessfully"}

@app.get("/db-test")
async def db_test(db: AsyncSession = Depends(get_db)):
    return {"message": "Database session received"}

@app.on_event("startup")
async def startup():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)




























#-------------------------------------------------------------------------------------------------------------------------------------------

@app.get("/")
def home():
    return {"message":"Task Board API is running"}


#-------------------------------------------------------------------------------------------------------------------------------------------

            
            