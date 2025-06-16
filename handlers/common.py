import asyncio

from aiog import *

import decorators
import init_clients
from . import dependencies


@init_clients.dp.callback_query(aiogram.F.data == "nothing")
async def handle_file_pins(callback: aiogram.types.CallbackQuery):
    await callback.answer()


@init_clients.dp.callback_query(aiogram.F.data == "cancel")
async def cancel(callback: aiogram.types.CallbackQuery, state: aiogram.fsm.context.FSMContext):
    await callback.message.edit_text("Вы все отменили")
    await state.clear()


@init_clients.dp.callback_query(aiogram.F.data == "cancel_and_remove")
async def cancel_and_remove(callback: aiogram.types.CallbackQuery, state: aiogram.fsm.context.FSMContext):
    await callback.message.delete()
    await state.clear()


@init_clients.dp.message(aiogram.F.text.lower() == "забыть историю сообщений")
@decorators.approve_required
async def button_forgot(message: aiogram.types.Message, state=None, text=None) -> None:
    if state and text:
        pass

    await message.delete()
    try:
        init_clients.user_context.remove_user(message.from_user.id)
    except KeyError:
        await message.answer("Я все забыл, но если сказать по правде, я ничего и не помнил...")
    except IndexError:
        await message.answer("А мы вообще знакомы, чтобы я тебя забывал?")
    else:
        await message.answer("Я все забыл, давай сначала")


@init_clients.dp.message(lambda message: message.chat.type == 'private')
@decorators.approve_required
async def what_you_want(message: aiogram.types.Message, state=None, text=None):
    if text is None:
        user_message = message.text
    else:
        user_message = text
    typing_task = asyncio.create_task(dependencies.show_typing(init_clients.bot, message))

    dependencies.new_query_to_gpt(user_message, message.from_user.id)

    try:
        gpt_response = await dependencies.send_to_gpt(init_clients.user_context[message.from_user.id])
    finally:
        typing_task.cancel()

    await message.answer(text=gpt_response, parse_mode=aiogram.enums.ParseMode.MARKDOWN)
