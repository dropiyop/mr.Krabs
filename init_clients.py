from aiog import *
import openai
import httpx_socks
import httpx

import config
import chat


bot = aiogram.Bot(
    token=config.TOKEN,
    default=aiogram.client.default.DefaultBotProperties(parse_mode=aiogram.enums.ParseMode.HTML))
dp = aiogram.Dispatcher(bot=bot, storage=aiogram.fsm.storage.memory.MemoryStorage())

transport = httpx_socks.AsyncProxyTransport.from_url(f"socks5://{config.PROXY_SERVER}:{config.PROXY_PORT}")
http_client = httpx.AsyncClient(transport=transport)

client_openai = openai.AsyncOpenAI(api_key=config.OPENAI_TOKEN, http_client=http_client)

user_context = chat.MessageHistoryManager()
