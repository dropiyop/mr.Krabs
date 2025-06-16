from aiog import *


class Form(aiogram.fsm.state.StatesGroup):
    waiting_for_contact = aiogram.fsm.state.State()

