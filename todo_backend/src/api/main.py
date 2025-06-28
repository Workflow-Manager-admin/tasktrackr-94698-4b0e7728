from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

# --- Dummy in-memory "database" ---
# In production, replace with a SQL database and proper ORM.
from uuid import uuid4

# Config settings (for demo; in production, load from .env)
SECRET_KEY = "todo_super_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Dummy user db
fake_users_db = {}

# Dummy task db: mapping user_id -> list of tasks
fake_tasks_db = {}

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

# --- MODELS ---


class User(BaseModel):
    id: str
    username: str
    hashed_password: str


class UserCreate(BaseModel):
    username: str = Field(..., description="Username for registration or login")
    password: str = Field(..., description="Password")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class TaskBase(BaseModel):
    title: str = Field(..., description="Title of the task")
    description: Optional[str] = Field("", description="Detailed description")
    due_date: Optional[datetime] = Field(
        None, description="Due date and time (optional)"
    )
    completed: bool = Field(False, description="Task completion status")


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None


class Task(TaskBase):
    id: str


# --- FASTAPI INSTANCE ---


app = FastAPI(
    title="ToDo Backend API",
    description=(
        "Backend for the ToDo List App. Provides endpoints for user authentication and task "
        "management."
    ),
    version="1.0.0",
    openapi_tags=[
        {'name': 'auth', 'description': 'User registration and authentication'},
        {'name': 'tasks', 'description': 'Task management: create, edit, delete, filter, complete'}
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Should be restricted in production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- UTILITY FUNCTIONS ---


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user(username: str):
    return fake_users_db.get(username, None)


def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user

# --- AUTH ROUTES ---


# PUBLIC_INTERFACE
@app.post(
    "/register",
    response_model=Token,
    tags=["auth"],
    summary="Register a new user",
    description=(
        "Register a user with a username and password. Returns a JWT token upon success."
    )
)
async def register_user(user_data: UserCreate):
    if user_data.username in fake_users_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    user_id = str(uuid4())
    hashed_password = get_password_hash(user_data.password)
    user = User(id=user_id, username=user_data.username, hashed_password=hashed_password)
    fake_users_db[user_data.username] = user
    # Create empty task list for the user
    fake_tasks_db[user_id] = []
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}


# PUBLIC_INTERFACE
@app.post(
    "/login",
    response_model=Token,
    tags=["auth"],
    summary="User login",
    description="Authenticate a user and obtain a JWT token."
)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# --- TASK ROUTES ---


# PUBLIC_INTERFACE
@app.post(
    "/tasks",
    response_model=Task,
    tags=["tasks"],
    summary="Create a task",
    description="Create a new task for the authenticated user."
)
async def create_task(
    task_in: TaskCreate,
    current_user: User = Depends(get_current_user)
):
    task_id = str(uuid4())
    task = Task(id=task_id, **task_in.dict())
    fake_tasks_db[current_user.id].append(task)
    return task


# PUBLIC_INTERFACE
@app.get(
    "/tasks",
    response_model=List[Task],
    tags=["tasks"],
    summary="List and filter tasks",
    description="Retrieve all (or filtered) tasks for the authenticated user."
)
async def list_tasks(
    completed: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    tasks = list(fake_tasks_db.get(current_user.id, []))
    if completed is not None:
        tasks = [t for t in tasks if t.completed == completed]
    if search:
        search_lower = search.lower()
        tasks = [
            t
            for t in tasks
            if search_lower in t.title.lower() or search_lower in (t.description or '').lower()
        ]
    return tasks


# PUBLIC_INTERFACE
@app.get(
    "/tasks/{task_id}",
    response_model=Task,
    tags=["tasks"],
    summary="Get a task by ID",
    description="Get a specific task by its ID for the authenticated user."
)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    tasks = fake_tasks_db.get(current_user.id, [])
    for t in tasks:
        if t.id == task_id:
            return t
    raise HTTPException(status_code=404, detail="Task not found")


# PUBLIC_INTERFACE
@app.put(
    "/tasks/{task_id}",
    response_model=Task,
    tags=["tasks"],
    summary="Update a task",
    description=(
        "Edit an existing task's details (title, description, due date, or completion status)."
    )
)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    current_user: User = Depends(get_current_user)
):
    tasks = fake_tasks_db.get(current_user.id, [])
    for idx, t in enumerate(tasks):
        if t.id == task_id:
            updated_data = t.dict()
            update_fields = task_update.dict(exclude_unset=True)
            updated_data.update(update_fields)
            updated_task = Task(**updated_data)
            tasks[idx] = updated_task
            return updated_task
    raise HTTPException(status_code=404, detail="Task not found")


# PUBLIC_INTERFACE
@app.delete(
    "/tasks/{task_id}",
    tags=["tasks"],
    summary="Delete a task",
    description="Delete a specific task by its ID for the authenticated user.",
    status_code=204
)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    tasks = fake_tasks_db.get(current_user.id, [])
    for idx, t in enumerate(tasks):
        if t.id == task_id:
            del tasks[idx]
            return
    raise HTTPException(status_code=404, detail="Task not found")


# PUBLIC_INTERFACE
@app.post(
    "/tasks/{task_id}/complete",
    response_model=Task,
    tags=["tasks"],
    summary="Mark task as complete",
    description="Mark the specified task as completed."
)
async def complete_task(
    task_id: str,
    current_user: User = Depends(get_current_user)
):
    tasks = fake_tasks_db.get(current_user.id, [])
    for idx, t in enumerate(tasks):
        if t.id == task_id:
            updated_task = Task(**{**t.dict(), "completed": True})
            tasks[idx] = updated_task
            return updated_task
    raise HTTPException(status_code=404, detail="Task not found")


# --- HEALTH CHECK ---


@app.get("/", tags=["health"])
def health_check():
    """PUBLIC_INTERFACE
    Simple health check endpoint. Returns a message indicating the API is healthy.
    """
    return {"message": "Healthy"}


# --- Swagger/OpenAPI Doc Customization for WebSocket (none present in this version) ---


# --- USAGE NOTE ---
"""
Note:
- This is a DEMO implementation using in-memory Python dicts as a database.
- For real applications, add persistent database integration, secure password hashing/management,
  and production-ready configuration.
- All endpoints require authentication except /, /login, /register.
- JWT is used for user sessions. Auth header: Authorization: Bearer <token>
"""
