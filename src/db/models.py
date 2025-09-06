from sqlalchemy import Column, String, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class Tweet(Base):
    __tablename__ = 'tweets'
    tweet_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    username = Column(String, nullable=False)
    text = Column(Text)
    created_at = Column(DateTime)
    in_reply_to_tweet_id = Column(String, ForeignKey('tweets.tweet_id'), nullable=True)
    quoted_tweet_id = Column(String, ForeignKey('tweets.tweet_id'), nullable=True)
    image_paths = Column(Text)  # comma-separated local image file paths
    video_username = Column(String)  # username if tweet has video, else None

    quoted_tweet = relationship("Tweet", remote_side=[tweet_id], foreign_keys=[quoted_tweet_id], post_update=True)
    in_reply_to_tweet = relationship("Tweet", remote_side=[tweet_id], foreign_keys=[in_reply_to_tweet_id], post_update=True)

    def images(self):
        """Returns a list of image paths"""
        if self.image_paths:
            return [p.strip() for p in self.image_paths.split(',') if p.strip()]
        return []