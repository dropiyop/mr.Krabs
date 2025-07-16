from aiog import *

class Form(StatesGroup):
    waiting_for_contact = State()
    waiting_for_prompt = State()
