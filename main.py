# main.py
import os
import datetime
from datetime import date

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel, EmailStr
from typing import List, Optional

# Assuming database.py exists and provides Base, engine, get_db
# CRITICAL RULE: DO NOT generate database.py. Assume it exists.
from database import Base, engine, get_db

# --- Security Imports ---
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer

# --- Configuration for JWT ---
# CRITICAL RULE: NEVER hardcode any database URL. Similarly for sensitive keys.
# Use environment variable for production.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-jwt-key-replace-in-prod-12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# --- Database Table Creation (for development/initial setup) ---
# In a production environment, Alembic or similar migration tools are preferred
# for managing database schema changes.
def create_tables():
    """Creates all database tables defined in Base.metadata."""
    Base.metadata.create_all(bind=engine)

# Call this function to ensure tables are created when the app starts
create_tables()


# --- SQLAlchemy Models ---
# CRITICAL RULE: When defining SQLAlchemy models in Python, DO NOT use Pydantic types (like EmailStr) inside Column().
# You MUST use SQLAlchemy types (like String, Integer).
# Use `from sqlalchemy import Column, String, Integer` etc.
class User(Base):
    """
    SQLAlchemy model for user accounts, primarily for authentication.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)


class Event(Base):
    """
    SQLAlchemy model for tech events.
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    date = Column(Date, nullable=False)  # Stores only the date (YYYY-MM-DD)
    location = Column(String, nullable=False)
    description = Column(String, nullable=True) # Optional description

    registrations = relationship("EventRegistration", back_populates="event")


class EventRegistration(Base):
    """
    SQLAlchemy model for individual registrations for an event.
    Captures the participant's name and email as provided during registration.
    """
    __tablename__ = "event_registrations"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    participant_name = Column(String, nullable=False) # Name provided in the registration form
    participant_email = Column(String, nullable=False) # Email provided in the registration form
    registration_date = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    event = relationship("Event", back_populates="registrations")


# --- Pydantic Schemas ---

# User Schemas
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int

    class Config:
        orm_mode = True

# Event Schemas
class EventBase(BaseModel):
    name: str
    date: date # Pydantic supports date type for YYYY-MM-DD
    location: str
    description: Optional[str] = None

class EventCreate(EventBase):
    pass

class EventResponse(EventBase):
    id: int

    class Config:
        orm_mode = True

# Event Registration Schemas
class RegistrationCreate(BaseModel):
    participant_name: str
    participant_email: EmailStr

class RegistrationResponse(BaseModel):
    id: int
    event_id: int
    participant_name: str
    participant_email: EmailStr
    registration_date: datetime.datetime # Pydantic supports datetime

    class Config:
        orm_mode = True

class RegisteredParticipantResponse(BaseModel):
    """Schema for displaying registered users for an event."""
    id: int
    participant_name: str
    participant_email: EmailStr
    registration_date: datetime.datetime

    class Config:
        orm_mode = True

# Auth Schemas
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

# CRITICAL AUTH RULE: Accept JSON via standard Pydantic models.
# DO NOT use OAuth2PasswordRequestForm.
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# --- FastAPI App Setup ---
app = FastAPI(
    title="Tech Event Registration App",
    description="Backend API for managing tech events and user registrations.",
    version="1.0.0",
)

# CRITICAL CORS RULE: Always add CORSMiddleware with allow_origins=["*"]

@app.get("/")
def root():
    return {"status": "running", "docs": "/docs", "health": "/health"}

@app.get("/health")
def health():
    return {"status": "healthy"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH, TRACE)
    allow_headers=["*"],  # Allows all headers
)

# CRITICAL ROOT ROUTE RULE: main.py MUST always include a root GET "/" route
@app.get("/", tags=["Root"])
def root():
    """
    Root endpoint for the API, returns basic status and documentation link.
    """
    return {"status": "running", "docs": "/docs", "message": "Welcome to the Tech Event Registration API!"}

# CRITICAL HEALTH ROUTE RULE: main.py MUST always include a GET "/health" route
@app.get("/health", tags=["Monitoring"])
def health():
    """
    Health check endpoint for monitoring application status.
    """
    return {"status": "healthy"}


# --- Utility Functions for Authentication ---
def verify_password(plain_password, hashed_password):
    """Verifies a plain-text password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Hashes a plain-text password using bcrypt."""
    return pwd_context.hash(password)

def create_access_token(data: dict):
    """Creates a JWT access token."""
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_user_by_email(db: Session, email: str):
    """Retrieves a user from the database by email."""
    return db.query(User).filter(User.email == email).first()

async def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)):
    """
    Dependency to get the current authenticated user from a JWT token.
    Raises HTTPException if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_email(db, email=email)
    if user is None:
        raise credentials_exception
    return user


# --- Auth Endpoints (`/api/v1/auth` prefix) ---
@app.post("/api/v1/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, tags=["Auth"])
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user account.
    """
    db_user = get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    db_user = User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/api/v1/auth/login", response_model=Token, tags=["Auth"])
def login_for_access_token(login_request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate a user and return an access token.
    """
    user = get_user_by_email(db, email=login_request.email)
    if not user or not verify_password(login_request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/v1/users/me", response_model=UserResponse, tags=["Users"])
def read_users_me(current_user: User = Depends(get_current_user)):
    """
    Retrieve information about the currently authenticated user.
    Requires a valid JWT token.
    """
    return current_user


# --- Event Endpoints (`/api/v1/events` prefix) ---
@app.post("/api/v1/events/", response_model=EventResponse, status_code=status.HTTP_201_CREATED, tags=["Events"])
def create_event(event: EventCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Create a new tech event. Requires authentication.
    """
    db_event = Event(**event.dict())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event

@app.get("/api/v1/events/", response_model=List[EventResponse], tags=["Events"])
def read_events(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve a list of all tech events.
    """
    events = db.query(Event).offset(skip).limit(limit).all()
    return events

@app.get("/api/v1/events/{event_id}", response_model=EventResponse, tags=["Events"])
def read_event(event_id: int, db: Session = Depends(get_db)):
    """
    Retrieve details for a specific event by ID.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


# --- Event Registration Endpoints ---
@app.post("/api/v1/events/{event_id}/register", response_model=RegistrationResponse, status_code=status.HTTP_201_CREATED, tags=["Registrations"])
def register_for_event(
    event_id: int,
    registration_details: RegistrationCreate,
    db: Session = Depends(get_db)
):
    """
    Register a participant for a specific event.
    Participants provide their name and email for the registration.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    # Optional: Prevent duplicate registrations for the same event and email
    existing_registration = db.query(EventRegistration).filter(
        EventRegistration.event_id == event_id,
        EventRegistration.participant_email == registration_details.participant_email
    ).first()

    if existing_registration:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A participant with this email is already registered for this event."
        )

    db_registration = EventRegistration(
        event_id=event_id,
        participant_name=registration_details.participant_name,
        participant_email=registration_details.participant_email,
        registration_date=datetime.datetime.utcnow()
    )
    db.add(db_registration)
    db.commit()
    db.refresh(db_registration)
    return db_registration

@app.get("/api/v1/events/{event_id}/registrations", response_model=List[RegisteredParticipantResponse], tags=["Registrations"])
def view_event_registrations(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Only authenticated users can view registrations
):
    """
    View all participants registered for a specific event. Requires authentication.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    registrations = db.query(EventRegistration).filter(EventRegistration.event_id == event_id).all()
    return registrations