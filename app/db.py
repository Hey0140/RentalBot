import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")
PG_DB = os.getenv("PG_DB")
PG_PORT = os.getenv("PG_PORT", "5432")

DATABASE_URL = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@db:{PG_PORT}/{PG_DB}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
