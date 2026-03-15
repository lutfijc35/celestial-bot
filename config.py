import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID") or "0")
APPROVAL_CHANNEL_ID = int(os.getenv("APPROVAL_CHANNEL_ID") or "0")
GUILD_LIST_CHANNEL_ID = int(os.getenv("GUILD_LIST_CHANNEL_ID") or "0")
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID") or "0")
RULES_MESSAGE_ID = int(os.getenv("RULES_MESSAGE_ID") or "0")
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID") or "0")
REGISTER_CHANNEL_ID = int(os.getenv("REGISTER_CHANNEL_ID") or "0")
OTHER_GAMES_CHANNEL_ID = int(os.getenv("OTHER_GAMES_CHANNEL_ID") or "0")
MEMBER_ROLE_ID = int(os.getenv("MEMBER_ROLE_ID") or "0")
DEFAULT_ROLE_ID = int(os.getenv("DEFAULT_ROLE_ID") or "0")
APPROVAL_MODE = os.getenv("APPROVAL_MODE", "manual")
DB_PATH = os.getenv("DB_PATH", "data/celestial.db")
