from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base

engine = create_engine('sqlite:///tweets.db')  # Or your chosen DB URI
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)