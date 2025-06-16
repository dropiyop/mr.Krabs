import re
import asyncio
import init_clients
import config


async def show_typing(bot, message):
    while True:
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        await asyncio.sleep(4)


def new_query_to_gpt(message, user_id):
    if user_id not in init_clients.user_context:
        init_clients.user_context[user_id].add_message(
            role=init_clients.chat.Message.ROLE_SYSTEM,
            content="СИСТЕМНЫЙ ПРОМТ")

    init_clients.user_context[user_id].add_message(
        role=init_clients.chat.Message.ROLE_USER,
        content=message
    )


async def send_to_gpt(messages: init_clients.chat.MessageHistory, temperature=0.1, json_shame=None) -> str:
    if json_shame is None:
        chat_completion = await init_clients.client_openai.chat.completions.create(
            messages=messages.to_json(),
            model=config.MODEL,
            temperature=temperature
        )
        return chat_completion.choices[0].message.content
    else:
        chat_completion = await init_clients.client_openai.chat.completions.create(
            messages=messages.to_json(),
            model=config.MODEL,
            temperature=temperature,
            response_format=json_shame
        )
        return chat_completion.choices[0].message.content
