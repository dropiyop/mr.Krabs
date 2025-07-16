import dotenv
import os
import pathlib


env_path = pathlib.Path(__file__).resolve().parent / '.env'
dotenv.load_dotenv(dotenv_path=env_path)

CASCADE_USERS_URL = os.getenv('CASCADE_USERS_URL')

CASCADE_USER = os.getenv('CASCADE_USER')
CASCADE_PASSWORD = os.getenv('CASCADE_PASSWORD')
TOKEN = os.getenv("TOKEN")
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")
PROXY_SERVER = os.getenv("PROXY_SERVER")
PROXY_PORT = os.getenv("PROXY_PORT")
MODEL = os.getenv("MODEL")
