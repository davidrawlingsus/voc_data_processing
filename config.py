"""Configuration for Caplena API connection."""
import os


class Config:
    """Configuration class for Caplena API."""
    
    API_KEY = os.getenv("CAPLENA_API_KEY", "1a7caf0d098c33575f4a3be7f5f7c5f786441713")



