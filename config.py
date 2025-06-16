import dotenv
import os
import pathlib


env_path = pathlib.Path(__file__).resolve().parent / '.env'
dotenv.load_dotenv(dotenv_path=env_path)

TOKEN = os.getenv("TOKEN")
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")
PROXY_SERVER = os.getenv("PROXY_SERVER")
PROXY_PORT = os.getenv("PROXY_PORT")
MODEL = os.getenv("MODEL")
