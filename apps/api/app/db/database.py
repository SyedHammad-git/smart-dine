import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Environment variables load karein (.env se)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing in environment variables.")

# PostgreSQL / Neon Engine create karein
engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class jo models ke liye lazmi hai
Base = declarative_base()

# Dependency function database session ke liye
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()