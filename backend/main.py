
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import bcrypt
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import (
    create_engine, String, Float, DateTime, UniqueConstraint,
    select, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

load_dotenv()

# ── Database connection ───────────────────────────────────────────────────────

database_url = URL.create(
    "postgresql+psycopg",
    username=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", ""),
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME", "FarmIQ"),
)

engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# ── Password hashing (bcrypt 5.x directly — no passlib) ──────────────────────
# rounds=6 is fast for development. Use 12+ in production.
BCRYPT_ROUNDS = 6


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── ORM Base & Models ─────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    soil_moisture: Mapped[float] = mapped_column(Float)
    temperature: Mapped[float] = mapped_column(Float)
    humidity: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email",  name="uq_users_email"),
        UniqueConstraint("mobile", name="uq_users_mobile"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), index=True)
    mobile: Mapped[str] = mapped_column(String(20), index=True)
    role: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

VALID_ROLES = {"farmer", "farm_manager", "agricultural_expert"}
MOBILE_RE   = re.compile(r"^\+\d{1,4}\d{10}$")
STRONG_PW   = re.compile(r"^(?=.*[A-Z])(?=.*\d).{8,}$")


class UserRegister(BaseModel):
    full_name: str      = Field(min_length=2, max_length=200)
    email:     EmailStr
    mobile:    str      = Field(min_length=8, max_length=20)
    role:      str
    password:  str      = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def name_must_have_chars(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        return v

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, v: str) -> str:
        if not MOBILE_RE.match(v):
            raise ValueError(
                "Mobile must include country code followed by exactly 10 digits, e.g. +919876543210."
            )
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not STRONG_PW.match(v):
            raise ValueError(
                "Password must be at least 8 characters and contain "
                "at least one uppercase letter and one number."
            )
        return v


class UserLogin(BaseModel):
    mobile:   str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id:         int
    full_name:  str
    email:      str
    mobile:     str
    role:       str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadingCreate(BaseModel):
    device_id:     str   = Field(min_length=1, max_length=100)
    soil_moisture: float = Field(ge=0, le=100)
    temperature:   float = Field(ge=-50, le=100)
    humidity:      float = Field(ge=0, le=100)


class ReadingResponse(ReadingCreate):
    id:         int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── DB dependency ─────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        # Create tables that don't exist yet (safe — never drops data)
        Base.metadata.create_all(bind=engine)

        # Add uq_users_mobile constraint if it wasn't in the original table
        with engine.connect() as conn:
            exists = conn.execute(text("""
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'uq_users_mobile'
                  AND table_name = 'users'
            """)).fetchone()
            if not exists:
                conn.execute(text(
                    "ALTER TABLE users ADD CONSTRAINT uq_users_mobile UNIQUE (mobile)"
                ))
                conn.commit()
                print("Added uq_users_mobile constraint.")

        print("FarmIQ PostgreSQL database connected and ready.")
    except Exception as exc:
        print(f"Startup error: {exc}")
        raise
    yield
    engine.dispose()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="FarmIQ API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── General routes ────────────────────────────────────────────────────────────

@app.get("/")
def home():
    return {"message": "FarmIQ backend is running"}


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(select(text("1")))
        return {"status": "healthy", "database": "connected"}
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database connection failed")


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post(
    "/api/auth/register",
    response_model=UserResponse,
    status_code=201,
    summary="Register a new FarmIQ user",
)
def register_user(payload: UserRegister, db: Session = Depends(get_db)):
    # Check email uniqueness
    if db.scalars(select(User).where(User.email == payload.email.lower())).first():
        raise HTTPException(status_code=409, detail="Email is already registered.")

    # Check mobile uniqueness
    if db.scalars(select(User).where(User.mobile == payload.mobile)).first():
        raise HTTPException(status_code=409, detail="Mobile number is already registered.")

    new_user = User(
        full_name=payload.full_name,
        email=payload.email.lower(),
        mobile=payload.mobile,
        role=payload.role,
        password_hash=hash_password(payload.password),
    )
    db.add(new_user)
    try:
        db.commit()
        db.refresh(new_user)
        return new_user
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or mobile is already registered.")
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@app.post(
    "/api/auth/login",
    response_model=UserResponse,
    summary="Sign in with mobile number and password",
)
def login_user(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalars(
        select(User).where(User.mobile == payload.mobile)
    ).first()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect mobile number or password.")

    return user


# ── Sensor-reading routes ─────────────────────────────────────────────────────

@app.post("/api/sensor-readings/", response_model=ReadingResponse)
def create_sensor_reading(reading: ReadingCreate, db: Session = Depends(get_db)):
    record = SensorReading(**reading.model_dump())
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
        return record
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Could not save sensor reading")


@app.get("/api/sensor-readings/", response_model=list[ReadingResponse])
def get_sensor_readings(db: Session = Depends(get_db)):
    statement = (
        select(SensorReading)
        .order_by(SensorReading.created_at.desc())
        .limit(100)
    )
    return db.scalars(statement).all()
